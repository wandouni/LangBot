"""Persist the uploader-supplied display name for knowledge base files."""

from alembic import op
import sqlalchemy as sa

revision = '0041_file_original_name'
down_revision = '0040_session_summaries'
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if 'knowledge_base_files' not in inspector.get_table_names():
        return
    columns = {column['name'] for column in inspector.get_columns('knowledge_base_files')}
    if 'original_file_name' not in columns:
        # Historical names were discarded at upload time and cannot be recovered.
        op.add_column('knowledge_base_files', sa.Column('original_file_name', sa.String(512), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if 'knowledge_base_files' not in inspector.get_table_names():
        return
    columns = {column['name'] for column in inspector.get_columns('knowledge_base_files')}
    if 'original_file_name' in columns:
        op.drop_column('knowledge_base_files', 'original_file_name')
