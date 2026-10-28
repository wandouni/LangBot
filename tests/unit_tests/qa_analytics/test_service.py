"""Unit tests for Q&A analytics collection and read queries."""

from __future__ import annotations

import asyncio
import base64
import datetime
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from langbot.pkg.api.http.context import ExecutionContext
from langbot.pkg.entity import persistence
from langbot.pkg.entity.persistence.base import Base
from langbot.pkg.entity.persistence.bot import Bot
from langbot.pkg.entity.persistence.qa_analytics import QAAnalyticsRecord
from langbot.pkg.qa_analytics import context as qa_context
from langbot.pkg.qa_analytics.service import QAAnalyticsService
from langbot.pkg.persistence.tenant_uow import _validate_scoped_statement_call
from langbot.pkg.utils import importutil

importutil.import_modules_in_pkg(persistence)

WORKSPACE = '00000000-0000-0000-0000-00000000000a'
OTHER_WORKSPACE = '00000000-0000-0000-0000-00000000000b'
BOT_A = '00000000-0000-0000-0000-0000000000a1'
BOT_B = '00000000-0000-0000-0000-0000000000b1'


class _UnitOfWork:
    def __init__(self, session):
        self.session = session

    async def execute(self, statement):
        # Mirror the production tenant guard so read queries cannot use SQL
        # constructs that the real UoW would reject.
        _validate_scoped_statement_call((statement,), {})
        return await self.session.execute(statement)


@pytest.fixture
async def database(tmp_path):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "qa.db"}')
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def tenant_uow(workspace_uuid):
        # Production tenant UoWs execute through an ORM session.  Using a Core
        # connection here would return column-keyed rows for ``select(model)``
        # and hide production-only row-shape bugs.
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin():
                yield _UnitOfWork(session)

    plugin_root = Path(__file__).resolve().parents[3] / 'plugins' / 'qa-analytics'

    async def get_plugin_assets(author, name, filepath):
        path = plugin_root / filepath
        if not path.is_file():
            return {'asset_base64': '', 'mime_type': ''}
        return {
            'asset_base64': base64.b64encode(path.read_bytes()).decode('ascii'),
            'mime_type': 'application/json',
        }

    app = SimpleNamespace(
        instance_config=SimpleNamespace(
            data={
                'qa_analytics': {
                    'enabled': True,
                    'retention_days': 90,
                    'mask_ip': True,
                    'word_cloud_sample_size': 100,
                    'word_cloud_words': 20,
                }
            }
        ),
        logger=Mock(),
        persistence_mgr=SimpleNamespace(tenant_uow=tenant_uow),
        plugin_connector=SimpleNamespace(get_plugin_assets=get_plugin_assets),
    )
    service = QAAnalyticsService(app)
    yield service, engine
    await engine.dispose()


async def _insert(engine, **overrides):
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    values = {
        'id': str(uuid.uuid4()),
        'workspace_uuid': WORKSPACE,
        'query_uuid': str(uuid.uuid4()),
        'session_key': f'bot:embed:{uuid.uuid4()}',
        'bot_uuid': BOT_A,
        'question': '问题',
        'rewritten_question': None,
        'answer': '回答',
        'normalized_question': '问题',
        'normalized_group_question': '问题',
        'latency_ms': 100,
        'visitor_ip': '203.0.113.42',
        'region': 'Shanghai',
        'created_at': now,
        'finished_at': now,
    }
    values.update(overrides)
    async with engine.begin() as connection:
        await connection.execute(sqlalchemy.insert(QAAnalyticsRecord).values(**values))
    return values


async def _insert_bot(engine, bot_uuid=BOT_A, name='Admissions', workspace_uuid=WORKSPACE):
    async with engine.begin() as connection:
        await connection.execute(
            sqlalchemy.insert(Bot).values(
                uuid=bot_uuid,
                workspace_uuid=workspace_uuid,
                name=name,
                description='',
                adapter='websocket',
                adapter_config={},
                enable=True,
            )
        )


async def _seed(engine):
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    first = await _insert(
        engine,
        session_key='bot:embed:session-a',
        question='护理专业能去哪些科室',
        rewritten_question='护理专业就业方向',
        normalized_question='护理专业能去哪些科室',
        normalized_group_question='护理专业就业方向',
        latency_ms=100,
        created_at=now - datetime.timedelta(hours=1),
    )
    second = await _insert(
        engine,
        session_key='bot:embed:session-a',
        question='护理专业能去哪些科室',
        rewritten_question='护理专业就业方向',
        normalized_question='护理专业能去哪些科室',
        normalized_group_question='护理专业就业方向',
        latency_ms=200,
        created_at=now - datetime.timedelta(hours=2),
    )
    third = await _insert(
        engine,
        session_key='bot:embed:session-b',
        bot_uuid=BOT_B,
        question='学费是多少',
        rewritten_question=None,
        normalized_question='学费是多少',
        normalized_group_question='学费是多少',
        latency_ms=300,
        visitor_ip='198.51.100.7',
        region='Beijing',
        created_at=now - datetime.timedelta(hours=3),
    )
    return first, second, third


def _query(message: str, answer: str = '这是回答') -> SimpleNamespace:
    query = SimpleNamespace(
        bot_uuid=None,
        pipeline_uuid=None,
        query_uuid=None,
        launcher_type='person',
        launcher_id='visitor-1',
        variables={'user_message_text': message},
        resp_message_chain=[],
        resp_messages=[SimpleNamespace(content=answer)],
        message_event=SimpleNamespace(
            _qa_visitor_ip='10.1.2.3',
            _qa_session_id='session-x',
        ),
    )
    query._execution_context = ExecutionContext(
        instance_uuid='instance-a',
        workspace_uuid=WORKSPACE,
        placement_generation=1,
    )
    return query


class TestRanges:
    def test_today_uses_visitor_timezone(self, database):
        service, _ = database
        now = datetime.datetime(2026, 10, 26, 10, 30, tzinfo=datetime.timezone.utc)
        key, start, end = service.resolve_range('today', -480, now=now)
        assert key == 'today'
        assert start == datetime.datetime(2026, 10, 25, 16, 0)
        assert end == datetime.datetime(2026, 10, 26, 10, 30)

    def test_rolling_and_all_ranges(self, database):
        service, _ = database
        now = datetime.datetime(2026, 10, 26, 10, 30, tzinfo=datetime.timezone.utc)
        _, start, _ = service.resolve_range('7d', 0, now=now)
        assert start == now.replace(tzinfo=None) - datetime.timedelta(days=7)
        _, start, _ = service.resolve_range('30d', 0, now=now)
        assert start == now.replace(tzinfo=None) - datetime.timedelta(days=30)
        key, start, _ = service.resolve_range('all', 0, now=now)
        assert key == 'all'
        assert start is None
        assert service.resolve_range('invalid', 0, now=now)[0] == '7d'


class TestReadQueries:
    @pytest.mark.asyncio
    async def test_overview_aggregates_and_word_cloud(self, database):
        service, engine = database
        await _seed(engine)

        overview = await service.get_overview(WORKSPACE, '7d', 0)

        assert overview['total_questions'] == 3
        assert overview['independent_sessions'] == 2
        assert overview['high_frequency_types'] == 1
        assert overview['average_latency_ms'] == 200
        assert overview['top_questions'][0]['count'] == 2
        # Rankings show what the visitor asked, not a plugin-provided rewrite.
        assert overview['top_questions'][0]['question'] == '护理专业能去哪些科室'
        words = {item['word']: item['count'] for item in overview['word_cloud']}
        assert words['护理'] == 2
        assert words['学费'] == 1

    @pytest.mark.asyncio
    async def test_overview_and_tables_filter_by_bot(self, database):
        service, engine = database
        await _seed(engine)

        overview = await service.get_overview(WORKSPACE, '7d', 0, bot_uuid=BOT_A)
        assert overview['total_questions'] == 2
        assert overview['independent_sessions'] == 1
        assert overview['average_latency_ms'] == 150

        questions = await service.get_questions(WORKSPACE, '7d', 0, bot_uuid=BOT_B)
        assert questions['total'] == 1
        assert questions['items'][0]['question'] == '学费是多少'

        visits = await service.get_visits(WORKSPACE, '7d', 0, bot_uuid=BOT_B)
        assert visits['total'] == 1
        assert visits['items'][0]['rounds'] == 1

    @pytest.mark.asyncio
    async def test_bot_list_and_detail_are_workspace_scoped(self, database):
        service, engine = database
        first, _, _ = await _seed(engine)
        await _insert_bot(engine, BOT_A, 'Admissions')
        await _insert_bot(engine, BOT_B, 'Student services')
        await _insert_bot(engine, 'other-bot', 'Other Workspace', OTHER_WORKSPACE)

        bots = await service.get_bots(WORKSPACE)
        assert [item['uuid'] for item in bots['items']] == [BOT_A, BOT_B]
        assert [item['name'] for item in bots['items']] == ['Admissions', 'Student services']

        other = await service.get_bots(OTHER_WORKSPACE)
        assert [item['uuid'] for item in other['items']] == ['other-bot']

        assert await service.get_question_detail(WORKSPACE, first['id'], BOT_A) is not None
        assert await service.get_question_detail(WORKSPACE, first['id'], BOT_B) is None

    @pytest.mark.asyncio
    async def test_questions_filter_mask_and_pagination(self, database):
        service, engine = database
        await _seed(engine)

        result = await service.get_questions(WORKSPACE, '7d', 0, keyword='学费')
        assert result['total'] == 1
        assert result['items'][0]['question'] == '学费是多少'
        assert result['items'][0]['visitor_ip'] == '198.51.*.*'

        by_ip = await service.get_questions(WORKSPACE, '7d', 0, visitor_ip='198.51.100.7')
        assert by_ip['total'] == 1

        by_region = await service.get_questions(WORKSPACE, '7d', 0, region='shang')
        assert by_region['total'] == 2
        by_region = await service.get_questions(WORKSPACE, '7d', 0, region='beijing')
        assert by_region['total'] == 1

        paged = await service.get_questions(WORKSPACE, '7d', 0, page=2, page_size=2)
        assert paged['total'] == 3
        assert len(paged['items']) == 1

    @pytest.mark.asyncio
    async def test_question_detail_is_workspace_scoped(self, database):
        service, engine = database
        first, _, _ = await _seed(engine)

        detail = await service.get_question_detail(WORKSPACE, first['id'])
        assert detail is not None
        assert detail['question'] == '护理专业能去哪些科室'
        assert detail['visitor_ip'] == '203.0.113.42'
        assert await service.get_question_detail(OTHER_WORKSPACE, first['id']) is None

    @pytest.mark.asyncio
    async def test_visits_group_sessions(self, database):
        service, engine = database
        await _seed(engine)

        visits = await service.get_visits(WORKSPACE, '7d', 0)

        assert visits['total'] == 2
        assert visits['items'][0]['rounds'] == 2
        assert visits['items'][1]['rounds'] == 1
        assert visits['items'][0]['dwell_seconds'] >= 0

    @pytest.mark.asyncio
    async def test_cleanup_deletes_only_expired_workspace_rows(self, database):
        service, engine = database
        old = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(days=40)
        await _insert(engine, created_at=old)
        await _insert(engine, created_at=old, workspace_uuid=OTHER_WORKSPACE)
        current = await _insert(engine)

        deleted = await service.cleanup_expired_records(
            SimpleNamespace(workspace_uuid=WORKSPACE),
            retention_days=30,
        )

        assert deleted == 1
        assert await service.get_question_detail(WORKSPACE, current['id']) is not None


class TestCollection:
    def test_retrieval_metadata_is_not_mistaken_for_a_rewritten_question(self):
        metadata = {
            'trace_id': 'retrieval-4e43b3f35aee',
            'trace_spans': [{'name': 'vector_search', 'trace_id': 'retrieval-4e43b3f35aee'}],
        }

        assert qa_context.extract_rewritten_question(metadata) == ''
        assert qa_context.extract_rewritten_question({'rewritten_question': '护理专业就业方向'}) == ('护理专业就业方向')
        assert qa_context.extract_rewritten_question({'nested': {'rewrittenQuery': '学费多少'}}) == '学费多少'

    @pytest.mark.asyncio
    async def test_embed_session_uses_widget_identity_and_visitor_ip(self, database):
        service, _ = database
        collection = service.begin_query(_query('护理专业能去哪些科室'))

        assert collection is not None
        assert collection.session_key.endswith(':embed:session-x')
        assert collection.visitor_ip == '10.1.2.3'

    @pytest.mark.asyncio
    async def test_non_embed_session_uses_launcher_identity(self, database):
        service, _ = database
        query = _query('学费是多少')
        query.message_event = SimpleNamespace()

        collection = service.begin_query(query)

        assert collection is not None
        assert collection.session_key.endswith(':person:visitor-1')
        assert collection.visitor_ip == ''

    @pytest.mark.asyncio
    async def test_disabled_dashboard_stops_collection(self, database):
        service, _ = database
        service.ap.instance_config.data['qa_analytics']['enabled'] = False

        assert service.begin_query(_query('学费是多少')) is None

    @pytest.mark.asyncio
    async def test_only_knowledge_base_queries_are_recorded(self, database):
        service, engine = database
        query = _query('护理专业能去哪些科室')
        collection = service.begin_query(query)
        assert collection is not None
        assert collection.workspace_uuid == WORKSPACE

        token = qa_context.current_collection_context.set(collection)
        try:
            await service.finish_query(query, collection)
        finally:
            qa_context.current_collection_context.reset(token)

        result = await service.get_questions(WORKSPACE, '7d', 0)
        assert result['total'] == 0

        query = _query('护理专业能去哪些科室')
        collection = service.begin_query(query)
        token = qa_context.current_collection_context.set(collection)
        try:
            qa_context.mark_knowledge_base_used()
            qa_context.record_rewritten_question({'rewritten_question': '护理专业就业方向'})
            await service.finish_query(query, collection)
        finally:
            qa_context.current_collection_context.reset(token)

        result = await service.get_questions(WORKSPACE, '7d', 0)
        assert result['total'] == 1
        detail = await service.get_question_detail(WORKSPACE, result['items'][0]['id'])
        assert detail is not None
        assert detail['question'] == '护理专业能去哪些科室'
        assert detail['rewritten_question'] == '护理专业就业方向'
        assert detail['answer'] == '这是回答'
        assert detail['region'] == 'local'
        assert query.variables['_qa_analytics_recorded'] is True

    @pytest.mark.asyncio
    async def test_knowledge_base_flag_survives_runtime_action_task(self, database):
        service, _ = database
        query = _query('学费是多少')
        collection = service.begin_query(query)
        assert collection is not None
        assert not collection.knowledge_base_used

        # Knowledge retrieval runs in the Plugin Runtime connector task, not
        # the pipeline task where begin_query stored the ContextVar.
        async def runtime_retrieval() -> None:
            with qa_context.bind_query_collection_context(query):
                qa_context.mark_knowledge_base_used()

        await asyncio.create_task(runtime_retrieval())
        assert collection.knowledge_base_used is True

        await service.finish_query(query, collection)
        result = await service.get_questions(WORKSPACE, '7d', 0)
        assert result['total'] == 1

    @pytest.mark.asyncio
    async def test_page_api_rejects_unknown_endpoint(self, database):
        service, _ = database
        with pytest.raises(ValueError, match='Unknown endpoint'):
            await service.handle_page_api(
                SimpleNamespace(workspace_uuid=WORKSPACE),
                '/qa-analytics/nope',
                'POST',
                {},
            )

    @pytest.mark.asyncio
    async def test_page_api_overview(self, database):
        service, engine = database
        await _seed(engine)
        data = await service.handle_page_api(
            SimpleNamespace(workspace_uuid=WORKSPACE),
            '/qa-analytics/overview',
            'POST',
            {'range': '7d', 'tz_offset_minutes': 0},
        )
        assert data['total_questions'] == 3

    @pytest.mark.asyncio
    async def test_page_api_serves_bot_list_and_applies_bot_filter(self, database):
        service, engine = database
        await _seed(engine)
        await _insert_bot(engine, BOT_A, 'Admissions')
        await _insert_bot(engine, BOT_B, 'Student services')
        execution_context = SimpleNamespace(workspace_uuid=WORKSPACE)

        bots = await service.handle_page_api(
            execution_context,
            '/qa-analytics/bots',
            'POST',
            {},
        )
        assert [item['uuid'] for item in bots['items']] == [BOT_A, BOT_B]

        overview = await service.handle_page_api(
            execution_context,
            '/qa-analytics/overview',
            'POST',
            {'range': '7d', 'tz_offset_minutes': 0, 'bot_uuid': BOT_B},
        )
        assert overview['total_questions'] == 1

        questions = await service.handle_page_api(
            execution_context,
            '/qa-analytics/questions',
            'POST',
            {'range': '7d', 'tz_offset_minutes': 0, 'bot_uuid': BOT_A},
        )
        assert questions['total'] == 2

    @pytest.mark.asyncio
    async def test_page_api_questions_detail_and_visits(self, database):
        service, engine = database
        first, _, _ = await _seed(engine)
        execution_context = SimpleNamespace(workspace_uuid=WORKSPACE)

        questions = await service.handle_page_api(
            execution_context,
            '/qa-analytics/questions',
            'POST',
            {'range': '7d', 'tz_offset_minutes': 0, 'keyword': '护理'},
        )
        assert questions['total'] == 2
        assert questions['items'][0]['visitor_ip'] == '203.0.*.*'

        detail = await service.handle_page_api(
            execution_context,
            '/qa-analytics/questions/detail',
            'POST',
            {'id': first['id']},
        )
        assert detail['question'] == '护理专业能去哪些科室'
        assert detail['visitor_ip'] == '203.0.113.42'

        visits = await service.handle_page_api(
            execution_context,
            '/qa-analytics/visits',
            'POST',
            {'range': '7d', 'tz_offset_minutes': 0},
        )
        assert visits['total'] == 2

    @pytest.mark.asyncio
    async def test_page_api_ownership_uses_configured_plugin_identity(self, database):
        service, _ = database
        assert service.owns_page_api('langbot-team', 'qa-analytics')
        assert not service.owns_page_api('other-team', 'qa-analytics')
        assert not service.owns_page_api('langbot-team', 'other-plugin')

    @pytest.mark.asyncio
    async def test_page_api_serves_plugin_translations(self, database):
        service, _ = database
        execution_context = SimpleNamespace(workspace_uuid=WORKSPACE)

        chinese = await service.handle_page_api(
            execution_context,
            '/qa-analytics/i18n',
            'POST',
            {'language': 'zh-Hans'},
        )
        assert chinese['tabs.stats'] == '问答统计'
        assert chinese['noRewrite'] == '未提供改写'

        fallback = await service.handle_page_api(
            execution_context,
            '/qa-analytics/i18n',
            'POST',
            {'language': 'xx-XX'},
        )
        assert fallback['tabs.stats'] == 'Overview'
