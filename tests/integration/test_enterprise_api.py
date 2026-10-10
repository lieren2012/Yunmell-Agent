from __future__ import annotations


async def test_enterprise_organization_team_policies_round_trip(env):
    client, _, admin_auth = env
    created_org = await client.post(
        "/api/admin/enterprise/organizations",
        headers=admin_auth,
        json={"name": "云迈集成测试企业"},
    )
    assert created_org.status_code == 201
    organization_id = created_org.json()["organization_id"]

    created_team = await client.post(
        f"/api/admin/enterprise/organizations/{organization_id}/teams",
        headers=admin_auth,
        json={"name": "平台团队"},
    )
    assert created_team.status_code == 201
    team_id = created_team.json()["team_id"]

    created_user = await client.post(
        "/api/users",
        headers=admin_auth,
        json={"username": "enterprise-member", "password": "TestPass12", "role": "user"},
    )
    assert created_user.status_code == 201
    user_id = created_user.json()["id"]

    member = await client.put(
        f"/api/admin/enterprise/organizations/{organization_id}/members",
        headers=admin_auth,
        json={"user_id": user_id, "team_id": team_id, "role": "member"},
    )
    assert member.status_code == 200

    models = await client.put(
        f"/api/admin/enterprise/organizations/{organization_id}/teams/{team_id}/models",
        headers=admin_auth,
        json={"models": [{"provider_name": "openai", "model": "gpt-5"}]},
    )
    assert models.status_code == 200
    assert models.json() == [{"provider_name": "openai", "model": "gpt-5"}]

    quota = await client.put(
        f"/api/admin/enterprise/organizations/{organization_id}/teams/{team_id}/quota",
        headers=admin_auth,
        json={
            "period": "monthly",
            "token_limit": 100000,
            "request_limit": 1000,
            "concurrency_limit": 2,
        },
    )
    assert quota.status_code == 200
    assert quota.json()["concurrency_limit"] == 2

    controls = await client.put(
        f"/api/admin/enterprise/organizations/{organization_id}/teams/{team_id}/controls",
        headers=admin_auth,
        json={"shell_enabled": False, "browser_enabled": True},
    )
    assert controls.status_code == 200
    assert controls.json()["browser_enabled"] is True
    assert controls.json()["shell_enabled"] is False

    listed = await client.get(
        f"/api/admin/enterprise/organizations/{organization_id}/members",
        headers=admin_auth,
    )
    assert listed.status_code == 200
    assert listed.json()[0]["user_id"] == user_id


async def test_enterprise_management_requires_users_permission(env):
    client, _, admin_auth = env
    created = await client.post(
        "/api/users",
        headers=admin_auth,
        json={"username": "enterprise-reader", "password": "TestPass12", "role": "user"},
    )
    assert created.status_code == 201
    login = await client.post(
        "/api/auth/login",
        json={"username": "enterprise-reader", "password": "TestPass12"},
    )
    assert login.status_code == 200
    member_auth = {"Authorization": f"Bearer {login.json()['access_token']}"}

    denied = await client.get(
        "/api/admin/enterprise/organizations",
        headers=member_auth,
    )
    assert denied.status_code == 403


async def test_deleting_user_removes_enterprise_membership(env):
    client, _, admin_auth = env
    organization = await client.post(
        "/api/admin/enterprise/organizations",
        headers=admin_auth,
        json={"name": "级联删除测试企业"},
    )
    organization_id = organization.json()["organization_id"]
    team = await client.post(
        f"/api/admin/enterprise/organizations/{organization_id}/teams",
        headers=admin_auth,
        json={"name": "删除测试团队"},
    )
    team_id = team.json()["team_id"]
    user = await client.post(
        "/api/users",
        headers=admin_auth,
        json={"username": "enterprise-delete-me", "password": "TestPass12", "role": "user"},
    )
    user_id = user.json()["id"]
    await client.put(
        f"/api/admin/enterprise/organizations/{organization_id}/members",
        headers=admin_auth,
        json={"user_id": user_id, "team_id": team_id, "role": "member"},
    )

    deleted = await client.delete(f"/api/users/{user_id}", headers=admin_auth)
    assert deleted.status_code in (200, 204)
    members = await client.get(
        f"/api/admin/enterprise/organizations/{organization_id}/members",
        headers=admin_auth,
    )
    assert members.status_code == 200
    assert all(row["user_id"] != user_id for row in members.json())
