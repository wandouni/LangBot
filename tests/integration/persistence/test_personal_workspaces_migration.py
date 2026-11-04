from __future__ import annotations

import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from langbot.pkg.entity.persistence.base import Base
from langbot.pkg.entity.persistence.user import User
from langbot.pkg.entity.persistence.workspace import (
    Workspace,
    WorkspaceExecutionState,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from langbot.pkg.entity.persistence.metadata import WorkspaceMetadata
from langbot.pkg.persistence.alembic_runner import run_alembic_stamp, run_alembic_upgrade
from langbot.pkg.workspace.identity import personal_workspace_slug, personal_workspace_uuid


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

INSTANCE_UUID = 'instance-personal-migration'
ADMIN_UUID = '00000000-0000-4000-8000-000000000010'
OPERATOR_UUID = '00000000-0000-4000-8000-000000000020'
DEFAULT_WORKSPACE_UUID = '00000000-0000-4000-8000-000000000100'


async def _seed_shared_instance(engine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(
            sa.text("INSERT INTO metadata (key, value) VALUES ('instance_uuid', :value)"),
            {'value': INSTANCE_UUID},
        )
        await connection.execute(
            sa.insert(User),
            [
                {
                    'uuid': ADMIN_UUID,
                    'user': 'admin@example.com',
                    'normalized_email': 'admin@example.com',
                    'password': 'hash',
                    'account_type': 'local',
                },
                {
                    'uuid': OPERATOR_UUID,
                    'user': 'operator@example.com',
                    'normalized_email': 'operator@example.com',
                    'password': 'hash',
                    'account_type': 'local',
                },
            ],
        )
        await connection.execute(
            sa.insert(Workspace),
            [
                {
                    'uuid': DEFAULT_WORKSPACE_UUID,
                    'instance_uuid': INSTANCE_UUID,
                    'name': 'Default Workspace',
                    'slug': 'default',
                    'type': 'team',
                    'status': 'active',
                    'source': 'local',
                    'created_by_account_uuid': ADMIN_UUID,
                }
            ],
        )
        await connection.execute(
            sa.insert(WorkspaceExecutionState),
            [
                {
                    'workspace_uuid': DEFAULT_WORKSPACE_UUID,
                    'instance_uuid': INSTANCE_UUID,
                    'active_generation': 1,
                    'state': 'active',
                    'write_fenced': False,
                    'source': 'local',
                }
            ],
        )
        await connection.execute(
            sa.insert(WorkspaceMembership),
            [
                {
                    'uuid': '00000000-0000-4000-8000-000000000201',
                    'workspace_uuid': DEFAULT_WORKSPACE_UUID,
                    'account_uuid': ADMIN_UUID,
                    'role': 'owner',
                    'status': 'active',
                },
                {
                    'uuid': '00000000-0000-4000-8000-000000000202',
                    'workspace_uuid': DEFAULT_WORKSPACE_UUID,
                    'account_uuid': OPERATOR_UUID,
                    'role': 'operator',
                    'status': 'active',
                },
            ],
        )
        await connection.execute(
            sa.insert(WorkspaceMetadata),
            [
                {
                    'workspace_uuid': DEFAULT_WORKSPACE_UUID,
                    'key': 'message_language',
                    'value': 'zh_Hans',
                }
            ],
        )
        await connection.execute(
            sa.insert(WorkspaceInvitation),
            [
                {
                    'uuid': '00000000-0000-4000-8000-000000000301',
                    'workspace_uuid': DEFAULT_WORKSPACE_UUID,
                    'normalized_email': 'pending@example.com',
                    'role': 'viewer',
                    'token_hash': 'hashed-token',
                    'status': 'pending',
                    'expires_at': datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
                    + datetime.timedelta(days=7),
                    'created_by_account_uuid': ADMIN_UUID,
                }
            ],
        )


async def _upgrade(engine) -> None:
    await run_alembic_stamp(engine, '0042_qa_analytics')
    await run_alembic_upgrade(engine, '0043_personal_workspaces')


async def _snapshot(engine) -> dict:
    async with engine.connect() as connection:
        workspaces = (
            await connection.execute(
                sa.text(
                    'SELECT uuid, slug, type, source FROM workspaces '
                    'WHERE instance_uuid = :instance ORDER BY slug'
                ),
                {'instance': INSTANCE_UUID},
            )
        ).mappings().all()
        memberships = (
            await connection.execute(
                sa.text(
                    'SELECT workspace_uuid, account_uuid, role, status FROM workspace_memberships '
                    'ORDER BY account_uuid, workspace_uuid'
                )
            )
        ).mappings().all()
        invitation = (
            await connection.execute(
                sa.text("SELECT status, revoked_at FROM workspace_invitations WHERE uuid = '00000000-0000-4000-8000-000000000301'")
            )
        ).mappings().one()
        metadata_rows = (
            await connection.execute(
                sa.text('SELECT workspace_uuid, key, value FROM workspace_metadata ORDER BY workspace_uuid, key')
            )
        ).mappings().all()
        execution_rows = (
            await connection.execute(
                sa.text('SELECT workspace_uuid, state, active_generation FROM workspace_execution_states')
            )
        ).mappings().all()
    return {
        'workspaces': [dict(row) for row in workspaces],
        'memberships': [dict(row) for row in memberships],
        'invitation': dict(invitation),
        'metadata': [dict(row) for row in metadata_rows],
        'execution': [dict(row) for row in execution_rows],
    }


async def test_migration_splits_shared_instance_into_personal_workspaces(tmp_path):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "personal-migration.db"}')
    try:
        await _seed_shared_instance(engine)
        await _upgrade(engine)

        snapshot = await _snapshot(engine)
        personal_uuid = personal_workspace_uuid(INSTANCE_UUID, OPERATOR_UUID)

        assert snapshot['workspaces'] == [
            {
                'uuid': DEFAULT_WORKSPACE_UUID,
                'slug': 'default',
                'type': 'team',
                'source': 'local',
            },
            {
                'uuid': personal_uuid,
                'slug': personal_workspace_slug(OPERATOR_UUID),
                'type': 'personal',
                'source': 'local',
            },
        ]
        # The historical owner stays in Default; the operator is moved out, not
        # demoted inside the shared Workspace.
        assert snapshot['memberships'] == [
            {'workspace_uuid': DEFAULT_WORKSPACE_UUID, 'account_uuid': ADMIN_UUID, 'role': 'owner', 'status': 'active'},
            {
                'workspace_uuid': DEFAULT_WORKSPACE_UUID,
                'account_uuid': OPERATOR_UUID,
                'role': 'operator',
                'status': 'removed',
            },
            {'workspace_uuid': personal_uuid, 'account_uuid': OPERATOR_UUID, 'role': 'owner', 'status': 'active'},
        ]
        assert snapshot['invitation']['status'] == 'revoked'
        assert snapshot['invitation']['revoked_at'] is not None
        # Pipeline defaults inherit the Workspace message language.
        assert {
            'workspace_uuid': personal_uuid,
            'key': 'message_language',
            'value': 'zh_Hans',
        } in snapshot['metadata']
        assert {
            'workspace_uuid': personal_uuid,
            'state': 'active',
            'active_generation': 1,
        } in snapshot['execution']

        # Downgrade is refused while personal Workspaces exist: the old image
        # requires exactly one local Workspace.
        from langbot.pkg.persistence.alembic_runner import run_alembic_downgrade

        with pytest.raises(RuntimeError, match='personal Workspaces'):
            await run_alembic_downgrade(engine, '0042_qa_analytics')
    finally:
        await engine.dispose()


async def test_migration_is_idempotent_when_replayed(tmp_path):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "personal-migration-replay.db"}')
    try:
        await _seed_shared_instance(engine)
        await _upgrade(engine)
        first = await _snapshot(engine)

        # Force the revision back to 0042 without touching data, then run the
        # upgrade again against an already-split database.
        await _upgrade(engine)
        second = await _snapshot(engine)

        assert second['workspaces'] == first['workspaces']
        assert second['memberships'] == first['memberships']
        assert second['invitation'] == first['invitation']
        assert len(second['metadata']) == len(first['metadata'])
        assert len(second['execution']) == len(first['execution'])
    finally:
        await engine.dispose()
