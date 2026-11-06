"""
API integration tests for the instance log endpoint.

The process log is global to the instance, so the route must expose it only to
the Default Workspace and must forward pagination pointers untouched.

Run: uv run pytest tests/integration/api/test_logs.py -q
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock, Mock
from types import SimpleNamespace

from tests.factories import FakeApp


pytestmark = pytest.mark.integration

DEFAULT_WORKSPACE_UUID = '00000000-0000-0000-0000-00000000000a'
OTHER_WORKSPACE_UUID = '00000000-0000-0000-0000-0000000000bb'


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
        'langbot.pkg.api.http.controller.groups.logs',
        'langbot.pkg.api.http.controller.main',
    ]

    with isolated_sys_modules(
        mocks={
            'langbot.pkg.core.app': mock_app,
            'langbot.pkg.core.entities': mock_entities,
        },
        clear=clear,
    ):
        import langbot.pkg.api.http.controller.groups.logs as _logs  # noqa: E402, F401

        yield


@pytest.fixture(scope='module')
def fake_logs_app():
    """Create FakeApp with auth, Workspace and log-cache dependencies."""
    app = FakeApp()

    app.instance_config.data.update(
        {
            'api': {'port': 5300},
            'system': {'allow_modify_login_info': True, 'limitation': {}},
        }
    )

    app.user_service = Mock()
    app.user_service.is_initialized = AsyncMock(return_value=True)
    app.user_service.verify_jwt_token = AsyncMock(return_value='test@example.com')
    account = SimpleNamespace(
        uuid='00000000-0000-0000-0000-000000000001',
        user='test@example.com',
    )
    app.user_service.get_authenticated_account = AsyncMock(return_value=account)
    app.user_service.get_user_by_email = AsyncMock(return_value=account)
    app.workspace_collaboration_service = SimpleNamespace(
        resolve_account_workspace=AsyncMock(
            return_value=SimpleNamespace(
                execution=SimpleNamespace(
                    instance_uuid='instance-logs-api',
                    placement_generation=1,
                ),
                workspace=SimpleNamespace(uuid=DEFAULT_WORKSPACE_UUID),
                membership=SimpleNamespace(
                    uuid='00000000-0000-0000-0000-000000000010',
                    role='owner',
                    projection_revision=0,
                ),
            )
        )
    )
    app.apikey_service = Mock()
    app.apikey_service.verify_api_key = AsyncMock(return_value=True)

    app.workspace_service = SimpleNamespace(
        get_default_workspace=AsyncMock(return_value=SimpleNamespace(uuid=DEFAULT_WORKSPACE_UUID)),
        get_execution_binding=AsyncMock(return_value=SimpleNamespace(placement_generation=1)),
    )

    app.log_cache = Mock()
    app.log_cache.get_log_by_pointer = Mock(return_value=('first line\nsecond line', 2, 17))

    return app


@pytest.fixture(autouse=True)
def reset_log_cache(fake_logs_app):
    fake_logs_app.log_cache.reset_mock()
    fake_logs_app.log_cache.get_log_by_pointer.side_effect = None
    fake_logs_app.log_cache.get_log_by_pointer.return_value = ('first line\nsecond line', 2, 17)


@pytest.fixture(scope='module')
async def quart_test_client(fake_logs_app, http_controller_cls):
    """Create a Quart test client for the logs route."""
    controller = http_controller_cls(fake_logs_app)
    await controller.initialize()

    client = controller.quart_app.test_client()
    yield client


@pytest.mark.usefixtures('mock_circular_import_chain')
class TestLogsEndpoint:
    """Tests for /api/v1/logs."""

    @pytest.mark.asyncio
    async def test_returns_log_page_from_default_workspace(self, quart_test_client, fake_logs_app):
        """GET /api/v1/logs returns the cache page and its next pointer."""
        response = await quart_test_client.get('/api/v1/logs', headers={'Authorization': 'Bearer test_token'})

        assert response.status_code == 200
        data = await response.get_json()
        assert data['code'] == 0
        assert data['data'] == {
            'logs': 'first line\nsecond line',
            'end_page_number': 2,
            'end_offset': 17,
        }

        fake_logs_app.workspace_service.get_execution_binding.assert_awaited_once_with(
            DEFAULT_WORKSPACE_UUID,
            expected_generation=1,
        )
        fake_logs_app.log_cache.get_log_by_pointer.assert_called_once_with(
            start_page_number=0,
            start_offset=0,
        )

    @pytest.mark.asyncio
    async def test_forwards_pagination_pointers(self, quart_test_client, fake_logs_app):
        """start_page_number and start_offset are passed through as integers."""
        response = await quart_test_client.get(
            '/api/v1/logs?start_page_number=3&start_offset=42',
            headers={'Authorization': 'Bearer test_token'},
        )

        assert response.status_code == 200
        fake_logs_app.log_cache.get_log_by_pointer.assert_called_once_with(
            start_page_number=3,
            start_offset=42,
        )

    @pytest.mark.asyncio
    async def test_non_default_workspace_cannot_read_instance_logs(
        self,
        quart_test_client,
        fake_logs_app,
    ):
        """A personal or tenant Workspace never sees another tenant's log lines."""
        fake_logs_app.workspace_collaboration_service.resolve_account_workspace.return_value = SimpleNamespace(
            execution=SimpleNamespace(
                instance_uuid='instance-logs-api',
                placement_generation=1,
            ),
            workspace=SimpleNamespace(uuid=OTHER_WORKSPACE_UUID),
            membership=SimpleNamespace(
                uuid='00000000-0000-0000-0000-000000000011',
                role='owner',
                projection_revision=0,
            ),
        )
        try:
            response = await quart_test_client.get(
                '/api/v1/logs',
                headers={'Authorization': 'Bearer test_token'},
            )
        finally:
            fake_logs_app.workspace_collaboration_service.resolve_account_workspace.return_value = SimpleNamespace(
                execution=SimpleNamespace(
                    instance_uuid='instance-logs-api',
                    placement_generation=1,
                ),
                workspace=SimpleNamespace(uuid=DEFAULT_WORKSPACE_UUID),
                membership=SimpleNamespace(
                    uuid='00000000-0000-0000-0000-000000000010',
                    role='owner',
                    projection_revision=0,
                ),
            )

        assert response.status_code == 404
        data = await response.get_json()
        assert data['code'] == 'resource_not_found'
        fake_logs_app.log_cache.get_log_by_pointer.assert_not_called()

    @pytest.mark.asyncio
    async def test_requires_authentication(self, quart_test_client, fake_logs_app):
        """Instance logs are unavailable without a token."""
        response = await quart_test_client.get('/api/v1/logs')

        assert response.status_code == 401
        fake_logs_app.log_cache.get_log_by_pointer.assert_not_called()
