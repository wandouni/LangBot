from __future__ import annotations

import asyncio
import importlib
import os
import typing
from urllib.parse import urlsplit

import quart
import quart_cors
from werkzeug.exceptions import RequestEntityTooLarge

from ....core import app, entities as core_entities
from ....utils import importutil

from . import groups
from . import group
from .groups import provider as groups_provider
from .groups import platform as groups_platform
from .groups import pipelines as groups_pipelines
from .groups import knowledge as groups_knowledge
from .groups import resources as groups_resources
from ...mcp.mount import MCPMount

importutil.import_modules_in_pkg(groups)
importutil.import_modules_in_pkg(groups_provider)
importutil.import_modules_in_pkg(groups_platform)
importutil.import_modules_in_pkg(groups_pipelines)
importutil.import_modules_in_pkg(groups_knowledge)
importutil.import_modules_in_pkg(groups_resources)

# The traceability subsystem is self-contained and auto-registers its routes
# through ``group.group_class``. Importing it here (instead of from within the
# ``groups`` package) keeps the feature decoupled: the Core controller package
# contains no code that depends on it, only this single bootstrap import. It
# runs after the package scan so its routes join the same registry.
importlib.import_module('langbot.pkg.operation_trace.routes')


class BoundedJSONRequest(quart.Request):
    """Parse bounded HTTP JSON bodies outside the shared event loop."""

    async def get_json(
        self,
        force: bool = False,
        silent: bool = False,
        cache: bool = True,
    ) -> typing.Any:
        # Keep Quart's cache and error semantics, changing only where the
        # potentially 10 MiB JSON decoder runs. The RouterGroup establishes a
        # trusted Workspace blocking-work scope before calling route handlers.
        if cache and self._cached_json[silent] is not Ellipsis:
            return self._cached_json[silent]
        if not (force or self.is_json):
            return None

        data = await self.get_data(cache=cache, as_text=False)
        try:
            result = await asyncio.to_thread(self.json_module.loads, data)
        except ValueError as error:
            if silent:
                result = None
            else:
                result = self.on_json_loading_failed(error)

        if cache:
            self._cached_json[silent] = result
        return result


# The embed widget is served from LangBot but runs on arbitrary customer
# sites, so only these public routes keep wildcard CORS. Authenticated APIs
# are limited to an explicit origin allow list.
_EMBED_CORS_PATH_PREFIX = '/api/v1/embed/'
_EMBED_CORS_ALLOW_HEADERS = 'Authorization, Content-Type'
_EMBED_CORS_ALLOW_METHODS = 'GET, POST, OPTIONS'
_API_CORS_ALLOW_METHODS = 'GET, HEAD, POST, OPTIONS, PUT, PATCH, DELETE'
_API_CORS_ALLOW_HEADERS = (
    'Authorization, Content-Type, X-API-Key, X-Workspace-Id, X-LangBot-Language'
)
_DEV_CORS_ORIGINS = ('http://localhost:3000', 'http://127.0.0.1:3000')


def _origin_from_url(value: typing.Any) -> str:
    """Return ``scheme://host[:port]`` for a configured absolute URL."""
    try:
        parsed = urlsplit(str(value or '').strip())
    except ValueError:
        return ''
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        return ''
    return f'{parsed.scheme}://{parsed.netloc}'


def _is_same_origin(origin: str, host: str) -> bool:
    """Return True when an origin header points at the request's own host."""
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return bool(parsed.netloc) and parsed.netloc.lower() == str(host or '').lower()


def _configured_cors_origins(api_config: typing.Any) -> list[str]:
    """Build the CORS allow list for authenticated API routes.

    ``api.cors_origins`` wins when set. Otherwise the browser origins implied
    by ``api.webui_url`` / ``api.webhook_prefix`` are allowed, plus the Vite
    dev server. Same-origin WebUI deployments need no entry at all.
    """
    configured = api_config.get('cors_origins', []) if isinstance(api_config, dict) else []
    if isinstance(configured, str):
        configured = configured.split(',')
    if not isinstance(configured, (list, tuple)):
        configured = []

    origins: list[str] = []
    for item in configured:
        origin = str(item or '').strip().rstrip('/')
        if origin:
            origins.append(origin)

    if origins:
        return list(dict.fromkeys(origins))

    origins.extend(_DEV_CORS_ORIGINS)
    if isinstance(api_config, dict):
        for key in ('webui_url', 'webhook_prefix'):
            origin = _origin_from_url(api_config.get(key))
            if origin:
                origins.append(origin)
    return list(dict.fromkeys(origins))


class HTTPController:
    ap: app.Application

    quart_app: quart.Quart

    def __init__(self, ap: app.Application) -> None:
        self.ap = ap
        self.quart_app = quart.Quart(__name__)
        self.quart_app.request_class = BoundedJSONRequest
        self._cors_origins = _configured_cors_origins(self.ap.instance_config.data.get('api', {}))

        @self.quart_app.after_request
        async def apply_cors_headers(response: quart.Response) -> quart.Response:
            origin = quart.request.origin
            if not origin:
                return response

            if (quart.request.path or '').startswith(_EMBED_CORS_PATH_PREFIX):
                # Public widget routes are called from whatever site embeds the
                # widget. The endpoints authenticate with the signed session
                # token and use no cookies, so wildcard access is safe here.
                response.headers['Access-Control-Allow-Origin'] = '*'
                response.headers['Access-Control-Allow-Headers'] = _EMBED_CORS_ALLOW_HEADERS
                response.headers['Access-Control-Allow-Methods'] = _EMBED_CORS_ALLOW_METHODS
                response.headers['Access-Control-Max-Age'] = '600'
                return response

            if origin in self._cors_origins:
                response.headers['Access-Control-Allow-Origin'] = origin
                response.headers['Access-Control-Allow-Methods'] = _API_CORS_ALLOW_METHODS
                response.headers['Access-Control-Allow-Headers'] = (
                    quart.request.access_control_request_headers or _API_CORS_ALLOW_HEADERS
                )
                response.headers['Access-Control-Max-Age'] = '600'
                response.vary.add('Origin')
            return response

        @self.quart_app.before_websocket
        async def check_websocket_origin() -> None:
            # Browsers send Origin on the WebSocket handshake. Allow same-origin
            # pages and explicitly configured origins; the embed socket is
            # exempt because it runs on customer sites and authenticates with a
            # signed session token.
            view_func = self.quart_app.view_functions.get(quart.websocket.endpoint)
            if getattr(view_func, quart_cors.QUART_CORS_EXEMPT_ATTRIBUTE, False):
                return
            origin = quart.websocket.origin
            if not origin:
                # Non-browser protocol clients (reverse WebSocket, CLI) omit it
                # and authenticate through their own token checks.
                return
            host = quart.websocket.headers.get('Host', '')
            if origin in self._cors_origins or _is_same_origin(origin, host):
                return
            quart.abort(400)

        # Set maximum content length to prevent large file uploads
        self.quart_app.config['MAX_CONTENT_LENGTH'] = group.MAX_FILE_SIZE

        # MCP server (mounted at /mcp, see ..mcp.mount). Built lazily in
        # initialize() so the service layer is ready.
        self.mcp_mount: MCPMount | None = None

    async def initialize(self) -> None:
        # Register custom error handler for file size limit
        @self.quart_app.errorhandler(RequestEntityTooLarge)
        async def handle_request_entity_too_large(e):
            return quart.jsonify(
                {
                    'code': 400,
                    'msg': 'File size exceeds 10MB limit. Please split large files into smaller parts.',
                }
            ), 400

        await self.register_routes()

        # Build the MCP server and start its session-manager lifespan in the
        # background so the streamable-HTTP transport is ready to serve.
        self.mcp_mount = MCPMount(self.ap)
        await self.mcp_mount.start_session_manager()
        self.ap.logger.info('LangBot MCP server mounted at /mcp (API-key authenticated).')

    async def run(self) -> None:
        if True:

            async def shutdown_trigger_placeholder():
                while True:
                    await asyncio.sleep(1)

            async def exception_handler(*args, **kwargs):
                try:
                    await self._run_task(*args, **kwargs)
                except Exception as e:
                    self.ap.logger.error(f'Failed to start HTTP service: {e}')

            self.ap.task_mgr.create_task(
                exception_handler(
                    host=self.ap.instance_config.data['api'].get('host', '0.0.0.0'),
                    port=self.ap.instance_config.data['api']['port'],
                    shutdown_trigger=shutdown_trigger_placeholder,
                ),
                name='http-api-quart',
                scopes=[core_entities.LifecycleControlScope.APPLICATION],
            )

            # await asyncio.sleep(5)

    async def _run_task(self, host: str, port: int, shutdown_trigger) -> None:
        """Serve the Quart app, fronted by the MCP dispatcher at /mcp.

        Mirrors Quart.run_task() but wraps the ASGI app so MCP requests are
        intercepted before Quart's router. Falls back to plain Quart if the
        MCP mount failed to build for any reason.
        """
        from hypercorn.config import Config as HyperConfig
        from hypercorn.asyncio import serve as hypercorn_serve

        config = HyperConfig()
        config.access_log_format = '%(h)s %(r)s %(s)s %(b)s %(D)s'
        config.accesslog = '-'
        config.bind = [f'{host}:{port}']
        config.errorlog = config.accesslog
        config.websocket_max_message_size = group.MAX_FILE_SIZE

        asgi_app = self.quart_app
        if self.mcp_mount is not None:
            asgi_app = self.mcp_mount.wrap(self.quart_app)

        await hypercorn_serve(asgi_app, config, shutdown_trigger=shutdown_trigger)

    async def register_routes(self) -> None:
        @self.quart_app.route('/healthz')
        async def healthz():
            get_resource_stats = getattr(
                self.ap,
                'get_runtime_resource_stats',
                None,
            )
            return {
                'code': 0,
                'msg': 'ok',
                'resources': (get_resource_stats() if callable(get_resource_stats) else {}),
            }

        for g in group.preregistered_groups:
            ginst = g(self.ap, self.quart_app)
            await ginst.initialize()

        from ....utils import paths

        frontend_path = paths.get_frontend_path()

        async def frontend_index():
            from .social_preview import cloud_preview_html

            response = await quart.send_from_directory(
                frontend_path, 'index.html', mimetype='text/html', conditional=False
            )
            if quart.request.host.split(':', 1)[0].lower() == 'cloud.langbot.app':
                response.set_data(cloud_preview_html(await response.get_data(as_text=True), quart.request.host))
                response.headers.pop('ETag', None)
                response.headers.pop('Last-Modified', None)
            return response

        @self.quart_app.route('/')
        async def index():
            response = await frontend_index()
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            return response

        @self.quart_app.route('/<path:path>')
        async def static_file(path: str):
            if not (
                os.path.exists(os.path.join(frontend_path, path)) and os.path.isfile(os.path.join(frontend_path, path))
            ):
                if os.path.exists(os.path.join(frontend_path, path + '.html')):
                    path += '.html'
                elif not path.startswith('api/'):
                    # SPA fallback: serve index.html for all non-API, non-static routes
                    # so that React Router can handle client-side routing (Vite SPA).
                    # For /home/* sub-routes, first try parent .html files (pre-rendered pages).
                    if path.startswith('home/'):
                        segments = path.rstrip('/').split('/')
                        for i in range(len(segments) - 1, 0, -1):
                            parent_path = '/'.join(segments[:i]) + '.html'
                            if os.path.exists(os.path.join(frontend_path, parent_path)):
                                response = await quart.send_from_directory(
                                    frontend_path, parent_path, mimetype='text/html'
                                )
                                response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                                response.headers['Pragma'] = 'no-cache'
                                response.headers['Expires'] = '0'
                                return response

                    # Fallback to index.html for SPA client-side routing
                    response = await frontend_index()
                    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                    response.headers['Pragma'] = 'no-cache'
                    response.headers['Expires'] = '0'
                    return response
                else:
                    return await quart.send_from_directory(frontend_path, '404.html')

            mimetype = None

            if path.endswith('.html'):
                mimetype = 'text/html'
            elif path.endswith('.js'):
                mimetype = 'application/javascript'
            elif path.endswith('.css'):
                mimetype = 'text/css'
            elif path.endswith('.png'):
                mimetype = 'image/png'
            elif path.endswith('.jpg'):
                mimetype = 'image/jpeg'
            elif path.endswith('.jpeg'):
                mimetype = 'image/jpeg'
            elif path.endswith('.gif'):
                mimetype = 'image/gif'
            elif path.endswith('.svg'):
                mimetype = 'image/svg+xml'
            elif path.endswith('.ico'):
                mimetype = 'image/x-icon'
            elif path.endswith('.json'):
                mimetype = 'application/json'
            elif path.endswith('.txt'):
                mimetype = 'text/plain'

            response = await quart.send_from_directory(frontend_path, path, mimetype=mimetype)
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            return response
