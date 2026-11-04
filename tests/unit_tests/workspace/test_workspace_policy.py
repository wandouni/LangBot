from langbot.pkg.workspace.policy import (
    CloudWorkspacePolicy,
    PersonalWorkspacePolicy,
    open_core_workspace_policy,
)


def test_open_source_policy_grants_one_personal_workspace_per_account() -> None:
    policy = open_core_workspace_policy()

    assert isinstance(policy, PersonalWorkspacePolicy)
    assert policy.workspace_limit is None
    assert policy.multi_workspace_enabled is False
    assert policy.personal_workspace_enabled is True
    # Sharing is disabled permanently in this edition.
    assert policy.members_enabled is False
    assert policy.invitations_enabled is False


def test_personal_policy_does_not_limit_workspace_provisioning() -> None:
    # Provisioning is driven by accounts, not by a user-facing creation quota.
    open_core_workspace_policy().require_workspace_creation_allowed(0)
    open_core_workspace_policy().require_workspace_creation_allowed(10_000)


def test_cloud_policy_is_not_exported_as_the_default_policy() -> None:
    # CloudWorkspacePolicy remains a contract for the future verified, closed
    # bootstrap.  Constructing it explicitly must not change the OSS default.
    assert CloudWorkspacePolicy().multi_workspace_enabled is True
    assert isinstance(open_core_workspace_policy(), PersonalWorkspacePolicy)
