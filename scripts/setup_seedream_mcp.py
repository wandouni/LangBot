# /// script
# requires-python = ">=3.10"
# ///
"""Configure the Doubao Seedream MCP server for Claude Code, Codex and WorkBuddy.

Designed to be executed by an AI coding agent: it detects the platform, locates
``uvx``, checks whether the gateway recognises the model name, merges the MCP
entry into each client config without disturbing unrelated settings, then
performs a real MCP ``initialize`` + ``tools/list`` handshake and prints a JSON
report.

Usage:
    python3 scripts/setup_seedream_mcp.py --dry-run
    python3 scripts/setup_seedream_mcp.py
    python3 scripts/setup_seedream_mcp.py --targets claude,codex

Exit codes:
    0  every requested target is configured and verified
    1  verification failed after writing
    2  a prerequisite is missing (uvx, token)
    3  gateway does not authorize the model
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SERVER_NAME = 'seedream'
# 网关只登记了别名、不接受完整 Model ID，因此使用带「模型名直通」补丁的构建：
# https://github.com/wandouni/Seedream_MCP/releases/tag/v4.2.0.post1
WHEEL_URL = (
    'https://github.com/wandouni/Seedream_MCP/releases/download/'
    'v4.2.0.post1/seedream_image_mcp-4.2.0.post1-py3-none-any.whl'
)
PACKAGE_ENTRY = 'seedream-image-mcp'
DEFAULT_BASE_URL = 'https://ai.ctaigw.cn/v1'
DEFAULT_MODEL_ID = 'doubao-seedream-5.0-lite'
DEFAULT_SIZE = '2K'
BLOCK_BEGIN = '# >>> seedream-mcp (managed by scripts/setup_seedream_mcp.py)'
BLOCK_END = '# <<< seedream-mcp'
MIN_PIXELS = 3_686_400
TARGETS = ('claude', 'codex', 'workbuddy')


class SetupError(Exception):
    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- environment


def resolve_home(raw: str | None) -> Path:
    return Path(raw).expanduser().resolve() if raw else Path.home()


def find_uvx(home: Path) -> str | None:
    """Return an absolute uvx path usable by GUI apps that ignore shell PATH."""
    found = shutil.which('uvx')
    if found:
        return str(Path(found).resolve())
    candidates = [
        home / '.local' / 'bin' / ('uvx.exe' if os.name == 'nt' else 'uvx'),
        home / '.cargo' / 'bin' / ('uvx.exe' if os.name == 'nt' else 'uvx'),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def detect_token(home: Path, explicit: str | None) -> str | None:
    if explicit:
        return explicit.strip()
    for env_name in ('ARK_API_KEY', 'SEEDREAM_API_KEY'):
        value = os.environ.get(env_name)
        if value and value.strip():
            return value.strip()
    # Claude Code stores the gateway key here when cc-switch manages the provider.
    settings = home / '.claude' / 'settings.json'
    if settings.is_file():
        try:
            data = json.loads(settings.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return None
        value = (data.get('env') or {}).get('ANTHROPIC_AUTH_TOKEN')
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def default_data_root(home: Path) -> str:
    if os.name == 'nt':
        return str(home / 'Pictures' / 'Seedream')
    return str(home / 'Pictures' / 'Seedream')


# ---------------------------------------------------------------- gateway


def gateway_check(base_url: str, token: str, model_id: str) -> dict[str, Any]:
    """Distinguish 'model registered' (HTTP 400 on a bad size) from 'model unknown' (403).

    The gateway only registers the alias, so a 403 here means the model name itself
    is wrong — not that a whitelist entry is missing.
    """
    body = json.dumps({'model': model_id, 'prompt': 'probe', 'size': '1024x1024'}).encode()
    request = urllib.request.Request(
        f'{base_url.rstrip("/")}/images/generations',
        data=body,
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return {'ok': True, 'http_status': response.status, 'detail': 'unexpected success'}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors='replace')
        if exc.code == 403 or 'model_no_authorization' in detail:
            return {
                'ok': False,
                'http_status': exc.code,
                'reason': 'model_not_authorized',
                'detail': detail[:400],
                'action': (
                    f'网关未登记模型 {model_id}；当前网关只接受别名 doubao-seedream-5.0-lite，请用 --model-id 指定它'
                ),
            }
        if exc.code in (400, 200):
            return {'ok': True, 'http_status': exc.code, 'detail': 'authorized (bad-size probe rejected)'}
        if exc.code == 401:
            return {
                'ok': False,
                'http_status': exc.code,
                'reason': 'bad_token_or_base_url',
                'detail': detail[:400],
                'action': '检查 ARK_API_KEY 与 base_url 是否带 /v1',
            }
        return {'ok': False, 'http_status': exc.code, 'reason': 'unexpected', 'detail': detail[:400]}
    except urllib.error.URLError as exc:
        return {'ok': False, 'reason': 'network', 'detail': str(exc)}


# ---------------------------------------------------------------- writers


def backup(path: Path, stamp: str) -> str | None:
    if not path.is_file():
        return None
    target = path.with_name(f'{path.name}.bak-{stamp}')
    shutil.copy2(path, target)
    return str(target)


def merge_json_server(path: Path, server: dict[str, Any], dry_run: bool, stamp: str) -> dict[str, Any]:
    existed = path.is_file()
    data: dict[str, Any] = {}
    if existed:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as exc:
            raise SetupError(f'{path} 不是合法 JSON，拒绝覆盖：{exc}') from exc
    servers = data.setdefault('mcpServers', {})
    if not isinstance(servers, dict):
        raise SetupError(f'{path} 的 mcpServers 不是对象，拒绝覆盖')
    previous = servers.get(SERVER_NAME)
    changed = previous != server
    servers[SERVER_NAME] = server
    if not dry_run and changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        backup_path = backup(path, stamp)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return {'path': str(path), 'changed': True, 'backup': backup_path, 'created': not existed}
    return {'path': str(path), 'changed': changed, 'backup': None, 'created': not existed and not dry_run}


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def uvx_args() -> list[str]:
    """``uvx --from <wheel URL> seedream-image-mcp``：从公开 Release 安装补丁版。"""
    return ['--from', WHEEL_URL, PACKAGE_ENTRY]


def render_codex_block(uvx: str, env: dict[str, str]) -> str:
    args = ', '.join(toml_string(item) for item in uvx_args())
    lines = [
        BLOCK_BEGIN,
        f'[mcp_servers.{SERVER_NAME}]',
        f'command = {toml_string(uvx)}',
        f'args = [{args}]',
        f'[mcp_servers.{SERVER_NAME}.env]',
    ]
    lines += [f'{key} = {toml_string(value)}' for key, value in env.items()]
    lines.append(BLOCK_END)
    return '\n'.join(lines) + '\n'


def toml_headers(text: str) -> list[str]:
    """Return every table header, e.g. ``mcp_servers.seedream.env``."""
    headers: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith('['):
            continue
        inner = stripped.lstrip('[').split(']', 1)[0].strip()
        if inner:
            headers.append(inner)
    return headers


def is_seedream_header(header: str) -> bool:
    prefix = f'mcp_servers.{SERVER_NAME}'
    return header == prefix or header.startswith(f'{prefix}.')


def strip_codex_sections(text: str) -> str:
    """Drop non-managed ``[mcp_servers.seedream*]`` tables.

    Appending the managed block next to a hand-written table would define the
    same table twice, and Codex rejects the whole file as invalid TOML.
    """
    kept: list[str] = []
    skipping = False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith('['):
            header = stripped.lstrip('[').split(']', 1)[0].strip()
            skipping = bool(header) and is_seedream_header(header)
        if not skipping:
            kept.append(line)
    return ''.join(kept).rstrip('\n') + '\n' if kept else ''


def merge_codex_toml(path: Path, block: str, dry_run: bool, stamp: str, force: bool) -> dict[str, Any]:
    text = path.read_text(encoding='utf-8') if path.is_file() else ''
    had_block = BLOCK_BEGIN in text
    if had_block:
        start = text.index(BLOCK_BEGIN)
        end = text.index(BLOCK_END, start) + len(BLOCK_END)
        new_text = text[:start] + block.rstrip('\n') + text[end:]
    else:
        if any(is_seedream_header(item) for item in toml_headers(text)) and not force:
            raise SetupError(f'{path} 已存在手工编写的 [mcp_servers.{SERVER_NAME}] 段，未加 --force 时不覆盖')
        text = strip_codex_sections(text)
        new_text = text if text.endswith('\n') or not text else text + '\n'
        new_text = new_text + ('\n' if new_text.strip() else '') + block
    changed = new_text != text
    if not dry_run and changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        backup_path = backup(path, stamp)
        path.write_text(new_text, encoding='utf-8')
        return {'path': str(path), 'changed': True, 'backup': backup_path, 'created': not text}
    return {'path': str(path), 'changed': changed, 'backup': None, 'created': not text and not dry_run}


# ---------------------------------------------------------------- handshake


def mcp_handshake(uvx: str, env: dict[str, str], timeout: float) -> dict[str, Any]:
    """Run a real stdio session and confirm the generation tools are exposed.

    The exchange is sequential on purpose: writing every request up front lets the
    server drop ``tools/list`` when stdin closes before it is processed.
    """
    process_env = {**os.environ, **env}
    try:
        proc = subprocess.Popen(
            [uvx, *uvx_args()],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=process_env,
        )
    except OSError as exc:
        return {'ok': False, 'reason': 'spawn_failed', 'detail': str(exc)}

    lines: queue.Queue[str | None] = queue.Queue()
    stderr_lines: list[str] = []

    def pump(stream, target) -> None:
        for line in stream:
            target(line)
        target(None)

    threading.Thread(target=pump, args=(proc.stdout, lines.put), daemon=True).start()
    threading.Thread(
        target=pump,
        args=(proc.stderr, lambda line: stderr_lines.append(line or '')),
        daemon=True,
    ).start()

    deadline = time.monotonic() + timeout

    def send(message: dict[str, Any]) -> bool:
        try:
            assert proc.stdin is not None
            proc.stdin.write(json.dumps(message) + '\n')
            proc.stdin.flush()
            return True
        except (BrokenPipeError, ValueError):
            return False

    def wait_for(request_id: int) -> dict[str, Any] | None:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                line = lines.get(timeout=remaining)
            except queue.Empty:
                return None
            if line is None:
                return None
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get('id') == request_id:
                return message

    tools: list[str] = []
    try:
        if not send(
            {
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'initialize',
                'params': {
                    'protocolVersion': '2024-11-05',
                    'capabilities': {},
                    'clientInfo': {'name': 'setup-seedream-mcp', 'version': '1.0'},
                },
            }
        ):
            return {'ok': False, 'reason': 'spawn_failed', 'detail': 'stdin closed'}

        if wait_for(1) is None:
            return {'ok': False, 'reason': 'timeout', 'detail': ''.join(stderr_lines)[-400:]}

        send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        send({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})

        response = wait_for(2)
        if response is None:
            return {'ok': False, 'reason': 'timeout', 'detail': ''.join(stderr_lines)[-400:]}
        for tool in (response.get('result') or {}).get('tools') or []:
            name = tool.get('name')
            if name:
                tools.append(name)
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except (subprocess.TimeoutExpired, OSError):
            proc.kill()

    ok = 'text_to_image' in tools
    return {
        'ok': ok,
        'tools': sorted(tools),
        'stderr_tail': '' if ok else ''.join(stderr_lines)[-300:],
    }


# ---------------------------------------------------------------- main


def build_env(token: str, base_url: str, model_id: str, data_root: str) -> dict[str, str]:
    return {
        'ARK_API_KEY': token,
        'ARK_BASE_URL': base_url,
        'SEEDREAM_MODEL_ID': model_id,
        # 包默认已开直通，显式写出便于排查：配置里的模型名原样进请求体，
        # 不再被展开成网关未登记的完整 Model ID。
        'SEEDREAM_MODEL_PASSTHROUGH': 'true',
        'SEEDREAM_DEFAULT_SIZE': DEFAULT_SIZE,
        'SEEDREAM_DEFAULT_WATERMARK': 'false',
        'SEEDREAM_DATA_ROOT': data_root,
    }


def server_config(command: str, env: dict[str, str]) -> dict[str, Any]:
    return {'type': 'stdio', 'command': command, 'args': uvx_args(), 'env': env}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', help='覆盖用户主目录，用于测试或非标准部署')
    parser.add_argument('--token', help='网关 Token；缺省依次读取 ARK_API_KEY、~/.claude/settings.json')
    parser.add_argument('--base-url', default=DEFAULT_BASE_URL)
    parser.add_argument('--model-id', default=DEFAULT_MODEL_ID)
    parser.add_argument('--data-root', help='图片落盘根目录，默认 ~/Pictures/Seedream')
    parser.add_argument('--targets', default='claude,codex,workbuddy')
    parser.add_argument('--dry-run', action='store_true', help='只检查与打印计划，不写文件')
    parser.add_argument('--force', action='store_true', help='覆盖手工编写的 Codex 同名段')
    parser.add_argument('--skip-gateway-check', action='store_true')
    parser.add_argument('--skip-handshake', action='store_true')
    parser.add_argument('--timeout', type=float, default=180.0, help='MCP 握手超时秒数')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    home = resolve_home(args.home)
    targets = [item.strip() for item in args.targets.split(',') if item.strip()]
    unknown = [item for item in targets if item not in TARGETS]
    if unknown:
        raise SetupError(f'未知目标：{", ".join(unknown)}；可选 {", ".join(TARGETS)}', 2)

    stamp = time.strftime('%Y%m%d%H%M%S')
    report: dict[str, Any] = {
        'platform': 'windows' if os.name == 'nt' else sys.platform,
        'home': str(home),
        'dry_run': args.dry_run,
        'targets': targets,
    }

    uvx = find_uvx(home)
    report['uvx'] = uvx
    if not uvx:
        report['status'] = 'prerequisite_missing'
        report['action'] = (
            'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
            if os.name == 'nt'
            else 'curl -LsSf https://astral.sh/uv/install.sh | sh'
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    token = detect_token(home, args.token)
    if not token:
        report['status'] = 'token_missing'
        report['action'] = '通过 --token 传入网关 Token，或设置 ARK_API_KEY'
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    if not args.skip_gateway_check:
        check = gateway_check(args.base_url, token, args.model_id)
        report['gateway'] = check
        if not check.get('ok'):
            report['status'] = 'gateway_blocked'
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 3

    data_root = args.data_root or default_data_root(home)
    env = build_env(token, args.base_url, args.model_id, data_root)

    writes: dict[str, Any] = {}
    failures: list[str] = []
    try:
        if 'claude' in targets:
            writes['claude'] = merge_json_server(home / '.claude.json', server_config(uvx, env), args.dry_run, stamp)
        if 'codex' in targets:
            writes['codex'] = merge_codex_toml(
                home / '.codex' / 'config.toml',
                render_codex_block(uvx, env),
                args.dry_run,
                stamp,
                args.force,
            )
        if 'workbuddy' in targets:
            writes['workbuddy'] = merge_json_server(
                home / '.workbuddy' / 'mcp.json', server_config(uvx, env), args.dry_run, stamp
            )
    except SetupError as exc:
        report['status'] = 'write_failed'
        report['writes'] = writes
        report['error'] = str(exc)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return exc.code
    report['writes'] = writes

    if (home / '.cc-switch' / 'cc-switch.db').is_file():
        report['warning'] = (
            '检测到 cc-switch：其 MCP 矩阵会按自身数据库重写 Claude Code/Codex 配置。'
            '改完请提示用户在 cc-switch 的 MCP 面板里同步添加同名服务，否则切换 provider 后会被覆盖。'
        )

    if not args.skip_handshake and not args.dry_run:
        report['handshake'] = mcp_handshake(uvx, env, args.timeout)
        if not report['handshake'].get('ok'):
            failures.append('handshake')
    elif args.dry_run:
        report['handshake'] = {'ok': None, 'skipped': 'dry-run'}

    report['status'] = 'verified' if not failures else 'configured_unverified'
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except SetupError as error:
        print(json.dumps({'status': 'error', 'error': str(error)}, ensure_ascii=False, indent=2))
        sys.exit(error.code)
