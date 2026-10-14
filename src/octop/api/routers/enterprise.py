"""Admin API for the private-deployment enterprise structure."""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from octop.api.deps import get_server, require_permission
from octop.infra.db.repos.enterprise import EnterpriseRepo, TeamRow
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User

router = APIRouter()


class NameBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class MemberBody(BaseModel):
    user_id: int = Field(gt=0)
    team_id: str | None = None
    role: str = Field(default="member", pattern="^(owner|admin|member)$")


class ModelPolicyBody(BaseModel):
    models: list[dict[str, str]] = Field(default_factory=list)


class QuotaBody(BaseModel):
    period: str = Field(default="monthly", pattern="^(monthly|weekly|daily)$")
    token_limit: int | None = Field(default=None, ge=0)
    request_limit: int | None = Field(default=None, ge=0)
    concurrency_limit: int | None = Field(default=None, ge=0)


class ControlPolicyBody(BaseModel):
    shell_enabled: bool = False
    browser_enabled: bool = False
    desktop_enabled: bool = False
    filesystem_enabled: bool = True
    network_enabled: bool = True


class RegistrationReviewBody(BaseModel):
    status: str = Field(pattern="^(approved|rejected|needs_info)$")
    note: str | None = Field(default=None, max_length=1000)


class DefaultModelBody(BaseModel):
    provider_name: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=200)


class RegistrationPolicyBody(BaseModel):
    review_required: bool


def _repo(server: Any) -> EnterpriseRepo:
    return cast(EnterpriseRepo, server.services.enterprise_repo)


def _name(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise OctopError(ErrorCode.FORBIDDEN, "name must not be empty", status=400)
    return cleaned


def _organization_payload(row: Any) -> dict[str, Any]:
    return {
        "organization_id": row.organization_id,
        "name": row.name,
        "login_slug": row.login_slug,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "default_provider_name": row.default_provider_name,
        "default_model": row.default_model,
        "registration_review_required": row.registration_review_required,
    }


@router.get("/organizations", summary="List enterprise organizations")
async def list_organizations(
    _: User = Depends(require_permission("users")),
    server: Any = Depends(get_server),
) -> list[dict[str, Any]]:
    return [_organization_payload(row) for row in _repo(server).list_organizations()]


@router.post("/organizations", status_code=201, summary="Create an enterprise organization")
async def create_organization(
    body: NameBody,
    actor: User = Depends(require_permission("users")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    try:
        row = _repo(server).create_organization(_name(body.name))
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise OctopError(
                ErrorCode.FORBIDDEN, "organization name already exists", status=409
            ) from exc
        raise
    server.services.audit_repo.write(
        actor=actor.username, action="organization.create", target=row.organization_id
    )
    return _organization_payload(row)


@router.get("/organizations/{organization_id}/teams", summary="List organization teams")
async def list_teams(
    organization_id: str,
    _: User = Depends(require_permission("users")),
    server: Any = Depends(get_server),
) -> list[dict[str, Any]]:
    if _repo(server).get_organization(organization_id) is None:
        raise OctopError(ErrorCode.NOT_FOUND, "organization not found")
    return [
        {
            "team_id": row.team_id,
            "organization_id": row.organization_id,
            "name": row.name,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in _repo(server).list_teams(organization_id)
    ]


@router.post(
    "/organizations/{organization_id}/teams", status_code=201, summary="Create an organization team"
)
async def create_team(
    organization_id: str,
    body: NameBody,
    actor: User = Depends(require_permission("users")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    repo = _repo(server)
    if repo.get_organization(organization_id) is None:
        raise OctopError(ErrorCode.NOT_FOUND, "organization not found")
    try:
        row = repo.create_team(organization_id, _name(body.name))
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise OctopError(ErrorCode.FORBIDDEN, "team name already exists", status=409) from exc
        raise
    server.services.audit_repo.write(actor=actor.username, action="team.create", target=row.team_id)
    return {
        "team_id": row.team_id,
        "organization_id": row.organization_id,
        "name": row.name,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/organizations/{organization_id}/members", summary="List organization members")
async def list_members(
    organization_id: str,
    _: User = Depends(require_permission("users")),
    server: Any = Depends(get_server),
) -> list[dict[str, Any]]:
    if _repo(server).get_organization(organization_id) is None:
        raise OctopError(ErrorCode.NOT_FOUND, "organization not found")
    return [
        {
            "id": row.id,
            "organization_id": row.organization_id,
            "user_id": row.user_id,
            "team_id": row.team_id,
            "role": row.role,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in _repo(server).list_members(organization_id)
    ]


@router.put(
    "/organizations/{organization_id}/members", summary="Add or update an organization member"
)
async def upsert_member(
    organization_id: str,
    body: MemberBody,
    actor: User = Depends(require_permission("users")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    repo = _repo(server)
    if repo.get_organization(organization_id) is None:
        raise OctopError(ErrorCode.NOT_FOUND, "organization not found")
    if server.services.user_repo.get(body.user_id) is None:
        raise OctopError(ErrorCode.NOT_FOUND, "user not found")
    if body.team_id is not None and not any(
        row.team_id == body.team_id for row in repo.list_teams(organization_id)
    ):
        raise OctopError(ErrorCode.NOT_FOUND, "team not found")
    row = repo.upsert_member(organization_id, body.user_id, body.team_id, body.role)
    server.services.audit_repo.write(
        actor=actor.username,
        action="organization.member.upsert",
        target=f"{organization_id}:{body.user_id}",
    )
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "user_id": row.user_id,
        "team_id": row.team_id,
        "role": row.role,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _team_or_404(server: Any, organization_id: str, team_id: str) -> TeamRow:
    repo = _repo(server)
    if repo.get_organization(organization_id) is None:
        raise OctopError(ErrorCode.NOT_FOUND, "organization not found")
    team = next(
        (item for item in repo.list_teams(organization_id) if item.team_id == team_id), None
    )
    if team is None:
        raise OctopError(ErrorCode.NOT_FOUND, "team not found")
    return team


@router.get(
    "/organizations/{organization_id}/teams/{team_id}/models", summary="List team model allowlist"
)
async def list_team_models(
    organization_id: str,
    team_id: str,
    _: User = Depends(require_permission("users")),
    server: Any = Depends(get_server),
) -> list[dict[str, str]]:
    _team_or_404(server, organization_id, team_id)
    return _repo(server).list_allowed_models(team_id)


@router.put(
    "/organizations/{organization_id}/teams/{team_id}/models",
    summary="Replace team model allowlist",
)
async def replace_team_models(
    organization_id: str,
    team_id: str,
    body: ModelPolicyBody,
    actor: User = Depends(require_permission("users")),
    server: Any = Depends(get_server),
) -> list[dict[str, str]]:
    _team_or_404(server, organization_id, team_id)
    models: list[tuple[str, str]] = []
    for item in body.models:
        provider = (item.get("provider_name") or "").strip()
        model = (item.get("model") or "").strip()
        if provider and model and (provider, model) not in models:
            models.append((provider, model))
    _repo(server).replace_allowed_models(team_id, models)
    server.services.audit_repo.write(
        actor=actor.username, action="team.models.replace", target=team_id
    )
    return _repo(server).list_allowed_models(team_id)


@router.get("/organizations/{organization_id}/teams/{team_id}/quota", summary="Get team quota")
async def get_team_quota(
    organization_id: str,
    team_id: str,
    _: User = Depends(require_permission("users")),
    server: Any = Depends(get_server),
) -> dict[str, Any] | None:
    _team_or_404(server, organization_id, team_id)
    row = _repo(server).get_quota(team_id)
    if row is None:
        return None
    return {
        "team_id": row.team_id,
        "period": row.period,
        "token_limit": row.token_limit,
        "request_limit": row.request_limit,
        "concurrency_limit": row.concurrency_limit,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.put("/organizations/{organization_id}/teams/{team_id}/quota", summary="Set team quota")
async def set_team_quota(
    organization_id: str,
    team_id: str,
    body: QuotaBody,
    actor: User = Depends(require_permission("users")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    _team_or_404(server, organization_id, team_id)
    row = _repo(server).upsert_quota(
        team_id,
        period=body.period,
        token_limit=body.token_limit,
        request_limit=body.request_limit,
        concurrency_limit=body.concurrency_limit,
    )
    server.services.audit_repo.write(
        actor=actor.username, action="team.quota.update", target=team_id
    )
    return {
        "team_id": row.team_id,
        "period": row.period,
        "token_limit": row.token_limit,
        "request_limit": row.request_limit,
        "concurrency_limit": row.concurrency_limit,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _control_payload(row: Any) -> dict[str, Any]:
    return {
        "team_id": row.team_id,
        "shell_enabled": row.shell_enabled,
        "browser_enabled": row.browser_enabled,
        "desktop_enabled": row.desktop_enabled,
        "filesystem_enabled": row.filesystem_enabled,
        "network_enabled": row.network_enabled,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get(
    "/organizations/{organization_id}/teams/{team_id}/controls",
    summary="Get team local control policy",
)
async def get_team_controls(
    organization_id: str,
    team_id: str,
    _: User = Depends(require_permission("users")),
    server: Any = Depends(get_server),
) -> dict[str, Any] | None:
    _team_or_404(server, organization_id, team_id)
    row = _repo(server).get_control_policy(team_id)
    return _control_payload(row) if row else None


@router.put(
    "/organizations/{organization_id}/teams/{team_id}/controls",
    summary="Set team local control policy",
)
async def set_team_controls(
    organization_id: str,
    team_id: str,
    body: ControlPolicyBody,
    actor: User = Depends(require_permission("users")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    _team_or_404(server, organization_id, team_id)
    row = _repo(server).upsert_control_policy(team_id, **body.model_dump())
    server.services.audit_repo.write(
        actor=actor.username, action="team.controls.update", target=team_id
    )
    return _control_payload(row)


@router.get(
    "/organizations/{organization_id}/registration-applications",
    summary="List enterprise registration applications",
)
async def list_registration_applications(
    organization_id: str,
    status: str | None = None,
    _: User = Depends(require_permission("users")),
    server: Any = Depends(get_server),
) -> list[dict[str, Any]]:
    repo = _repo(server)
    if repo.get_organization(organization_id) is None:
        raise OctopError(ErrorCode.NOT_FOUND, "organization not found")
    return [
        {
            "application_id": row.application_id,
            "organization_id": row.organization_id,
            "user_id": row.user_id,
            "status": row.status,
            "submitted_at": row.submitted_at,
            "reviewed_at": row.reviewed_at,
            "reviewed_by": row.reviewed_by,
            "review_note": row.review_note,
            "supplement": row.supplement,
        }
        for row in repo.list_registration_applications(organization_id, status=status)
    ]


@router.post(
    "/organizations/{organization_id}/registration-applications/{application_id}/review",
    summary="Review an enterprise registration",
)
async def review_registration_application(
    organization_id: str,
    application_id: str,
    body: RegistrationReviewBody,
    actor: User = Depends(require_permission("users")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    repo = _repo(server)
    current = repo.get_registration_application(application_id)
    if current is None or current.organization_id != organization_id:
        raise OctopError(ErrorCode.NOT_FOUND, "registration application not found")
    try:
        row = repo.review_registration_application(
            application_id,
            status=body.status,
            reviewer_id=actor.id,
            note=body.note,
        )
    except ValueError as exc:
        raise OctopError(ErrorCode.SLASH_BAD_ARGS, str(exc), status=400) from exc
    if body.status == "approved":
        existing = next(
            (item for item in repo.list_members(organization_id) if item.user_id == row.user_id),
            None,
        )
        team_id = existing.team_id if existing else None
        if (
            team_id is None
            and server.services.settings_repo.get("yunmell.deployment.organization")
            == organization_id
        ):
            team_id = server.services.settings_repo.get("yunmell.deployment.team")
        repo.upsert_member(
            organization_id, row.user_id, team_id, existing.role if existing else "member"
        )
    server.services.audit_repo.write(
        actor=actor.username,
        action=f"enterprise.registration.{body.status}",
        target=application_id,
        payload=f"organization_id={organization_id};user_id={row.user_id}",
    )
    return {
        "application_id": row.application_id,
        "organization_id": row.organization_id,
        "user_id": row.user_id,
        "status": row.status,
        "reviewed_at": row.reviewed_at,
        "reviewed_by": row.reviewed_by,
        "review_note": row.review_note,
    }


@router.put(
    "/organizations/{organization_id}/default-model", summary="Set enterprise default model"
)
async def set_enterprise_default_model(
    organization_id: str,
    body: DefaultModelBody,
    actor: User = Depends(require_permission("providers")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    repo = _repo(server)
    if repo.get_organization(organization_id) is None:
        raise OctopError(ErrorCode.NOT_FOUND, "organization not found")
    provider = server.services.provider_repo.get_by_name(body.provider_name.strip())
    if provider is None or not provider.enabled:
        raise OctopError(ErrorCode.NOT_FOUND, "provider not found or disabled")
    model = body.model.strip()
    if not any(str(item.get("id")) == model for item in provider.get_models()):
        raise OctopError(
            ErrorCode.SLASH_BAD_ARGS, "model is not configured on provider", status=400
        )
    row = repo.set_default_model(organization_id, provider.name, model)
    server.services.audit_repo.write(
        actor=actor.username,
        action="organization.default_model.update",
        target=organization_id,
        payload=f"provider={provider.name};model={model}",
    )
    return _organization_payload(row)


@router.put(
    "/organizations/{organization_id}/registration-policy",
    summary="Set enterprise registration review policy",
)
async def set_registration_policy(
    organization_id: str,
    body: RegistrationPolicyBody,
    actor: User = Depends(require_permission("users")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    repo = _repo(server)
    if repo.get_organization(organization_id) is None:
        raise OctopError(ErrorCode.NOT_FOUND, "organization not found")
    row = repo.set_registration_review_required(organization_id, body.review_required)
    server.services.audit_repo.write(
        actor=actor.username,
        action="organization.registration_policy.update",
        target=organization_id,
        payload=f"review_required={body.review_required}",
    )
    return _organization_payload(row)
