"""Real platform ingress -> pipeline -> Agent Runner -> outbound reply tests.

The only deterministic piece is the QA Runner plugin already used by
``test_runner_plugin_runtime.py``.  Everything between the signed HTTP Bot
webhook and the reply captured by ``/sync`` is the production path: the real
Quart process, bot manager routing, pipeline execution, plugin runtime action
transport and monitoring persistence.

Run: uv run pytest tests/e2e/test_platform_message_flow.py -q -m e2e
"""

from __future__ import annotations

import json
import sqlite3
import time

import pytest
import yaml

from langbot.pkg.platform.sources import http_bot_signing as signing
from tests.e2e import test_runner_plugin_runtime as runtime

# Reuse the real process lifecycle; override the config below so the HTTP Bot
# adapter is discoverable.  Imported fixtures become module-local FixtureDefs,
# so this module gets its own process, plugin runtime and ports.
runner_runtime_ports = runtime.runner_runtime_ports
runner_runtime_process = runtime.runner_runtime_process
runner_langbot_process = runtime.runner_langbot_process
runner_client = runtime.runner_client

pytestmark = pytest.mark.e2e

INBOUND_SECRET = 'e2e-http-bot-inbound-secret'


@pytest.fixture(scope='session')
def runner_e2e_tmpdir(tmp_path_factory):
    """Keep the isolated LangBot data directory per module."""
    return tmp_path_factory.mktemp('platform-flow')


@pytest.fixture(scope='session')
def runner_e2e_port():
    return runtime._free_port()


@pytest.fixture(scope='session')
def runner_e2e_config_path(runner_e2e_tmpdir, runner_e2e_port, runner_runtime_ports):
    """Build the Runner config, then re-enable the built-in HTTP Bot adapter."""
    path = runtime.runner_e2e_config_path.__wrapped__(
        runner_e2e_tmpdir,
        runner_e2e_port,
        runner_runtime_ports,
        None,  # No browser preview origin: this module posts webhooks only.
    )
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    config['system']['disabled_adapters'] = [
        name for name in config['system']['disabled_adapters'] if name != 'http_bot'
    ]
    path.write_text(yaml.safe_dump(config, default_flow_style=False), encoding='utf-8')
    return path


def _create_http_bot(client, token: str, pipeline_id: str) -> str:
    """Create an enabled HTTP Bot bound to the given pipeline for private chat."""
    response = client.post(
        '/api/v1/platform/bots',
        headers={'Authorization': f'Bearer {token}'},
        json={
            'name': 'HTTP Bot E2E',
            'description': 'Signed inbound platform flow',
            'adapter': 'http_bot',
            'adapter_config': {
                'inbound_secret': INBOUND_SECRET,
                'callback_url': 'http://127.0.0.1:1/unused-callback',
                'signature_required': True,
                'callback_timeout': 30,
            },
            'enable': True,
            'event_bindings': [
                {
                    'id': 'e2e-person-binding',
                    'event_pattern': 'message.received',
                    'target_type': 'pipeline',
                    'target_uuid': pipeline_id,
                    'filters': [{'field': 'chat_type', 'operator': 'eq', 'value': 'person'}],
                    'priority': 0,
                    'enabled': True,
                    'description': 'Private chat routes to the QA Runner pipeline',
                    'order': 0,
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['code'] == 0, payload
    return payload['data']['uuid']


def _post_sync(client, bot_uuid: str, body: bytes, *, signed: bool):
    """POST one inbound turn, optionally signing it with the inbound secret."""
    headers = {'Content-Type': 'application/json'}
    if signed:
        timestamp, signature = signing.sign(INBOUND_SECRET, body)
        headers[signing.HEADER_TIMESTAMP] = timestamp
        headers[signing.HEADER_SIGNATURE] = signature
    return client.post(f'/bots/{bot_uuid}/sync', content=body, headers=headers)


def _wait_for_monitoring_rows(db_path, bot_uuid: str, timeout: float = 15) -> list[tuple]:
    """Wait until both the inbound and the reply row are persisted and settled."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with sqlite3.connect(db_path) as connection:
            rows = connection.execute(
                """
                SELECT role, message_content, status, runner_name
                FROM monitoring_messages
                WHERE bot_id = ?
                ORDER BY timestamp, id
                """,
                (bot_uuid,),
            ).fetchall()
        if (
            len(rows) == 2
            and rows[0][0] == 'user'
            and rows[1][0] == 'assistant'
            and all(row[2] not in {'pending', 'error'} for row in rows)
        ):
            return rows
        time.sleep(0.2)
    return rows


def test_signed_http_bot_message_runs_pipeline_and_returns_reply(
    runner_client,
    runner_e2e_tmpdir,
):
    """One signed inbound message must produce the Runner reply and persisted history."""
    token = runtime._init_and_auth(runner_client)
    runtime._ensure_qa_plugin(runner_client, token, runner_e2e_tmpdir / 'agent-runner-qa.zip')
    pipeline_id = runtime._create_boundary_pipeline(runner_client, token)
    bot_uuid = _create_http_bot(runner_client, token, pipeline_id)

    body = json.dumps(
        {
            'session_id': 'e2e-http-session',
            'sender': {'id': 'e2e-user', 'name': 'E2E User'},
            'message': [{'type': 'Plain', 'text': 'hello from platform'}],
        },
        ensure_ascii=False,
        separators=(',', ':'),
    ).encode()

    rejected = _post_sync(runner_client, bot_uuid, body, signed=False)
    assert rejected.status_code == 401, rejected.text

    accepted = _post_sync(runner_client, bot_uuid, body, signed=True)
    assert accepted.status_code == 200, accepted.text
    payload = accepted.json()
    assert payload['code'] == 0, payload
    reply = payload['data']
    assert reply['message'] == [{'type': 'Plain', 'text': 'e2e echo: hello from platform'}]
    assert reply['reply_to'].startswith('in_')

    rows = _wait_for_monitoring_rows(runner_e2e_tmpdir / 'data' / 'langbot.db', bot_uuid)

    assert [row[0] for row in rows] == ['user', 'assistant'], rows
    assert 'hello from platform' in rows[0][1]
    reply_text = ''.join(
        component.get('text') or '' for component in json.loads(rows[1][1]) if component.get('type') == 'Plain'
    )
    assert reply_text == 'e2e echo: hello from platform'
    assert all(row[2] == 'success' for row in rows), rows
    assert rows[1][3] == runtime.QA_RUNNER_ID
