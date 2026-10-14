"""Regression coverage for the ``channels`` module permission.

The channel router and the user-management form both use the same module key,
but a permission displayed in the form is only useful if it reaches the user
row and is enforced for an already-issued JWT.  Keep these checks separate
from the broader channels CRUD suite so failures point at authz propagation.
"""

from __future__ import annotations

from typing import Any

from tests.support.auth import create_agent, create_user, resolve_user_id


async def _user_agent(
    client: Any, admin_auth: dict[str, str], *, permissions: list[str]
) -> tuple[dict[str, str], str, int]:
    username = "channel-perm-user"
    user_auth = await create_user(
        client,
        admin_auth,
        username=username,
        permissions=permissions,
    )
    agent_id = await create_agent(client, user_auth, name=f"{username}-agent")
    user_id = await resolve_user_id(client, admin_auth, username)
    return user_auth, agent_id, user_id


async def test_user_with_channels_permission_can_create_channel(env_with_provider: Any) -> None:
    client, server, admin_auth = env_with_provider
    user_auth, agent_id, user_id = await _user_agent(
        client,
        admin_auth,
        # Mint the JWT before an external DB writer grants the permission.  A
        # stale in-process User cache must not hide the newly granted key.
        permissions=[],
    )
    server.services.user_repo.set_permissions(user_id, ["channels"])

    me = await client.get("/api/auth/me", headers=user_auth)
    assert me.status_code == 200
    assert me.json()["permissions"] == ["channels"]

    listed = await client.get("/api/users", headers=admin_auth)
    row = next(item for item in listed.json() if item["id"] == user_id)
    assert row["permissions"] == ["channels"]

    created = await client.post(
        f"/api/agents/{agent_id}/channels",
        headers=user_auth,
        json={"kind": "feishu", "name": "authorized", "config": {}},
    )
    assert created.status_code == 201, created.text


async def test_user_without_channels_permission_is_forbidden(env_with_provider: Any) -> None:
    client, _server, admin_auth = env_with_provider
    user_auth, agent_id, user_id = await _user_agent(
        client,
        admin_auth,
        permissions=[],
    )

    me = await client.get("/api/auth/me", headers=user_auth)
    assert me.status_code == 200
    assert me.json()["permissions"] == []

    listed = await client.get("/api/users", headers=admin_auth)
    row = next(item for item in listed.json() if item["id"] == user_id)
    assert row["permissions"] == []

    denied = await client.post(
        f"/api/agents/{agent_id}/channels",
        headers=user_auth,
        json={"kind": "feishu", "name": "denied", "config": {}},
    )
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["details"]["permission"] == "channels"


async def test_granting_channels_updates_existing_token(env_with_provider: Any) -> None:
    """A DB permission grant is visible to a token issued before the grant."""
    client, server, admin_auth = env_with_provider
    user_auth, agent_id, user_id = await _user_agent(
        client,
        admin_auth,
        permissions=[],
    )

    server.services.user_repo.set_permissions(user_id, ["channels"])
    allowed = await client.post(
        f"/api/agents/{agent_id}/channels",
        headers=user_auth,
        json={"kind": "feishu", "name": "after-grant", "config": {}},
    )
    assert allowed.status_code == 201, allowed.text


async def test_revoking_channels_blocks_existing_token(env_with_provider: Any) -> None:
    client, server, admin_auth = env_with_provider
    user_auth, agent_id, user_id = await _user_agent(
        client,
        admin_auth,
        permissions=["channels"],
    )

    allowed = await client.post(
        f"/api/agents/{agent_id}/channels",
        headers=user_auth,
        json={"kind": "feishu", "name": "before-revoke", "config": {}},
    )
    assert allowed.status_code == 201, allowed.text

    # Simulate another worker/process writing the control-plane row.  The
    # user's old JWT must be checked against the refreshed DB projection.
    server.services.user_repo.set_permissions(user_id, [])
    revoked = await client.get("/api/users", headers=admin_auth)
    row = next(item for item in revoked.json() if item["id"] == user_id)
    assert row["permissions"] == []

    # Reuse the token issued before the permission change.  Authorization is
    # evaluated from the current user projection, so this must fail immediately.
    stale = await client.post(
        f"/api/agents/{agent_id}/channels",
        headers=user_auth,
        json={"kind": "feishu", "name": "after-revoke", "config": {}},
    )
    assert stale.status_code == 403, stale.text
    assert stale.json()["error"]["details"]["permission"] == "channels"
