"""Validate that the dashboard plugin can be mounted by the plugin runtime."""

from __future__ import annotations

from pathlib import Path

import yaml

from langbot_plugin.api.definition.components.manifest import ComponentManifest
from langbot_plugin.api.definition.components.page import Page

PLUGIN_ROOT = Path(__file__).resolve().parents[3] / 'plugins' / 'qa-analytics'


def test_dashboard_page_declares_a_runtime_component(monkeypatch):
    monkeypatch.chdir(PLUGIN_ROOT)
    manifest_path = Path('components/pages/dashboard.yaml')
    manifest = yaml.safe_load(manifest_path.read_text(encoding='utf-8'))

    assert manifest['kind'] == 'Page'
    assert manifest['execution']['python']['path'] == 'dashboard_page.py'

    component = ComponentManifest('langbot-team', manifest, str(manifest_path))
    page_class = component.get_python_component_class()

    assert issubclass(page_class, Page)
    assert (manifest_path.parent / component.spec['path']).is_file()
