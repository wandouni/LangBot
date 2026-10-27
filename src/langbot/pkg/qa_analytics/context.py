"""Per-query collection context shared by the pipeline and retrieval hooks."""

from __future__ import annotations

import contextvars
import dataclasses
import datetime
import typing


@dataclasses.dataclass(slots=True)
class QACollectionContext:
    """Structured data gathered while one question is being answered."""

    workspace_uuid: str
    bot_uuid: str
    pipeline_uuid: str
    query_uuid: str
    session_key: str
    visitor_ip: str
    started_at: datetime.datetime
    started_perf: float
    rewritten_question: str = ''
    knowledge_base_used: bool = False


current_collection_context: contextvars.ContextVar[QACollectionContext | None] = contextvars.ContextVar(
    'qa_analytics_collection_context',
    default=None,
)

_REWRITE_KEYS = (
    'rewritten_question',
    'rewritten_query',
    'rewrittenQuestion',
    'rewrittenQuery',
    'rewrite',
    'query_rewrite',
    'queryRewrite',
)


def _first_rewritten_value(value: typing.Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in _REWRITE_KEYS:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for nested in value.values():
            candidate = _first_rewritten_value(nested)
            if candidate:
                return candidate
    if isinstance(value, (list, tuple)):
        for nested in value:
            candidate = _first_rewritten_value(nested)
            if candidate:
                return candidate
    return ''


def extract_rewritten_question(metadata: typing.Any) -> str:
    """Read a rewritten question from a RAG retrieval response.

    Plugins are not forced to return one.  Several common key names are
    accepted so the dashboard degrades to the original question instead of
    presenting an empty label when a plugin uses a slightly different field.
    """

    return _first_rewritten_value(metadata)[:4000]


def mark_knowledge_base_used() -> None:
    """Only knowledge-base questions belong in the dashboard."""

    context = current_collection_context.get()
    if context is not None:
        context.knowledge_base_used = True


def record_rewritten_question(metadata: typing.Any) -> None:
    """Attach the first rewritten question seen for the current pipeline run."""

    context = current_collection_context.get()
    if context is None or context.rewritten_question:
        return
    rewritten = extract_rewritten_question(metadata)
    if rewritten:
        context.rewritten_question = rewritten
