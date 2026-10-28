"""Repository-wide test execution policy."""

import os

import pytest

pytest_plugins = ['tests.utils.required_suites']


@pytest.fixture(autouse=True)
def _restore_plugin_file_storage_dir():
    """Undo the process-wide transfer root a shared PluginConnector sets.

    ``PluginRuntimeConnector`` writes ``LANGBOT_PLUGIN_FILE_STORAGE_DIR`` into
    ``os.environ`` for shared deployments; keep that from leaking into unrelated
    tests in the same process.
    """

    from langbot_plugin.runtime.security import PLUGIN_FILE_STORAGE_DIR_ENV

    missing = object()
    original = os.environ.get(PLUGIN_FILE_STORAGE_DIR_ENV, missing)
    yield
    if original is missing:
        os.environ.pop(PLUGIN_FILE_STORAGE_DIR_ENV, None)
    else:
        os.environ[PLUGIN_FILE_STORAGE_DIR_ENV] = original
