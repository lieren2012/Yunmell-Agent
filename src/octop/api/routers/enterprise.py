"""Admin API for the private-deployment enterprise structure."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from octop.api.deps import get_server, require_permission
from octop.infra.db.repos.enterprise import EnterpriseRepo
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


def _repo(server: Any) -> EnterpriseRepo:
    return server.services.enterprise_repo


def _name(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise OctopError(ErrorCode.FORBIDDEN, "name must not be empty", status=400)
    return cleaned


@router.get("/organizations", summary="List enterprise organizations")
async def list_organizations(
    _: User = Depends(require_permission("users")),
    server: Any = Depends(get_server),
) -> list[dict[str, Any]]:
    return [
        {
            "organization_id": row.organization_id,
            "name": row.name,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in _repo(server).list_organizations()
    ]


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
    return {
        "organization_id": row.organization_id,
        "name": row.name,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


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


def _team_or_404(server: Any, organization_id: str, team_id: str):
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
