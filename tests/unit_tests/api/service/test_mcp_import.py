"""Tests for parsing and importing pasted MCP JSON configs."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from langbot.pkg.api.http.service.mcp import (
    MCPService,
    parse_mcp_import_config,
)


def test_parses_claude_style_config_as_remote_server():
    servers = parse_mcp_import_config(
        {
            'mcpServers': {
                'sqlbot-sales-12': {
                    'type': 'sse',
                    'url': 'https://sqlbot.example.com/mcp',
                    'headers': {'Authorization': 'Bearer token'},
                }
            }
        }
    )

    assert len(servers) == 1
    server = servers[0]
    assert server['name'] == 'sqlbot-sales-12'
    assert server['mode'] == 'remote'
    assert server['enable'] is True
    assert server['extra_args']['url'] == 'https://sqlbot.example.com/mcp'
    assert server['extra_args']['headers'] == {'Authorization': 'Bearer token'}


def test_derives_name_from_host_when_missing():
    servers = parse_mcp_import_config({'url': 'https://mcp.example.com/mcp'})

    assert servers[0]['name'] == 'mcp.example.com'


def test_accepts_streamable_http_type():
    servers = parse_mcp_import_config(
        {'mcpServers': {'remote': {'type': 'streamableHttp', 'url': 'http://localhost:8001/mcp'}}}
    )

    assert servers[0]['mode'] == 'remote'


@pytest.mark.parametrize(
    'entry',
    [
        {'type': 'stdio', 'url': 'http://localhost:8001/mcp'},
        {'url': 'http://localhost:8001/mcp', 'command': 'npx'},
        {'url': 'http://localhost:8001/mcp', 'args': ['-y']},
        {'type': 'websocket', 'url': 'http://localhost:8001/mcp'},
    ],
)
def test_rejects_stdio_and_unknown_transports(entry):
    with pytest.raises(ValueError):
        parse_mcp_import_config({'mcpServers': {'bad': entry}})


@pytest.mark.parametrize(
    'url',
    [
        'ftp://example.com/mcp',
        'example.com/mcp',
        'https://user:pass@example.com/mcp',
        '',
    ],
)
def test_rejects_invalid_urls(url):
    with pytest.raises(ValueError):
        parse_mcp_import_config({'mcpServers': {'bad': {'url': url}}})


def test_rejects_non_string_headers():
    with pytest.raises(ValueError):
        parse_mcp_import_config(
            {'mcpServers': {'bad': {'url': 'https://example.com/mcp', 'headers': {'X-Token': 1}}}}
        )


@pytest.mark.parametrize(
    'headers',
    [
        {'Bad Header': 'value'},
        {'X-Token': 'line1\r\nX-Injected: 1'},
        {'X-Token': 'value\x00'},
    ],
)
def test_rejects_unsafe_headers(headers):
    with pytest.raises(ValueError):
        parse_mcp_import_config(
            {'mcpServers': {'bad': {'url': 'https://example.com/mcp', 'headers': headers}}}
        )


def test_rejects_too_many_servers_and_headers():
    servers = {
        f'server-{index}': {'url': f'https://example.com/{index}'}
        for index in range(11)
    }
    with pytest.raises(ValueError):
        parse_mcp_import_config({'mcpServers': servers})

    headers = {f'X-{index}': 'value' for index in range(21)}
    with pytest.raises(ValueError):
        parse_mcp_import_config(
            {'mcpServers': {'bad': {'url': 'https://example.com/mcp', 'headers': headers}}}
        )


def test_rejects_empty_or_unknown_config():
    with pytest.raises(ValueError):
        parse_mcp_import_config({})
    with pytest.raises(ValueError):
        parse_mcp_import_config({'mcpServers': {}})
    with pytest.raises(ValueError):
        parse_mcp_import_config([])


@pytest.mark.asyncio
async def test_import_reports_partial_failures(monkeypatch):
    service = MCPService(SimpleNamespace(logger=SimpleNamespace(exception=lambda *_: None)))

    async def fake_create(_context, server_data):
        if server_data['name'] == 'duplicate':
            raise ValueError('MCP server already exists: duplicate')
        return f"uuid-{server_data['name']}"

    monkeypatch.setattr(service, 'create_mcp_server', fake_create)
    result = await service.import_mcp_servers(
        None,
        {
            'mcpServers': {
                'ok': {'url': 'https://example.com/ok'},
                'duplicate': {'url': 'https://example.com/duplicate'},
            }
        },
    )

    assert result['servers'] == [{'name': 'ok', 'uuid': 'uuid-ok'}]
    assert result['errors'] == [
        {'name': 'duplicate', 'message': 'MCP server already exists: duplicate'}
    ]


@pytest.mark.asyncio
async def test_import_rejects_invalid_config_before_creating(monkeypatch):
    service = MCPService(SimpleNamespace(logger=SimpleNamespace(exception=lambda *_: None)))
    called = []

    async def fake_create(_context, server_data):
        called.append(server_data)
        return 'uuid'

    monkeypatch.setattr(service, 'create_mcp_server', fake_create)

    with pytest.raises(ValueError):
        await service.import_mcp_servers(None, {'mcpServers': {'bad': {'command': 'npx'}}})
    assert called == []
