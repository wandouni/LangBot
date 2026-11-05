import sqlalchemy

from .base import Base


class QAAnalyticsRecord(Base):
    """One recorded knowledge-base question and its answer.

    The table serves the analytics dashboard only.  It is deliberately
    independent from conversation history and monitoring records so that
    retention, masking, and aggregation can evolve without touching those
    stores.
    """

    __tablename__ = 'qa_analytics_records'

    id = sqlalchemy.Column(sqlalchemy.String(64), primary_key=True)
    workspace_uuid = sqlalchemy.Column(
        sqlalchemy.String(36),
        sqlalchemy.ForeignKey('workspaces.uuid', ondelete='CASCADE'),
        nullable=False,
    )
    query_uuid = sqlalchemy.Column(sqlalchemy.String(64), nullable=True, index=True)
    session_key = sqlalchemy.Column(sqlalchemy.String(512), nullable=False)
    bot_uuid = sqlalchemy.Column(sqlalchemy.String(36), nullable=True)
    pipeline_uuid = sqlalchemy.Column(sqlalchemy.String(36), nullable=True)
    question = sqlalchemy.Column(sqlalchemy.Text, nullable=False, default='')
    rewritten_question = sqlalchemy.Column(sqlalchemy.Text, nullable=True)
    answer = sqlalchemy.Column(sqlalchemy.Text, nullable=True)
    normalized_question = sqlalchemy.Column(sqlalchemy.String(512), nullable=False, default='')
    normalized_group_question = sqlalchemy.Column(sqlalchemy.String(512), nullable=False, default='')
    latency_ms = sqlalchemy.Column(sqlalchemy.Integer, nullable=True)
    visitor_ip = sqlalchemy.Column(sqlalchemy.String(64), nullable=True)
    region = sqlalchemy.Column(sqlalchemy.String(255), nullable=True)
    created_at = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)
    finished_at = sqlalchemy.Column(sqlalchemy.DateTime, nullable=True)

    __table_args__ = (
        sqlalchemy.Index(
            'ix_qa_analytics_records_workspace_created',
            'workspace_uuid',
            'created_at',
            'id',
        ),
        sqlalchemy.Index(
            'ix_qa_analytics_records_workspace_session',
            'workspace_uuid',
            'session_key',
            'created_at',
        ),
        sqlalchemy.Index(
            'ix_qa_analytics_records_workspace_ip',
            'workspace_uuid',
            'visitor_ip',
            'created_at',
        ),
        sqlalchemy.Index(
            'ix_qa_analytics_records_workspace_region',
            'workspace_uuid',
            'region',
            'created_at',
        ),
        sqlalchemy.Index(
            'ix_qa_analytics_records_workspace_norm',
            'workspace_uuid',
            'normalized_group_question',
        ),
    )


class QAAnalyticsConsultMessage(Base):
    """A visitor lead submitted from a standalone consultation page.

    Leads are intentionally kept apart from ``qa_analytics_records``: they are
    personal contact data used by admissions staff, not anonymous analytics,
    so they must not be aggregated or deleted by the analytics retention job.
    """

    __tablename__ = 'qa_analytics_consult_messages'

    id = sqlalchemy.Column(sqlalchemy.String(64), primary_key=True)
    workspace_uuid = sqlalchemy.Column(
        sqlalchemy.String(36),
        sqlalchemy.ForeignKey('workspaces.uuid', ondelete='CASCADE'),
        nullable=False,
    )
    bot_uuid = sqlalchemy.Column(sqlalchemy.String(36), nullable=True)
    province = sqlalchemy.Column(sqlalchemy.String(64), nullable=False, default='')
    city = sqlalchemy.Column(sqlalchemy.String(64), nullable=False, default='')
    name = sqlalchemy.Column(sqlalchemy.String(128), nullable=False, default='')
    score = sqlalchemy.Column(sqlalchemy.String(32), nullable=False, default='')
    contact = sqlalchemy.Column(sqlalchemy.String(255), nullable=False, default='')
    status = sqlalchemy.Column(sqlalchemy.String(16), nullable=False, default='pending')
    created_at = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)
    processed_at = sqlalchemy.Column(sqlalchemy.DateTime, nullable=True)

    __table_args__ = (
        sqlalchemy.Index(
            'ix_qa_analytics_consult_messages_workspace_created',
            'workspace_uuid',
            'created_at',
            'id',
        ),
        sqlalchemy.Index(
            'ix_qa_analytics_consult_messages_workspace_status',
            'workspace_uuid',
            'status',
            'created_at',
        ),
    )
