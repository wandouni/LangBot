from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy
from quart import Quart
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from langbot.pkg.api.http.controller.groups.workspaces import (
    InvitationsRouterGroup,
    WorkspacesRouterGroup,
)
from langbot.pkg.api.http.service.user import UserService
from langbot.pkg.entity.persistence.base import Base
from langbot.pkg.entity.persistence.user import User
from langbot.pkg.entity.persistence.workspace import WorkspaceMembership
from langbot.pkg.persistence.mgr import PersistenceManager
from langbot.pkg.workspace.collaboration import WorkspaceCollaborationService
from langbot.pkg.workspace.policy import PersonalWorkspacePolicy
from langbot.pkg.workspace.service import WorkspaceService


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

INSTANCE_UUID = 'instance-personal-api'


@pytest.fixture
async def personal_workspace_api(tmp_path):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "personal-api.db"}')
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    application = SimpleNamespace()
    application.persistence_mgr = PersistenceManager(application)
    application.persistence_mgr.db = SimpleNamespace(get_engine=lambda: engine)
    application.instance_config = SimpleNamespace(
        data={
            'system': {
                'jwt': {'secret': 'personal-api-secret', 'expire': 3600},
                'allow_modify_login_info': True,
            },
            'api': {'global_api_key': '', 'webui_url': 'https://langbot.example'},
        }
    )
    application.logger = logging.getLogger('personal-workspace-api-test')
    application.workspace_service = WorkspaceService(
        application,
        policy=PersonalWorkspacePolicy(),
        instance_uuid=INSTANCE_UUID,
    )
    application.workspace_collaboration_service = WorkspaceCollaborationService(
        application,
        application.workspace_service,
    )
    application.user_service = UserService(application)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    admin = User(
        uuid=str(uuid.uuid4()),
        user='admin@example.com',
        normalized_email='admin@example.com',
        password='admin-hash',
        account_type='local',
    )
    operator = User(
        uuid=str(uuid.uuid4()),
        user='204618@example.com',
        normalized_email='204618@example.com',
        password='operator-hash',
        account_type='local',
    )
    async with session_factory.begin() as session:
        session.add_all([admin, operator])
        await session.flush()
        default_workspace = await application.workspace_service.ensure_default_workspace(session=session)
        await application.workspace_service.claim_initial_owner(admin.uuid, session=session)
        personal_workspace, _ = await application.workspace_service.ensure_personal_workspace(
            operator.uuid,
            session=session,
        )

    admin_token = await application.user_service.generate_jwt_token(admin)
    operator_token = await application.user_service.generate_jwt_token(operator)

    quart_app = Quart(__name__)
    await WorkspacesRouterGroup(application, quart_app).initialize()
    await InvitationsRouterGroup(application, quart_app).initialize()

    yield SimpleNamespace(
        application=application,
        client=quart_app.test_client(),
        admin=admin,
        operator=operator,
        admin_token=admin_token,
        operator_token=operator_token,
        default_workspace_uuid=default_workspace.uuid,
        personal_workspace_uuid=personal_workspace.uuid,
    )
    await engine.dispose()


def _auth(token: str, workspace_uuid: str | None = None) -> dict[str, str]:
    headers = {'Authorization': f'Bearer {token}'}
    if workspace_uuid is not None:
        headers['X-Workspace-Id'] = workspace_uuid
    return headers


async def test_bootstrap_lists_only_the_accounts_own_workspace(personal_workspace_api):
    api = personal_workspace_api

    admin_response = await api.client.get(
        '/api/v1/workspaces/bootstrap',
        headers=_auth(api.admin_token),
    )
    operator_response = await api.client.get(
        '/api/v1/workspaces/bootstrap',
        headers=_auth(api.operator_token),
    )

    assert admin_response.status_code == 200
    assert operator_response.status_code == 200
    admin_workspaces = (await admin_response.get_json())['data']['workspaces']
    operator_workspaces = (await operator_response.get_json())['data']['workspaces']

    assert [item['workspace']['uuid'] for item in admin_workspaces] == [api.default_workspace_uuid]
    assert [item['workspace']['uuid'] for item in operator_workspaces] == [api.personal_workspace_uuid]
    # Sharing permissions are removed from the personal edition, so the
    # frontend never renders member or invitation surfaces.
    personal_permissions = set(operator_workspaces[0]['permissions'])
    assert 'member.invite' not in personal_permissions
    assert 'workspace.delete' not in personal_permissions
    assert 'resource.manage' in personal_permissions


async def test_current_workspace_is_resolved_per_account(personal_workspace_api):
    api = personal_workspace_api

    admin_current = await api.client.get('/api/v1/workspaces/current', headers=_auth(api.admin_token))
    operator_current = await api.client.get('/api/v1/workspaces/current', headers=_auth(api.operator_token))

    assert admin_current.status_code == 200
    assert operator_current.status_code == 200
    assert (await admin_current.get_json())['data']['workspace']['uuid'] == api.default_workspace_uuid
    assert (await operator_current.get_json())['data']['workspace']['uuid'] == api.personal_workspace_uuid


async def test_workspace_selector_cannot_enter_another_accounts_workspace(personal_workspace_api):
    api = personal_workspace_api

    cross_response = await api.client.get(
        '/api/v1/workspaces/current',
        headers=_auth(api.operator_token, api.default_workspace_uuid),
    )
    assert cross_response.status_code == 404
    assert (await cross_response.get_json())['code'] == 'resource_not_found'

    # Without a selector the personal account stays in its own Workspace, so
    # the member route is denied by permissions before any path lookup.
    path_response = await api.client.get(
        f'/api/v1/workspaces/{api.default_workspace_uuid}/members',
        headers=_auth(api.operator_token),
    )
    assert path_response.status_code == 403
    assert (await path_response.get_json())['code'] == 'permission_denied'


async def test_personal_workspace_cannot_manage_members_or_invite(personal_workspace_api):
    api = personal_workspace_api

    members_response = await api.client.get(
        f'/api/v1/workspaces/{api.personal_workspace_uuid}/members',
        headers=_auth(api.operator_token),
    )
    assert members_response.status_code == 403
    assert (await members_response.get_json())['code'] == 'permission_denied'

    invite_response = await api.client.post(
        f'/api/v1/workspaces/{api.personal_workspace_uuid}/invitations',
        headers=_auth(api.operator_token),
        json={'email': 'invitee@example.com', 'role': 'viewer'},
    )
    assert invite_response.status_code == 403
    assert (await invite_response.get_json())['code'] == 'permission_denied'

    # Unauthenticated invitation inspection is guarded by the policy itself.
    accept_response = await api.client.post(
        '/api/v1/invitations/inspect',
        json={'token': 'lbi_not-a-real-token'},
    )
    assert accept_response.status_code == 403
    assert (await accept_response.get_json())['code'] == 'sharing_disabled'


async def test_personal_account_keeps_exactly_one_active_membership(personal_workspace_api):
    api = personal_workspace_api
    async with api.application.persistence_mgr.get_db_engine().connect() as connection:
        rows = (
            await connection.execute(
                sqlalchemy.select(WorkspaceMembership.workspace_uuid, WorkspaceMembership.role).where(
                    WorkspaceMembership.account_uuid == api.operator.uuid,
                    WorkspaceMembership.status == 'active',
                )
            )
        ).all()

    assert [tuple(row) for row in rows] == [(api.personal_workspace_uuid, 'owner')]
