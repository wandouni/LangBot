"""Real knowledge-base upload -> ingestion -> retrieval tests.

The Knowledge Engine is the same QA plugin used by the Runner E2E, extended
with a deterministic engine component.  Everything else is the production
path: the real Quart process stores the upload, dispatches ingestion to the
real SDK Plugin Runtime over WebSocket, the engine writes vectors through the
host ``vector_upsert`` action into a temporary embedded Chroma store, and
``/retrieve`` reads them back through ``vector_search``.

Two knowledge bases are ingested to prove that retrieval is scoped by the
server-derived physical collection (instance + Workspace + knowledge base),
so one base can never observe another base's chunks.

Run: uv run pytest tests/e2e/test_knowledge_rag_flow.py -q -m e2e
"""

from __future__ import annotations

import shutil
import time

import httpx
import pytest
import yaml

from tests.e2e import test_runner_plugin_runtime as runtime

# Reuse the Runner process lifecycle.  Imported fixtures become module-local
# FixtureDefs, so this module gets its own process, plugin runtime and ports.
runner_runtime_ports = runtime.runner_runtime_ports
runner_runtime_process = runtime.runner_runtime_process
runner_langbot_process = runtime.runner_langbot_process
runner_client = runtime.runner_client

pytestmark = pytest.mark.e2e

ENGINE_PLUGIN_ID = 'e2e/agent-runner-qa'

_ENGINE_YAML = """
apiVersion: langbot/v1
kind: KnowledgeEngine
metadata:
  name: demo
  label:
    en_US: QA Demo Knowledge Engine
    zh_Hans: QA Demo Knowledge Engine
  description:
    en_US: Deterministic hashed bag-of-words engine for E2E tests.
    zh_Hans: 用于 E2E 的确定性词袋引擎。
spec:
  creation_schema: []
  retrieval_schema: []
execution:
  python:
    path: demo.py
    attr: DemoKnowledgeEngine
"""

_ENGINE_PY = '''
from __future__ import annotations

import hashlib
import re

from langbot_plugin.api.definition.components.knowledge_engine.engine import (
    KnowledgeEngine,
    KnowledgeEngineCapability,
)
from langbot_plugin.api.entities.builtin.provider.message import ContentElement
from langbot_plugin.api.entities.builtin.rag.context import (
    RetrievalContext,
    RetrievalResponse,
    RetrievalResultEntry,
)
from langbot_plugin.api.entities.builtin.rag.enums import DocumentStatus
from langbot_plugin.api.entities.builtin.rag.models import IngestionContext, IngestionResult

DIMENSIONS = 64


def _embed(text: str) -> list[float]:
    """Deterministic hashed bag-of-words vector, so E2E needs no embedding model."""
    vector = [0.0] * DIMENSIONS
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        vector[int(digest, 16) % DIMENSIONS] += 1.0
    norm = sum(value * value for value in vector) ** 0.5 or 1.0
    return [value / norm for value in vector]


class DemoKnowledgeEngine(KnowledgeEngine):
    @classmethod
    def get_capabilities(cls) -> list[str]:
        return [KnowledgeEngineCapability.DOC_INGESTION]

    async def ingest(self, context: IngestionContext) -> IngestionResult:
        file_object = context.file_object
        raw = await self.plugin.get_knowledge_file_stream(file_object.storage_path)
        chunks = [line.strip() for line in raw.decode("utf-8", errors="replace").splitlines() if line.strip()]
        document_id = file_object.metadata.document_id
        if chunks:
            await self.plugin.vector_upsert(
                collection_id=context.get_collection_id(),
                vectors=[_embed(chunk) for chunk in chunks],
                ids=[f"{document_id}:{index}" for index in range(len(chunks))],
                metadata=[{"text": chunk, "file_id": document_id} for chunk in chunks],
                documents=chunks,
            )
        return IngestionResult(
            document_id=document_id,
            status=DocumentStatus.COMPLETED,
            chunks_created=len(chunks),
        )

    async def delete_document(self, kb_id: str, document_id: str) -> bool:
        await self.plugin.vector_delete(collection_id=kb_id, file_ids=[document_id])
        return True

    async def retrieve(self, context: RetrievalContext) -> RetrievalResponse:
        top_k = int(context.retrieval_settings.get("top_k", 5))
        hits = await self.plugin.vector_search(
            collection_id=context.get_collection_id(),
            query_vector=_embed(context.query),
            top_k=top_k,
            filters=context.filters or None,
        )
        results = [
            RetrievalResultEntry(
                id=str(hit["id"]),
                content=[ContentElement(type="text", text=str(hit.get("metadata", {}).get("text", "")))],
                metadata=dict(hit.get("metadata") or {}),
                distance=float(hit.get("distance", 0.0)),
                score=hit.get("score"),
            )
            for hit in hits
        ]
        return RetrievalResponse(results=results, total_found=len(results))
'''


@pytest.fixture(scope='session')
def runner_e2e_tmpdir(tmp_path_factory):
    """Keep the isolated LangBot data directory per module."""
    return tmp_path_factory.mktemp('knowledge-rag')


@pytest.fixture(scope='session')
def runner_e2e_port():
    return runtime._free_port()


def _extend_qa_plugin_with_engine(package_root):
    """Add a KnowledgeEngine component to the Runner test plugin and re-zip it."""
    engine_dir = package_root / 'components' / 'knowledge_engine'
    engine_dir.mkdir(parents=True, exist_ok=True)
    (engine_dir / 'demo.yaml').write_text(_ENGINE_YAML.strip() + '\n', encoding='utf-8')
    (engine_dir / 'demo.py').write_text(_ENGINE_PY.strip() + '\n', encoding='utf-8')

    manifest_path = package_root / 'manifest.yaml'
    manifest = yaml.safe_load(manifest_path.read_text(encoding='utf-8'))
    manifest['spec']['components']['KnowledgeEngine'] = {'fromDirs': [{'path': 'components/knowledge_engine/'}]}
    manifest_path.write_text(yaml.safe_dump(manifest, default_flow_style=False), encoding='utf-8')

    shutil.make_archive(
        str(package_root.parent / 'agent-runner-qa'),
        'zip',
        root_dir=package_root,
    )


@pytest.fixture(scope='session')
def runner_e2e_config_path(runner_e2e_tmpdir, runner_e2e_port, runner_runtime_ports):
    """Build the Runner stack, then add the Knowledge Engine to its plugin zip."""
    path = runtime.runner_e2e_config_path.__wrapped__(
        runner_e2e_tmpdir,
        runner_e2e_port,
        runner_runtime_ports,
        None,  # No browser preview origin: this module talks HTTP only.
    )
    _extend_qa_plugin_with_engine(runner_e2e_tmpdir / 'agent-runner-qa-package')
    return path


def _auth_headers(token: str) -> dict[str, str]:
    return {'Authorization': f'Bearer {token}'}


def _wait_for_engine(client: httpx.Client, headers: dict[str, str], timeout: float = 60) -> dict:
    """Wait until the installed plugin exposes its Knowledge Engine."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get('/api/v1/knowledge/engines', headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload['code'] == 0, payload
        engines = payload['data']['engines']
        for engine in engines:
            if engine['plugin_id'] == ENGINE_PLUGIN_ID:
                return engine
        time.sleep(1)
    raise AssertionError(f'{ENGINE_PLUGIN_ID} Knowledge Engine was not discovered: {engines}')


def _create_knowledge_base(client: httpx.Client, headers: dict[str, str], name: str) -> str:
    response = client.post(
        '/api/v1/knowledge/bases',
        headers=headers,
        json={
            'name': name,
            'description': 'E2E ingestion and retrieval probe',
            'knowledge_engine_plugin_id': ENGINE_PLUGIN_ID,
            'creation_settings': {},
            'retrieval_settings': {},
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['code'] == 0, payload
    return payload['data']['uuid']


def _upload_and_ingest(
    client: httpx.Client,
    headers: dict[str, str],
    kb_uuid: str,
    tmpdir,
    *,
    file_name: str,
    content: str,
) -> dict:
    """Upload one document through the HTTP API and wait for ingestion to settle."""
    upload = client.post(
        '/api/v1/files/documents',
        headers=headers,
        files={'file': (file_name, content.encode(), 'text/plain')},
    )
    assert upload.status_code == 200, upload.text
    upload_payload = upload.json()
    assert upload_payload['code'] == 0, upload_payload
    file_id = upload_payload['data']['file_id']

    added = client.post(
        f'/api/v1/knowledge/bases/{kb_uuid}/files',
        headers=headers,
        json={'file_id': file_id, 'original_file_name': file_name},
    )
    assert added.status_code == 200, added.text
    added_payload = added.json()
    assert added_payload['code'] == 0, added_payload
    assert added_payload['data']['task_id']

    deadline = time.time() + 90
    while time.time() < deadline:
        response = client.get(f'/api/v1/knowledge/bases/{kb_uuid}/files', headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload['code'] == 0, payload
        files = payload['data']['files']
        if len(files) == 1 and files[0]['status'] in {'completed', 'failed', 'interrupted'}:
            assert files[0]['status'] == 'completed', (files, (tmpdir / 'data' / 'langbot.log'))
            return files[0]
        time.sleep(0.5)
    raise AssertionError(f'Knowledge file {file_name} did not finish ingestion: {files}')


def _retrieve(client: httpx.Client, headers: dict[str, str], kb_uuid: str, query: str) -> list[dict]:
    response = client.post(
        f'/api/v1/knowledge/bases/{kb_uuid}/retrieve',
        headers=headers,
        json={'query': query, 'retrieval_settings': {'top_k': 5}},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['code'] == 0, payload
    return payload['data']['results']


def _result_texts(results: list[dict]) -> list[str]:
    return [
        element.get('text') or ''
        for result in results
        for element in result.get('content') or []
        if element.get('type') == 'text'
    ]


def test_knowledge_upload_ingest_and_retrieve_is_collection_scoped(
    runner_client,
    runner_e2e_tmpdir,
):
    """Upload -> async ingestion -> vector retrieval must work and stay per-KB."""
    token = runtime._init_and_auth(runner_client)
    runtime._ensure_qa_plugin(runner_client, token, runner_e2e_tmpdir / 'agent-runner-qa.zip')
    headers = _auth_headers(token)
    engine = _wait_for_engine(runner_client, headers)
    assert 'doc_ingestion' in engine['capabilities'], engine

    alpha_kb = _create_knowledge_base(runner_client, headers, 'Alpha KB')
    gamma_kb = _create_knowledge_base(runner_client, headers, 'Gamma KB')
    assert alpha_kb != gamma_kb

    alpha_file = _upload_and_ingest(
        runner_client,
        headers,
        alpha_kb,
        runner_e2e_tmpdir,
        file_name='alpha.txt',
        content='alpha unique marker\nshared sentence\n',
    )
    gamma_file = _upload_and_ingest(
        runner_client,
        headers,
        gamma_kb,
        runner_e2e_tmpdir,
        file_name='gamma.txt',
        content='gamma isolated payload\nshared sentence\n',
    )
    # The engine's returned document id must survive the completed status write.
    assert alpha_file['engine_document_id'] == alpha_file['uuid']
    assert gamma_file['engine_document_id'] == gamma_file['uuid']

    alpha_hits = _retrieve(runner_client, headers, alpha_kb, 'alpha unique marker')
    assert alpha_hits, 'retrieval returned no results for an ingested knowledge base'
    assert 'alpha unique marker' in _result_texts(alpha_hits)[0]
    assert all('gamma' not in text for text in _result_texts(alpha_hits))

    gamma_hits = _retrieve(runner_client, headers, gamma_kb, 'gamma isolated payload')
    assert gamma_hits
    assert 'gamma isolated payload' in _result_texts(gamma_hits)[0]
    assert all('alpha' not in text for text in _result_texts(gamma_hits))

    # The vector store really was written to disk under the LangBot work dir.
    chroma_db = runner_e2e_tmpdir / 'data' / 'chroma' / 'chroma.sqlite3'
    assert chroma_db.is_file(), 'embedded Chroma database was not persisted'
