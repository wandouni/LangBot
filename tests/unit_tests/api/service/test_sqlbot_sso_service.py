"""Unit tests for the LangBot -> SqlBot login handoff."""

from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace

import httpx
import pytest

from langbot.pkg.api.http.service.sqlbot_sso import (
    ERROR_DISABLED,
    ERROR_INVALID_RESPONSE,
    ERROR_PORTAL_DISABLED,
    ERROR_RATE_LIMITED,
    ERROR_TIMEOUT,
    SQLBOT_SSO_TICKET_PATH,
    SQLBOT_SSO_VERSION,
    SqlbotSsoError,
    SqlbotSsoService,
)


pytestmark = pytest.mark.asyncio

SECRET = 'test-shared-secret-value-0123456789'


def _config(*, portal_enabled: bool = True, sqlbot_enabled: bool = True, sso_enabled: bool = True) -> dict:
    return {
        'system': {
            'portal': {
                'enabled': portal_enabled,
                'sqlbot_enabled': sqlbot_enabled,
                'langbot_path': '/home/monitoring',
                'sqlbot_path': '/sqlbot/',
                'public_origin': 'http://10.8.16.56:5300',
            }
        },
        'sqlbot': {
            'base_url': 'http://sqlbot:8000',
            'context_path': '/sqlbot',
            'ticket_ttl_seconds': 60,
            'request_timeout_seconds': 5,
            'rate_limit_per_minute': 10,
            'sso': {
                'enabled': sso_enabled,
                'shared_secret': SECRET,
                'binding_ttl_seconds': 120,
            },
        },
    }


def _service(config: dict | None = None) -> SqlbotSsoService:
    ap = SimpleNamespace(instance_config=SimpleNamespace(data=config if config is not None else _config()))
    return SqlbotSsoService(ap)


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None, raw: bytes | None = None) -> None:
        self.status_code = status_code
        self.content = raw if raw is not None else json.dumps(payload or {}).encode()

    def json(self):
        return json.loads(self.content)


def _install_client(monkeypatch, outcome) -> list[dict]:
    calls: list[dict] = []

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def post(self, url, content=None, headers=None):
            calls.append({'url': url, 'content': content, 'headers': headers})
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr(httpx, 'AsyncClient', _FakeClient)
    return calls


def test_signature_matches_fixed_vector() -> None:
    body = b'{"account":"zhangsan"}'
    signature = SqlbotSsoService.sign_request(
        SECRET,
        timestamp='1700000000',
        nonce='0123456789abcdef0123456789abcdef',
        method='POST',
        path='/sqlbot/api/v1/system/langbot/sso/ticket',
        body=body,
    )
    signing = '\n'.join(
        [
            SQLBOT_SSO_VERSION,
            '1700000000',
            '0123456789abcdef0123456789abcdef',
            'POST',
            '/sqlbot/api/v1/system/langbot/sso/ticket',
            hashlib.sha256(body).hexdigest(),
        ]
    )
    assert signature == hmac.new(SECRET.encode(), signing.encode(), hashlib.sha256).hexdigest()


async def test_portal_disabled_is_refused() -> None:
    service = _service(_config(portal_enabled=False))

    with pytest.raises(SqlbotSsoError) as error:
        await service.issue_ticket(account='zhangsan', account_uuid='uuid-1')

    assert error.value.code == ERROR_PORTAL_DISABLED
    assert error.value.status_code == 403


async def test_handoff_disabled_without_secret() -> None:
    config = _config()
    config['sqlbot']['sso']['shared_secret'] = 'short'
    service = _service(config)

    assert service.portal_capability()['enabled'] is True
    assert service.portal_capability()['sqlbot_enabled'] is False
    with pytest.raises(SqlbotSsoError) as error:
        await service.issue_ticket(account='zhangsan', account_uuid='uuid-1')

    assert error.value.code == ERROR_DISABLED


async def test_issue_ticket_returns_redirect_and_binding(monkeypatch) -> None:
    calls = _install_client(monkeypatch, _FakeResponse(payload={'ticket': 'ticket-value-1234567890', 'expires_in': 60}))
    service = _service()

    grant = await service.issue_ticket(account='zhangsan', account_uuid='uuid-1')

    assert grant.redirect_url == '/sqlbot/#/login?sso_ticket=ticket-value-1234567890'
    assert grant.expires_in == 60
    assert grant.binding_cookie_path == '/sqlbot/'
    assert grant.binding_max_age == 120
    assert grant.cookie_secure is False
    assert len(grant.binding_secret) >= 32

    assert len(calls) == 1
    call = calls[0]
    assert call['url'] == 'http://sqlbot:8000/sqlbot/api/v1/system/langbot/sso/ticket'
    body = json.loads(call['content'])
    assert body['account'] == 'zhangsan'
    assert body['account_uuid'] == 'uuid-1'
    assert body['binding_hash'] == hashlib.sha256(grant.binding_secret.encode()).hexdigest()

    headers = call['headers']
    assert headers['X-LangBot-SSO-Version'] == SQLBOT_SSO_VERSION
    expected = SqlbotSsoService.sign_request(
        SECRET,
        timestamp=headers['X-LangBot-SSO-Timestamp'],
        nonce=headers['X-LangBot-SSO-Nonce'],
        method='POST',
        path='/sqlbot' + SQLBOT_SSO_TICKET_PATH,
        body=call['content'],
    )
    assert headers['X-LangBot-SSO-Signature'] == expected


async def test_https_public_origin_sets_secure_cookie() -> None:
    config = _config()
    config['system']['portal']['public_origin'] = 'https://langbot.example.com'
    service = _service(config)

    assert service.settings().cookie_secure is True


async def test_timeout_maps_to_timeout_error(monkeypatch) -> None:
    _install_client(monkeypatch, httpx.ReadTimeout('slow'))
    service = _service()

    with pytest.raises(SqlbotSsoError) as error:
        await service.issue_ticket(account='zhangsan', account_uuid='uuid-1')

    assert error.value.code == ERROR_TIMEOUT
    assert error.value.status_code == 504


async def test_non_200_maps_to_unavailable(monkeypatch) -> None:
    _install_client(monkeypatch, _FakeResponse(status_code=500, payload={'detail': 'boom'}))
    service = _service()

    with pytest.raises(SqlbotSsoError) as error:
        await service.issue_ticket(account='zhangsan', account_uuid='uuid-1')

    assert error.value.code == 'sqlbot_sso_unavailable'


async def test_invalid_json_maps_to_invalid_response(monkeypatch) -> None:
    _install_client(monkeypatch, _FakeResponse(raw=b'<html>no</html>'))
    service = _service()

    with pytest.raises(SqlbotSsoError) as error:
        await service.issue_ticket(account='zhangsan', account_uuid='uuid-1')

    assert error.value.code == ERROR_INVALID_RESPONSE


async def test_ticket_shape_is_validated(monkeypatch) -> None:
    _install_client(monkeypatch, _FakeResponse(payload={'ticket': 'short'}))
    service = _service()

    with pytest.raises(SqlbotSsoError) as error:
        await service.issue_ticket(account='zhangsan', account_uuid='uuid-1')

    assert error.value.code == ERROR_INVALID_RESPONSE


async def test_rate_limit_is_per_account(monkeypatch) -> None:
    _install_client(monkeypatch, _FakeResponse(payload={'ticket': 'ticket-value-1234567890'}))
    config = _config()
    config['sqlbot']['rate_limit_per_minute'] = 2
    service = _service(config)

    await service.issue_ticket(account='zhangsan', account_uuid='uuid-1')
    await service.issue_ticket(account='zhangsan', account_uuid='uuid-1')
    with pytest.raises(SqlbotSsoError) as error:
        await service.issue_ticket(account='zhangsan', account_uuid='uuid-1')

    assert error.value.code == ERROR_RATE_LIMITED
    # Another Account still has its own window.
    await service.issue_ticket(account='lisi', account_uuid='uuid-2')


def test_portal_capability_hides_internal_settings() -> None:
    capability = _service().portal_capability()

    assert capability == {
        'enabled': True,
        'sqlbot_enabled': True,
        'langbot_path': '/home/monitoring',
        'sqlbot_path': '/sqlbot/',
    }


def test_portal_disabled_by_default_when_config_is_missing() -> None:
    service = _service({})

    assert service.portal_capability()['enabled'] is False
