"""Real-stack browser smoke for the quick-start wizard.

The browser logs in through the production login form, opens ``/wizard``,
creates a Bot and its pipeline through the real HTTP API, seeds the Local
Agent model that an offline instance cannot fetch from Space, and then saves
the Bot through the wizard's real update path.  The plugin supply is the same
local SDK download used by the Runner E2E, repackaged as ``langbot-team/
LocalAgent`` so the wizard sees its default Runner.

Run: uv run pytest tests/e2e/test_wizard_real_stack.py -q -m e2e
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time

import pytest
import yaml

from tests.e2e import test_runner_plugin_runtime as runtime
from tests.e2e.utils.process_manager import find_project_root

runner_runtime_ports = runtime.runner_runtime_ports
runner_runtime_process = runtime.runner_runtime_process
runner_langbot_process = runtime.runner_langbot_process
runner_client = runtime.runner_client

pytestmark = pytest.mark.e2e

LOCAL_AGENT_RUNNER_ID = 'plugin:langbot-team/LocalAgent/default'
WIZARD_ADAPTER = 'web_page_bot'


@pytest.fixture(scope='session')
def runner_e2e_tmpdir(tmp_path_factory):
    """Keep the isolated LangBot data directory per module."""
    return tmp_path_factory.mktemp('wizard-real-stack')


@pytest.fixture(scope='session')
def runner_e2e_port():
    return runtime._free_port()


@pytest.fixture(scope='session')
def runner_e2e_config_path(runner_e2e_tmpdir, runner_e2e_port, runner_runtime_ports):
    """Build the Runner config and expose the Page Bot adapter to the wizard."""
    path = runtime.runner_e2e_config_path.__wrapped__(
        runner_e2e_tmpdir,
        runner_e2e_port,
        runner_runtime_ports,
        None,  # The wizard flow opens no WebSocket.
    )
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    config['system']['disabled_adapters'] = [
        name for name in config['system']['disabled_adapters'] if name != WIZARD_ADAPTER
    ]
    path.write_text(yaml.safe_dump(config, default_flow_style=False), encoding='utf-8')
    return path


def _local_agent_package(tmpdir) -> 'object':
    """Repackage the local QA Runner as langbot-team/LocalAgent."""
    source = tmpdir / 'agent-runner-qa-package'
    target = tmpdir / 'local-agent-package'
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)

    manifest_path = target / 'manifest.yaml'
    manifest = yaml.safe_load(manifest_path.read_text(encoding='utf-8'))
    manifest['metadata']['author'] = 'langbot-team'
    manifest['metadata']['name'] = 'LocalAgent'
    manifest['metadata']['label'] = {'en_US': 'Local Agent', 'zh_Hans': '本地代理'}
    manifest_path.write_text(yaml.safe_dump(manifest, default_flow_style=False), encoding='utf-8')

    archive = tmpdir / 'local-agent'
    shutil.make_archive(str(archive), 'zip', root_dir=target)
    return archive.with_suffix('.zip')


def _wait_for_runner_stage(client, token: str, timeout: float = 90) -> None:
    """Wait until the wizard pipeline metadata exposes the Local Agent Runner."""
    headers = {'Authorization': f'Bearer {token}'}
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get('/api/v1/pipelines/_/metadata', headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload['code'] == 0, payload
        ai = next(group for group in payload['data']['configs'] if group.get('name') == 'ai')
        if any(stage['name'] == LOCAL_AGENT_RUNNER_ID for stage in ai['stages']):
            return
        time.sleep(1)
    raise AssertionError(f'{LOCAL_AGENT_RUNNER_ID} was not registered by the plugin runtime')


def _adapter_label(client, token: str) -> str:
    response = client.get('/api/v1/platform/adapters', headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['code'] == 0, payload
    adapter = next(item for item in payload['data']['adapters'] if item['name'] == WIZARD_ADAPTER)
    label = adapter['label']
    return label.get('en_US') if isinstance(label, dict) else str(label)


def test_chromium_quick_start_creates_and_saves_bot(runner_client, runner_e2e_tmpdir):
    """Login -> wizard -> create Bot -> save, all against the real backend."""
    token = runtime._init_and_auth(runner_client)
    runtime._install_qa_plugin(runner_client, token, _local_agent_package(runner_e2e_tmpdir))
    _wait_for_runner_stage(runner_client, token)

    env = os.environ.copy()
    env.update(
        {
            'LANGBOT_WIZARD_API_URL': str(runner_client.base_url).rstrip('/'),
            'LANGBOT_WIZARD_WEB_PORT': str(runtime._free_port()),
            'LANGBOT_WIZARD_TOKEN': token,
            'LANGBOT_WIZARD_ADAPTER_NAME': WIZARD_ADAPTER,
            'LANGBOT_WIZARD_ADAPTER_LABEL': _adapter_label(runner_client, token),
            'LANGBOT_WIZARD_BROWSER_OUTPUT': str(runner_e2e_tmpdir / 'browser-results'),
        }
    )
    browser = subprocess.Popen(
        ['node', 'node_modules/@playwright/test/cli.js', 'test', '--config=playwright.wizard.config.ts'],
        cwd=find_project_root() / 'web',
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = browser.communicate(timeout=360)
        assert browser.returncode == 0, f'Chromium wizard E2E:\n{stdout}\n{stderr}'
        print(stdout)
    finally:
        try:
            os.killpg(browser.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            browser.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(browser.pid, signal.SIGKILL)
            browser.wait(timeout=5)
