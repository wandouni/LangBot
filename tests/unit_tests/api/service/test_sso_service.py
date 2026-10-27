"""Unit tests for the CAS single sign-on protocol layer."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from langbot.pkg.api.http.service.sso import (
    ERROR_INVALID_RESPONSE,
    SsoFailure,
    SsoService,
    parse_service_validate_response,
    normalize_cas_account,
)


pytestmark = pytest.mark.asyncio

SUCCESS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<cas:serviceResponse xmlns:cas="http://www.yale.edu/tp/cas">
  <cas:authenticationSuccess>
    <cas:user>20230001</cas:user>
    <cas:attributes>
      <cas:usertype>teacher</cas:usertype>
      <cas:realname>55Sz5pm25pm2</cas:realname>
      <cas:email>x@example.edu.cn</cas:email>
      <cas:edupersoncard>440101199001011234</cas:edupersoncard>
      <cas:sex>2</cas:sex>
    </cas:attributes>
  </cas:authenticationSuccess>
</cas:serviceResponse>
"""

FAILURE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<cas:serviceResponse xmlns:cas="http://www.yale.edu/tp/cas">
  <cas:authenticationFailure code="INVALID_TICKET">Ticket not recognized</cas:authenticationFailure>
</cas:serviceResponse>
"""


def _service(config: dict | None = None) -> SsoService:
    ap = SimpleNamespace(
        instance_config=SimpleNamespace(data=config or {}),
    )
    return SsoService(ap)


def test_parse_success_keeps_only_the_admission_attribute() -> None:
    account, attributes, failure = parse_service_validate_response(SUCCESS_XML)

    assert account == '20230001'
    assert attributes == {'usertype': 'teacher'}
    assert failure is None


def test_parse_failure_is_protocol_traffic_not_an_exception() -> None:
    account, attributes, failure = parse_service_validate_response(FAILURE_XML)

    assert account is None
    assert attributes == {}
    assert failure == 'INVALID_TICKET'


def test_parse_rejects_dtds() -> None:
    payload = b'<!DOCTYPE foo [<!ENTITY x "y">]><cas:serviceResponse/>'

    with pytest.raises(SsoFailure) as error:
        parse_service_validate_response(payload)

    assert error.value.code == ERROR_INVALID_RESPONSE


def test_account_normalization_rejects_email_shapes() -> None:
    assert normalize_cas_account(' 20230001 ') == '20230001'
    assert normalize_cas_account('T2023-01') == 't2023-01'
    assert normalize_cas_account('teacher@example.edu.cn') is None
    assert normalize_cas_account('ab') is None
    assert normalize_cas_account('工号001') is None


def test_settings_require_a_complete_configuration() -> None:
    disabled = _service({'sso': {'cas': {'enabled': True}}})
    assert disabled.login_enabled() is False

    config = {
        'api': {'webui_url': 'http://localhost:3000'},
        'system': {'jwt': {'secret': 'a' * 32}},
        'sso': {
            'cas': {
                'enabled': True,
                'base_url': 'https://sso.example.edu.cn/lyuapServer',
                'state_secret': 'b' * 32,
            }
        },
    }
    settings = _service(config)._settings()

    assert settings.enabled is True
    assert settings.service_url == 'http://localhost:3000/api/v1/user/sso/cas/callback'
    assert '?' not in settings.service_url
    assert settings.cookie_secure is False
    assert settings.allowed_user_types == ('teacher',)


def test_settings_prefer_the_explicit_service_base() -> None:
    config = {
        'api': {'webui_url': 'http://localhost:3000'},
        'sso': {
            'cas': {
                'enabled': True,
                'base_url': 'https://sso.example.edu.cn/lyuapServer',
                'service_base_url': 'https://langbot.example.edu.cn',
                'state_secret': 'b' * 32,
            }
        },
    }
    settings = _service(config)._settings()

    assert settings.service_url == 'https://langbot.example.edu.cn/api/v1/user/sso/cas/callback'
    assert settings.service_host == 'langbot.example.edu.cn'
    assert settings.cookie_secure is True


def test_settings_do_not_fall_back_from_a_malformed_explicit_base() -> None:
    config = {
        'api': {'webui_url': 'http://localhost:3000'},
        'sso': {
            'cas': {
                'enabled': True,
                'base_url': 'https://sso.example.edu.cn/lyuapServer',
                # A path is not allowed in the browser origin.
                'service_base_url': 'https://langbot.example.edu.cn/app',
                'state_secret': 'b' * 32,
            }
        },
    }
    settings = _service(config)._settings()

    assert settings.enabled is False
    assert settings.service_url == ''


async def test_state_round_trip_and_tamper_detection() -> None:
    config = {
        'api': {'webui_url': 'http://localhost:3000'},
        'sso': {
            'cas': {
                'enabled': True,
                'base_url': 'https://sso.example.edu.cn/lyuapServer',
                'state_secret': 'b' * 32,
            }
        },
    }
    service = _service(config)
    settings = service._settings()

    state = service._issue_state(settings)
    service._verify_state(settings, state)

    nonce, issued_at, signature = state.split('.')
    with pytest.raises(SsoFailure):
        service._verify_state(settings, f'{nonce}.{issued_at}.{"0" * len(signature)}')


def _establish_settings(allowed: str = 'teacher') -> SimpleNamespace:
    return SimpleNamespace(
        allowed_user_types=tuple(item.strip() for item in allowed.split(',')),
        auto_provision=True,
    )


async def test_establish_rejects_missing_usertype() -> None:
    account = SimpleNamespace(user='20230001')
    user_service = SimpleNamespace(
        is_initialized=AsyncMock(return_value=True),
        establish_sso_account=AsyncMock(return_value=account),
        generate_jwt_token=AsyncMock(return_value='token'),
    )
    service = _service()
    service.ap.user_service = user_service

    with pytest.raises(SsoFailure) as error:
        await service._establish(_establish_settings(), '20230001', {})

    assert error.value.code == 'sso_usertype_forbidden'
    user_service.establish_sso_account.assert_not_called()


async def test_establish_allows_configured_usertype() -> None:
    account = SimpleNamespace(user='20230001')
    user_service = SimpleNamespace(
        is_initialized=AsyncMock(return_value=True),
        establish_sso_account=AsyncMock(return_value=account),
        generate_jwt_token=AsyncMock(return_value='token'),
    )
    service = _service()
    service.ap.user_service = user_service

    token = await service._establish(_establish_settings(), '20230001', {'usertype': 'Teacher'})

    assert token == 'token'
    user_service.establish_sso_account.assert_awaited_once_with('20230001', auto_provision=True)


async def test_expired_state_is_rejected() -> None:
    config = {
        'api': {'webui_url': 'http://localhost:3000'},
        'sso': {
            'cas': {
                'enabled': True,
                'base_url': 'https://sso.example.edu.cn/lyuapServer',
                'state_secret': 'b' * 32,
                'state_ttl_seconds': 30,
            }
        },
    }
    service = _service(config)
    settings = service._settings()
    issued_at = int(time.time()) - 31
    signature = service._sign_state(settings.state_secret, 'nonce', issued_at)

    with pytest.raises(SsoFailure):
        service._verify_state(settings, f'nonce.{issued_at}.{signature}')
