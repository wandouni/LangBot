"""Split each local account into its own personal Workspace.

Existing resources stay in the Default Workspace, which is owned by the
existing owner account. Every other account that was an active member of a
local Workspace receives an empty personal Workspace and loses the old shared
membership. Invitations are revoked because OSS sharing is disabled.

The migration is idempotent: workspaces whose slug already exists are reused,
and accounts that already have an active personal membership are skipped.

Personal Workspaces are SQLite-only in this OSS build. PostgreSQL OSS pins
every transaction to a single local Workspace through RLS, so upgrading a
PostgreSQL instance that still has shared members would silently cross tenant
boundaries. Such upgrades fail instead of producing a corrupted layout.
"""

from __future__ import annotations

import datetime
import uuid

import sqlalchemy as sa
from alembic import op

revision = '0043_personal_workspaces'
down_revision = '0042_qa_analytics'
branch_labels = None
depends_on = None

# Must match ``langbot.pkg.workspace.identity._WORKSPACE_IDENTITY_NAMESPACE``.
# Migrations intentionally do not import business code, so the constant is
# duplicated here.
_NAMESPACE = uuid.UUID('8ea04f29-8528-4cc3-bb28-30a838c89d76')
_LOCAL_TEAM_INDEX = 'uq_workspaces_local_team_instance'
_LOCAL_PERSONAL_INDEX = 'uq_workspaces_local_personal_owner'
_LEGACY_LOCAL_INDEX = 'uq_workspaces_local_instance'
_LOCAL_TEAM_PREDICATE = "source = 'local' AND type = 'team'"
_LOCAL_PERSONAL_PREDICATE = "source = 'local' AND type = 'personal'"


def _table_names(conn: sa.Connection) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def _index_names(conn: sa.Connection, table: str) -> set[str]:
    return {item['name'] for item in sa.inspect(conn).get_indexes(table)}


def _personal_workspace_uuid(instance_uuid: str, account_uuid: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f'{instance_uuid}:personal:{account_uuid}'))


def _personal_workspace_slug(account_uuid: str) -> str:
    return f'personal-{account_uuid}'


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def _instance_uuid(conn: sa.Connection) -> str | None:
    metadata = sa.table(
        'metadata',
        sa.column('key', sa.String(255)),
        sa.column('value', sa.String(255)),
    )
    value = conn.execute(sa.select(metadata.c.value).where(metadata.c.key == 'instance_uuid')).scalar_one_or_none()
    if isinstance(value, str) and value.strip():
        return value.strip()

    workspaces = sa.table(
        'workspaces',
        sa.column('instance_uuid', sa.String(255)),
        sa.column('source', sa.String(32)),
    )
    row = conn.execute(
        sa.select(workspaces.c.instance_uuid).where(workspaces.c.source == 'local').limit(1)
    ).scalar_one_or_none()
    if isinstance(row, str) and row.strip():
        return row.strip()
    return None


def _replace_workspace_indexes(conn: sa.Connection) -> None:
    columns = {column['name'] for column in sa.inspect(conn).get_columns('workspaces')}
    existing = _index_names(conn, 'workspaces')
    if _LEGACY_LOCAL_INDEX in existing:
        op.drop_index(_LEGACY_LOCAL_INDEX, table_name='workspaces')
    if 'type' not in columns:
        # Historical/minimal test schemas may lack WorkspaceType. They cannot
        # hold personal Workspaces, so only the legacy row-level constraint
        # matters; there is nothing type-specific to index.
        return
    if _LOCAL_TEAM_INDEX not in existing:
        op.create_index(
            _LOCAL_TEAM_INDEX,
            'workspaces',
            ['instance_uuid'],
            unique=True,
            sqlite_where=sa.text(_LOCAL_TEAM_PREDICATE),
            postgresql_where=sa.text(_LOCAL_TEAM_PREDICATE),
        )
    if _LOCAL_PERSONAL_INDEX not in existing:
        op.create_index(
            _LOCAL_PERSONAL_INDEX,
            'workspaces',
            ['instance_uuid', 'created_by_account_uuid'],
            unique=True,
            sqlite_where=sa.text(_LOCAL_PERSONAL_PREDICATE),
            postgresql_where=sa.text(_LOCAL_PERSONAL_PREDICATE),
        )


def upgrade() -> None:
    conn = op.get_bind()
    tables = _table_names(conn)
    if 'workspaces' not in tables:
        return

    _replace_workspace_indexes(conn)

    required = {
        'users',
        'workspace_memberships',
        'workspace_execution_states',
        'workspace_metadata',
        'workspace_invitations',
    }
    if not required.issubset(tables):
        return

    instance_uuid = _instance_uuid(conn)
    if instance_uuid is None:
        return

    workspace_columns = {column['name'] for column in sa.inspect(conn).get_columns('workspaces')}
    has_type = 'type' in workspace_columns

    workspaces = sa.table(
        'workspaces',
        sa.column('uuid', sa.String(36)),
        sa.column('instance_uuid', sa.String(255)),
        sa.column('name', sa.String(255)),
        sa.column('slug', sa.String(255)),
        sa.column('type', sa.String(32)),
        sa.column('status', sa.String(32)),
        sa.column('created_by_account_uuid', sa.String(36)),
        sa.column('source', sa.String(32)),
        sa.column('projection_revision', sa.BigInteger()),
        sa.column('created_at', sa.DateTime()),
        sa.column('updated_at', sa.DateTime()),
    )
    local_workspaces = conn.execute(
        sa.select(
            workspaces.c.uuid,
            workspaces.c.slug,
            workspaces.c.type if has_type else sa.literal('team').label('type'),
            workspaces.c.created_at,
        )
        .where(
            workspaces.c.instance_uuid == instance_uuid,
            workspaces.c.source == 'local',
        )
        .order_by(workspaces.c.created_at, workspaces.c.uuid)
    ).all()
    if not local_workspaces:
        return

    default_workspace = next((row for row in local_workspaces if row.slug == 'default'), None)
    if default_workspace is None:
        # Pre-v4 data has no slug. The oldest local Workspace is the one the
        # singleton policy treated as Default, and it must stay the owner of
        # all existing resources.
        default_workspace = local_workspaces[0]

    local_uuids = [row.uuid for row in local_workspaces]
    existing_personal = {row.uuid for row in local_workspaces if row.type == 'personal'}

    memberships = sa.table(
        'workspace_memberships',
        sa.column('uuid', sa.String(36)),
        sa.column('workspace_uuid', sa.String(36)),
        sa.column('account_uuid', sa.String(36)),
        sa.column('role', sa.String(32)),
        sa.column('status', sa.String(32)),
        sa.column('joined_at', sa.DateTime()),
        sa.column('source', sa.String(32)),
        sa.column('projection_revision', sa.BigInteger()),
        sa.column('created_at', sa.DateTime()),
        sa.column('updated_at', sa.DateTime()),
    )
    active_rows = conn.execute(
        sa.select(
            memberships.c.uuid,
            memberships.c.workspace_uuid,
            memberships.c.account_uuid,
            memberships.c.role,
        ).where(
            memberships.c.workspace_uuid.in_(local_uuids),
            memberships.c.status == 'active',
        )
    ).all()

    personal_accounts: set[str] = set()
    accounts_by_uuid: dict[str, list[sa.Row]] = {}
    for row in active_rows:
        accounts_by_uuid.setdefault(row.account_uuid, []).append(row)
        if row.workspace_uuid in existing_personal:
            personal_accounts.add(row.account_uuid)

    default_owner_accounts = {
        row.account_uuid
        for row in active_rows
        if row.workspace_uuid == default_workspace.uuid and row.role == 'owner'
    }
    needs_personal = {
        account_uuid
        for account_uuid in accounts_by_uuid
        if account_uuid not in default_owner_accounts and account_uuid not in personal_accounts
    }

    if conn.dialect.name == 'postgresql' and (needs_personal or existing_personal):
        raise RuntimeError(
            'This OSS build supports personal Workspaces only with SQLite. '
            'PostgreSQL OSS pins every transaction to a single local Workspace, '
            'so this instance cannot be split per account.'
        )

    users = sa.table(
        'users',
        sa.column('uuid', sa.String(36)),
        sa.column('user', sa.String(255)),
    )
    execution_states = sa.table(
        'workspace_execution_states',
        sa.column('workspace_uuid', sa.String(36)),
        sa.column('instance_uuid', sa.String(255)),
        sa.column('active_generation', sa.BigInteger()),
        sa.column('state', sa.String(32)),
        sa.column('write_fenced', sa.Boolean()),
        sa.column('source', sa.String(32)),
        sa.column('desired_state_revision', sa.BigInteger()),
        sa.column('updated_at', sa.DateTime()),
    )
    workspace_metadata = sa.table(
        'workspace_metadata',
        sa.column('workspace_uuid', sa.String(36)),
        sa.column('key', sa.String(255)),
        sa.column('value', sa.Text()),
    )

    default_language = conn.execute(
        sa.select(workspace_metadata.c.value).where(
            workspace_metadata.c.workspace_uuid == default_workspace.uuid,
            workspace_metadata.c.key == 'message_language',
        )
    ).scalar_one_or_none()

    now = _now()
    for account_uuid in sorted(needs_personal):
        slug = _personal_workspace_slug(account_uuid)
        existing = conn.execute(
            sa.select(workspaces.c.uuid).where(
                workspaces.c.instance_uuid == instance_uuid,
                workspaces.c.slug == slug,
            )
        ).scalar_one_or_none()
        if existing is not None:
            personal_uuid = existing
        else:
            if not has_type:
                raise RuntimeError('Cannot create a personal Workspace: workspaces.type is missing')
            personal_uuid = _personal_workspace_uuid(instance_uuid, account_uuid)
            username = conn.execute(sa.select(users.c.user).where(users.c.uuid == account_uuid)).scalar_one_or_none()
            display_name = username.strip() if isinstance(username, str) and username.strip() else account_uuid
            conn.execute(
                sa.insert(workspaces).values(
                    uuid=personal_uuid,
                    instance_uuid=instance_uuid,
                    name=display_name,
                    slug=slug,
                    type='personal',
                    status='active',
                    created_by_account_uuid=account_uuid,
                    source='local',
                    projection_revision=0,
                    created_at=now,
                    updated_at=now,
                )
            )

        if (
            conn.execute(
                sa.select(execution_states.c.workspace_uuid).where(
                    execution_states.c.workspace_uuid == personal_uuid
                )
            ).scalar_one_or_none()
            is None
        ):
            conn.execute(
                sa.insert(execution_states).values(
                    workspace_uuid=personal_uuid,
                    instance_uuid=instance_uuid,
                    active_generation=1,
                    state='active',
                    write_fenced=False,
                    source='local',
                    desired_state_revision=0,
                    updated_at=now,
                )
            )

        membership_uuid = conn.execute(
            sa.select(memberships.c.uuid).where(
                memberships.c.workspace_uuid == personal_uuid,
                memberships.c.account_uuid == account_uuid,
            )
        ).scalar_one_or_none()
        if membership_uuid is None:
            conn.execute(
                sa.insert(memberships).values(
                    uuid=str(uuid.uuid4()),
                    workspace_uuid=personal_uuid,
                    account_uuid=account_uuid,
                    role='owner',
                    status='active',
                    joined_at=now,
                    source='local',
                    projection_revision=0,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            conn.execute(
                sa.update(memberships)
                .where(memberships.c.uuid == membership_uuid)
                .values(role='owner', status='active', joined_at=now, updated_at=now)
            )

        if default_language is not None and (
            conn.execute(
                sa.select(workspace_metadata.c.value).where(
                    workspace_metadata.c.workspace_uuid == personal_uuid,
                    workspace_metadata.c.key == 'message_language',
                )
            ).scalar_one_or_none()
            is None
        ):
            conn.execute(
                sa.insert(workspace_metadata).values(
                    workspace_uuid=personal_uuid,
                    key='message_language',
                    value=default_language,
                )
            )

        # Leave exactly one active membership: the new personal Workspace.
        # The account keeps its historical resources through the Default
        # Workspace owner, never through a shared membership.
        conn.execute(
            sa.update(memberships)
            .where(
                memberships.c.account_uuid == account_uuid,
                memberships.c.workspace_uuid.in_(local_uuids),
                memberships.c.workspace_uuid != personal_uuid,
                memberships.c.status == 'active',
            )
            .values(status='removed', updated_at=now)
        )
        personal_accounts.add(account_uuid)

    # Sharing is disabled in this edition; pending invitations must not become
    # a hidden way to rejoin the Default Workspace.
    instance_workspaces = conn.execute(
        sa.select(workspaces.c.uuid).where(workspaces.c.instance_uuid == instance_uuid)
    ).scalars().all()
    if instance_workspaces:
        invitations = sa.table(
            'workspace_invitations',
            sa.column('workspace_uuid', sa.String(36)),
            sa.column('status', sa.String(32)),
            sa.column('revoked_at', sa.DateTime()),
            sa.column('updated_at', sa.DateTime()),
        )
        conn.execute(
            sa.update(invitations)
            .where(
                invitations.c.workspace_uuid.in_(instance_workspaces),
                invitations.c.status == 'pending',
            )
            .values(status='revoked', revoked_at=now, updated_at=now)
        )


def downgrade() -> None:
    conn = op.get_bind()
    tables = _table_names(conn)
    if 'workspaces' not in tables:
        return

    workspaces = sa.table(
        'workspaces',
        sa.column('instance_uuid', sa.String(255)),
        sa.column('source', sa.String(32)),
    )
    counts = conn.execute(
        sa.select(workspaces.c.instance_uuid, sa.func.count())
        .where(workspaces.c.source == 'local')
        .group_by(workspaces.c.instance_uuid)
    ).all()
    if any(count > 1 for _, count in counts):
        raise RuntimeError(
            'Cannot downgrade while personal Workspaces exist. Restore the pre-upgrade database backup instead.'
        )

    existing = _index_names(conn, 'workspaces')
    for index in (_LOCAL_TEAM_INDEX, _LOCAL_PERSONAL_INDEX):
        if index in existing:
            op.drop_index(index, table_name='workspaces')
    if _LEGACY_LOCAL_INDEX not in existing:
        op.create_index(
            _LEGACY_LOCAL_INDEX,
            'workspaces',
            ['instance_uuid'],
            unique=True,
            sqlite_where=sa.text("source = 'local'"),
            postgresql_where=sa.text("source = 'local'"),
        )
