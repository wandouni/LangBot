"""Create the Workspace-scoped consultation message board store."""

from alembic import op
import sqlalchemy as sa

revision = '0044_qa_consult_messages'
down_revision = '0043_personal_workspaces'
branch_labels = None
depends_on = None

TABLE = 'qa_analytics_consult_messages'
INDEXES = (
    ('ix_qa_analytics_consult_messages_workspace_created', ['workspace_uuid', 'created_at', 'id']),
    ('ix_qa_analytics_consult_messages_workspace_status', ['workspace_uuid', 'status', 'created_at']),
)


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if TABLE not in inspector.get_table_names():
        op.create_table(
            TABLE,
            sa.Column('id', sa.String(64), primary_key=True),
            sa.Column(
                'workspace_uuid',
                sa.String(36),
                sa.ForeignKey('workspaces.uuid', ondelete='CASCADE'),
                nullable=False,
            ),
            sa.Column('bot_uuid', sa.String(36), nullable=True),
            sa.Column('province', sa.String(64), nullable=False),
            sa.Column('city', sa.String(64), nullable=False),
            sa.Column('name', sa.String(128), nullable=False),
            sa.Column('score', sa.String(32), nullable=False),
            sa.Column('contact', sa.String(255), nullable=False),
            sa.Column('status', sa.String(16), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('processed_at', sa.DateTime(), nullable=True),
        )

    existing = {item['name'] for item in sa.inspect(connection).get_indexes(TABLE)}
    for index, columns in INDEXES:
        if index not in existing:
            op.create_index(index, TABLE, columns)

    if connection.dialect.name == 'postgresql':
        predicate = "workspace_uuid::text = NULLIF(current_setting('langbot.workspace_uuid', true), '')"
        op.execute(sa.text(f'ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'DROP POLICY IF EXISTS langbot_workspace_isolation ON {TABLE}'))
        op.execute(
            sa.text(
                f'CREATE POLICY langbot_workspace_isolation ON {TABLE} AS PERMISSIVE FOR ALL TO PUBLIC '
                f'USING ({predicate}) WITH CHECK ({predicate})'
            )
        )


def downgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if TABLE not in inspector.get_table_names():
        return
    existing_indexes = {item['name'] for item in inspector.get_indexes(TABLE)}
    for index, _ in reversed(INDEXES):
        if index in existing_indexes:
            op.drop_index(index, table_name=TABLE)
    op.drop_table(TABLE)
