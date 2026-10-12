from __future__ import annotations

import pytest

from octop.infra.deployment.connection import normalize_address
from octop.infra.deployment.desktop import DesktopIdentityBridge
from octop.infra.errors import OctopError


def test_management_address_is_canonical_and_has_no_embedded_credentials() -> None:
    assert normalize_address("https://EXAMPLE.com:443/") == "https://example.com"
    assert normalize_address("http://10.31.3.82:6602/") == "http://10.31.3.82:6602"
    for value in ("http://user:pass@example.com", "http://example.com?tenant=other"):
        with pytest.raises(OctopError):
            normalize_address(value)


def test_admin_management_permissions_do_not_become_local_tool_permissions() -> None:
    profile = {"role": "admin", "permissions": ["users", "providers", "terminal", "desktop"]}
    assert DesktopIdentityBridge.local_permissions(profile, {}) == []


def test_explicit_local_permissions_are_separate_from_management_permissions() -> None:
    profile = {"role": "admin", "permissions": ["users", "providers", "terminal"]}
    context = {"local_permissions": ["terminal"]}
    assert DesktopIdentityBridge.local_permissions(profile, context) == ["terminal"]
