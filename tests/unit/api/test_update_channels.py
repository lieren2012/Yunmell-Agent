"""Regression coverage for fork provenance and independent release selection."""

import io
import json

from octop.api.routers import update


def test_yunmell_version_never_becomes_official_baseline(monkeypatch):
    monkeypatch.setattr(update, "get_local_version", lambda: "9.8.7")
    monkeypatch.setenv("OCTOP_OFFICIAL_VERSION", "9.8.7")
    assert update._channel_current_version("official") == "1.0.2b8"
    assert update._channel_current_version("yunmell") == "9.8.7"
    assert update._channel_payload("official")["last_check_time"] is None


def test_release_list_selects_beta_only_when_enabled(monkeypatch):
    releases = [
        {"tag_name": "v9.0.0", "draft": True},
        {"tag_name": "v1.1.0b1", "prerelease": True, "body": "beta"},
        {"tag_name": "v1.0.8", "prerelease": False},
        {"tag_name": "v1.0.9", "prerelease": False, "body": "stable"},
    ]
    monkeypatch.setattr(
        update.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(json.dumps(releases).encode())
    )
    stable = update._fetch_yunmell_release(stable_only=True)
    beta = update._fetch_yunmell_release(stable_only=False)
    assert stable["version"] == "1.0.9"
    assert stable["notes"] == "stable"
    assert beta["version"] == "1.1.0b1"
    assert beta["prerelease"] is True


def test_prerelease_install_does_not_fall_back_to_older_stable(monkeypatch):
    """A b10 install must not be told that the older 1.0.9 is latest."""
    releases = [
        {"tag_name": "v1.0.9", "prerelease": False, "body": "stable"},
        {"tag_name": "v1.0.10b10", "prerelease": True, "body": "current"},
        {"tag_name": "v1.0.10b11", "prerelease": True, "body": "next"},
    ]
    monkeypatch.setattr(
        update.urllib.request,
        "urlopen",
        lambda *a, **kw: io.BytesIO(json.dumps(releases).encode()),
    )

    latest = update._fetch_yunmell_release(stable_only=True, current_version="1.0.10b10")
    assert latest["version"] == "1.0.10b11"
    assert update.is_newer(latest["version"], "1.0.10b10")

    current = update._fetch_yunmell_release(stable_only=True, current_version="1.0.0")
    assert current["version"] == "1.0.9"

    beta = update._fetch_yunmell_release(stable_only=False, current_version="1.0.0")
    assert beta["version"] == "1.0.10b11"
