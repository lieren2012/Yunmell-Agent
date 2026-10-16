"""HTTP ACL for knowledge-base instance settings vs page CRUD."""

from __future__ import annotations

import time
from typing import Any

from tests.support.auth import create_provider, create_user


async def test_capability_reports_unconfigured_embedding_without_waiting(env: Any) -> None:
    client, _server, admin_auth = env
    started = time.perf_counter()
    response = await client.get("/api/knowledge-bases/capability", headers=admin_auth)
    elapsed = time.perf_counter() - started
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["feature_enabled"] is False
    assert body["usable"] is False
    assert body["checks"]["model_selected"] is False
    assert body["prerequisites_ok"] is False
    # Capability is a local status read; an unconfigured vector model must not
    # leave the page waiting on a provider/network probe.
    assert elapsed < 2.0, f"capability status took {elapsed:.3f}s"


async def test_feature_toggle_requires_knowledge_settings(env: Any) -> None:
    client, _server, admin_auth = env
    page_auth = await create_user(client, admin_auth, username="kb_page_user")
    denied = await client.put(
        "/api/knowledge-bases/feature",
        headers=page_auth,
        json={"enabled": False},
    )
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "FORBIDDEN"

    settings_auth = await create_user(
        client,
        admin_auth,
        username="kb_settings_user",
        permissions=["knowledge_bases", "knowledge_settings"],
    )
    allowed = await client.put(
        "/api/knowledge-bases/feature",
        headers=settings_auth,
        json={"enabled": False},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["feature_enabled"] is False


async def test_personal_base_can_be_created_before_embedding_setup(env: Any) -> None:
    client, _server, admin_auth = env
    member_auth = await create_user(
        client,
        admin_auth,
        username="kb_personal_unconfigured",
        permissions=["knowledge_bases"],
    )

    created = await client.post(
        "/api/knowledge-bases",
        headers=member_auth,
        json={"name": "我的本地资料"},
    )

    assert created.status_code == 201, created.text
    assert created.json()["name"] == "我的本地资料"
    listed = await client.get("/api/knowledge-bases", headers=member_auth)
    assert listed.status_code == 200, listed.text
    assert [row["name"] for row in listed.json()] == ["我的本地资料"]


async def test_embedding_options_expose_remote_only_with_knowledge_settings(env: Any) -> None:
    client, _server, admin_auth = env
    provider = await create_provider(
        client,
        admin_auth,
        name="enterprise-embedding",
        models=[{"id": "text-embedding-3-small", "name": "Remote embedding", "embedding": True}],
    )
    page_auth = await create_user(
        client,
        admin_auth,
        username="kb_options_user",
        permissions=["knowledge_bases"],
    )
    personal = await client.get("/api/knowledge-bases/embedding-options", headers=page_auth)
    assert personal.status_code == 200, personal.text
    assert personal.json()["onnx"]
    assert personal.json()["remote"] == []
    assert provider["name"] not in personal.text
    assert "text-embedding-3-small" not in personal.text

    settings_auth = await create_user(
        client,
        admin_auth,
        username="kb_options_admin",
        permissions=["knowledge_settings"],
    )
    allowed = await client.get("/api/knowledge-bases/embedding-options", headers=settings_auth)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["onnx"] == personal.json()["onnx"]
    assert allowed.json()["remote"] == [
        {
            "provider_id": str(provider["id"]),
            "provider_name": provider["name"],
            "models": [{"id": "text-embedding-3-small", "name": "Remote embedding"}],
        }
    ]


async def test_enterprise_knowledge_projection_and_admin_crud_preserve_personal_scope(
    env: Any, monkeypatch: Any
) -> None:
    client, server, admin_auth = env
    member_auth = await create_user(
        client,
        admin_auth,
        username="enterprise-kb-reader",
        permissions=["knowledge_bases"],
    )
    # The CRUD contract is independent of vector-runtime installation.  The
    # indexing path still enforces the real gate when documents are uploaded.
    monkeypatch.setattr(
        "octop.infra.knowledge.service.assert_knowledge_usable", lambda *_args, **_kwargs: None
    )
    created = await client.post(
        "/api/admin/enterprise/knowledge-bases",
        headers=admin_auth,
        json={"name": "企业手册", "description": "共享资料", "max_documents": 12},
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["scope"] == "enterprise"
    assert payload["read_only"] is True
    kb_id = payload["knowledge_base_id"]

    projection = await client.get("/api/enterprise/knowledge-bases", headers=member_auth)
    assert projection.status_code == 200, projection.text
    assert [row["knowledge_base_id"] for row in projection.json()] == [kb_id]
    detail = await client.get(f"/api/enterprise/knowledge-bases/{kb_id}", headers=member_auth)
    assert detail.status_code == 200
    assert detail.json()["max_documents"] == 12
    documents = await client.get(
        f"/api/enterprise/knowledge-bases/{kb_id}/documents", headers=member_auth
    )
    assert documents.status_code == 200, documents.text
    assert documents.json() == []

    updated = await client.patch(
        f"/api/admin/enterprise/knowledge-bases/{kb_id}",
        headers=admin_auth,
        json={"name": "企业手册 v2", "description": "更新", "max_documents": 24},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "企业手册 v2"

    denied = await client.delete(
        f"/api/admin/enterprise/knowledge-bases/{kb_id}", headers=member_auth
    )
    assert denied.status_code == 403
    assert (
        await client.delete(f"/api/admin/enterprise/knowledge-bases/{kb_id}", headers=admin_auth)
    ).status_code == 204
    missing = await client.get(f"/api/enterprise/knowledge-bases/{kb_id}", headers=member_auth)
    assert missing.status_code == 404
    # Existing personal rows are never included in the enterprise projection.
    personal = server.services.knowledge_repo.create_base(owner_user_id=1, name="个人库")
    assert personal.shared is False
    projection_after = await client.get("/api/enterprise/knowledge-bases", headers=member_auth)
    assert all(row["knowledge_base_id"] != personal.id for row in projection_after.json())
