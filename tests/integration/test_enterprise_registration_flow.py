from __future__ import annotations


async def _create_enterprise(client, auth, name: str) -> tuple[str, str]:
    response = await client.post(
        "/api/admin/enterprise/organizations",
        headers=auth,
        json={"name": name},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    return payload["organization_id"], payload["login_slug"]


async def _register(client, slug: str, username: str) -> str:
    response = await client.post(
        f"/api/auth/enterprises/{slug}/register",
        json={
            "username": username,
            "password": "TestPass12",
            "display_name": username,
            "email": f"{username}@example.com",
            "email_code": "123456",
        },
    )
    assert response.status_code == 202, response.text
    return response.json()["application_id"]


async def _enterprise_login(client, slug: str, username: str):
    return await client.post(
        f"/api/auth/enterprises/{slug}/login",
        json={"username": username, "password": "TestPass12"},
    )


async def test_pending_user_cannot_login_until_approved(env):
    client, _, admin_auth = env
    _, slug = await _create_enterprise(client, admin_auth, "审批企业")
    application_id = await _register(client, slug, "pending-user")

    pending = await _enterprise_login(client, slug, "pending-user")
    assert pending.status_code == 401

    applications = await client.get(
        "/api/admin/enterprise/organizations",
        headers=admin_auth,
    )
    organization_id = next(
        row["organization_id"] for row in applications.json() if row["login_slug"] == slug
    )
    reviewed = await client.post(
        f"/api/admin/enterprise/organizations/{organization_id}/registration-applications/{application_id}/review",
        headers=admin_auth,
        json={"status": "approved", "note": "资料齐全"},
    )
    assert reviewed.status_code == 200, reviewed.text

    approved = await _enterprise_login(client, slug, "pending-user")
    assert approved.status_code == 200, approved.text


async def test_rejected_user_cannot_login(env):
    client, _, admin_auth = env
    organization_id, slug = await _create_enterprise(client, admin_auth, "驳回企业")
    application_id = await _register(client, slug, "rejected-user")
    reviewed = await client.post(
        f"/api/admin/enterprise/organizations/{organization_id}/registration-applications/{application_id}/review",
        headers=admin_auth,
        json={"status": "rejected", "note": "资料不足"},
    )
    assert reviewed.status_code == 200
    rejected = await _enterprise_login(client, slug, "rejected-user")
    assert rejected.status_code == 401


async def test_enterprise_user_cannot_login_through_other_enterprise(env):
    client, _, admin_auth = env
    org_a, slug_a = await _create_enterprise(client, admin_auth, "企业 A")
    _, slug_b = await _create_enterprise(client, admin_auth, "企业 B")
    application_id = await _register(client, slug_a, "isolated-user")
    reviewed = await client.post(
        f"/api/admin/enterprise/organizations/{org_a}/registration-applications/{application_id}/review",
        headers=admin_auth,
        json={"status": "approved"},
    )
    assert reviewed.status_code == 200
    assert (await _enterprise_login(client, slug_a, "isolated-user")).status_code == 200
    assert (await _enterprise_login(client, slug_b, "isolated-user")).status_code == 401


async def test_enterprise_default_model_is_configurable(env):
    client, _, admin_auth = env
    organization_id, _ = await _create_enterprise(client, admin_auth, "默认模型企业")
    provider = await client.post(
        "/api/admin/providers",
        headers=admin_auth,
        json={
            "name": "enterprise-openai",
            "kind": "openai",
            "api_key": "sk-test",
            "models": [{"id": "gpt-5", "name": "GPT-5", "enabled": True}],
        },
    )
    assert provider.status_code == 201, provider.text
    organization = await client.get("/api/admin/enterprise/organizations", headers=admin_auth)
    slug = next(
        row["login_slug"]
        for row in organization.json()
        if row["organization_id"] == organization_id
    )
    saved = await client.put(
        f"/api/admin/enterprise/organizations/{organization_id}/default-model",
        headers=admin_auth,
        json={"provider_name": "enterprise-openai", "model": "gpt-5"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["default_provider_name"] == "enterprise-openai"
    assert saved.json()["default_model"] == "gpt-5"
    assert (await client.get(f"/api/auth/enterprises/{slug}")).status_code == 200


async def test_enterprise_registration_can_be_auto_approved(env):
    client, _, admin_auth = env
    organization_id, slug = await _create_enterprise(client, admin_auth, "免审企业")
    policy = await client.put(
        f"/api/admin/enterprise/organizations/{organization_id}/registration-policy",
        headers=admin_auth,
        json={"review_required": False},
    )
    assert policy.status_code == 200
    application_id = await _register(client, slug, "auto-approved-user")
    assert application_id
    login = await _enterprise_login(client, slug, "auto-approved-user")
    assert login.status_code == 200, login.text
