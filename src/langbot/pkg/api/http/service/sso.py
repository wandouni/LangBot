"""CAS 2.0 single sign-on for the local WebUI.

The CAS server only answers "who is this person". LangBot still owns the
session: after a successful service validation this module creates or updates
the local Account and hands the browser a normal LangBot JWT through a
short-lived, HttpOnly one-time cookie. The token is never placed in a URL.

Protocol invariants (do not relax):

* the ``service`` value is built once from configuration, never from request
  headers, and never carries a query string or fragment;
* the ``cas_state`` cookie is ``SameSite=Lax`` because the callback is a
  cross-site top-level navigation;
* CAS reports protocol failures as HTTP 200 + XML, so the XML body decides;
* the browser host must match the registered callback host, otherwise the
  state cookie is written to one host and read from another.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import re
import secrets
import time
import typing
import xml.etree.ElementTree as ElementTree
from urllib.parse import quote, urlsplit

import httpx
import quart

from . import user as user_service_module

if typing.TYPE_CHECKING:
    from ....core.app import Application


CAS_STATE_COOKIE = 'cas_state'
CAS_SESSION_COOKIE = 'sso_session'
CAS_STATE_COOKIE_PATH = '/api/v1/user/sso/cas'
CAS_SESSION_COOKIE_PATH = '/api/v1/user/sso'
CAS_DEFAULT_SERVICE_PATH = '/api/v1/user/sso/cas/callback'
CAS_MAX_RESPONSE_BYTES = 1024 * 1024
CAS_SESSION_COOKIE_MAX_AGE = 120
CAS_RATE_LIMIT_MAX_CLIENTS = 10000

_ACCOUNT_PATTERN = re.compile(r'[a-z0-9._-]{3,40}')

# Browser-facing error codes. The login page maps every code to localized text;
# no server detail (which may contain a work ID or CAS internals) is shown.
ERROR_STATE = 'sso_state'
ERROR_HOST_MISMATCH = 'sso_host_mismatch'
ERROR_USERNAME = 'sso_username'
ERROR_USERTYPE_FORBIDDEN = 'sso_usertype_forbidden'
ERROR_TICKET_INVALID = 'sso_ticket_invalid'
ERROR_UNREACHABLE = 'sso_unreachable'
ERROR_TIMEOUT = 'sso_timeout'
ERROR_TLS = 'sso_tls'
ERROR_INVALID_RESPONSE = 'sso_invalid_response'
ERROR_DISABLED = 'sso_disabled'
ERROR_ACCOUNT_DISABLED = 'sso_account_disabled'
ERROR_RATE_LIMITED = 'sso_rate_limited'
ERROR_UNAVAILABLE = 'sso_unavailable'


class SsoFailure(Exception):
    """A login failure that is safe to expose as a redirect error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclasses.dataclass(frozen=True, slots=True)
class CasSettings:
    enabled: bool
    base_url: str
    service_url: str
    service_host: str
    cookie_secure: bool
    state_secret: str
    state_ttl_seconds: int
    allowed_user_types: tuple[str, ...]
    auto_provision: bool
    timeout_seconds: float
    rate_limit_per_minute: int
    ca_cert_path: str
    insecure_skip_verify: bool
    button_label: str


def _as_bool(value: typing.Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {'1', 'true', 'yes', 'on'}:
            return True
        if normalized in {'0', 'false', 'no', 'off'}:
            return False
    return default


def _as_int(value: typing.Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _as_float(value: typing.Any, default: float, *, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def normalize_cas_account(raw: str) -> str | None:
    """Return a stable local login name for a CAS ``cas:user`` value.

    Work IDs are ASCII; anything else (notably a value containing ``@``) is
    rejected instead of being coerced into an email-shaped identity.
    """
    candidate = (raw or '').strip().casefold()
    if candidate.startswith('{') and candidate.endswith('}'):
        # Some CAS deployments return the value wrapped in braces.
        candidate = candidate[1:-1].strip()
    if not _ACCOUNT_PATTERN.fullmatch(candidate):
        return None
    return candidate


def parse_service_validate_response(xml_bytes: bytes) -> tuple[str | None, dict[str, str], str | None]:
    """Parse a CAS 2.0 ``serviceValidate`` body.

    Returns ``(user, attributes, failure_code)``. A failure element is normal
    protocol traffic (HTTP status is 200 in that case), so it is returned as a
    code rather than raised.
    """
    if len(xml_bytes) > CAS_MAX_RESPONSE_BYTES:
        raise SsoFailure(ERROR_INVALID_RESPONSE)
    upper = xml_bytes.upper()
    if b'<!DOCTYPE' in upper or b'<!ENTITY' in upper:
        # ElementTree expands internal entities; refuse DTDs outright.
        raise SsoFailure(ERROR_INVALID_RESPONSE)
    try:
        root = ElementTree.fromstring(xml_bytes)
    except (ElementTree.ParseError, ValueError) as exc:
        raise SsoFailure(ERROR_INVALID_RESPONSE) from exc

    def local_name(tag: str) -> str:
        return tag.rsplit('}', 1)[-1]

    failure = next((node for node in root.iter() if local_name(node.tag) == 'authenticationFailure'), None)
    if failure is not None:
        return None, {}, failure.get('code') or 'authentication_failure'

    success = next((node for node in root.iter() if local_name(node.tag) == 'authenticationSuccess'), None)
    if success is None:
        raise SsoFailure(ERROR_INVALID_RESPONSE)

    cas_user = ''
    attributes: dict[str, str] = {}
    for node in success.iter():
        name = local_name(node.tag)
        if name == 'user' and not cas_user:
            cas_user = (node.text or '').strip()
        elif name == 'attributes':
            for child in node:
                attribute_name = local_name(child.tag).lower()
                value = (child.text or '').strip()
                if not value:
                    values = [
                        (item.text or '').strip()
                        for item in child
                        if local_name(item.tag) in {'value', 'attributeValue'}
                    ]
                    value = ','.join(item for item in values if item)
                # Only the one attribute the admission policy needs is kept.
                # ``email``, ``edupersoncard`` (national ID), ``sex``,
                # ``realname``, and display aliases are intentionally dropped
                # so they can never reach logs or persistence.
                if attribute_name == 'usertype':
                    attributes[attribute_name] = value
    if not cas_user:
        raise SsoFailure(ERROR_INVALID_RESPONSE)
    return cas_user, attributes, None


class SsoService:
    def __init__(self, ap: Application) -> None:
        self.ap = ap
        self._rate_windows: dict[str, tuple[float, int]] = {}

    # ---- configuration -------------------------------------------------

    def _raw_config(self) -> dict[str, typing.Any]:
        data = getattr(getattr(self.ap, 'instance_config', None), 'data', {}) or {}
        sso = data.get('sso') if isinstance(data, dict) else None
        cas = sso.get('cas') if isinstance(sso, dict) else None
        return cas if isinstance(cas, dict) else {}

    def _service_base_url(self, cas: dict[str, typing.Any], api: dict[str, typing.Any]) -> str:
        explicit = str(cas.get('service_base_url') or '').strip()
        # An explicit value is authoritative: never fall back to a different
        # origin because the configured one is malformed, that would register a
        # callback host the operator did not intend.
        candidates = (explicit,) if explicit else (api.get('webui_url'), api.get('webhook_prefix'))
        for candidate in candidates:
            value = str(candidate or '').strip().rstrip('/')
            if not value:
                continue
            parsed = urlsplit(value)
            if parsed.scheme in {'http', 'https'} and parsed.netloc and not parsed.query and not parsed.fragment:
                if parsed.path in {'', '/'}:
                    return f'{parsed.scheme}://{parsed.netloc}'
        return ''

    def _settings(self) -> CasSettings:
        data = getattr(getattr(self.ap, 'instance_config', None), 'data', {}) or {}
        api = data.get('api') if isinstance(data.get('api'), dict) else {}
        cas = self._raw_config()

        base_url = str(cas.get('base_url') or '').strip().rstrip('/')
        parsed_base = urlsplit(base_url)
        base_valid = (
            parsed_base.scheme in {'http', 'https'}
            and bool(parsed_base.netloc)
            and not parsed_base.query
            and not parsed_base.fragment
        )

        service_path = str(cas.get('service_path') or CAS_DEFAULT_SERVICE_PATH).strip()
        path_valid = service_path.startswith('/') and '?' not in service_path and '#' not in service_path
        service_base = self._service_base_url(cas, api)

        secret = str(cas.get('state_secret') or '').strip()
        if not secret:
            system = data.get('system') if isinstance(data.get('system'), dict) else {}
            jwt = system.get('jwt') if isinstance(system.get('jwt'), dict) else {}
            secret = str(jwt.get('secret') or '').strip()

        cookie_secure_raw = str(cas.get('cookie_secure', 'auto')).strip().lower()
        if cookie_secure_raw in {'true', '1', 'yes', 'on'}:
            cookie_secure = True
        elif cookie_secure_raw in {'false', '0', 'no', 'off'}:
            cookie_secure = False
        else:
            cookie_secure = urlsplit(service_base).scheme == 'https'

        allowed_raw = str(cas.get('allowed_user_types') or '').strip() or 'teacher'
        allowed_types = tuple(item.strip().lower() for item in allowed_raw.split(',') if item.strip())

        enabled = bool(
            _as_bool(cas.get('enabled'), False)
            and base_valid
            and path_valid
            and service_base
            and len(secret) >= 16
            and allowed_types
        )
        service_url = f'{service_base}{service_path}' if enabled else ''

        return CasSettings(
            enabled=enabled,
            base_url=base_url,
            service_url=service_url,
            service_host=urlsplit(service_base).netloc.casefold() if service_base else '',
            cookie_secure=cookie_secure,
            state_secret=secret,
            state_ttl_seconds=_as_int(cas.get('state_ttl_seconds'), 300, minimum=30, maximum=900),
            allowed_user_types=allowed_types or ('teacher',),
            auto_provision=_as_bool(cas.get('auto_provision'), True),
            timeout_seconds=_as_float(cas.get('timeout_seconds'), 10.0, minimum=1.0, maximum=60.0),
            rate_limit_per_minute=_as_int(cas.get('rate_limit_per_minute'), 20, minimum=1, maximum=600),
            ca_cert_path=str(cas.get('ca_cert_path') or '').strip(),
            insecure_skip_verify=_as_bool(cas.get('insecure_skip_verify'), False),
            button_label=str(cas.get('button_label') or '').strip()[:64],
        )

    def login_enabled(self) -> bool:
        try:
            return self._settings().enabled
        except Exception:
            return False

    def login_label(self) -> str:
        try:
            settings = self._settings()
        except Exception:
            return ''
        return settings.button_label if settings.enabled else ''

    # ---- rate limiting -------------------------------------------------

    @staticmethod
    def _client_ip() -> str:
        forwarded = quart.request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
        if forwarded:
            return forwarded
        return str(quart.request.remote_addr or 'unknown')

    def _admit(self, limit: int, *, bucket: str) -> bool:
        """Fixed one-minute window per client. Process-local by design."""
        now = time.monotonic()
        key = f'{bucket}:{self._client_ip()}'
        window_start, count = self._rate_windows.get(key, (now, 0))
        if now - window_start >= 60.0:
            window_start, count = now, 0
        if count >= limit:
            self._rate_windows[key] = (window_start, count)
            return False
        self._rate_windows[key] = (window_start, count + 1)
        if len(self._rate_windows) > CAS_RATE_LIMIT_MAX_CLIENTS:
            cutoff = now - 60.0
            self._rate_windows = {
                item_key: item_value for item_key, item_value in self._rate_windows.items() if item_value[0] > cutoff
            }
        return True

    # ---- state ---------------------------------------------------------

    @staticmethod
    def _sign_state(secret: str, nonce: str, issued_at: int) -> str:
        message = f'{nonce}.{issued_at}'.encode('utf-8')
        return hmac.new(secret.encode('utf-8'), message, hashlib.sha256).hexdigest()

    def _issue_state(self, settings: CasSettings) -> str:
        nonce = secrets.token_urlsafe(24)
        issued_at = int(time.time())
        signature = self._sign_state(settings.state_secret, nonce, issued_at)
        return f'{nonce}.{issued_at}.{signature}'

    def _verify_state(self, settings: CasSettings, raw_state: str) -> None:
        if not isinstance(raw_state, str) or not raw_state:
            raise SsoFailure(ERROR_STATE)
        parts = raw_state.split('.')
        if len(parts) != 3:
            raise SsoFailure(ERROR_STATE)
        nonce, issued_raw, signature = parts
        try:
            issued_at = int(issued_raw)
        except ValueError as exc:
            raise SsoFailure(ERROR_STATE) from exc
        now = int(time.time())
        if issued_at > now + 60 or now - issued_at > settings.state_ttl_seconds:
            raise SsoFailure(ERROR_STATE)
        expected = self._sign_state(settings.state_secret, nonce, issued_at)
        if not hmac.compare_digest(expected, signature):
            raise SsoFailure(ERROR_STATE)

    # ---- HTTP responses ------------------------------------------------

    @staticmethod
    def _error_redirect(code: str) -> quart.Response:
        return quart.redirect(f'/login?error={quote(code, safe="")}', code=302)

    def _clear_cookie(self, response: quart.Response, name: str, path: str, secure: bool) -> None:
        response.delete_cookie(
            name,
            path=path,
            secure=secure,
            httponly=True,
            samesite='Lax',
        )

    def _failure_response(self, settings: CasSettings, code: str) -> quart.Response:
        response = self._error_redirect(code)
        self._clear_cookie(response, CAS_STATE_COOKIE, CAS_STATE_COOKIE_PATH, settings.cookie_secure)
        self._clear_cookie(response, CAS_SESSION_COOKIE, CAS_SESSION_COOKIE_PATH, settings.cookie_secure)
        return response

    def _host_matches(self, settings: CasSettings) -> bool:
        forwarded_host = quart.request.headers.get('X-Forwarded-Host', '').split(',')[0].strip()
        requested_host = forwarded_host or str(quart.request.host or '')
        return bool(requested_host) and requested_host.casefold() == settings.service_host

    # ---- CAS client ----------------------------------------------------

    def _verify_option(self, settings: CasSettings) -> typing.Any:
        if settings.ca_cert_path:
            return settings.ca_cert_path
        if settings.insecure_skip_verify:
            return False
        return True

    async def _validate_ticket(self, settings: CasSettings, ticket: str) -> tuple[str, dict[str, str]]:
        url = f'{settings.base_url}/serviceValidate'
        try:
            async with httpx.AsyncClient(
                timeout=settings.timeout_seconds,
                verify=self._verify_option(settings),
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    url,
                    params={'ticket': ticket, 'service': settings.service_url},
                )
        except httpx.TimeoutException as exc:
            raise SsoFailure(ERROR_TIMEOUT) from exc
        except httpx.ConnectError as exc:
            detail = str(exc).lower()
            if 'certificate' in detail or 'ssl' in detail or 'tls' in detail:
                raise SsoFailure(ERROR_TLS) from exc
            raise SsoFailure(ERROR_UNREACHABLE) from exc
        except httpx.HTTPError as exc:
            raise SsoFailure(ERROR_UNAVAILABLE) from exc

        if 300 <= response.status_code < 400:
            # A configured base URL missing its context path usually surfaces
            # as a redirect; following it would hide the misconfiguration.
            raise SsoFailure(ERROR_INVALID_RESPONSE)
        if response.status_code != 200:
            raise SsoFailure(ERROR_UNAVAILABLE)
        if len(response.content) > CAS_MAX_RESPONSE_BYTES:
            raise SsoFailure(ERROR_INVALID_RESPONSE)

        cas_user, attributes, failure_code = parse_service_validate_response(response.content)
        if failure_code is not None or not cas_user:
            raise SsoFailure(ERROR_TICKET_INVALID)
        return cas_user, attributes

    # ---- account establishment ----------------------------------------

    async def _establish(self, settings: CasSettings, raw_username: str, attributes: dict[str, str]) -> str:
        account_name = normalize_cas_account(raw_username)
        if account_name is None:
            raise SsoFailure(ERROR_USERNAME)

        # Fail closed: a missing ``usertype`` is not permission to log in.
        user_type = (attributes.get('usertype') or '').strip().lower()
        if '*' not in settings.allowed_user_types:
            if not user_type or user_type not in settings.allowed_user_types:
                raise SsoFailure(ERROR_USERTYPE_FORBIDDEN)

        if not await self.ap.user_service.is_initialized():
            # The instance setup flow owns Workspace creation. SSO must never
            # become the implicit bootstrap path that claims the owner role.
            raise SsoFailure(ERROR_DISABLED)

        try:
            account = await self.ap.user_service.establish_sso_account(
                account_name,
                auto_provision=settings.auto_provision,
            )
        except user_service_module.SsoProvisioningDisabledError as exc:
            raise SsoFailure(ERROR_DISABLED) from exc

        return await self.ap.user_service.generate_jwt_token(account)

    # ---- endpoints -----------------------------------------------------

    async def handle_login(self) -> quart.Response:
        settings = self._settings()
        if not settings.enabled:
            return self._error_redirect(ERROR_DISABLED)
        if not self._admit(settings.rate_limit_per_minute, bucket='login'):
            return self._error_redirect(ERROR_RATE_LIMITED)

        state = self._issue_state(settings)
        redirect_url = f'{settings.base_url}/login?service={quote(settings.service_url, safe="")}'
        response = quart.redirect(redirect_url, code=302)
        response.set_cookie(
            CAS_STATE_COOKIE,
            state,
            max_age=settings.state_ttl_seconds,
            path=CAS_STATE_COOKIE_PATH,
            secure=settings.cookie_secure,
            httponly=True,
            samesite='Lax',
        )
        return response

    async def handle_callback(self) -> quart.Response:
        settings = self._settings()
        if not settings.enabled:
            return self._error_redirect(ERROR_DISABLED)
        if not self._admit(settings.rate_limit_per_minute, bucket='callback'):
            return self._failure_response(settings, ERROR_RATE_LIMITED)

        # Read the state up front; every exit path below clears the cookie, so
        # a retry never reuses a state that was already presented here.
        state = quart.request.cookies.get(CAS_STATE_COOKIE, '')

        try:
            if not self._host_matches(settings):
                raise SsoFailure(ERROR_HOST_MISMATCH)
            self._verify_state(settings, state)
            ticket = (quart.request.args.get('ticket') or '').strip()
            if not ticket or len(ticket) > 4096:
                raise SsoFailure(ERROR_TICKET_INVALID)

            cas_user, attributes = await self._validate_ticket(settings, ticket)
            token = await self._establish(settings, cas_user, attributes)
        except SsoFailure as failure:
            self.ap.logger.warning('CAS single sign-on failed: %s', failure.code)
            return self._failure_response(settings, failure.code)
        except user_service_module.AccountDisabledError:
            self.ap.logger.warning('CAS single sign-on rejected a disabled Account')
            return self._failure_response(settings, ERROR_ACCOUNT_DISABLED)
        except user_service_module.ControlPlaneDirectoryRequiredError:
            self.ap.logger.warning('CAS single sign-on is unavailable in multi-Workspace mode')
            return self._failure_response(settings, ERROR_DISABLED)
        except Exception:
            self.ap.logger.exception('CAS single sign-on failed unexpectedly')
            return self._failure_response(settings, ERROR_UNAVAILABLE)

        response = quart.redirect('/login?sso=1', code=302)
        self._clear_cookie(response, CAS_STATE_COOKIE, CAS_STATE_COOKIE_PATH, settings.cookie_secure)
        response.set_cookie(
            CAS_SESSION_COOKIE,
            token,
            max_age=CAS_SESSION_COOKIE_MAX_AGE,
            path=CAS_SESSION_COOKIE_PATH,
            secure=settings.cookie_secure,
            httponly=True,
            samesite='Lax',
        )
        return response

    async def exchange_session(self) -> quart.Response:
        settings = self._settings()
        token = quart.request.cookies.get(CAS_SESSION_COOKIE, '')
        account = None
        if token:
            try:
                account = await self.ap.user_service.get_authenticated_account(token)
            except Exception:
                account = None

        if account is None:
            response = quart.jsonify(
                {
                    'code': 'sso_session_invalid',
                    'msg': 'No pending SSO session is available',
                    'data': None,
                }
            )
            response.status_code = 401
        else:
            response = quart.jsonify(
                {
                    'code': 0,
                    'msg': 'ok',
                    'data': {'token': token, 'user': account.user},
                }
            )
        self._clear_cookie(response, CAS_SESSION_COOKIE, CAS_SESSION_COOKIE_PATH, settings.cookie_secure)
        return response
