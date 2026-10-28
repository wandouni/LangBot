"""Per-query collection context shared by the pipeline and retrieval hooks."""

from __future__ import annotations

import contextlib
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

_QUERY_CONTEXT_ATTRIBUTE = '_qa_collection_context'


def attach_collection_context(query: typing.Any, context: QACollectionContext) -> None:
    """Attach the collection context to the Query that owns it.

    Knowledge retrieval runs as a Plugin Runtime action, which executes on the
    connector's socket task instead of the pipeline task.  ContextVars do not
    cross that boundary, so the context travels with the Query and is rebound
    when the retrieval action runs (see ``bind_query_collection_context``).
    """

    object.__setattr__(query, _QUERY_CONTEXT_ATTRIBUTE, context)


@contextlib.contextmanager
def bind_query_collection_context(query: typing.Any) -> typing.Iterator[None]:
    """Rebind the Query's collection context inside a Runtime action task."""

    context = getattr(query, _QUERY_CONTEXT_ATTRIBUTE, None) if query is not None else None
    if context is None:
        yield
        return
    token = current_collection_context.set(context)
    try:
        yield
    finally:
        current_collection_context.reset(token)


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
    """Return a string stored under a known rewrite key, if any.

    Retrieval metadata also contains unrelated strings (trace ids, document
    text, counters).  Only values addressed by one of ``_REWRITE_KEYS`` are
    rewritten questions; accepting any nested string would store a trace id
    such as ``retrieval-...`` as the rewritten question.
    """

    if isinstance(value, dict):
        for key in _REWRITE_KEYS:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for nested in value.values():
            candidate = _first_rewritten_value(nested)
            if candidate:
                return candidate
    elif isinstance(value, (list, tuple)):
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
