"""Stable deployment selection without rewriting historical memberships."""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

from octop.infra.db.repos.deployment import DeploymentRepo
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.permissions import ALL_PERMISSION_KEYS, user_has_permission
from octop.infra.users.resource_policy import public_policy_fields

ORG_KEY = "yunmell.deployment.organization"
TEAM_KEY = "yunmell.deployment.team"


def deployment(server: Any) -> tuple[Any, Any]:
    services = server.services
    repo = services.enterprise_repo
    organization = repo.get_organization(services.settings_repo.get(ORG_KEY) or "")
    if organization is None:
        rows = repo.list_organizations()
        rows.sort(
            key=lambda row: (
                -len(repo.list_members(row.organization_id)),
                row.created_at,
                row.organization_id,
            )
        )
        organization = rows[0] if rows else repo.create_organization("云迈智能体")
        services.settings_repo.set(ORG_KEY, organization.organization_id)
    team = next(
        (
            row
            for row in repo.list_teams(organization.organization_id)
            if row.team_id == services.settings_repo.get(TEAM_KEY)
        ),
        None,
    )
    if team is None:
        rows = repo.list_teams(organization.organization_id)
        rows.sort(key=lambda item: (item.created_at, item.team_id))
        team = (
            rows[0] if rows else repo.create_team(organization.organization_id, organization.name)
        )
        services.settings_repo.set(TEAM_KEY, team.team_id)
    return organization, team


def public_info(server: Any) -> dict[str, Any]:
    organization, _ = deployment(server)
    return {
        "organization_id": organization.organization_id,
        "name": organization.name,
        "registration_open": organization.registration_open,
        "review_required": organization.registration_review_required,
    }


def issue_receipt(server: Any, application_id: str) -> str:
    receipt = secrets.token_urlsafe(32)
    DeploymentRepo(server.services.db).add_receipt(
        hashlib.sha256(receipt.encode()).hexdigest(), application_id
    )
    return receipt


def receipt_status(server: Any, receipt: str | None) -> dict[str, Any]:
    if not receipt:
        return {"status": "none"}
    application_id = DeploymentRepo(server.services.db).receipt_application(
        hashlib.sha256(receipt.encode()).hexdigest()
    )
    application = (
        server.services.enterprise_repo.get_registration_application(application_id)
        if application_id
        else None
    )
    if application is None:
        return {"status": "none"}
    organization, _ = deployment(server)
    if application.organization_id != organization.organization_id:
        return {"status": "none"}
    return {
        "status": application.status,
        "application_id": application.application_id,
        "review_note": application.review_note,
        "name": organization.name,
    }


def default_model(server: Any, user: Any) -> tuple[Any, dict[str, Any]]:
    organization, _ = deployment(server)
    provider = server.services.provider_repo.get_by_name(organization.default_provider_name or "")
    model = (
        next(
            (
                item
                for item in provider.get_models()
                if item.get("id") == organization.default_model and item.get("enabled", True)
            ),
            None,
        )
        if provider
        else None
    )
    if (
        provider is None
        or not provider.enabled
        or not provider.api_key
        or not provider.base_url
        or model is None
    ):
        raise OctopError(
            ErrorCode.FORBIDDEN, "企业默认模型未配置或已停用，请联系管理员", status=503
        )
    if not user.is_admin and not server.services.enterprise_repo.model_allowed_for_user(
        user.id, f"{provider.name}/{organization.default_model}"
    ):
        raise OctopError(
            ErrorCode.FORBIDDEN, "企业默认模型不符合历史团队模型限制，请联系管理员修正", status=403
        )
    return provider, model


def session_context(server: Any, user: Any) -> dict[str, Any]:
    organization, team = deployment(server)
    policy = server.services.enterprise_repo.get_control_policy(team.team_id)
    controls = {
        kind: (
            bool(getattr(policy, f"{kind}_enabled"))
            if policy
            else kind in {"filesystem", "network"}
        )
        and server.services.enterprise_repo.control_allowed_for_user(user.id, kind)
        for kind in ["shell", "browser", "desktop", "filesystem", "network"]
    }
    try:
        provider, model = default_model(server, user)
        metadata = {
            "provider": provider.name,
            "model": model["id"],
            "name": model.get("name") or model["id"],
            "input": model.get("input") or ["text"],
            "context_window": model.get("context_window"),
            "max_tokens": model.get("max_tokens"),
        }
        model_error = None
    except OctopError as error:
        metadata, model_error = None, error.message
    # The desktop runtime enforces the same module permission catalog as the
    # control plane.  Admins must retain the full local catalog (channels,
    # skill packages, usage, etc.); regular users receive only explicit,
    # known permissions assigned by the control plane.
    local_permissions = (
        sorted(ALL_PERMISSION_KEYS)
        if user.is_admin
        else sorted({key for key in user.permissions if key in ALL_PERMISSION_KEYS})
    )
    policies = public_policy_fields(server.services.user_policy_repo.list_for_user(user.id))
    allowed = []
    if user_has_permission(user, "providers"):
        from octop.infra.agents.providers.resolved import list_resolved_models

        allowed = [
            item
            for item in list_resolved_models(server.services.provider_repo.list_all())
            if server.services.enterprise_repo.model_allowed_for_user(
                user.id, f"{item['provider_name']}/{item['model']}"
            )
        ]
    return {
        "organization_id": organization.organization_id,
        "name": organization.name,
        "team_id": team.team_id,
        "default_model": metadata,
        "model_error": model_error,
        "controls": controls,
        "resource_policy": {key: policies.get(key) for key in ["token_quota", "max_agents"]},
        "allowed_models": allowed,
        "local_permissions": local_permissions,
    }
