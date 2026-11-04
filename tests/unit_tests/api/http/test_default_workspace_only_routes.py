from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import quart

from langbot.pkg.api.http.controller.groups.logs import LogsRouterGroup
from langbot.pkg.workspace.policy import PersonalWorkspacePolicy


pytestmark = pytest.mark.asyncio

DEFAULT_WORKSPACE_UUID = '00000000-0000-4000-8000-0000000000d1'
PERSONAL_WORKSPACE_UUID = '00000000-0000-4000-8000-0000000000d2'


def _application() -> SimpleNamespace:
    workspace_service = SimpleNamespace(
        policy=PersonalWorkspacePolicy(),
        get_default_workspace=AsyncMock(
            return_value=SimpleNamespace(uuid=DEFAULT_WORKSPACE_UUID),
        ),
        get_execution_binding=AsyncMock(return_value=SimpleNamespace()),
    )
    return SimpleNamespace(
        deployment=SimpleNamespace(mode='oss', multi_workspace_enabled=False),
        workspace_service=workspace_service,
        workspace_collaboration_service=SimpleNamespace(
            resolve_account_workspace=AsyncMock(return_value=None),
        ),
        user_service=SimpleNamespace(
            get_authenticated_account=AsyncMock(
                return_value=SimpleNamespace(
                    uuid='00000000-0000-4000-8000-0000000000a1',
                    user='owner@example.com',
                    normalized_email='owner@example.com',
                )
            ),
        ),
        log_cache=SimpleNamespace(get_log_by_pointer=Mock(return_value=('', 0, 0))),
        logger=Mock(),
    )


def _access(workspace_uuid: str) -> SimpleNamespace:
    return SimpleNamespace(
        workspace=SimpleNamespace(uuid=workspace_uuid, source='local', created_at=None),
        membership=SimpleNamespace(uuid='membership-a', role='owner', projection_revision=0),
        execution=SimpleNamespace(instance_uuid='instance-a', placement_generation=1),
    )


async def _client(application) -> quart.testing.QuartClient:
    quart_app = quart.Quart(__name__)
    await LogsRouterGroup(application, quart_app).initialize()
    return quart_app.test_client()


async def test_process_logs_are_hidden_from_personal_workspaces():
    application = _application()
    application.workspace_collaboration_service.resolve_account_workspace = AsyncMock(
        return_value=_access(PERSONAL_WORKSPACE_UUID),
    )
    client = await _client(application)

    response = await client.get('/api/v1/logs', headers={'Authorization': 'Bearer token'})

    assert response.status_code == 404
    assert (await response.get_json())['code'] == 'resource_not_found'
    application.log_cache.get_log_by_pointer.assert_not_called()


async def test_process_logs_remain_available_in_the_default_workspace():
    application = _application()
    application.workspace_collaboration_service.resolve_account_workspace = AsyncMock(
        return_value=_access(DEFAULT_WORKSPACE_UUID),
    )
    client = await _client(application)

    response = await client.get('/api/v1/logs', headers={'Authorization': 'Bearer token'})

    assert response.status_code == 200
    assert (await response.get_json())['data'] == {
        'logs': '',
        'end_page_number': 0,
        'end_offset': 0,
    }
