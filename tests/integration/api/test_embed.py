"""
API integration tests for embed widget endpoints.

Tests real HTTP API behavior for embed widget functionality.

Run: uv run pytest tests/integration/api/test_embed.py -q
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from unittest.mock import MagicMock, AsyncMock, Mock
from types import SimpleNamespace

from tests.factories import FakeApp


pytestmark = pytest.mark.integration
SESSION_ID = '31c0f2e9-b115-4ee6-8f15-3e624d6456b1'


@pytest.fixture(scope='module')
def mock_circular_import_chain():
    """Break circular import chain for API controller."""
    from tests.utils.import_isolation import isolated_sys_modules, MockLifecycleControlScope

    class FakeMinimalApplication:
        pass

    mock_app = MagicMock()
    mock_app.Application = FakeMinimalApplication

    mock_entities = MagicMock()
    mock_entities.LifecycleControlScope = MockLifecycleControlScope

    clear = [
        'langbot.pkg.api.http.controller.group',
        'langbot.pkg.api.http.controller.groups',
        'langbot.pkg.api.http.controller.groups.pipelines',
        'langbot.pkg.api.http.controller.groups.pipelines.embed',
        'langbot.pkg.api.http.controller.main',
    ]

    with isolated_sys_modules(
        mocks={
            'langbot.pkg.core.app': mock_app,
            'langbot.pkg.core.entities': mock_entities,
        },
        clear=clear,
    ):
        import langbot.pkg.api.http.controller.groups.pipelines.embed as _embed  # noqa: E402, F401

        yield


@pytest.fixture(scope='module')
def fake_embed_app():
    """Create FakeApp with embed widget services (module scope)."""
    app = FakeApp()

    app.instance_config.data.update(
        {
            'api': {'port': 5300},
            'system': {'allow_modify_login_info': True, 'limitation': {}},
        }
    )

    # Create mock web_page_bot with valid UUID format
    mock_bot_entity = Mock()
    mock_bot_entity.uuid = 'a1b2c3d4-5678-90ab-cdef-123456789abc'
    mock_bot_entity.adapter = 'web_page_bot'
    mock_bot_entity.enable = True
    mock_bot_entity.use_pipeline_uuid = 'test-pipeline-uuid'
    mock_bot_entity.name = 'Test Web Bot'
    mock_bot_entity.adapter_config = {
        'turnstile_secret_key': '',
        'turnstile_site_key': '',
        'language': 'en_US',
        'bubble_icon': 'logo',
    }

    mock_runtime_bot = Mock()
    mock_runtime_bot.bot_entity = mock_bot_entity
    mock_runtime_bot.get_pipeline_target_for_event_type = Mock(return_value='test-pipeline-uuid')
    mock_runtime_bot.execution_context = SimpleNamespace(
        instance_uuid='instance-test',
        workspace_uuid='workspace-test',
        placement_generation=1,
    )

    # Platform manager with bots
    app.platform_mgr = Mock()
    app.platform_mgr.bots = [mock_runtime_bot]
    app.platform_mgr.resolve_public_bot = AsyncMock(
        side_effect=lambda route_key: mock_runtime_bot if route_key == mock_bot_entity.uuid else None
    )

    # WebSocket proxy bot with adapter
    mock_websocket_adapter = Mock()
    mock_websocket_adapter.get_websocket_messages = Mock(return_value=[{'id': 'msg-1', 'content': 'test message'}])
    mock_websocket_adapter.reset_session = Mock()
    mock_websocket_adapter.handle_websocket_message = AsyncMock()

    mock_ws_proxy_bot = Mock()
    mock_ws_proxy_bot.adapter = mock_websocket_adapter
    app.platform_mgr.websocket_proxy_bot = mock_ws_proxy_bot
    app.platform_mgr.get_websocket_proxy_bot = AsyncMock(return_value=mock_ws_proxy_bot)
    app.workspace_service = SimpleNamespace(
        get_execution_binding=AsyncMock(
            return_value=SimpleNamespace(
                instance_uuid='instance-test',
                workspace_uuid='workspace-test',
                placement_generation=1,
            )
        )
    )

    # Monitoring service for feedback
    app.monitoring_service = Mock()
    app.monitoring_service.record_feedback = AsyncMock()

    # Q&A analytics owns the consultation message board storage.
    app.qa_analytics_service = Mock()
    app.qa_analytics_service.is_enabled = Mock(return_value=True)
    app.qa_analytics_service.submit_consult_message = AsyncMock(
        return_value={'id': 'consult-id', 'created_at': '2026-11-04T00:00:00Z'}
    )

    return app


@pytest.fixture(scope='module')
async def quart_test_client(fake_embed_app, http_controller_cls):
    """Create Quart test client (module scope)."""
    controller = http_controller_cls(fake_embed_app)
    await controller.initialize()

    client = controller.quart_app.test_client()
    yield client


@pytest.mark.usefixtures('mock_circular_import_chain')
class TestEmbedWidgetEndpoint:
    """Tests for widget.js endpoint."""

    @pytest.mark.asyncio
    async def test_get_widget_js_success(self, quart_test_client, fake_embed_app):
        """GET /api/v1/embed/{bot_uuid}/widget.js returns JS."""
        response = await quart_test_client.get('/api/v1/embed/a1b2c3d4-5678-90ab-cdef-123456789abc/widget.js')

        assert response.status_code == 200
        assert 'javascript' in response.content_type
        fake_embed_app.platform_mgr.resolve_public_bot.assert_any_await('a1b2c3d4-5678-90ab-cdef-123456789abc')

        body = await response.get_data(as_text=True)
        assert 'a1b2c3d4-5678-90ab-cdef-123456789abc' in body
        assert 'baseUrl: "http://localhost"' in body
        assert 'roleGroups: []' in body
        assert 'welcomeMessage: ""' in body
        assert '__LANGBOT_QUICK_QUESTIONS__' not in body
        assert '__LANGBOT_' not in body

    @pytest.mark.asyncio
    async def test_get_widget_js_injects_quick_question_groups(self, quart_test_client, fake_embed_app, monkeypatch):
        """Admin-configured groups are sanitized and injected as a JS array."""
        config = fake_embed_app.platform_mgr.bots[0].bot_entity.adapter_config
        raw = [
            {
                'id': 'group-a',
                'label': 'Group A',
                'questions': ['A1', ' A2 ', 'A1', '</script><b>x</b>'],
            },
            {
                'id': 'group-a',
                'label': 'Group B',
                'questions': 'B1\n\nB2',
            },
            {'id': 'empty-label', 'label': '   ', 'questions': ['dropped']},
        ]
        monkeypatch.setitem(config, 'quick_question_groups', raw)

        response = await quart_test_client.get('/api/v1/embed/a1b2c3d4-5678-90ab-cdef-123456789abc/widget.js')
        body = await response.get_data(as_text=True)

        expected = [
            {
                'id': 'group-a',
                'label': 'Group A',
                'questions': ['A1', 'A2', '</script><b>x</b>'],
            },
            {
                'id': 'group-a-2',
                'label': 'Group B',
                'questions': ['B1', 'B2'],
            },
        ]
        expected_json = json.dumps(expected, ensure_ascii=True).replace('<', '\\u003c')

        assert f'roleGroups: {expected_json}' in body
        assert '__LANGBOT_ROLE_GROUPS__' not in body
        assert '</script><b>x</b>' not in body

    @pytest.mark.asyncio
    async def test_get_widget_js_injects_welcome_message(self, quart_test_client, fake_embed_app, monkeypatch):
        """The saved welcome message is escaped and injected as a JS string."""
        config = fake_embed_app.platform_mgr.bots[0].bot_entity.adapter_config
        monkeypatch.setitem(config, 'welcome_message', ' 你好 </script>\n第二行 ')

        response = await quart_test_client.get('/api/v1/embed/a1b2c3d4-5678-90ab-cdef-123456789abc/widget.js')
        body = await response.get_data(as_text=True)

        expected_json = json.dumps('你好 </script>\n第二行', ensure_ascii=True).replace('<', '\\u003c')

        assert f'welcomeMessage: {expected_json}' in body
        assert '__LANGBOT_WELCOME_MESSAGE__' not in body
        assert '</script>' not in body

    def test_parse_quick_question_groups_normalizes_and_limits(self):
        """Group parser accepts arrays/JSON strings and applies every bound."""
        import langbot.pkg.api.http.controller.groups.pipelines.embed as embed

        assert embed._parse_quick_question_groups(None) == []
        assert embed._parse_quick_question_groups('not json') == []
        assert embed._parse_quick_question_groups(123) == []

        parsed = embed._parse_quick_question_groups(
            json.dumps(
                [
                    {'label': ' A ', 'questions': [' q1 ', '', 'q1']},
                    {'id': 'custom', 'label': 'B', 'questions': 'b1\nb2'},
                    {'id': 'custom', 'label': 'C', 'questions': []},
                    {'label': '   ', 'questions': ['dropped']},
                    {'id': 'x' * 100, 'label': 'y' * 50, 'questions': ['z']},
                ]
            )
        )
        assert parsed == [
            {'id': 'group-1', 'label': 'A', 'questions': ['q1']},
            {'id': 'custom', 'label': 'B', 'questions': ['b1', 'b2']},
            {'id': 'custom-2', 'label': 'C', 'questions': []},
            {'id': 'x' * 64, 'label': 'y' * 32, 'questions': ['z']},
        ]

        capped = embed._parse_quick_question_groups([{'label': f'G{i}', 'questions': []} for i in range(10)])
        assert [group['label'] for group in capped] == [f'G{i}' for i in range(6)]

        long_questions = [
            {
                'label': 'Long',
                'questions': ['x' * 250] + [f'Q{i}' for i in range(20)],
            }
        ]
        questions = embed._parse_quick_question_groups(long_questions)[0]['questions']
        assert len(questions) == 12
        assert questions[0] == 'x' * 200

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ('query', 'expected_base'),
        [('', 'https://public.example/bot'), ('?preview=wizard', 'http://localhost')],
    )
    async def test_widget_preview_uses_current_backend(
        self, quart_test_client, fake_embed_app, monkeypatch, query, expected_base
    ):
        monkeypatch.setitem(fake_embed_app.instance_config.data['api'], 'webhook_prefix', 'https://public.example/bot')
        response = await quart_test_client.get('/api/v1/embed/a1b2c3d4-5678-90ab-cdef-123456789abc/widget.js' + query)
        assert response.status_code == 200
        body = await response.get_data(as_text=True)
        assert f'baseUrl: "{expected_base}"' in body
        assert f'logoUrl: "{expected_base}"' in body

    def test_widget_template_cache_reloads_after_file_change(self, monkeypatch, tmp_path):
        """Development edits to widget.js take effect without restarting the backend."""
        import langbot.pkg.api.http.controller.groups.pipelines.embed as embed

        template_path = tmp_path / 'widget.js'
        template_path.write_text('first version', encoding='utf-8')
        monkeypatch.setattr(embed.paths, 'get_resource_path', lambda _: str(template_path))
        embed._widget_template_cache = None
        embed._widget_template_cache_mtime_ns = None

        assert embed._get_widget_template() == 'first version'

        previous_mtime_ns = template_path.stat().st_mtime_ns
        template_path.write_text('second version', encoding='utf-8')
        os.utime(template_path, ns=(previous_mtime_ns + 1_000_000, previous_mtime_ns + 1_000_000))

        assert embed._get_widget_template() == 'second version'

    @pytest.mark.asyncio
    async def test_get_widget_js_invalid_uuid(self, quart_test_client):
        """GET widget.js with invalid UUID returns 400."""
        response = await quart_test_client.get('/api/v1/embed/invalid-uuid/widget.js')

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_get_widget_js_bot_not_found(self, quart_test_client):
        """GET widget.js for non-existent bot returns 404."""
        response = await quart_test_client.get('/api/v1/embed/00000000-0000-0000-0000-000000000000/widget.js')

        assert response.status_code == 404


@pytest.mark.usefixtures('mock_circular_import_chain')
class TestEmbedLogoEndpoint:
    """Tests for logo endpoint."""

    @pytest.mark.asyncio
    async def test_get_logo_success(self, quart_test_client):
        """GET /api/v1/embed/logo returns image."""
        response = await quart_test_client.get('/api/v1/embed/logo')

        assert response.status_code == 200
        assert 'image/webp' in response.content_type

        body = await response.get_data()
        assert body == (Path(__file__).parents[3] / 'src/langbot/templates/embed/logo.webp').read_bytes()
        assert body[:4] == b'RIFF' and body[8:12] == b'WEBP'


@pytest.mark.usefixtures('mock_circular_import_chain')
class TestEmbedTurnstileVerifyEndpoint:
    """Tests for Turnstile verification endpoint."""

    @pytest.mark.asyncio
    async def test_turnstile_verify_no_secret(self, quart_test_client, monkeypatch):
        """POST turnstile verify without secret returns dummy token."""
        import langbot.pkg.api.http.controller.groups.pipelines.embed as embed

        monkeypatch.setattr(embed.time, 'time', lambda: 1720000000.25)
        response = await quart_test_client.post(
            '/api/v1/embed/a1b2c3d4-5678-90ab-cdef-123456789abc/turnstile/verify', json={'token': 'test-token'}
        )

        assert response.status_code == 200
        data = await response.get_json()
        assert data['code'] == 0
        assert 'token' in data['data']

        assert data['data']['token'] == '1720000000.25.dummy'

    @pytest.mark.asyncio
    async def test_turnstile_verify_invalid_uuid(self, quart_test_client):
        """POST turnstile verify with invalid UUID returns 400."""
        response = await quart_test_client.post(
            '/api/v1/embed/invalid-uuid/turnstile/verify', json={'token': 'test-token'}
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_turnstile_verify_missing_token(self, quart_test_client):
        """POST turnstile verify without token returns 400."""
        response = await quart_test_client.post(
            '/api/v1/embed/a1b2c3d4-5678-90ab-cdef-123456789abc/turnstile/verify', json={}
        )

        assert response.status_code == 400


@pytest.mark.usefixtures('mock_circular_import_chain')
class TestEmbedMessagesEndpoint:
    """Tests for messages endpoint."""

    @pytest.mark.asyncio
    async def test_get_messages_person_success(self, quart_test_client, fake_embed_app):
        """GET messages/person returns messages."""
        response = await quart_test_client.get(
            f'/api/v1/embed/a1b2c3d4-5678-90ab-cdef-123456789abc/messages/person?session_id={SESSION_ID}',
            headers={'Authorization': 'Bearer 1234567890.dummy'},
        )

        assert response.status_code == 200
        data = await response.get_json()
        assert data['code'] == 0
        assert 'messages' in data['data']
        proxy_bot = fake_embed_app.platform_mgr.get_websocket_proxy_bot.return_value
        proxy_bot.adapter.get_websocket_messages.assert_called_with('test-pipeline-uuid', 'person', SESSION_ID)

    @pytest.mark.asyncio
    async def test_get_messages_group_success(self, quart_test_client, fake_embed_app):
        """GET messages/group returns messages."""
        response = await quart_test_client.get(
            f'/api/v1/embed/a1b2c3d4-5678-90ab-cdef-123456789abc/messages/group?session_id={SESSION_ID}',
            headers={'Authorization': 'Bearer 1234567890.dummy'},
        )

        assert response.status_code == 200

        data = await response.get_json()
        assert data['code'] == 0
        assert data['data']['messages'] == [{'id': 'msg-1', 'content': 'test message'}]
        adapter = fake_embed_app.platform_mgr.get_websocket_proxy_bot.return_value.adapter
        adapter.get_websocket_messages.assert_called_with('test-pipeline-uuid', 'group', SESSION_ID)

    @pytest.mark.asyncio
    async def test_get_messages_requires_session_id(self, quart_test_client):
        """GET messages without a client session identifier returns 400."""
        response = await quart_test_client.get(
            '/api/v1/embed/a1b2c3d4-5678-90ab-cdef-123456789abc/messages/person',
            headers={'Authorization': 'Bearer 1234567890.dummy'},
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_get_messages_invalid_session_type(self, quart_test_client):
        """GET messages with invalid session_type returns 400."""
        response = await quart_test_client.get(
            f'/api/v1/embed/a1b2c3d4-5678-90ab-cdef-123456789abc/messages/invalid?session_id={SESSION_ID}',
            headers={'Authorization': 'Bearer 1234567890.dummy'},
        )

        assert response.status_code == 400

        assert (await response.get_json())['msg'] == 'session_type must be person or group'


@pytest.mark.usefixtures('mock_circular_import_chain')
class TestEmbedResetEndpoint:
    """Tests for session reset endpoint."""

    @pytest.mark.asyncio
    async def test_reset_session_person_success(self, quart_test_client, fake_embed_app):
        """POST reset/person resets session."""
        response = await quart_test_client.post(
            f'/api/v1/embed/a1b2c3d4-5678-90ab-cdef-123456789abc/reset/person?session_id={SESSION_ID}',
            headers={'Authorization': 'Bearer 1234567890.dummy'},
        )

        assert response.status_code == 200
        data = await response.get_json()
        assert data['code'] == 0
        proxy_bot = fake_embed_app.platform_mgr.get_websocket_proxy_bot.return_value
        proxy_bot.adapter.reset_session.assert_called_with('test-pipeline-uuid', 'person', SESSION_ID)

    @pytest.mark.asyncio
    async def test_reset_session_requires_session_id(self, quart_test_client):
        """POST reset without a client session identifier returns 400."""
        response = await quart_test_client.post(
            '/api/v1/embed/a1b2c3d4-5678-90ab-cdef-123456789abc/reset/person',
            headers={'Authorization': 'Bearer 1234567890.dummy'},
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_reset_session_invalid_uuid(self, quart_test_client):
        """POST reset with invalid UUID returns 400."""
        response = await quart_test_client.post(
            '/api/v1/embed/invalid-uuid/reset/person', headers={'Authorization': 'Bearer 1234567890.dummy'}
        )

        assert response.status_code == 400


@pytest.mark.usefixtures('mock_circular_import_chain')
class TestEmbedFeedbackEndpoint:
    """Tests for feedback submission endpoint."""

    @pytest.mark.asyncio
    async def test_submit_feedback_like(self, quart_test_client, fake_embed_app, monkeypatch):
        """POST feedback with type=1 (like) succeeds."""
        import langbot.pkg.api.http.controller.groups.pipelines.embed as embed

        monkeypatch.setattr(embed.uuid, 'uuid4', lambda: SimpleNamespace(hex='123456789abcdef0123456789abcdef0'))
        fake_embed_app.monitoring_service.record_feedback.reset_mock()
        response = await quart_test_client.post(
            '/api/v1/embed/a1b2c3d4-5678-90ab-cdef-123456789abc/feedback',
            headers={'Authorization': 'Bearer 1234567890.dummy'},
            json={'message_id': 'msg-123', 'feedback_type': 1},
        )

        assert response.status_code == 200
        data = await response.get_json()
        assert data['code'] == 0
        assert 'feedback_id' in data['data']

        data = await response.get_json()
        assert data['code'] == 0
        assert data['data']['feedback_id'] == 'embed_123456789abc'
        called = fake_embed_app.monitoring_service.record_feedback
        assert called.await_count == 1
        assert called.await_args.args[0].workspace_uuid == 'workspace-test'
        assert called.await_args.kwargs == {
            'feedback_id': 'embed_123456789abc',
            'feedback_type': 1,
            'bot_id': 'a1b2c3d4-5678-90ab-cdef-123456789abc',
            'bot_name': 'Test Web Bot',
            'pipeline_id': 'test-pipeline-uuid',
            'message_id': 'msg-123',
            'platform': 'web_page_bot',
        }

    @pytest.mark.asyncio
    async def test_submit_feedback_dislike(self, quart_test_client, fake_embed_app, monkeypatch):
        """POST feedback with type=2 (dislike) succeeds."""
        import langbot.pkg.api.http.controller.groups.pipelines.embed as embed

        monkeypatch.setattr(embed.uuid, 'uuid4', lambda: SimpleNamespace(hex='123456789abcdef0123456789abcdef0'))
        fake_embed_app.monitoring_service.record_feedback.reset_mock()
        response = await quart_test_client.post(
            '/api/v1/embed/a1b2c3d4-5678-90ab-cdef-123456789abc/feedback',
            headers={'Authorization': 'Bearer 1234567890.dummy'},
            json={'message_id': 'msg-123', 'feedback_type': 2},
        )

        assert response.status_code == 200

        data = await response.get_json()
        assert data['code'] == 0
        assert data['data']['feedback_id'] == 'embed_123456789abc'
        called = fake_embed_app.monitoring_service.record_feedback
        assert called.await_count == 1
        assert called.await_args.args[0].workspace_uuid == 'workspace-test'
        assert called.await_args.kwargs == {
            'feedback_id': 'embed_123456789abc',
            'feedback_type': 2,
            'bot_id': 'a1b2c3d4-5678-90ab-cdef-123456789abc',
            'bot_name': 'Test Web Bot',
            'pipeline_id': 'test-pipeline-uuid',
            'message_id': 'msg-123',
            'platform': 'web_page_bot',
        }

    @pytest.mark.asyncio
    async def test_submit_feedback_invalid_type(self, quart_test_client):
        """POST feedback with invalid type returns 400."""
        response = await quart_test_client.post(
            '/api/v1/embed/a1b2c3d4-5678-90ab-cdef-123456789abc/feedback',
            headers={'Authorization': 'Bearer 1234567890.dummy'},
            json={'message_id': 'msg-123', 'feedback_type': 99},
        )

        assert response.status_code == 400


@pytest.mark.usefixtures('mock_circular_import_chain')
class TestEmbedConsultMessagesEndpoint:
    """Tests for the standalone consultation page message board endpoint."""

    BOT_UUID = 'a1b2c3d4-5678-90ab-cdef-123456789abc'
    URL = f'/api/v1/embed/{BOT_UUID}/consult-messages'

    @pytest.fixture(autouse=True)
    def reset_rate_limit(self, monkeypatch):
        import langbot.pkg.api.http.controller.groups.pipelines.embed as embed

        monkeypatch.setattr(embed, '_consult_rate_windows', {})

    @pytest.fixture(autouse=True)
    def reset_submit_mock(self, fake_embed_app):
        fake_embed_app.qa_analytics_service.submit_consult_message.reset_mock()

    @pytest.mark.asyncio
    async def test_submit_uses_bot_workspace_and_hides_details(self, quart_test_client, fake_embed_app):
        payload = {
            'province': '广东省',
            'city': '广州市',
            'name': '张三',
            'score': '520',
            'contact': '13800000000',
        }
        response = await quart_test_client.post(self.URL, json=payload)

        assert response.status_code == 200
        body = await response.get_json()
        assert body == {'code': 0, 'msg': 'ok', 'data': {'ok': True}}
        text = json.dumps(body, ensure_ascii=False)
        assert '张三' not in text
        assert '13800000000' not in text

        called = fake_embed_app.qa_analytics_service.submit_consult_message
        assert called.await_count == 1
        assert called.await_args.args[0] == 'workspace-test'
        assert called.await_args.args[1] == self.BOT_UUID
        assert called.await_args.args[2] == payload

    @pytest.mark.asyncio
    async def test_invalid_bot_uuid_returns_400(self, quart_test_client, fake_embed_app):
        response = await quart_test_client.post(
            '/api/v1/embed/not-a-uuid/consult-messages',
            json={'province': '广东省'},
        )

        assert response.status_code == 400
        fake_embed_app.qa_analytics_service.submit_consult_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_bot_returns_404(self, quart_test_client, fake_embed_app):
        response = await quart_test_client.post(
            '/api/v1/embed/00000000-0000-0000-0000-000000000000/consult-messages',
            json={'province': '广东省'},
        )

        assert response.status_code == 404
        fake_embed_app.qa_analytics_service.submit_consult_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_object_body_returns_400(self, quart_test_client, fake_embed_app):
        response = await quart_test_client.post(
            self.URL,
            data='not json',
            headers={'Content-Type': 'application/json'},
        )

        assert response.status_code == 400
        fake_embed_app.qa_analytics_service.submit_consult_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_field_returns_400(self, quart_test_client, fake_embed_app, monkeypatch):
        monkeypatch.setattr(
            fake_embed_app.qa_analytics_service,
            'submit_consult_message',
            AsyncMock(side_effect=ValueError('province is required')),
        )
        response = await quart_test_client.post(self.URL, json={'city': '广州市'})

        assert response.status_code == 400
        body = await response.get_json()
        assert body['msg'] == 'province is required'

    @pytest.mark.asyncio
    async def test_disabled_analytics_returns_503(self, quart_test_client, fake_embed_app, monkeypatch):
        monkeypatch.setattr(fake_embed_app.qa_analytics_service, 'is_enabled', Mock(return_value=False))
        response = await quart_test_client.post(
            self.URL,
            json={'province': '广东省', 'city': '广州市', 'name': '张三', 'score': '520', 'contact': '1'},
        )

        assert response.status_code == 503
        fake_embed_app.qa_analytics_service.submit_consult_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rate_limit_returns_429(self, quart_test_client, fake_embed_app, monkeypatch):
        import langbot.pkg.api.http.controller.groups.pipelines.embed as embed

        monkeypatch.setattr(embed, '_CONSULT_RATE_LIMIT', 0)
        response = await quart_test_client.post(
            self.URL,
            json={'province': '广东省', 'city': '广州市', 'name': '张三', 'score': '520', 'contact': '1'},
        )

        assert response.status_code == 429
        fake_embed_app.qa_analytics_service.submit_consult_message.assert_not_awaited()


@pytest.mark.usefixtures('mock_circular_import_chain')
class TestEmbedWebSocketEndpoint:
    """The public socket authenticates before resolving shared runtime state."""

    @pytest.mark.asyncio
    async def test_authenticates_before_connecting(self, quart_test_client, fake_embed_app, monkeypatch):
        import langbot.pkg.api.http.controller.groups.pipelines.embed as embed

        authenticated = False
        original_authenticate = embed.EmbedRouterGroup._authenticate_websocket
        original_add = embed.ws_connection_manager.add_connection
        proxy = fake_embed_app.platform_mgr.get_websocket_proxy_bot

        async def authenticate(router, runtime_bot):
            nonlocal authenticated
            await original_authenticate(router, runtime_bot)
            authenticated = True

        async def get_proxy(*_args, **_kwargs):
            assert authenticated, 'Runtime lookup must follow successful authentication'
            return proxy.return_value

        async def add_connection(*args, **kwargs):
            assert authenticated, 'Connection registration must follow successful authentication'
            return await original_add(*args, **kwargs)

        monkeypatch.setattr(embed.EmbedRouterGroup, '_authenticate_websocket', authenticate)
        monkeypatch.setattr(proxy, 'side_effect', get_proxy)
        monkeypatch.setattr(embed.ws_connection_manager, 'add_connection', add_connection)
        async with quart_test_client.websocket(
            f'/api/v1/embed/a1b2c3d4-5678-90ab-cdef-123456789abc/ws/connect'
            f'?session_type=person&session_id={SESSION_ID}',
            headers={'Origin': 'http://localhost'},
        ) as websocket:
            await websocket.send(json.dumps({'type': 'authenticate', 'token': ''}))
            connected = json.loads(await websocket.receive())
            assert connected['type'] == 'connected'
            assert connected['bot_uuid'] == 'a1b2c3d4-5678-90ab-cdef-123456789abc'
            await websocket.send(json.dumps({'type': 'disconnect'}))

        fake_embed_app.workspace_service.get_execution_binding.assert_awaited_with(
            'workspace-test',
            expected_generation=1,
        )

    @pytest.mark.asyncio
    async def test_rejects_non_auth_first_frame_before_runtime_lookup(self, quart_test_client, fake_embed_app):
        fake_embed_app.platform_mgr.get_websocket_proxy_bot.reset_mock()

        async with quart_test_client.websocket(
            f'/api/v1/embed/a1b2c3d4-5678-90ab-cdef-123456789abc/ws/connect'
            f'?session_type=person&session_id={SESSION_ID}',
            headers={'Origin': 'http://localhost'},
        ) as websocket:
            await websocket.send(json.dumps({'type': 'message', 'message': []}))
            response = json.loads(await websocket.receive())
            assert response == {'type': 'error', 'message': 'Unauthorized'}

        fake_embed_app.platform_mgr.get_websocket_proxy_bot.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_invalid_turnstile_session_before_runtime_lookup(self, quart_test_client, fake_embed_app):
        fake_embed_app.platform_mgr.get_websocket_proxy_bot.reset_mock()
        config = fake_embed_app.platform_mgr.resolve_public_bot.side_effect(
            'a1b2c3d4-5678-90ab-cdef-123456789abc'
        ).bot_entity.adapter_config
        config['turnstile_secret_key'] = 'test-secret'
        try:
            async with quart_test_client.websocket(
                f'/api/v1/embed/a1b2c3d4-5678-90ab-cdef-123456789abc/ws/connect'
                f'?session_type=person&session_id={SESSION_ID}',
                headers={'Origin': 'http://localhost'},
            ) as websocket:
                await websocket.send(json.dumps({'type': 'authenticate', 'token': 'invalid'}))
                response = json.loads(await websocket.receive())
                assert response == {'type': 'error', 'message': 'Unauthorized'}
        finally:
            config['turnstile_secret_key'] = ''

        fake_embed_app.platform_mgr.get_websocket_proxy_bot.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_message_when_bot_is_disabled_after_connect(self, quart_test_client, fake_embed_app):
        runtime_bot = fake_embed_app.platform_mgr.resolve_public_bot.side_effect('a1b2c3d4-5678-90ab-cdef-123456789abc')
        adapter = fake_embed_app.platform_mgr.get_websocket_proxy_bot.return_value.adapter
        adapter.handle_websocket_message.reset_mock()

        async with quart_test_client.websocket(
            f'/api/v1/embed/a1b2c3d4-5678-90ab-cdef-123456789abc/ws/connect'
            f'?session_type=person&session_id={SESSION_ID}',
            headers={'Origin': 'http://localhost'},
        ) as websocket:
            await websocket.send(json.dumps({'type': 'authenticate', 'token': ''}))
            connected = json.loads(await websocket.receive())
            assert connected['type'] == 'connected'
            # WebSocket handlers have no request context; the visitor IP must
            # still be captured from the WebSocket object.
            from langbot.pkg.platform.sources.websocket_manager import ws_connection_manager

            connection = ws_connection_manager.connections.get(connected['connection_id'])
            assert connection is not None
            assert connection.metadata.get('client_ip')
            runtime_bot.bot_entity.enable = False
            try:
                await websocket.send(json.dumps({'type': 'message', 'message': [{'type': 'text', 'text': 'hi'}]}))
                response = json.loads(await websocket.receive())
                assert response == {'type': 'error', 'message': 'Bot is unavailable'}
            finally:
                runtime_bot.bot_entity.enable = True

        adapter.handle_websocket_message.assert_not_awaited()
