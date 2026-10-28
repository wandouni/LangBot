"""Server-to-server login handoff from LangBot to SqlBot.

The browser never holds a SqlBot credential before this handoff. LangBot signs
a short server-to-server request with a shared secret, SqlBot answers with a
one-time ticket, and the browser redeems that ticket together with an HttpOnly
binding cookie. A stolen redirect URL alone is therefore useless.

Protocol invariants (do not relax):

* the target URL and the signed path are built from configuration, never from
  request headers;
* every request carries a fresh nonce and a Unix timestamp; SqlBot rejects
  replays and clock skew beyond its configured window;
* the binding secret stays in an HttpOnly cookie scoped to the SqlBot mount
  point, while only its SHA-256 hash travels to SqlBot;
* secrets, tickets and signatures are never logged.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import secrets
import time
import typing
from urllib.parse import quote, urlsplit

import httpx

from .sso import _as_bool, _as_float, _as_int

if typing.TYPE_CHECKING:
    from ....core.app import Application


SQLBOT_SSO_VERSION = 'v1'
SQLBOT_SSO_TICKET_PATH = '/api/v1/system/langbot/sso/ticket'
SQLBOT_BIND_COOKIE = 'sqlbot_sso_bind'
SQLBOT_MAX_RESPONSE_BYTES = 64 * 1024
SQLBOT_RATE_LIMIT_MAX_CLIENTS = 10000

ERROR_PORTAL_DISABLED = 'portal_disabled'
ERROR_DISABLED = 'sqlbot_sso_disabled'
ERROR_RATE_LIMITED = 'sqlbot_sso_rate_limited'
ERROR_UNAVAILABLE = 'sqlbot_sso_unavailable'
ERROR_INVALID_RESPONSE = 'sqlbot_sso_invalid_response'
ERROR_TIMEOUT = 'sqlbot_sso_timeout'


class SqlbotSsoError(Exception):
    """A handoff failure whose code is safe to expose to the WebUI."""

    def __init__(self, code: str, status_code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.message = message


@dataclasses.dataclass(frozen=True, slots=True)
class SqlbotSsoSettings:
    enabled: bool
    portal_enabled: bool
    sqlbot_enabled: bool
    base_url: str
    context_path: str
    shared_secret: str
    ticket_ttl_seconds: int
    binding_ttl_seconds: int
    timeout_seconds: float
    rate_limit_per_minute: int
    cookie_secure: bool


@dataclasses.dataclass(frozen=True, slots=True)
class SqlbotTicketGrant:
    redirect_url: str
    expires_in: int
    binding_secret: str
    binding_cookie_path: str
    binding_max_age: int
    cookie_secure: bool


class SqlbotSsoService:
    """Mint SqlBot login tickets for an already authenticated LangBot Account."""

    def __init__(self, ap: Application) -> None:
        self.ap = ap
        # account_uuid -> (window_started_at, admissions). Fixed-window quota,
        # process-local like every other login limiter here.
        self._rate_windows: dict[str, tuple[float, int]] = {}

    # ---- configuration -------------------------------------------------

    def _config_section(self, name: str) -> dict[str, typing.Any]:
        data = getattr(getattr(self.ap, 'instance_config', None), 'data', {}) or {}
        section = data.get(name) if isinstance(data, dict) else None
        return section if isinstance(section, dict) else {}

    def _portal_config(self) -> dict[str, typing.Any]:
        system = self._config_section('system')
        portal = system.get('portal')
        return portal if isinstance(portal, dict) else {}

    def settings(self) -> SqlbotSsoSettings:
        portal = self._portal_config()
        sqlbot = self._config_section('sqlbot')
        sso = sqlbot.get('sso')
        if not isinstance(sso, dict):
            sso = {}

        base_url = str(sqlbot.get('base_url') or '').strip().rstrip('/')
        parsed = urlsplit(base_url)
        base_valid = (
            parsed.scheme in {'http', 'https'}
            and bool(parsed.netloc)
            and not parsed.query
            and not parsed.fragment
            and parsed.username is None
            and parsed.password is None
        )

        context_path = str(sqlbot.get('context_path') or '/sqlbot').strip()
        if not context_path.startswith('/'):
            context_path = f'/{context_path}'
        context_path = context_path.rstrip('/')
        path_valid = '?' not in context_path and '#' not in context_path

        shared_secret = str(sso.get('shared_secret') or '').strip()
        ticket_ttl = _as_int(sqlbot.get('ticket_ttl_seconds'), 60, minimum=10, maximum=600)
        binding_ttl = max(
            ticket_ttl,
            _as_int(sso.get('binding_ttl_seconds'), 120, minimum=10, maximum=900),
        )

        public_origin = str(portal.get('public_origin') or '').strip()
        parsed_origin = urlsplit(public_origin)
        cookie_secure = (
            parsed_origin.scheme == 'https' if parsed_origin.scheme in {'http', 'https'} else False
        )

        portal_enabled = _as_bool(portal.get('enabled'), False)
        sqlbot_enabled = _as_bool(portal.get('sqlbot_enabled'), False)
        handoff_enabled = bool(
            _as_bool(sso.get('enabled'), False)
            and base_valid
            and path_valid
            and len(shared_secret) >= 16
        )

        return SqlbotSsoSettings(
            enabled=portal_enabled and sqlbot_enabled and handoff_enabled,
            portal_enabled=portal_enabled,
            sqlbot_enabled=sqlbot_enabled,
            base_url=base_url,
            context_path=context_path or '',
            shared_secret=shared_secret,
            ticket_ttl_seconds=ticket_ttl,
            binding_ttl_seconds=binding_ttl,
            timeout_seconds=_as_float(sqlbot.get('request_timeout_seconds'), 5.0, minimum=1.0, maximum=60.0),
            rate_limit_per_minute=_as_int(sqlbot.get('rate_limit_per_minute'), 10, minimum=1, maximum=600),
            cookie_secure=cookie_secure,
        )

    def portal_capability(self) -> dict[str, typing.Any]:
        """Return the non-secret portal description exposed by ``/system/info``."""
        portal = self._portal_config()
        settings = self.settings()
        langbot_path = str(portal.get('langbot_path') or '/home/monitoring').strip()
        if not langbot_path.startswith('/') or langbot_path.startswith('//'):
            langbot_path = '/home/monitoring'
        sqlbot_path = str(portal.get('sqlbot_path') or '/sqlbot/').strip()
        if not sqlbot_path.startswith('/') or sqlbot_path.startswith('//'):
            sqlbot_path = '/sqlbot/'
        if not sqlbot_path.endswith('/'):
            sqlbot_path = f'{sqlbot_path}/'
        return {
            'enabled': settings.portal_enabled,
            'sqlbot_enabled': settings.enabled,
            'langbot_path': langbot_path,
            'sqlbot_path': sqlbot_path,
        }

    # ---- rate limiting -------------------------------------------------

    def _admit(self, key: str, limit: int) -> bool:
        """Reserve one slot in the caller's fixed window.

        Must stay await-free so check-and-increment is atomic on the event loop.
        """
        now = time.monotonic()
        window = self._rate_windows.get(key)
        if window is None or now - window[0] >= 60.0:
            if len(self._rate_windows) >= SQLBOT_RATE_LIMIT_MAX_CLIENTS:
                oldest = min(
                    self._rate_windows,
                    key=lambda candidate: self._rate_windows[candidate][0],
                )
                self._rate_windows.pop(oldest, None)
            self._rate_windows[key] = (now, 1)
            return True
        started_at, admissions = window
        if admissions >= limit:
            return False
        self._rate_windows[key] = (started_at, admissions + 1)
        return True

    # ---- handoff -------------------------------------------------------

    def _signed_path(self, settings: SqlbotSsoSettings) -> str:
        return f'{settings.context_path}{SQLBOT_SSO_TICKET_PATH}'

    @staticmethod
    def sign_request(
        shared_secret: str,
        *,
        timestamp: str,
        nonce: str,
        method: str,
        path: str,
        body: bytes,
    ) -> str:
        """Build the canonical signing string and its HMAC-SHA256 signature."""
        signing = '\n'.join(
            [
                SQLBOT_SSO_VERSION,
                timestamp,
                nonce,
                method.upper(),
                path,
                hashlib.sha256(body).hexdigest(),
            ]
        )
        return hmac.new(shared_secret.encode(), signing.encode(), hashlib.sha256).hexdigest()

    async def issue_ticket(self, *, account: str, account_uuid: str) -> SqlbotTicketGrant:
        settings = self.settings()
        if not settings.portal_enabled:
            raise SqlbotSsoError(ERROR_PORTAL_DISABLED, 403, 'The application center is disabled')
        if not settings.enabled:
            raise SqlbotSsoError(ERROR_DISABLED, 403, 'SqlBot single sign-on is disabled')
        if not self._admit(account_uuid, settings.rate_limit_per_minute):
            raise SqlbotSsoError(ERROR_RATE_LIMITED, 429, 'Too many SqlBot login attempts, try again later')

        binding_secret = secrets.token_urlsafe(32)
        binding_hash = hashlib.sha256(binding_secret.encode()).hexdigest()
        body = json.dumps(
            {
                'account': account,
                'account_uuid': account_uuid,
                'binding_hash': binding_hash,
            },
            ensure_ascii=False,
            separators=(',', ':'),
        ).encode()
        path = self._signed_path(settings)
        timestamp = str(int(time.time()))
        nonce = secrets.token_hex(16)
        signature = self.sign_request(
            settings.shared_secret,
            timestamp=timestamp,
            nonce=nonce,
            method='POST',
            path=path,
            body=body,
        )
        headers = {
            'Content-Type': 'application/json',
            'X-LangBot-SSO-Version': SQLBOT_SSO_VERSION,
            'X-LangBot-SSO-Timestamp': timestamp,
            'X-LangBot-SSO-Nonce': nonce,
            'X-LangBot-SSO-Signature': signature,
        }

        try:
            async with httpx.AsyncClient(timeout=settings.timeout_seconds, follow_redirects=False) as client:
                response = await client.post(f'{settings.base_url}{path}', content=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise SqlbotSsoError(ERROR_TIMEOUT, 504, 'SqlBot did not answer in time') from exc
        except httpx.HTTPError as exc:
            raise SqlbotSsoError(ERROR_UNAVAILABLE, 503, 'SqlBot is unavailable') from exc

        if response.status_code != 200:
            raise SqlbotSsoError(ERROR_UNAVAILABLE, 503, 'SqlBot rejected the login handoff')
        if len(response.content) > SQLBOT_MAX_RESPONSE_BYTES:
            raise SqlbotSsoError(ERROR_INVALID_RESPONSE, 502, 'SqlBot returned an invalid response')
        try:
            payload = response.json()
        except ValueError as exc:
            raise SqlbotSsoError(ERROR_INVALID_RESPONSE, 502, 'SqlBot returned an invalid response') from exc
        ticket = payload.get('ticket') if isinstance(payload, dict) else None
        if not isinstance(ticket, str) or not 16 <= len(ticket) <= 512 or any(c.isspace() for c in ticket):
            raise SqlbotSsoError(ERROR_INVALID_RESPONSE, 502, 'SqlBot returned an invalid ticket')

        expires_in = _as_int(payload.get('expires_in'), settings.ticket_ttl_seconds, minimum=1, maximum=600)
        return SqlbotTicketGrant(
            redirect_url=f'{settings.context_path}/#/login?sso_ticket={quote(ticket, safe="")}',
            expires_in=expires_in,
            binding_secret=binding_secret,
            binding_cookie_path=f'{settings.context_path}/',
            binding_max_age=settings.binding_ttl_seconds,
            cookie_secure=settings.cookie_secure,
        )
