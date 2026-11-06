"""Embed widget routes - serve embeddable chat widget for external websites.

All user-facing URLs are keyed by **bot_uuid** (not pipeline_uuid) so that
internal pipeline identifiers are never exposed to end-users.  Each handler
resolves the bot_uuid to the owning ``web_page_bot`` RuntimeBot and extracts
the message event route's Pipeline target for internal routing.
"""

import asyncio
import datetime
import json
import logging
import uuid
import hmac
import hashlib
import os
import time
import re
import httpx

import quart
import quart_cors

from ... import group
from ......i18n import language, t
from ......i18n.workspace import get_workspace_language
from ......utils import httpclient, paths
from ......platform.sources.websocket_manager import WebSocketScope, is_valid_session_id, ws_connection_manager
from .websocket_chat import create_scoped_duplex_tasks, wait_for_duplex_tasks

logger = logging.getLogger(__name__)
_AUTH_TIMEOUT_SECONDS = 10.0

# Embed session tokens are bound to one bot and expire after this window.
_EMBED_SESSION_TOKEN_TTL_SECONDS = 86400
# Accept tokens minted slightly in the future on hosts whose clocks differ.
_EMBED_SESSION_TOKEN_FUTURE_SKEW_SECONDS = 60

# Anonymous consultation submissions are throttled in-process because the
# standalone pages cannot reuse the widget's Turnstile token (it lives in a
# closure).  The limits are generous enough for shared campus networks.
_CONSULT_RATE_WINDOW_SECONDS = 600.0
_CONSULT_RATE_LIMIT = 20
_CONSULT_RATE_MAX_CLIENTS = 10000
_consult_rate_windows: dict[str, tuple[float, int]] = {}


def _get_request_client_ip() -> str:
    """Return the visitor IP for a regular HTTP request."""
    try:
        forwarded = quart.request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
        if forwarded:
            return forwarded[:64]
        return str(quart.request.remote_addr or 'unknown')[:64]
    except Exception:
        return 'unknown'


def _admit_consult_submission(ip: str, bot_uuid: str) -> bool:
    """Reserve one slot in the caller's fixed submission window.

    Must stay await-free so check-and-increment is atomic on the event loop.
    """
    global _consult_rate_windows
    now = time.monotonic()
    key = f'{ip}:{bot_uuid}'
    window_start, count = _consult_rate_windows.get(key, (now, 0))
    if now - window_start >= _CONSULT_RATE_WINDOW_SECONDS:
        window_start, count = now, 0
    if count >= _CONSULT_RATE_LIMIT:
        _consult_rate_windows[key] = (window_start, count)
        return False
    _consult_rate_windows[key] = (window_start, count + 1)
    if len(_consult_rate_windows) > _CONSULT_RATE_MAX_CLIENTS:
        cutoff = now - _CONSULT_RATE_WINDOW_SECONDS
        _consult_rate_windows = {
            item_key: item_value for item_key, item_value in _consult_rate_windows.items() if item_value[0] > cutoff
        }
    return True


# Cache the widget template content
_widget_template_cache: str | None = None
_widget_template_cache_mtime_ns: int | None = None
_logo_bytes_cache: bytes | None = None


def _is_valid_uuid(s: str) -> bool:
    return bool(re.match(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', s))


_QUICK_QUESTIONS_MAX_ITEMS = 12
_QUICK_QUESTION_MAX_LENGTH = 200
_QUICK_QUESTIONS_MAX_RAW_CHARS = 20_000
_QUICK_QUESTION_GROUPS_MAX_ITEMS = 6
_QUICK_QUESTION_GROUPS_MAX_RAW_ITEMS = 50
_QUICK_QUESTION_GROUP_LABEL_MAX_LENGTH = 32
_QUICK_QUESTION_GROUP_ID_MAX_LENGTH = 64
_QUICK_QUESTION_GROUP_MAX_RAW_QUESTIONS = 120


def _normalize_question_list(raw: list) -> list[str]:
    """Trim, dedupe and bound one group's question list."""
    questions: list[str] = []
    seen: set[str] = set()

    for item in raw:
        if not isinstance(item, str):
            continue
        question = item.strip()
        if not question:
            continue
        if len(question) > _QUICK_QUESTION_MAX_LENGTH:
            question = question[:_QUICK_QUESTION_MAX_LENGTH].rstrip()
        if not question or question in seen:
            continue
        seen.add(question)
        questions.append(question)
        if len(questions) >= _QUICK_QUESTIONS_MAX_ITEMS:
            break

    return questions


def _parse_quick_question_groups(raw) -> list[dict]:
    """Normalize admin-configured quick question groups.

    ``adapter_config`` stores a JSON array. A JSON string is also accepted so
    configurations written by hand or by older forms keep working.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return []
    if not isinstance(raw, list):
        return []

    groups: list[dict] = []
    seen_ids: set[str] = set()

    # The field is admin-controlled, but bound the per-request work anyway.
    for item in raw[:_QUICK_QUESTION_GROUPS_MAX_RAW_ITEMS]:
        if len(groups) >= _QUICK_QUESTION_GROUPS_MAX_ITEMS:
            break
        if not isinstance(item, dict):
            continue

        label = item.get('label')
        if not isinstance(label, str):
            continue
        label = label.strip()
        if not label:
            continue
        if len(label) > _QUICK_QUESTION_GROUP_LABEL_MAX_LENGTH:
            label = label[:_QUICK_QUESTION_GROUP_LABEL_MAX_LENGTH].rstrip()
        if not label:
            continue

        raw_questions = item.get('questions', [])
        if isinstance(raw_questions, str):
            raw_questions = raw_questions[:_QUICK_QUESTIONS_MAX_RAW_CHARS].splitlines()
        if not isinstance(raw_questions, list):
            raw_questions = []
        questions = _normalize_question_list(
            raw_questions[:_QUICK_QUESTION_GROUP_MAX_RAW_QUESTIONS]
        )

        raw_id = item.get('id')
        group_id = raw_id.strip() if isinstance(raw_id, str) else ''
        if len(group_id) > _QUICK_QUESTION_GROUP_ID_MAX_LENGTH:
            group_id = group_id[:_QUICK_QUESTION_GROUP_ID_MAX_LENGTH]
        if not group_id:
            group_id = f'group-{len(groups) + 1}'
        base_id = group_id
        suffix = 2
        while group_id in seen_ids:
            group_id = f'{base_id}-{suffix}'
            suffix += 1
        seen_ids.add(group_id)

        groups.append({'id': group_id, 'label': label, 'questions': questions})

    return groups


def _get_client_ip() -> str:
    """Return the visitor IP for the active embed WebSocket connection.

    WebSocket handlers run in a WebSocket context, so ``quart.request`` is not
    available here; reading it through the request proxy would raise and the
    collector would store no IP at all.
    """
    try:
        forwarded = quart.websocket.headers.get('X-Forwarded-For', '').split(',')[0].strip()
        if forwarded:
            return forwarded[:64]
        return str(quart.websocket.remote_addr or '')[:64]
    except Exception:
        return ''


def _get_widget_template() -> str:
    """Load the widget template and refresh the cache when the file changes."""
    global _widget_template_cache, _widget_template_cache_mtime_ns
    template_path = paths.get_resource_path('templates/embed/widget.js')
    template_mtime_ns = os.stat(template_path).st_mtime_ns
    if _widget_template_cache is None or _widget_template_cache_mtime_ns != template_mtime_ns:
        with open(template_path, 'r', encoding='utf-8') as f:
            _widget_template_cache = f.read()
        _widget_template_cache_mtime_ns = template_mtime_ns
    return _widget_template_cache


def _get_logo_bytes() -> bytes:
    """Load and cache the logo image."""
    global _logo_bytes_cache
    if _logo_bytes_cache is None:
        logo_path = paths.get_resource_path('templates/embed/logo.webp')
        with open(logo_path, 'rb') as f:
            _logo_bytes_cache = f.read()
    return _logo_bytes_cache


@group.group_class('embed', '/api/v1/embed')
class EmbedRouterGroup(group.RouterGroup):
    # -- helpers -------------------------------------------------------------

    async def _resolve_bot(self, bot_uuid: str):
        """Resolve *bot_uuid* to ``(runtime_bot, pipeline_uuid)``.

        Returns ``(None, None)`` when the bot does not exist, is not a
        ``web_page_bot``, is disabled, or has no Pipeline target for messages.
        """
        bot = await self.ap.platform_mgr.resolve_public_bot(bot_uuid)
        pipeline_uuid = bot.get_pipeline_target_for_event_type('message.received') if bot is not None else None
        if bot is not None and bot.bot_entity.adapter == 'web_page_bot' and bot.bot_entity.enable and pipeline_uuid:
            language.set(await get_workspace_language(self.ap, bot.execution_context.workspace_uuid))
            return bot, pipeline_uuid
        return None, None

    @staticmethod
    def _get_bot_config(runtime_bot) -> dict:
        return runtime_bot.bot_entity.adapter_config

    def _session_signing_key(self, runtime_bot) -> str:
        """Return the HMAC key used to sign embed session tokens.

        A configured Turnstile secret is already a per-bot server-side secret,
        so it stays the key for backward compatibility.  When Turnstile is
        disabled the bot has no secret of its own, so derive a stable key from
        the instance JWT secret and the bot UUID.  Returning ``''`` makes
        verification fail closed instead of accepting arbitrary tokens.
        """
        config = self._get_bot_config(runtime_bot)
        secret = str(config.get('turnstile_secret_key') or '').strip()
        if secret:
            return secret

        system = self.ap.instance_config.data.get('system', {})
        jwt_config = system.get('jwt', {}) if isinstance(system, dict) else {}
        jwt_secret = str(jwt_config.get('secret') or '').strip() if isinstance(jwt_config, dict) else ''
        if not jwt_secret:
            return ''
        return hmac.new(
            jwt_secret.encode(),
            f'langbot-embed-session:{runtime_bot.bot_entity.uuid}'.encode(),
            hashlib.sha256,
        ).hexdigest()

    def _issue_session_token(self, runtime_bot) -> str:
        """Mint a timestamped token for one bot, or ``''`` without a key."""
        signing_key = self._session_signing_key(runtime_bot)
        if not signing_key:
            logger.error('Cannot issue embed session token: no signing key configured')
            return ''
        ts_str = f'{time.time()}'
        mac = hmac.new(signing_key.encode(), ts_str.encode(), hashlib.sha256).hexdigest()
        return f'{ts_str}.{mac}'

    def _verify_session_token_value(self, token: str, runtime_bot) -> bool:
        """Verify a token minted by :meth:`_issue_session_token`."""
        if not token:
            return False
        signing_key = self._session_signing_key(runtime_bot)
        if not signing_key:
            return False
        try:
            # Time floats contain a dot, so the MAC is separated from the right.
            ts_str, mac = token.rsplit('.', 1)
            ts = float(ts_str)
            now = time.time()
            if now - ts > _EMBED_SESSION_TOKEN_TTL_SECONDS:
                return False
            if ts - now > _EMBED_SESSION_TOKEN_FUTURE_SKEW_SECONDS:
                return False
            expected_mac = hmac.new(signing_key.encode(), ts_str.encode(), hashlib.sha256).hexdigest()
            return hmac.compare_digest(mac, expected_mac)
        except Exception:
            return False

    async def _verify_session_token(self, request, runtime_bot) -> bool:
        auth_header = request.headers.get('Authorization', '')
        token = auth_header[7:] if auth_header.startswith('Bearer ') else ''
        return self._verify_session_token_value(token, runtime_bot)

    async def _authenticate_websocket(self, runtime_bot) -> None:
        """Require the embed session token as the first WebSocket frame."""

        raw_message = await asyncio.wait_for(quart.websocket.receive(), timeout=_AUTH_TIMEOUT_SECONDS)
        payload = await asyncio.to_thread(json.loads, raw_message)
        if not isinstance(payload, dict) or payload.get('type') != 'authenticate':
            raise ValueError('Authentication is required')
        token = str(payload.get('token') or '')
        if not self._verify_session_token_value(token, runtime_bot):
            raise ValueError('Authentication is required')

    async def _assert_execution_active(self, runtime_bot) -> None:
        context = runtime_bot.execution_context
        await self.ap.workspace_service.get_execution_binding(
            context.workspace_uuid,
            expected_generation=context.placement_generation,
        )

    async def _resolve_connected_bot(self, owner_bot, pipeline_uuid: str):
        """Re-resolve mutable bot state before every public message."""
        current_bot, current_pipeline_uuid = await self._resolve_bot(owner_bot.bot_entity.uuid)
        if current_bot is None or current_pipeline_uuid != pipeline_uuid:
            raise RuntimeError('Bot is unavailable')

        owner_context = owner_bot.execution_context
        current_context = current_bot.execution_context
        if (
            current_context.instance_uuid,
            current_context.workspace_uuid,
            current_context.placement_generation,
        ) != (
            owner_context.instance_uuid,
            owner_context.workspace_uuid,
            owner_context.placement_generation,
        ):
            raise RuntimeError('Bot is unavailable')
        await self._assert_execution_active(current_bot)
        return current_bot

    # -- routes --------------------------------------------------------------

    async def initialize(self) -> None:
        @self.route('/<bot_uuid>/turnstile/verify', methods=['POST'], auth_type=group.AuthType.NONE)
        async def verify_turnstile(bot_uuid: str) -> str:
            if not _is_valid_uuid(bot_uuid):
                return self.http_status(400, -1, 'Invalid bot_uuid format')
            runtime_bot, pipeline_uuid = await self._resolve_bot(bot_uuid)
            if runtime_bot is None:
                return self.http_status(404, -1, 'Bot not found or not available')
            try:
                data = await quart.request.get_json()
                token = data.get('token') if isinstance(data, dict) else None

                config = self._get_bot_config(runtime_bot)
                secret = str(config.get('turnstile_secret_key') or '').strip()
                if secret:
                    if not token:
                        return self.http_status(400, -1, 'Token is required')

                    async with httpx.AsyncClient(event_hooks=httpclient.httpx_response_limit_hooks()) as client:
                        resp = await client.post(
                            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
                            data={'secret': secret, 'response': token},
                        )
                        result = await httpclient.parse_json_response(resp)

                    if not result.get('success'):
                        return self.http_status(403, -1, 'Turnstile verification failed')

                # Turnstile disabled still mints an HMAC token: the session
                # routes and the WebSocket must never accept anonymous callers.
                session_token = self._issue_session_token(runtime_bot)
                if not session_token:
                    return self.http_status(500, -1, 'Embed session signing is not configured')
                return self.success(data={'token': session_token})

            except Exception as e:
                logger.error(f'Turnstile verify failed: {e}', exc_info=True)
                return self.http_status(500, -1, 'Internal server error')

        @self.route('/<bot_uuid>/widget.js', methods=['GET'], auth_type=group.AuthType.NONE)
        async def serve_widget(bot_uuid: str) -> quart.Response:
            """Serve the embed widget JavaScript with injected configuration."""
            if not _is_valid_uuid(bot_uuid):
                return self.http_status(400, -1, 'Invalid bot_uuid format')
            runtime_bot, pipeline_uuid = await self._resolve_bot(bot_uuid)
            if runtime_bot is None:
                return quart.Response(
                    '// Bot not found or not available', status=404, content_type='application/javascript'
                )
            try:
                template = _get_widget_template()
            except FileNotFoundError:
                return quart.Response('// Widget template not found', status=404, content_type='application/javascript')

            base_url = quart.request.host_url.rstrip('/')
            webhook_prefix = self.ap.instance_config.data.get('api', {}).get('webhook_prefix', '')
            # The wizard previews the currently connected backend, which can
            # differ from the public address used by external website embeds.
            if webhook_prefix and quart.request.args.get('preview') != 'wizard':
                base_url = webhook_prefix.rstrip('/')

            if not re.match(r'^https?://[a-zA-Z0-9._:/-]+$', base_url):
                base_url = quart.request.host_url.rstrip('/')

            config = self._get_bot_config(runtime_bot)
            site_key = config.get('turnstile_site_key', '')
            locale = config.get('language', 'en_US') or 'en_US'
            bubble_icon = config.get('bubble_icon', 'logo') or 'logo'
            # Existing bots created before this field keep an empty value, so
            # the widget falls back to the standalone page subtitle.
            welcome_message = str(config.get('welcome_message') or '').strip()
            quick_question_groups = _parse_quick_question_groups(config.get('quick_question_groups', []))
            # ensure_ascii=True also escapes U+2028/U+2029; "<" is escaped so a
            # question or welcome text such as "</script>" can never terminate
            # an inline script.
            quick_question_groups_json = json.dumps(quick_question_groups, ensure_ascii=True).replace('<', '\\u003c')
            welcome_message_json = json.dumps(welcome_message, ensure_ascii=True).replace('<', '\\u003c')

            widget_js = template.replace('__LANGBOT_TURNSTILE_SITE_KEY__', site_key)
            widget_js = widget_js.replace('__LANGBOT_BOT_UUID__', bot_uuid)
            widget_js = widget_js.replace('__LANGBOT_BASE_URL__', base_url)
            widget_js = widget_js.replace('__LANGBOT_LOCALE__', locale)
            widget_js = widget_js.replace('__LANGBOT_BUBBLE_ICON__', bubble_icon)
            widget_js = widget_js.replace('"__LANGBOT_ROLE_GROUPS__"', quick_question_groups_json)
            widget_js = widget_js.replace("'__LANGBOT_ROLE_GROUPS__'", quick_question_groups_json)
            # Inject the free-text welcome message last so text containing
            # other __LANGBOT_* tokens cannot be rewritten by the replacements
            # above.
            widget_js = widget_js.replace('"__LANGBOT_WELCOME_MESSAGE__"', welcome_message_json)
            widget_js = widget_js.replace("'__LANGBOT_WELCOME_MESSAGE__'", welcome_message_json)

            response = quart.Response(widget_js, content_type='application/javascript; charset=utf-8')
            response.headers['Cache-Control'] = 'public, max-age=300'
            return response

        @self.route('/logo', methods=['GET'], auth_type=group.AuthType.NONE)
        async def serve_logo() -> quart.Response:
            """Serve the LangBot logo for the embed widget."""
            try:
                logo_data = _get_logo_bytes()
            except FileNotFoundError:
                return quart.Response('', status=404)

            response = quart.Response(logo_data, content_type='image/webp')
            response.headers['Cache-Control'] = 'public, max-age=86400'
            return response

        @self.route('/<bot_uuid>/messages/<session_type>', methods=['GET'], auth_type=group.AuthType.NONE)
        async def get_embed_messages(bot_uuid: str, session_type: str) -> str:
            if not _is_valid_uuid(bot_uuid):
                return self.http_status(400, -1, 'Invalid bot_uuid format')
            runtime_bot, pipeline_uuid = await self._resolve_bot(bot_uuid)
            if runtime_bot is None:
                return self.http_status(404, -1, 'Bot not found or not available')
            if not await self._verify_session_token(quart.request, runtime_bot):
                return self.http_status(403, -1, 'Unauthorized or session expired')
            try:
                if session_type not in ['person', 'group']:
                    return self.http_status(400, -1, 'session_type must be person or group')

                session_id = quart.request.args.get('session_id', '')
                if not is_valid_session_id(session_id):
                    return self.http_status(400, -1, 'Valid session_id is required')

                proxy_bot = await self.ap.platform_mgr.get_websocket_proxy_bot(runtime_bot.execution_context)
                websocket_adapter = proxy_bot.adapter
                if not websocket_adapter:
                    return self.http_status(404, -1, 'WebSocket adapter not found')

                messages = websocket_adapter.get_websocket_messages(pipeline_uuid, session_type, session_id)
                return self.success(data={'messages': messages})

            except Exception as e:
                logger.error(f'Failed to get embed messages: {e}', exc_info=True)
                return self.http_status(500, -1, 'Internal server error')

        @self.route('/<bot_uuid>/reset/<session_type>', methods=['POST'], auth_type=group.AuthType.NONE)
        async def reset_embed_session(bot_uuid: str, session_type: str) -> str:
            if not _is_valid_uuid(bot_uuid):
                return self.http_status(400, -1, 'Invalid bot_uuid format')
            runtime_bot, pipeline_uuid = await self._resolve_bot(bot_uuid)
            if runtime_bot is None:
                return self.http_status(404, -1, 'Bot not found or not available')
            if not await self._verify_session_token(quart.request, runtime_bot):
                return self.http_status(403, -1, 'Unauthorized or session expired')
            try:
                if session_type not in ['person', 'group']:
                    return self.http_status(400, -1, 'session_type must be person or group')

                session_id = quart.request.args.get('session_id', '')
                if not is_valid_session_id(session_id):
                    return self.http_status(400, -1, 'Valid session_id is required')

                proxy_bot = await self.ap.platform_mgr.get_websocket_proxy_bot(runtime_bot.execution_context)
                websocket_adapter = proxy_bot.adapter
                if not websocket_adapter:
                    return self.http_status(404, -1, 'WebSocket adapter not found')

                websocket_adapter.reset_session(pipeline_uuid, session_type, session_id)
                return self.success(data={'message': t('Session reset successfully')})

            except Exception as e:
                logger.error(f'Failed to reset embed session: {e}', exc_info=True)
                return self.http_status(500, -1, 'Internal server error')

        @self.route('/<bot_uuid>/feedback', methods=['POST'], auth_type=group.AuthType.NONE)
        async def submit_feedback(bot_uuid: str) -> str:
            if not _is_valid_uuid(bot_uuid):
                return self.http_status(400, -1, 'Invalid bot_uuid format')
            runtime_bot, pipeline_uuid = await self._resolve_bot(bot_uuid)
            if runtime_bot is None:
                return self.http_status(404, -1, 'Bot not found or not available')
            if not await self._verify_session_token(quart.request, runtime_bot):
                return self.http_status(403, -1, 'Unauthorized or session expired')
            try:
                data = await quart.request.get_json()
                message_id = data.get('message_id', '')
                feedback_type = data.get('feedback_type')

                if feedback_type not in (1, 2, 3):
                    return self.http_status(400, -1, 'feedback_type must be 1 (like), 2 (dislike), or 3 (cancel)')

                feedback_id = f'embed_{uuid.uuid4().hex[:12]}'

                await self.ap.monitoring_service.record_feedback(
                    runtime_bot.execution_context,
                    feedback_id=feedback_id,
                    feedback_type=feedback_type,
                    bot_id=runtime_bot.bot_entity.uuid,
                    bot_name=runtime_bot.bot_entity.name or bot_uuid,
                    pipeline_id=pipeline_uuid,
                    message_id=str(message_id),
                    platform='web_page_bot',
                )

                return self.success(data={'feedback_id': feedback_id})

            except Exception as e:
                logger.error(f'Failed to record feedback: {e}', exc_info=True)
                return self.http_status(500, -1, 'Internal server error')

        @self.route('/<bot_uuid>/consult-messages', methods=['POST'], auth_type=group.AuthType.NONE)
        async def submit_consult_message(bot_uuid: str) -> str:
            """Record a lead from the standalone consultation pages.

            The standalone page cannot read the widget's Turnstile session
            token, so this public route relies on strict field validation and
            a per-IP submission window instead of the embed session token.
            """
            if not _is_valid_uuid(bot_uuid):
                return self.http_status(400, -1, 'Invalid bot_uuid format')
            runtime_bot, _ = await self._resolve_bot(bot_uuid)
            if runtime_bot is None:
                return self.http_status(404, -1, 'Bot not found or not available')

            qa_service = getattr(self.ap, 'qa_analytics_service', None)
            if qa_service is None or not qa_service.is_enabled():
                return self.http_status(503, -1, 'Q&A analytics is disabled')

            if not _admit_consult_submission(_get_request_client_ip(), bot_uuid):
                return self.http_status(429, -1, 'Too many submissions; please try again later')

            try:
                data = await quart.request.get_json()
            except Exception:
                return self.http_status(400, -1, 'Invalid request body')
            if not isinstance(data, dict):
                return self.http_status(400, -1, 'Invalid request body')

            try:
                await qa_service.submit_consult_message(
                    runtime_bot.execution_context.workspace_uuid,
                    runtime_bot.bot_entity.uuid,
                    data,
                )
            except ValueError as exc:
                return self.http_status(400, -1, str(exc))
            except Exception as exc:
                # Never log the submitted contact details.
                logger.error(f'Failed to record consultation message: {type(exc).__name__}')
                return self.http_status(500, -1, 'Internal server error')

            return self.success(data={'ok': True})

        # -- Embed WebSocket endpoint ----------------------------------------

        @self.quart_app.websocket(self.path + '/<bot_uuid>/ws/connect')
        @quart_cors.cors_exempt
        async def embed_websocket_connect(bot_uuid: str):
            """WebSocket connection for embed widget, keyed by bot_uuid."""
            await quart.websocket.accept()
            if not _is_valid_uuid(bot_uuid):
                await quart.websocket.send(json.dumps({'type': 'error', 'message': 'Invalid bot_uuid format'}))
                return

            runtime_bot, pipeline_uuid = await self._resolve_bot(bot_uuid)
            if runtime_bot is None:
                await quart.websocket.send(
                    json.dumps({'type': 'error', 'message': t('Bot not found or not available')})
                )
                return

            session_type = quart.websocket.args.get('session_type', 'person')
            if session_type not in ['person', 'group']:
                await quart.websocket.send(
                    json.dumps({'type': 'error', 'message': 'session_type must be person or group'})
                )
                return

            session_id = quart.websocket.args.get('session_id', '')
            if not is_valid_session_id(session_id):
                await quart.websocket.send(json.dumps({'type': 'error', 'message': 'Valid session_id is required'}))
                return

            try:
                await self._authenticate_websocket(runtime_bot)
                await self._assert_execution_active(runtime_bot)
            except Exception:
                # ``code`` lets the widget discard an expired token and mint a
                # fresh one without parsing a localized message.
                await quart.websocket.send(
                    json.dumps({'type': 'error', 'message': t('Unauthorized'), 'code': 'unauthorized'})
                )
                return
            try:
                proxy_bot = await self.ap.platform_mgr.get_websocket_proxy_bot(runtime_bot.execution_context)
                websocket_adapter = proxy_bot.adapter
                if not websocket_adapter:
                    await quart.websocket.send(
                        json.dumps({'type': 'error', 'message': t('WebSocket adapter not found')})
                    )
                    return

                connection = await ws_connection_manager.add_connection(
                    websocket=quart.websocket._get_current_object(),
                    scope=WebSocketScope.from_context(runtime_bot.execution_context),
                    pipeline_uuid=pipeline_uuid,
                    session_type=session_type,
                    session_id=session_id,
                    metadata={
                        'user_agent': quart.websocket.headers.get('User-Agent', ''),
                        # Kept in memory only; the analytics collector persists it
                        # under the Workspace retention policy.
                        'client_ip': _get_client_ip(),
                    },
                    send_queue_size=(
                        self.ap.instance_config.data.get('system', {})
                        .get('websocket_retention', {})
                        .get('send_queue_size', 100)
                    ),
                    max_connections=(
                        self.ap.instance_config.data.get('system', {})
                        .get('websocket_retention', {})
                        .get('max_connections', 1024)
                    ),
                    max_connections_per_workspace=(
                        self.ap.instance_config.data.get('system', {})
                        .get('websocket_retention', {})
                        .get('max_connections_per_workspace', 32)
                    ),
                )

                await quart.websocket.send(
                    json.dumps(
                        {
                            'type': 'connected',
                            'connection_id': connection.connection_id,
                            'bot_uuid': bot_uuid,
                            'session_type': session_type,
                            'timestamp': connection.created_at.isoformat(),
                        }
                    )
                )

                logger.debug(
                    f'Embed WebSocket connected: {connection.connection_id} '
                    f'(bot={bot_uuid}, pipeline={pipeline_uuid}, session_type={session_type})'
                )

                receive_task, send_task = create_scoped_duplex_tasks(
                    self._handle_receive(
                        connection,
                        websocket_adapter,
                        runtime_bot,
                        pipeline_uuid,
                    ),
                    self._handle_send(connection),
                    runtime_bot.execution_context.workspace_uuid,
                )

                try:
                    await wait_for_duplex_tasks(receive_task, send_task)
                except Exception as e:
                    logger.error(f'Embed WebSocket task error: {e}')
                finally:
                    await ws_connection_manager.remove_connection(connection.connection_id)

            except Exception as e:
                logger.error(f'Embed WebSocket connection error: {e}', exc_info=True)
                try:
                    await quart.websocket.send(json.dumps({'type': 'error', 'message': t('Internal server error')}))
                except Exception:
                    pass

    # -- WebSocket receive/send helpers --------------------------------------

    async def _handle_receive(self, connection, websocket_adapter, owner_bot, pipeline_uuid: str):
        try:
            while connection.is_active:
                message = await quart.websocket.receive()
                await ws_connection_manager.update_activity(connection.connection_id)
                try:
                    data = await asyncio.to_thread(json.loads, message)
                    message_type = data.get('type', 'message')

                    if message_type == 'ping':
                        await connection.send_queue.put(
                            {'type': 'pong', 'timestamp': datetime.datetime.now().isoformat()}
                        )
                    elif message_type == 'message':
                        try:
                            current_bot = await self._resolve_connected_bot(owner_bot, pipeline_uuid)
                        except Exception:
                            await connection.send_queue.put({'type': 'error', 'message': t('Bot is unavailable')})
                            break
                        await websocket_adapter.handle_websocket_message(connection, data, owner_bot=current_bot)
                    elif message_type == 'disconnect':
                        break
                    else:
                        pass

                except json.JSONDecodeError:
                    await connection.send_queue.put({'type': 'error', 'message': t('Invalid JSON format')})

        except Exception as e:
            logger.error(f'Embed receive error: {e}', exc_info=True)
        finally:
            connection.is_active = False
            try:
                connection.send_queue.put_nowait(None)
            except asyncio.QueueFull:
                pass

    async def _handle_send(self, connection):
        try:
            while connection.is_active or not connection.send_queue.empty():
                try:
                    message = await asyncio.wait_for(connection.send_queue.get(), timeout=1.0)
                    if message is None:
                        break
                    encoded = await asyncio.to_thread(json.dumps, message)
                    await quart.websocket.send(encoded)
                except asyncio.TimeoutError:
                    continue
        except Exception as e:
            logger.error(f'Embed send error: {e}', exc_info=True)
        finally:
            connection.is_active = False
