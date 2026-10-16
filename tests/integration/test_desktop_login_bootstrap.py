"""Desktop authentication must not wait for expert graph/workspace initialization."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from octop.infra.deployment.desktop import bridge
from tests.support.app import octop_client


@pytest.fixture
async def desktop_login(tmp_path, monkeypatch):
    monkeypatch.setenv("OCTOP_DESKTOP_CLIENT", "1")
    monkeypatch.setenv("OCTOP_CONTROL_PLANE_URL", "http://management.example")
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path / "desktop-login"))
    async with octop_client(tmp_path / "desktop-login") as (client, server):
        context = {
            "name": "Login test enterprise",
            "controls": {
                "shell": False,
                "browser": False,
                "desktop": False,
                "filesystem": True,
                "network": True,
            },
            "resource_policy": {"max_agents": 1, "token_quota": 1500},
            "default_model": {"name": "Default model"},
            "allowed_models": [],
            "local_permissions": ["knowledge_bases"],
            "local_permissions_version": 1,
        }
        profile = {"id": 42, "username": "member", "role": "user", "permissions": []}
        replies = {
            "/auth/deployment/login": httpx.Response(
                200, json={"access_token": "fixture-remote-session", "user": profile}
            ),
            "/auth/deployment/session": httpx.Response(200, json=context),
        }

        async def remote(method, path, **kwargs):
            replies[path].request = httpx.Request(method, "http://management.example/api" + path)
            return replies[path]

        monkeypatch.setattr(bridge(server), "remote", remote)
        yield client, server, replies


@pytest.mark.parametrize("startup_fails", [False, True])
async def test_first_login_returns_with_trusted_policy_while_expert_starts(
    desktop_login, monkeypatch, startup_fails
):
    client, server, _replies = desktop_login
    registry = server.app_runtime.agent_registry
    harness = registry.harness_manager
    original_create = harness.acreate_agent
    original_bootstrap = registry._complete_create_bootstrap
    started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def slow_create(*args, **kwargs):
        started.set()
        await release.wait()
        if startup_fails:
            raise RuntimeError("fixture workspace initialization failed")
        return await original_create(*args, **kwargs)

    async def bootstrap(row):
        try:
            await original_bootstrap(row)
        finally:
            finished.set()

    monkeypatch.setattr(harness, "acreate_agent", slow_create)
    monkeypatch.setattr(registry, "_complete_create_bootstrap", bootstrap)
    login = asyncio.create_task(
        client.post("/api/auth/login", json={"username": "member", "password": "fixture"})
    )
    try:
        # An indefinitely stalled runtime must not hold the login response. A
        # longer UI timeout cannot satisfy this invariant; startup is unreleased.
        response = await asyncio.wait_for(asyncio.shield(login), timeout=5)
        assert response.status_code == 200, response.text
        await asyncio.wait_for(started.wait(), timeout=5)
        assert not finished.is_set()
        uid = response.json()["user"]["id"]
        headers = {"Authorization": "Bearer " + response.json()["access_token"]}
        row = server.services.user_repo.get(uid)
        assert row.password_hash is None
        assert row.permissions == ["knowledge_bases"]
        assert server.user_manager.get(row.username).permissions == ["knowledge_bases"]
        assert server.services.user_policy_repo.get(uid, "max_agents").value == "1"
        assert server.services.user_policy_repo.get(uid, "token_quota").value == "1500"
        membership = server.services.enterprise_repo.list_memberships_for_user(uid)[0]
        policy = server.services.enterprise_repo.get_control_policy(membership.team_id)
        assert policy.shell_enabled is False
        assert policy.filesystem_enabled is True
        assert bridge(server)._load_snapshot(uid) is not None
        assert not bridge(server).lock.locked()
        assert (await client.get("/api/agents")).status_code == 401
        me = await asyncio.wait_for(client.get("/api/auth/me", headers=headers), timeout=2)
        assert me.status_code == 200
        agents = (await client.get("/api/agents", headers=headers)).json()
        assert len(agents) == 1
        assert agents[0]["state"] == "starting"
        assert agents[0]["config"]["is_default"] is True
        aid = agents[0]["agent_id"]
    finally:
        release.set()
        await asyncio.wait_for(login, timeout=5)
        if started.is_set():
            await asyncio.wait_for(finished.wait(), timeout=5)

    status = (await client.get(f"/api/agents/{aid}/status", headers=headers)).json()
    assert status["state"] == ("failed" if startup_fails else "running")
    if startup_fails:
        assert "fixture workspace initialization failed" in status["last_error"]
        monkeypatch.setattr(harness, "acreate_agent", original_create)
        assert (await client.post(f"/api/agents/{aid}/start", headers=headers)).status_code == 204
        status = (await client.get(f"/api/agents/{aid}/status", headers=headers)).json()
        assert status["state"] == "running"
        assert status["last_error"] is None
    assert len(registry.list_agents(uid)) == 1


@pytest.mark.parametrize("failed_path", ["/auth/deployment/login", "/auth/deployment/session"])
async def test_failed_remote_auth_or_policy_never_starts_default(desktop_login, failed_path):
    client, server, replies = desktop_login
    replies[failed_path] = httpx.Response(401, json={"error": "fixture rejected"})
    response = await client.post(
        "/api/auth/login", json={"username": "member", "password": "fixture"}
    )
    assert response.status_code == 401
    assert "access_token" not in response.json()
    assert server.services.agent_repo.list_all() == []
    for user in server.services.user_repo.list():
        assert server.services.secret_repo.get(f"yunmell.remote-session:{user.id}") is None
    assert (await client.get("/api/agents")).status_code == 401


async def test_zero_expert_quota_does_not_bootstrap(desktop_login):
    client, server, replies = desktop_login
    context = replies["/auth/deployment/session"].json()
    context["resource_policy"]["max_agents"] = 0
    replies["/auth/deployment/session"] = httpx.Response(200, json=context)
    response = await client.post(
        "/api/auth/login", json={"username": "member", "password": "fixture"}
    )
    assert response.status_code == 200
    assert server.services.agent_repo.list_all() == []


@pytest.mark.parametrize("legacy_case", ["single", "multiple", "renamed", "explicit_nondefault"])
async def test_legacy_desktop_default_migration_is_narrow_and_recovers(
    desktop_login, monkeypatch, legacy_case
):
    client, server, replies = desktop_login
    context = replies["/auth/deployment/session"].json()
    replies["/auth/deployment/session"] = httpx.Response(
        200, json={**context, "default_model": None}
    )
    response = await client.post(
        "/api/auth/login", json={"username": "member", "password": "fixture"}
    )
    assert response.status_code == 200
    uid = response.json()["user"]["id"]
    repo = server.services.agent_repo
    config = {"memory": {"memory_enabled": False}}
    if legacy_case == "explicit_nondefault":
        config["is_default"] = False
    repo.create(
        agent_id="legacy-default",
        user_id=uid,
        name="Custom expert" if legacy_case == "renamed" else "我的智能体",
        default_model=f"yunmell-managed-{uid}/yunmell-default",
        config_json=json.dumps(config),
    )
    repo.set_state("legacy-default", "stopped")
    if legacy_case == "multiple":
        repo.create(agent_id="custom", user_id=uid, name="Custom expert")
        repo.set_state("custom", "stopped")
    registry = server.app_runtime.agent_registry
    original_recover = registry.ensure_default_agent_running
    recovered = asyncio.Event()

    async def recover(user_id):
        try:
            return await original_recover(user_id)
        finally:
            recovered.set()

    monkeypatch.setattr(registry, "ensure_default_agent_running", recover)
    await bridge(server).apply_context(uid, context)
    await asyncio.wait_for(recovered.wait(), timeout=5)
    migrated = repo.get("legacy-default")
    assert json.loads(migrated.config_json)["memory"] == config["memory"]
    if legacy_case == "single":
        assert json.loads(migrated.config_json)["is_default"] is True
        assert registry.runtime_state(migrated.agent_id) == "running"
        # The durable migration must also survive a later runtime restart.
        await registry.shutdown()
        await registry.boot(start_existing=False)
        await registry.restore_default_agents()
        assert registry.runtime_state(migrated.agent_id) == "running"
    else:
        assert not json.loads(migrated.config_json).get("is_default")
        assert registry.runtime_state(migrated.agent_id) == "stopped"
