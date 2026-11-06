from __future__ import annotations

import sys

import pytest


def restore_preregistered_groups() -> None:
    """Re-register RouterGroup classes hidden by module isolation.

    The per-module ``mock_circular_import_chain`` fixtures clear
    ``controller.group`` alongside a few group packages so ``main`` can be
    re-imported. Modules that stay in ``sys.modules`` are not executed again,
    so their ``group_class`` decorators appended to the discarded registry
    object. The re-imported ``main`` then sees only the partial registry and
    routes such as the dashboard WebSocket disappear, producing a 400 on
    handshake. Collect the already-imported group classes back into the
    current registry; ``dedupe_preregistered_groups`` drops duplicates.
    """
    from langbot.pkg.api.http.controller import group

    known = {(group_cls.name, group_cls.path) for group_cls in group.preregistered_groups}
    for module_name, module in list(sys.modules.items()):
        if not module_name.startswith('langbot.pkg.api.http.controller.groups'):
            continue
        for value in vars(module).values():
            if not isinstance(value, type):
                continue
            name = getattr(value, 'name', None)
            path = getattr(value, 'path', None)
            if not isinstance(name, str) or not isinstance(path, str):
                continue
            if not callable(getattr(value, 'initialize', None)):
                continue
            key = (name, path)
            if key in known:
                continue
            known.add(key)
            group.preregistered_groups.append(value)


def dedupe_preregistered_groups() -> None:
    """Keep API integration route registration isolated across test modules."""
    from langbot.pkg.api.http.controller import group

    seen: set[tuple[str, str]] = set()
    unique_groups = []
    for group_cls in group.preregistered_groups:
        key = (group_cls.name, group_cls.path)
        if key in seen:
            continue
        seen.add(key)
        unique_groups.append(group_cls)

    group.preregistered_groups[:] = unique_groups


@pytest.fixture(scope='module')
def http_controller_cls(mock_circular_import_chain):
    """Import HTTPController under each module's circular-import isolation."""
    from langbot.pkg.api.http.controller.main import HTTPController

    restore_preregistered_groups()
    dedupe_preregistered_groups()
    return HTTPController
