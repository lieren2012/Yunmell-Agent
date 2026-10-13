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
        "official_baseline_version",
        "product_version",
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

    assert body["official_baseline_version"] == "1.0.2b7"


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
    from octop.api.routers import update as router
    from octop.infra.setup.self_update import PyPIInfo

    c, auth = env_admin_client
    router._CHANNEL_CACHE.clear()
    monkeypatch.setattr(router, "get_local_version", lambda: "1.0.9")
    monkeypatch.setattr(
        router,
        "fetch_pypi_info",
        lambda: PyPIInfo(version="1.0.3b1", latest_stable="1.0.2", source="pypi.org"),
    )

    def unavailable(**kwargs: Any) -> Any:
        raise OSError("offline")

    monkeypatch.setattr(router, "_fetch_yunmell_release", unavailable)
    official = await c.post("/api/update/channels/official/check", headers=auth)
    yunmell = await c.post("/api/update/channels/yunmell/check", headers=auth)
    assert official.status_code == yunmell.status_code == 200
    assert official.json()["current_version"] == "1.0.2b7"
    assert official.json()["latest_version"] == "1.0.2"
    assert official.json()["has_update"] is True
    assert official.json()["latest_is_prerelease"] is False
    assert yunmell.json()["current_version"] == "1.0.9"
    assert yunmell.json()["error"] is not None
    combined = (await c.get("/api/update/channels/status", headers=auth)).json()
    assert combined["official"]["latest_version"] == "1.0.2"
    assert combined["yunmell"]["latest_version"] is None
    changed = await c.patch(
        "/api/update/channels/official/settings", json={"stable_only": False}, headers=auth
    )
    assert changed.json()["latest_version"] == "1.0.3b1"
    assert changed.json()["latest_is_prerelease"] is True
    combined = (await c.get("/api/update/channels/status", headers=auth)).json()
    assert combined["yunmell"]["stable_only"] is True
    router._CHANNEL_CACHE.clear()


async def test_official_action_does_not_overwrite_yunmell(
    env_admin_client: Any, monkeypatch: Any
) -> None:
    from octop.api.routers import update as router

    c, auth = env_admin_client
    router._CHANNEL_CACHE["official"] = {"latest_version": "1.0.3"}

    def unexpected_install(**kwargs: Any) -> Any:
        raise AssertionError("official action must not install over Yunmell")

    monkeypatch.setattr(router, "run_upgrade", unexpected_install)
    result = await c.post(
        "/api/update/channels/official/upgrade", json={"version": "1.0.3"}, headers=auth
    )
    assert result.status_code == 200
    assert result.json()["status"] == "upstream_sync_required"
    assert "TencentCloud/Octop" in result.json()["source_url"]
    router._CHANNEL_CACHE.clear()
