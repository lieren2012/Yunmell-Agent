from __future__ import annotations

import pytest

from octop.infra.deployment.connection import normalize_address
from octop.infra.deployment.desktop import DesktopIdentityBridge
from octop.infra.errors import OctopError
from octop.infra.users.permissions import ALL_PERMISSION_KEYS


def test_management_address_is_canonical_and_has_no_embedded_credentials() -> None:
    assert normalize_address("https://EXAMPLE.com:443/") == "https://example.com"
    assert normalize_address("http://10.31.3.82:6602/") == "http://10.31.3.82:6602"
    for value in ("http://user:pass@example.com", "http://example.com?tenant=other"):
        with pytest.raises(OctopError):
            normalize_address(value)


def test_admin_without_explicit_policy_gets_full_local_permissions() -> None:
    profile = {"role": "admin", "permissions": ["users", "providers", "terminal", "desktop"]}
    assert DesktopIdentityBridge.local_permissions(profile, {}) == sorted(ALL_PERMISSION_KEYS)


def test_admin_empty_legacy_policy_gets_full_local_permissions() -> None:
    profile = {"role": "admin", "permissions": ["users", "providers"]}
    assert DesktopIdentityBridge.local_permissions(profile, {"local_permissions": []}) == sorted(
        ALL_PERMISSION_KEYS
    )


def test_explicit_local_permissions_are_separate_from_management_permissions() -> None:
    profile = {"role": "admin", "permissions": ["users", "providers", "terminal"]}
    context = {"local_permissions": ["terminal"]}
    assert DesktopIdentityBridge.local_permissions(profile, context) == ["terminal"]


def test_regular_user_legacy_empty_policy_falls_back_to_profile_permissions() -> None:
    """b11 sent an empty local policy while retaining module permissions in /auth/me."""
    profile = {
        "role": "user",
        "permissions": ["channels", "skill_packages", "knowledge_bases"],
    }
    assert DesktopIdentityBridge.local_permissions(profile, {"local_permissions": []}) == [
        "channels",
        "skill_packages",
        "knowledge_bases",
    ]


def test_explicit_empty_policy_version_keeps_user_restricted() -> None:
    profile = {"role": "user", "permissions": ["channels", "skill_packages"]}
    assert DesktopIdentityBridge.local_permissions(
        profile, {"local_permissions": [], "local_permissions_version": 1}
    ) == []
