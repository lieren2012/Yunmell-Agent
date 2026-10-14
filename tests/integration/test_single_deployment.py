from __future__ import annotations

from octop.infra.deployment.desktop import bridge
from tests.support.app import octop_client


async def register(client, username):
    return await client.post(
        "/api/auth/deployment/register", json={"username": username, "password": "UiTestPass79"}
    )


async def test_registration_review_cookie_and_existing_user_library(env):
    client, server, admin = env
    info = (await client.get("/api/auth/deployment")).json()
    response = await register(client, "review-member")
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "pending"
    assert "HttpOnly" in response.headers["set-cookie"]
    assert (await client.get("/api/auth/deployment/registration/status")).json()[
        "status"
    ] == "pending"
    duplicate = await register(client, "review-member")
    assert duplicate.status_code == 409
    pending = await client.post(
        "/api/auth/deployment/login", json={"username": "review-member", "password": "UiTestPass79"}
    )
    assert pending.status_code == 401
    assert pending.json()["error"]["details"]["registration_status"] == "pending"
    application = response.json()["application_id"]
    approved = await client.post(
        f"/api/admin/enterprise/organizations/{info['organization_id']}/registration-applications/{application}/review",
        headers=admin,
        json={"status": "approved"},
    )
    assert approved.status_code == 200
    login = await client.post(
        "/api/auth/deployment/login", json={"username": "review-member", "password": "UiTestPass79"}
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    context = await client.get("/api/auth/deployment/session", headers=headers)
    assert context.status_code == 200, context.text
    assert "channels" in context.json()["local_permissions"]
    assert "skill_packages" in context.json()["local_permissions"]
    assert (await client.get("/api/admin/providers", headers=headers)).status_code == 403
    assert (
        await client.get("/api/admin/enterprise/deployment", headers=headers)
    ).status_code == 403
    uid = server.services.user_repo.get_by_username("review-member").id
    membership = server.services.enterprise_repo.list_memberships_for_user(uid)[0]
    assert membership.team_id is not None
    rows = (await client.get("/api/users?include_disabled=true", headers=admin)).json()
    assert any(row["id"] == uid for row in rows)


async def test_registration_open_and_auto_approval(env):
    client, server, admin = env
    info = (await client.get("/api/auth/deployment")).json()
    settings = {"name": "测试企业名称", "registration_open": False, "review_required": False}
    assert (
        await client.put("/api/admin/enterprise/deployment", headers=admin, json=settings)
    ).status_code == 200
    assert (await register(client, "closed-member")).status_code == 403
    assert server.services.user_repo.get_by_username("closed-member") is None
    settings["registration_open"] = True
    await client.put("/api/admin/enterprise/deployment", headers=admin, json=settings)
    response = await register(client, "auto-member")
    assert response.json()["status"] == "approved"
    assert response.json()["name"] == "测试企业名称"
    assert (await client.get("/api/auth/deployment")).json()["organization_id"] == info[
        "organization_id"
    ]
    assert (
        await client.post(
            "/api/auth/deployment/login",
            json={"username": "auto-member", "password": "UiTestPass79"},
        )
    ).status_code == 200


async def test_provider_keys_never_returned_and_default_is_not_personal(env):
    client, server, admin = env
    await client.post(
        "/api/admin/providers",
        headers=admin,
        json={
            "name": "managed",
            "kind": "openai",
            "base_url": "http://provider.example/v1",
            "api_key": "fixture-private-key",
            "models": [{"id": "6.1S", "enabled": True}],
        },
    )
    providers = await client.get("/api/admin/providers", headers=admin)
    assert "fixture-private-key" not in providers.text
    assert providers.json()[0]["api_key_configured"] is True
    server.services.settings_repo.set_active_model("managed", "6.1S")
    await client.get("/api/auth/deployment")
    context = await client.get("/api/auth/deployment/session", headers=admin)
    assert context.json()["default_model"] is None
    info = (await client.get("/api/auth/deployment")).json()
    await client.put(
        f"/api/admin/enterprise/organizations/{info['organization_id']}/default-model",
        headers=admin,
        json={"provider_name": "managed", "model": "6.1S"},
    )
    context = await client.get("/api/auth/deployment/session", headers=admin)
    assert context.json()["default_model"]["model"] == "6.1S"
    assert "fixture-private-key" not in context.text


async def test_desktop_remote_identity_local_runtime_and_authority_binding(
    env, tmp_path, monkeypatch
):
    remote_client, remote_server, admin = env
    remote_agents_before = len(remote_server.services.agent_repo.list_all())
    info = (await remote_client.get("/api/auth/deployment")).json()
    await remote_client.put(
        "/api/admin/enterprise/deployment",
        headers=admin,
        json={"name": "管理服务企业", "registration_open": True, "review_required": False},
    )
    await remote_client.post(
        "/api/admin/providers",
        headers=admin,
        json={
            "name": "managed",
            "kind": "openai",
            "base_url": "http://provider.example/v1",
            "api_key": "fixture-private-key",
            "models": [{"id": "6.1S", "enabled": True}],
        },
    )
    await remote_client.put(
        f"/api/admin/enterprise/organizations/{info['organization_id']}/default-model",
        headers=admin,
        json={"provider_name": "managed", "model": "6.1S"},
    )
    assert (await register(remote_client, "desktop-member")).status_code == 202
    monkeypatch.setenv("OCTOP_DESKTOP_CLIENT", "1")
    monkeypatch.setenv("OCTOP_CONTROL_PLANE_URL", "http://management.example")
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path / "desktop"))
    async with octop_client(tmp_path / "desktop") as (local_client, local_server):
        identity = bridge(local_server)

        async def remote(method, path, *, token=None, content=None, headers=None, authority=None):
            outgoing = dict(headers or {})
            if token:
                outgoing["Authorization"] = "Bearer " + token
            return await remote_client.request(
                method, "/api" + path, content=content, headers=outgoing
            )

        monkeypatch.setattr(identity, "remote", remote)
        response = await local_client.post(
            "/api/auth/login", json={"username": "desktop-member", "password": "UiTestPass79"}
        )
        assert response.status_code == 200, response.text
        user = response.json()["user"]
        assert user["deployment"]["name"] == "管理服务企业"
        uid = user["id"]
        assert local_server.services.user_repo.get(uid).password_hash is None
        remote_session = identity.token_for(uid)
        assert remote_session.encode() not in local_server.services.secret_repo.get(
            f"yunmell.remote-session:{uid}"
        )
        headers = {"Authorization": "Bearer " + response.json()["access_token"]}
        remote_calls: list[tuple[str, str]] = []

        async def unavailable_remote(method, path, **kwargs):
            remote_calls.append((method, path))
            raise AssertionError("local runtime request attempted control-plane access")

        monkeypatch.setattr(identity, "remote", unavailable_remote)
        local_me = await local_client.get("/api/auth/me", headers=headers)
        assert local_me.status_code == 200, local_me.text
        local_agents = await local_client.get("/api/agents", headers=headers)
        assert local_agents.status_code == 200, local_agents.text
        assert remote_calls == []
        models = await local_client.get("/api/providers/resolved", headers=headers)
        assert models.status_code == 200
        assert models.json()[0]["model"] == "yunmell-default"
        monkeypatch.setattr(identity, "remote", remote)
        enterprise_projection = await local_client.get(
            "/api/enterprise/knowledge-bases", headers=headers
        )
        assert enterprise_projection.status_code == 200, enterprise_projection.text
        assert (
            await local_client.get(
                "/api/enterprise/knowledge-bases/unknown/documents", headers=headers
            )
        ).status_code == 404
        assert (await local_client.get("/api/admin/providers", headers=headers)).status_code == 403
        created = await local_client.post(
            "/api/agents", headers=headers, json={"name": "普通用户创建"}
        )
        assert created.status_code == 201, created.text
        assert "yunmell-default" in created.json()["default_model"]
        assert len(local_server.services.agent_repo.list_by_user(uid)) == 2
        assert len(remote_server.services.agent_repo.list_all()) == remote_agents_before
        monkeypatch.setenv("OCTOP_CONTROL_PLANE_URL", "http://other.example")
        assert (await local_client.get("/api/auth/me", headers=headers)).status_code == 401


async def test_desktop_admin_management_requests_use_remote_admin_identity(
    env, tmp_path, monkeypatch
):
    """A desktop admin must retain remote admin access to management APIs.

    The desktop process stores a passwordless local projection for runtime
    isolation.  Management requests are forwarded with the encrypted remote
    session token, so local projection permissions must not turn the remote
    administrator into a 403 response.
    """
    remote_client, _remote_server, admin = env
    monkeypatch.setenv("OCTOP_DESKTOP_CLIENT", "1")
    monkeypatch.setenv("OCTOP_CONTROL_PLANE_URL", "http://management.example")
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path / "desktop-admin"))
    async with octop_client(tmp_path / "desktop-admin") as (local_client, local_server):
        identity = bridge(local_server)

        async def remote(method, path, *, token=None, content=None, headers=None, authority=None):
            outgoing = dict(headers or {})
            if token:
                outgoing["Authorization"] = "Bearer " + token
            return await remote_client.request(
                method, "/api" + path, content=content, headers=outgoing
            )

        monkeypatch.setattr(identity, "remote", remote)
        login = await local_client.post(
            "/api/auth/login", json={"username": "admin", "password": "TestPass12"}
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}

        profile = await local_client.get("/api/auth/me", headers=headers)
        assert profile.status_code == 200, profile.text
        assert profile.json()["username"] == "admin"
        assert profile.json()["role"] == "admin"
        local_row = local_server.services.user_repo.get(login.json()["user"]["id"])
        assert local_row is not None and local_row.role == "admin"
        context = await local_client.get("/api/auth/deployment/session", headers=headers)
        assert context.status_code == 200, context.text
        assert "channels" in context.json()["local_permissions"]
        assert "skill_packages" in context.json()["local_permissions"]

        listed = await local_client.get("/api/users", headers=headers)
        assert listed.status_code == 200, listed.text
        assert any(row["username"] == "admin" for row in listed.json())

        providers = await local_client.get("/api/admin/providers", headers=headers)
        assert providers.status_code == 200, providers.text


async def test_desktop_logout_revokes_local_projection(env, tmp_path, monkeypatch):
    remote_client, _remote_server, admin = env
    await remote_client.put(
        "/api/admin/enterprise/deployment",
        headers=admin,
        json={"name": "注销验收企业", "registration_open": True, "review_required": False},
    )
    assert (await register(remote_client, "logout-member")).status_code == 202
    monkeypatch.setenv("OCTOP_DESKTOP_CLIENT", "1")
    monkeypatch.setenv("OCTOP_CONTROL_PLANE_URL", "http://management.example")
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path / "desktop"))
    async with octop_client(tmp_path / "desktop") as (local_client, local_server):
        identity = bridge(local_server)

        async def remote(method, path, *, token=None, content=None, headers=None, authority=None):
            outgoing = dict(headers or {})
            if token:
                outgoing["Authorization"] = "Bearer " + token
            return await remote_client.request(
                method, "/api" + path, content=content, headers=outgoing
            )

        monkeypatch.setattr(identity, "remote", remote)
        login = await local_client.post(
            "/api/auth/login", json={"username": "logout-member", "password": "UiTestPass79"}
        )
        assert login.status_code == 200, login.text
        uid = login.json()["user"]["id"]
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        logged_out = await local_client.post("/api/auth/logout", headers=headers)
        assert logged_out.status_code == 204
        assert local_server.services.secret_repo.get(f"yunmell.remote-session:{uid}") is None
        assert (await local_client.get("/api/auth/me", headers=headers)).status_code == 401
