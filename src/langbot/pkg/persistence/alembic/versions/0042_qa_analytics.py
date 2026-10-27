"""Create the Workspace-scoped knowledge-base Q&A analytics store."""

from alembic import op
import sqlalchemy as sa

revision = '0042_qa_analytics'
down_revision = '0041_file_original_name'
branch_labels = None
depends_on = None

TABLE = 'qa_analytics_records'
INDEXES = (
    ('ix_qa_analytics_records_workspace_created', ['workspace_uuid', 'created_at', 'id']),
    ('ix_qa_analytics_records_workspace_session', ['workspace_uuid', 'session_key', 'created_at']),
    ('ix_qa_analytics_records_workspace_ip', ['workspace_uuid', 'visitor_ip', 'created_at']),
    ('ix_qa_analytics_records_workspace_region', ['workspace_uuid', 'region', 'created_at']),
    ('ix_qa_analytics_records_workspace_norm', ['workspace_uuid', 'normalized_group_question']),
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
            sa.Column('query_uuid', sa.String(64), nullable=True),
            sa.Column('session_key', sa.String(512), nullable=False),
            sa.Column('bot_uuid', sa.String(36), nullable=True),
            sa.Column('pipeline_uuid', sa.String(36), nullable=True),
            sa.Column('question', sa.Text(), nullable=False),
            sa.Column('rewritten_question', sa.Text(), nullable=True),
            sa.Column('answer', sa.Text(), nullable=True),
            sa.Column('normalized_question', sa.String(512), nullable=False),
            sa.Column('normalized_group_question', sa.String(512), nullable=False),
            sa.Column('latency_ms', sa.Integer(), nullable=True),
            sa.Column('visitor_ip', sa.String(64), nullable=True),
            sa.Column('region', sa.String(255), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('finished_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_qa_analytics_records_query_uuid', TABLE, ['query_uuid'])

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
    if 'ix_qa_analytics_records_query_uuid' in existing_indexes:
        op.drop_index('ix_qa_analytics_records_query_uuid', table_name=TABLE)
    for index, _ in reversed(INDEXES):
        if index in existing_indexes:
            op.drop_index(index, table_name=TABLE)
    op.drop_table(TABLE)
