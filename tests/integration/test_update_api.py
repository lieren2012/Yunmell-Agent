"""Integration tests for /api/update."""

from __future__ import annotations

from typing import Any


async def test_update_status_shape(env_admin_client: Any) -> None:
    c, auth = env_admin_client
    r = await c.get("/api/update/status", headers=auth)
    assert r.status_code == 200
    body = r.json()
    for key in (
        "current_version",
        "latest_version",
        "has_update",
        "is_editable",
        "service_mode",
        "desktop",
        "error",
        "last_check_time",
        "release_notes",
        "stable_only",
        "latest_is_prerelease",
    ):
        assert key in body


async def test_update_check_admin_only(env_admin_client: Any) -> None:
    c, auth = env_admin_client
    r = await c.post("/api/update/check", headers=auth)
    assert r.status_code == 200


async def test_update_settings_stable_only_roundtrip(env_admin_client: Any) -> None:
    c, auth = env_admin_client
    r = await c.patch("/api/update/settings", json={"stable_only": False}, headers=auth)
    assert r.status_code == 200
    assert r.json()["stable_only"] is False
    status = await c.get("/api/update/status", headers=auth)
    assert status.status_code == 200
    assert status.json()["stable_only"] is False
    r = await c.patch("/api/update/settings", json={"stable_only": True}, headers=auth)
    assert r.status_code == 200
    assert r.json()["stable_only"] is True


async def test_update_channels_are_independent(env_admin_client: Any, monkeypatch: Any) -> None:
    from octop.api.routers import update as update_router

    c, auth = env_admin_client
    update_router._CHANNEL_CACHE.clear()

    def fake_check(channel: str) -> dict[str, Any]:
        if channel == "official":
            result = {
                "channel": "official",
                "current_version": "1.0.0",
                "latest_version": "1.1.0",
                "has_update": True,
                "latest_is_prerelease": False,
                "release_notes": "official notes",
                "source": "pypi.org",
                "source_url": "https://pypi.org/project/octop/",
                "error": None,
                "last_check_time": "now",
                "upgrade_mode": "in_place",
            }
        else:
            result = {
            "channel": "yunmell",
            "current_version": "1.0.0",
            "latest_version": None,
            "has_update": False,
            "latest_is_prerelease": False,
            "release_notes": None,
            "source": "github.com/lieren2012/Yunmell-Agent",
            "source_url": "https://github.com/lieren2012/Yunmell-Agent/releases",
            "error": "Yunmell source unavailable",
            "last_check_time": "now",
            "upgrade_mode": "release",
            }
        update_router._CHANNEL_CACHE[channel] = result
        return result

    monkeypatch.setattr(update_router, "_check_channel", fake_check)
    official = await c.post("/api/update/channels/official/check", headers=auth)
    yunmell = await c.post("/api/update/channels/yunmell/check", headers=auth)
    assert official.status_code == 200
    assert official.json()["latest_version"] == "1.1.0"
    assert yunmell.status_code == 200
    assert yunmell.json()["error"] == "Yunmell source unavailable"

    combined = await c.get("/api/update/channels/status", headers=auth)
    assert combined.status_code == 200
    assert combined.json()["official"]["latest_version"] == "1.1.0"
    assert combined.json()["yunmell"]["latest_version"] is None
