from __future__ import annotations

import uuid


_INSTANCE_PREFIX = 'instance_'
_WORKSPACE_IDENTITY_NAMESPACE = uuid.UUID('8ea04f29-8528-4cc3-bb28-30a838c89d76')


def personal_workspace_uuid(instance_uuid: str, account_uuid: str) -> str:
    """Return the stable UUID of an account's personal OSS Workspace."""

    instance_value = instance_uuid.strip()
    account_value = account_uuid.strip()
    if not instance_value or not account_value:
        raise ValueError('Personal Workspace identity requires both instance and account UUIDs')
    return str(uuid.uuid5(_WORKSPACE_IDENTITY_NAMESPACE, f'{instance_value}:personal:{account_value}'))


def personal_workspace_slug(account_uuid: str) -> str:
    """Return the collision-free slug used for one account's personal Workspace."""

    account_value = account_uuid.strip()
    if not account_value:
        raise ValueError('Personal Workspace slug requires an account UUID')
    return f'personal-{account_value}'


def workspace_uuid_from_instance_id(instance_id: str) -> str:
    """Return the stable OSS Workspace UUID for a persisted instance identity."""
    value = instance_id.strip()
    if not value:
        raise ValueError('LangBot instance identity is empty')

    candidate = value[len(_INSTANCE_PREFIX) :] if value.startswith(_INSTANCE_PREFIX) else value
    try:
        return str(uuid.UUID(candidate))
    except ValueError:
        return str(uuid.uuid5(_WORKSPACE_IDENTITY_NAMESPACE, value))
