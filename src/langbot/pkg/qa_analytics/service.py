"""Collection and read-only query service for the Q&A analytics dashboard."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import datetime
import json
import time
import typing
import uuid

import sqlalchemy

from ..entity.persistence import bot as persistence_bot
from ..entity.persistence import qa_analytics as persistence_qa
from . import text as qa_text
from .context import QACollectionContext, attach_collection_context
from .geo import GeoResolver

_RANGE_KEYS = frozenset({'today', '7d', '30d', 'all'})
_DEFAULT_RANGE = '7d'
_MAX_PAGE_SIZE = 100
_MAX_KEYWORD_LENGTH = 200
_MAX_IP_LENGTH = 64
_MAX_REGION_LENGTH = 200
_MAX_BOT_UUID_LENGTH = 36
_MAX_CLEANUP_BATCH = 5000
_MAX_CLEANUP_BATCHES = 20
_CATALOG_LANGUAGES = frozenset(
    {
        'en_US',
        'zh_Hans',
        'zh_Hant',
        'ja_JP',
        'es_ES',
        'ru_RU',
        'th_TH',
        'vi_VN',
    }
)
_DEFAULT_CATALOG_LANGUAGE = 'en_US'


def _utc_now_naive() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _to_naive_utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(datetime.timezone.utc).replace(tzinfo=None)


def _iso_utc(value: datetime.datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=datetime.timezone.utc).isoformat()


def _bounded_int(value: typing.Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, minimum), maximum)


class QAAnalyticsService:
    """Record Q&A pairs and serve dashboard queries for one Workspace."""

    def __init__(self, ap: typing.Any) -> None:
        self.ap = ap
        self.geo = GeoResolver(ap)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def _config(self) -> dict[str, typing.Any]:
        config = getattr(getattr(self.ap, 'instance_config', None), 'data', {}) or {}
        value = config.get('qa_analytics', {})
        return value if isinstance(value, dict) else {}

    def is_enabled(self) -> bool:
        return bool(self._config().get('enabled', True))

    def mask_ips_in_lists(self) -> bool:
        return bool(self._config().get('mask_ip', True))

    def retention_days(self) -> int:
        return _bounded_int(self._config().get('retention_days', 90), 90, 1, 3650)

    def page_plugin_identity(self) -> tuple[str, str]:
        page_config = self._config().get('page', {})
        if not isinstance(page_config, dict):
            page_config = {}
        author = str(page_config.get('plugin_author', 'langbot-team') or 'langbot-team').strip()
        name = str(page_config.get('plugin_name', 'qa-analytics') or 'qa-analytics').strip()
        return author, name

    def owns_page_api(self, author: str, plugin_name: str) -> bool:
        configured_author, configured_name = self.page_plugin_identity()
        return author == configured_author and plugin_name == configured_name

    # ------------------------------------------------------------------
    # Collection
    # ------------------------------------------------------------------
    def begin_query(self, query: typing.Any) -> QACollectionContext | None:
        """Capture cheap per-query facts before the pipeline starts."""

        if not self.is_enabled():
            return None
        try:
            from ..pipeline.pool import get_query_execution_context

            execution_context = get_query_execution_context(query)
        except Exception:
            return None
        if not execution_context.workspace_uuid:
            return None

        event = getattr(query, 'message_event', None)
        visitor_ip = str(getattr(event, '_qa_visitor_ip', '') or '').strip()[:_MAX_IP_LENGTH]
        embed_session_id = str(getattr(event, '_qa_session_id', '') or '').strip()
        launcher_type = getattr(query, 'launcher_type', None)
        launcher_value = getattr(launcher_type, 'value', launcher_type) or 'unknown'
        if embed_session_id:
            session_part = f'embed:{embed_session_id}'
        else:
            session_part = f'{launcher_value}:{getattr(query, "launcher_id", "")}'
        session_key = f'{getattr(query, "bot_uuid", None) or "unknown"}:{session_part}'[:512]

        context = QACollectionContext(
            workspace_uuid=execution_context.workspace_uuid,
            bot_uuid=str(getattr(query, 'bot_uuid', None) or ''),
            pipeline_uuid=str(getattr(query, 'pipeline_uuid', None) or ''),
            query_uuid=str(getattr(query, 'query_uuid', None) or ''),
            session_key=session_key,
            visitor_ip=visitor_ip,
            started_at=_utc_now_naive(),
            started_perf=time.perf_counter(),
        )
        # Retrieval runs on the Runtime connector task, so keep the context on
        # the Query where the retrieval handler can find it.
        attach_collection_context(query, context)
        return context

    async def finish_query(self, query: typing.Any, context: QACollectionContext | None) -> None:
        """Persist one completed (or failed) question without delaying the answer."""

        if context is None or not context.knowledge_base_used:
            return
        variables = getattr(query, 'variables', None)
        if isinstance(variables, dict) and variables.get('_qa_analytics_recorded'):
            return

        question = self._extract_question(query)
        answer = self._extract_answer(query)
        rewritten = (context.rewritten_question or '').strip()
        if not rewritten and isinstance(variables, dict):
            rewritten = str(variables.get('_qa_rewritten_question', '') or '').strip()
        normalized_question = qa_text.normalize_question(question)
        # The dashboard's frequent-question ranking is built from the visitor's
        # question.  A plugin-provided rewrite is display metadata only and may
        # be absent or unrelated to what the visitor asked.
        normalized_group = normalized_question
        latency_ms = max(0, int((time.perf_counter() - context.started_perf) * 1000))
        finished_at = _utc_now_naive()

        region = ''
        if context.visitor_ip:
            try:
                region = await asyncio.wait_for(
                    asyncio.to_thread(self.geo.resolve, context.visitor_ip),
                    timeout=1.5,
                )
            except Exception:
                region = ''

        values = {
            'id': str(uuid.uuid4()),
            'workspace_uuid': context.workspace_uuid,
            'query_uuid': context.query_uuid[:64] or None,
            'session_key': context.session_key,
            'bot_uuid': context.bot_uuid[:36] or None,
            'pipeline_uuid': context.pipeline_uuid[:36] or None,
            'question': question,
            'rewritten_question': rewritten or None,
            'answer': answer or None,
            'normalized_question': normalized_question,
            'normalized_group_question': normalized_group,
            'latency_ms': latency_ms,
            'visitor_ip': context.visitor_ip or None,
            'region': region or None,
            'created_at': context.started_at,
            'finished_at': finished_at,
        }
        try:
            async with asyncio.timeout(2):
                await self._insert_record(values)
        except asyncio.TimeoutError:
            self.ap.logger.warning('Q&A analytics write timed out; one question was not recorded')
            return
        except Exception as exc:
            # Never include question text or the visitor IP in logs.
            self.ap.logger.warning(f'Q&A analytics write failed ({type(exc).__name__})')
            return
        if isinstance(variables, dict):
            variables['_qa_analytics_recorded'] = True

    async def _insert_record(self, values: dict[str, typing.Any]) -> None:
        tenant_uow = getattr(self.ap.persistence_mgr, 'tenant_uow', None)
        if callable(tenant_uow):
            async with tenant_uow(values['workspace_uuid']) as uow:
                await uow.execute(sqlalchemy.insert(persistence_qa.QAAnalyticsRecord).values(**values))
            return
        await self.ap.persistence_mgr.execute_async(
            sqlalchemy.insert(persistence_qa.QAAnalyticsRecord).values(**values)
        )

    @staticmethod
    def _extract_question(query: typing.Any) -> str:
        variables = getattr(query, 'variables', None)
        if isinstance(variables, dict):
            value = variables.get('user_message_text')
            if isinstance(value, str) and value.strip():
                return value.strip()
        try:
            return str(getattr(query, 'message_chain', '') or '').strip()
        except Exception:
            return ''

    @staticmethod
    def _extract_answer(query: typing.Any) -> str:
        chains = getattr(query, 'resp_message_chain', None) or []
        parts: list[str] = []
        for chain in chains:
            try:
                value = str(chain).strip()
            except Exception:
                value = ''
            if value:
                parts.append(value)
        if parts:
            return '\n'.join(parts)

        messages = getattr(query, 'resp_messages', None) or []
        for message in reversed(messages):
            content = getattr(message, 'content', None)
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                texts = [
                    str(getattr(element, 'text', '') or '').strip()
                    for element in content
                    if getattr(element, 'text', None)
                ]
                if texts:
                    return '\n'.join(text for text in texts if text)
        return ''

    # ------------------------------------------------------------------
    # Time ranges
    # ------------------------------------------------------------------
    def resolve_range(
        self,
        range_key: str | None,
        tz_offset_minutes: typing.Any = None,
        now: datetime.datetime | None = None,
    ) -> tuple[str, datetime.datetime | None, datetime.datetime]:
        """Resolve a dashboard range to naive UTC boundaries.

        ``tz_offset_minutes`` follows JavaScript's ``getTimezoneOffset()``:
        UTC minus local time in minutes.  It only affects "today"; the rolling
        ranges are fixed 7x24h / 30x24h windows.
        """

        key = str(range_key or _DEFAULT_RANGE).strip().lower()
        if key not in _RANGE_KEYS:
            key = _DEFAULT_RANGE
        current = now or datetime.datetime.now(datetime.timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=datetime.timezone.utc)
        end = current.astimezone(datetime.timezone.utc).replace(tzinfo=None)

        if key == 'all':
            return key, None, end
        if key in {'7d', '30d'}:
            days = 7 if key == '7d' else 30
            return key, end - datetime.timedelta(days=days), end

        try:
            offset = int(tz_offset_minutes)
        except (TypeError, ValueError):
            offset = None
        if offset is None or offset < -14 * 60 or offset > 14 * 60:
            local_now = current.astimezone()
            local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
            start = local_midnight.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        else:
            local_now = current + datetime.timedelta(minutes=-offset)
            local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
            start = (local_midnight + datetime.timedelta(minutes=offset)).replace(tzinfo=None)
        return key, start, end

    # ------------------------------------------------------------------
    # Read queries
    # ------------------------------------------------------------------
    def _record_conditions(
        self,
        workspace_uuid: str,
        start: datetime.datetime | None,
        end: datetime.datetime,
        bot_uuid: typing.Any = '',
    ) -> list[typing.Any]:
        model = persistence_qa.QAAnalyticsRecord
        conditions: list[typing.Any] = [model.workspace_uuid == workspace_uuid]
        if start is not None:
            conditions.append(model.created_at >= start)
        conditions.append(model.created_at <= end)
        bot_text = str(bot_uuid or '').strip()[:_MAX_BOT_UUID_LENGTH]
        if bot_text:
            conditions.append(model.bot_uuid == bot_text)
        return conditions

    @contextlib.asynccontextmanager
    async def _read_unit(self, workspace_uuid: str):
        tenant_uow = getattr(self.ap.persistence_mgr, 'tenant_uow', None)
        if callable(tenant_uow):
            async with tenant_uow(workspace_uuid) as uow:
                yield uow
        else:
            yield None

    async def _execute(self, uow: typing.Any, statement: typing.Any) -> typing.Any:
        if uow is not None:
            return await uow.execute(statement)
        return await self.ap.persistence_mgr.execute_async(statement)

    async def _scalar(self, uow: typing.Any, statement: typing.Any) -> int:
        result = await self._execute(uow, statement)
        value = result.scalar()
        return int(value or 0)

    async def get_bots(self, workspace_uuid: str) -> dict[str, typing.Any]:
        """List bots in the Workspace for the dashboard's bot filter."""

        model = persistence_bot.Bot
        async with self._read_unit(workspace_uuid) as uow:
            result = await self._execute(
                uow,
                sqlalchemy.select(model.uuid, model.name, model.enable)
                .where(model.workspace_uuid == workspace_uuid)
                .order_by(model.name.asc(), model.uuid.asc()),
            )
            rows = result.all()
        return {
            'items': [
                {
                    'uuid': row[0],
                    'name': row[1] or '',
                    'enabled': bool(row[2]),
                }
                for row in rows
            ]
        }

    async def get_overview(
        self,
        workspace_uuid: str,
        range_key: str,
        tz_offset_minutes: typing.Any = None,
        bot_uuid: typing.Any = '',
    ) -> dict[str, typing.Any]:
        resolved_key, start, end = self.resolve_range(range_key, tz_offset_minutes)
        model = persistence_qa.QAAnalyticsRecord
        conditions = self._record_conditions(workspace_uuid, start, end, bot_uuid)
        word_cloud_limit = _bounded_int(self._config().get('word_cloud_words', 100), 100, 1, 200)
        sample_size = _bounded_int(self._config().get('word_cloud_sample_size', 500), 500, 1, 5000)

        async with self._read_unit(workspace_uuid) as uow:
            total = await self._scalar(
                uow,
                sqlalchemy.select(sqlalchemy.func.count()).select_from(model).where(*conditions),
            )
            sessions = await self._scalar(
                uow,
                sqlalchemy.select(sqlalchemy.func.count(sqlalchemy.distinct(model.session_key))).where(*conditions),
            )
            frequent_subquery = (
                sqlalchemy.select(model.normalized_question)
                .where(*conditions, model.normalized_question != '')
                .group_by(model.normalized_question)
                .having(sqlalchemy.func.count() >= 2)
                .subquery()
            )
            high_frequency_types = await self._scalar(
                uow,
                sqlalchemy.select(sqlalchemy.func.count()).select_from(frequent_subquery),
            )
            latency_result = await self._execute(
                uow,
                sqlalchemy.select(
                    sqlalchemy.func.sum(model.latency_ms),
                    sqlalchemy.func.count(model.latency_ms),
                ).where(*conditions),
            )
            latency_sum, latency_count = latency_result.one()
            average_latency = (
                float(latency_sum) / int(latency_count) if latency_sum is not None and latency_count else None
            )

            sample_result = await self._execute(
                uow,
                sqlalchemy.select(model.question)
                .where(*conditions)
                .order_by(model.created_at.desc(), model.id.desc())
                .limit(sample_size),
            )
            sample_texts = [row[0] for row in sample_result.all() if row[0]]

            question_count = sqlalchemy.func.count()
            first_seen = sqlalchemy.func.min(model.created_at)
            top_result = await self._execute(
                uow,
                sqlalchemy.select(
                    model.normalized_question.label('group_key'),
                    question_count.label('question_count'),
                    first_seen.label('first_seen'),
                    sqlalchemy.func.min(model.id).label('sample_id'),
                )
                .where(*conditions, model.normalized_question != '')
                .group_by(model.normalized_question)
                .order_by(
                    question_count.desc(),
                    first_seen.asc(),
                )
                .limit(10),
            )
            top_rows = top_result.all()
            sample_ids = [row.sample_id for row in top_rows if row.sample_id]
            samples: dict[str, typing.Any] = {}
            if sample_ids:
                sample_record_result = await self._execute(
                    uow,
                    sqlalchemy.select(
                        model.id,
                        model.question,
                    ).where(model.id.in_(sample_ids)),
                )
                samples = {row[0]: row for row in sample_record_result.all()}

        word_cloud = await asyncio.to_thread(qa_text.build_word_cloud, sample_texts, word_cloud_limit)
        top_questions = []
        for row in top_rows:
            sample = samples.get(row.sample_id)
            display_question = ''
            if sample is not None:
                display_question = (sample[1] or '').strip()
            if not display_question:
                display_question = str(row.group_key or '')
            top_questions.append(
                {
                    'question': display_question,
                    'count': int(row.question_count or 0),
                }
            )

        return {
            'range': resolved_key,
            'started_at': _iso_utc(start),
            'ended_at': _iso_utc(end),
            'total_questions': total,
            'independent_sessions': sessions,
            'high_frequency_types': high_frequency_types,
            'average_latency_ms': int(round(float(average_latency))) if average_latency is not None else None,
            'word_cloud': word_cloud,
            'top_questions': top_questions,
        }

    def _question_filter_conditions(
        self,
        conditions: list[typing.Any],
        keyword: typing.Any,
        visitor_ip: typing.Any,
        region: typing.Any,
    ) -> list[typing.Any]:
        model = persistence_qa.QAAnalyticsRecord
        filters = list(conditions)
        keyword_text = str(keyword or '').strip()[:_MAX_KEYWORD_LENGTH]
        if keyword_text:
            escaped = keyword_text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            pattern = f'%{escaped}%'
            filters.append(
                sqlalchemy.or_(
                    model.question.ilike(pattern, escape='\\'),
                    model.rewritten_question.ilike(pattern, escape='\\'),
                )
            )
        ip_text = str(visitor_ip or '').strip()[:_MAX_IP_LENGTH]
        if ip_text:
            filters.append(model.visitor_ip.contains(ip_text, autoescape=True))
        region_text = str(region or '').strip()[:_MAX_REGION_LENGTH]
        if region_text:
            filters.append(model.region.ilike(f'%{region_text}%', escape='\\'))
        return filters

    async def get_questions(
        self,
        workspace_uuid: str,
        range_key: str,
        tz_offset_minutes: typing.Any = None,
        page: typing.Any = 1,
        page_size: typing.Any = 20,
        keyword: typing.Any = '',
        visitor_ip: typing.Any = '',
        region: typing.Any = '',
        bot_uuid: typing.Any = '',
    ) -> dict[str, typing.Any]:
        resolved_key, start, end = self.resolve_range(range_key, tz_offset_minutes)
        model = persistence_qa.QAAnalyticsRecord
        conditions = self._question_filter_conditions(
            self._record_conditions(workspace_uuid, start, end, bot_uuid),
            keyword,
            visitor_ip,
            region,
        )
        page_number = _bounded_int(page, 1, 1, 1_000_000)
        page_limit = _bounded_int(page_size, 20, 1, _MAX_PAGE_SIZE)
        offset = (page_number - 1) * page_limit

        async with self._read_unit(workspace_uuid) as uow:
            total = await self._scalar(
                uow,
                sqlalchemy.select(sqlalchemy.func.count()).select_from(model).where(*conditions),
            )
            result = await self._execute(
                uow,
                sqlalchemy.select(
                    model.id,
                    model.created_at,
                    model.question,
                    model.rewritten_question,
                    model.latency_ms,
                    model.visitor_ip,
                    model.region,
                )
                .where(*conditions)
                .order_by(model.created_at.desc(), model.id.desc())
                .limit(page_limit)
                .offset(offset),
            )
            rows = result.all()

        mask_ips = self.mask_ips_in_lists()
        items = []
        for row in rows:
            items.append(
                {
                    'id': row[0],
                    'created_at': _iso_utc(row[1]),
                    'question': row[2] or '',
                    'rewritten_question': row[3] or '',
                    'latency_ms': row[4],
                    'visitor_ip': qa_text.mask_ip(row[5]) if mask_ips else (row[5] or ''),
                    'region': row[6] or '',
                }
            )
        return {
            'range': resolved_key,
            'total': total,
            'page': page_number,
            'page_size': page_limit,
            'items': items,
        }

    async def get_question_detail(
        self,
        workspace_uuid: str,
        record_id: str,
        bot_uuid: typing.Any = '',
    ) -> dict[str, typing.Any] | None:
        model = persistence_qa.QAAnalyticsRecord
        text_id = str(record_id or '').strip()
        if not text_id:
            return None
        conditions: list[typing.Any] = [model.workspace_uuid == workspace_uuid, model.id == text_id]
        bot_text = str(bot_uuid or '').strip()[:_MAX_BOT_UUID_LENGTH]
        if bot_text:
            conditions.append(model.bot_uuid == bot_text)
        async with self._read_unit(workspace_uuid) as uow:
            result = await self._execute(
                uow,
                sqlalchemy.select(
                    model.id,
                    model.created_at,
                    model.finished_at,
                    model.question,
                    model.rewritten_question,
                    model.answer,
                    model.latency_ms,
                    model.visitor_ip,
                    model.region,
                )
                .where(*conditions)
                .limit(1),
            )
            row = result.first()
        if row is None:
            return None

        # Select explicit columns rather than the mapped entity: a production
        # tenant UoW executes through an ORM session, where ``select(model)``
        # returns a row keyed by the entity instead of its columns, so
        # attribute access such as ``row.id`` raises AttributeError.
        return {
            'id': row[0],
            'created_at': _iso_utc(row[1]),
            'finished_at': _iso_utc(row[2]),
            'question': row[3] or '',
            'rewritten_question': row[4] or '',
            'answer': row[5] or '',
            'latency_ms': row[6],
            'visitor_ip': row[7] or '',
            'region': row[8] or '',
        }

    async def get_visits(
        self,
        workspace_uuid: str,
        range_key: str,
        tz_offset_minutes: typing.Any = None,
        page: typing.Any = 1,
        page_size: typing.Any = 20,
        visitor_ip: typing.Any = '',
        region: typing.Any = '',
        bot_uuid: typing.Any = '',
    ) -> dict[str, typing.Any]:
        resolved_key, start, end = self.resolve_range(range_key, tz_offset_minutes)
        model = persistence_qa.QAAnalyticsRecord
        conditions = self._question_filter_conditions(
            self._record_conditions(workspace_uuid, start, end, bot_uuid),
            '',
            visitor_ip,
            region,
        )
        page_number = _bounded_int(page, 1, 1, 1_000_000)
        page_limit = _bounded_int(page_size, 20, 1, _MAX_PAGE_SIZE)
        offset = (page_number - 1) * page_limit

        async with self._read_unit(workspace_uuid) as uow:
            total = await self._scalar(
                uow,
                sqlalchemy.select(sqlalchemy.func.count(sqlalchemy.distinct(model.session_key))).where(*conditions),
            )
            last_seen = sqlalchemy.func.max(model.created_at)
            result = await self._execute(
                uow,
                sqlalchemy.select(
                    model.session_key,
                    sqlalchemy.func.min(model.created_at).label('first_seen'),
                    last_seen.label('last_seen'),
                    sqlalchemy.func.count().label('rounds'),
                    sqlalchemy.func.max(model.visitor_ip).label('visitor_ip'),
                    sqlalchemy.func.max(model.region).label('region'),
                )
                .where(*conditions)
                .group_by(model.session_key)
                .order_by(last_seen.desc())
                .limit(page_limit)
                .offset(offset),
            )
            rows = result.all()

        mask_ips = self.mask_ips_in_lists()
        items = []
        for row in rows:
            dwell_seconds = 0
            if row.first_seen is not None and row.last_seen is not None:
                dwell_seconds = max(0, int((row.last_seen - row.first_seen).total_seconds()))
            items.append(
                {
                    'session_key': row.session_key,
                    'first_seen': _iso_utc(row.first_seen),
                    'last_seen': _iso_utc(row.last_seen),
                    'dwell_seconds': dwell_seconds,
                    'rounds': int(row.rounds or 0),
                    'visitor_ip': qa_text.mask_ip(row.visitor_ip) if mask_ips else (row.visitor_ip or ''),
                    'region': row.region or '',
                }
            )
        return {
            'range': resolved_key,
            'total': total,
            'page': page_number,
            'page_size': page_limit,
            'items': items,
        }

    # ------------------------------------------------------------------
    # Page API
    # ------------------------------------------------------------------
    async def handle_page_api(
        self,
        request_context: typing.Any,
        endpoint: str,
        method: str,
        body: typing.Any,
    ) -> typing.Any:
        """Serve the dashboard plugin's read-only page requests."""

        if not self.is_enabled():
            raise ValueError('Q&A analytics is disabled')
        if method.upper() not in {'GET', 'POST'}:
            raise ValueError('Unsupported method')
        payload = body if isinstance(body, dict) else {}
        workspace_uuid = str(getattr(request_context, 'workspace_uuid', '') or '')
        if not workspace_uuid:
            raise ValueError('Workspace is required')

        if endpoint == '/qa-analytics/bots':
            return await self.get_bots(workspace_uuid)
        if endpoint == '/qa-analytics/overview':
            return await self.get_overview(
                workspace_uuid,
                payload.get('range'),
                payload.get('tz_offset_minutes'),
                payload.get('bot_uuid'),
            )
        if endpoint == '/qa-analytics/questions':
            return await self.get_questions(
                workspace_uuid,
                payload.get('range'),
                payload.get('tz_offset_minutes'),
                payload.get('page'),
                payload.get('page_size'),
                payload.get('keyword'),
                payload.get('ip'),
                payload.get('region'),
                payload.get('bot_uuid'),
            )
        if endpoint == '/qa-analytics/questions/detail':
            detail = await self.get_question_detail(
                workspace_uuid,
                payload.get('id'),
                payload.get('bot_uuid'),
            )
            if detail is None:
                raise ValueError('Question not found')
            return detail
        if endpoint == '/qa-analytics/visits':
            return await self.get_visits(
                workspace_uuid,
                payload.get('range'),
                payload.get('tz_offset_minutes'),
                payload.get('page'),
                payload.get('page_size'),
                payload.get('ip'),
                payload.get('region'),
                payload.get('bot_uuid'),
            )
        if endpoint == '/qa-analytics/i18n':
            return await self.get_page_translations(payload.get('language'))
        if endpoint == '/qa-analytics/health':
            return {'ok': True}
        raise ValueError('Unknown endpoint')

    async def get_page_translations(self, language: typing.Any) -> dict[str, str]:
        """Read the page catalog from the installed plugin's own assets.

        The WebUI loads authenticated plugin pages from a blob URL, so the page
        cannot fetch sibling JSON files directly.  Serving the catalog through
        the same read-only page API keeps the translation files in the plugin
        while still working inside the sandbox.
        """

        requested = str(language or '').strip().replace('-', '_')
        if requested not in _CATALOG_LANGUAGES:
            requested = _DEFAULT_CATALOG_LANGUAGE
        author, plugin_name = self.page_plugin_identity()
        connector = getattr(self.ap, 'plugin_connector', None)
        get_assets = getattr(connector, 'get_plugin_assets', None)
        if not callable(get_assets):
            return {}

        for candidate in (requested, _DEFAULT_CATALOG_LANGUAGE):
            try:
                asset = await asyncio.wait_for(
                    get_assets(
                        author,
                        plugin_name,
                        f'components/pages/dashboard/i18n/{candidate}.json',
                    ),
                    timeout=5,
                )
            except Exception:
                continue
            raw = asset.get('asset_base64') if isinstance(asset, dict) else None
            if not raw:
                continue
            try:
                payload = json.loads(base64.b64decode(raw).decode('utf-8'))
            except Exception:
                continue
            if isinstance(payload, dict):
                catalog = {
                    str(key): value for key, value in payload.items() if isinstance(key, str) and isinstance(value, str)
                }
                if catalog:
                    return catalog
        return {}

    # ------------------------------------------------------------------
    # Retention
    # ------------------------------------------------------------------
    async def cleanup_expired_records(
        self,
        context: typing.Any,
        retention_days: int | None = None,
        batch_size: int = 1000,
        max_batches: int = _MAX_CLEANUP_BATCHES,
    ) -> int:
        workspace_uuid = str(getattr(context, 'workspace_uuid', '') or '').strip()
        if not workspace_uuid:
            raise ValueError('Q&A analytics cleanup requires a Workspace')
        days = _bounded_int(
            retention_days if retention_days is not None else self.retention_days(),
            self.retention_days(),
            1,
            3650,
        )
        cutoff = _utc_now_naive() - datetime.timedelta(days=days)
        limit = _bounded_int(batch_size, 1000, 1, _MAX_CLEANUP_BATCH)
        batches = _bounded_int(max_batches, _MAX_CLEANUP_BATCHES, 1, _MAX_CLEANUP_BATCHES)
        model = persistence_qa.QAAnalyticsRecord
        deleted_total = 0

        async with self._read_unit(workspace_uuid) as uow:
            for _ in range(batches):
                id_result = await self._execute(
                    uow,
                    sqlalchemy.select(model.id)
                    .where(model.workspace_uuid == workspace_uuid, model.created_at < cutoff)
                    .limit(limit),
                )
                ids = [row[0] for row in id_result.all()]
                if not ids:
                    break
                await self._execute(
                    uow,
                    sqlalchemy.delete(model).where(
                        model.workspace_uuid == workspace_uuid,
                        model.id.in_(ids),
                    ),
                )
                deleted_total += len(ids)
                if len(ids) < limit:
                    break
        return deleted_total

    def close(self) -> None:
        self.geo.close()
