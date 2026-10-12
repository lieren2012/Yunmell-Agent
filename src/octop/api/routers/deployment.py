"""Public single-enterprise enrollment and authenticated deployment context."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Cookie, Depends, Request, Response
from pydantic import BaseModel, Field

from octop.api.deps import current_user, get_server, require_permission
from octop.api.routers.auth import EnterpriseRegistrationBody, LoginBody, login
from octop.infra.db.repos.deployment import DeploymentRepo
from octop.infra.deployment.service import (
    deployment,
    issue_receipt,
    public_info,
    receipt_status,
    session_context,
)
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User

router = APIRouter()
admin_router = APIRouter()
COOKIE = "yunmell_registration_receipt"


@router.get("/deployment", summary="Get this service's enterprise name and registration policy")
async def info(server: Any = Depends(get_server)) -> dict[str, Any]:
    if server.user_manager is None or server.user_manager.count() == 0:
        raise OctopError(ErrorCode.SETUP_REQUIRED, "管理服务尚未完成管理员初始化", status=503)
    return public_info(server)


@router.post(
    "/deployment/register", status_code=202, summary="Register with this service's enterprise"
)
async def register(
    body: EnterpriseRegistrationBody,
    request: Request,
    response: Response,
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    organization, team = deployment(server)
    if not organization.registration_open:
        raise OctopError(ErrorCode.FORBIDDEN, "该企业暂未开放注册，请联系管理员", status=403)
    username = body.username.strip()
    if not username:
        raise OctopError(ErrorCode.SLASH_BAD_ARGS, "请填写账号", status=400)
    from octop.infra.db.repos.user_roles import seeded_user_role_assignment

    assignment = seeded_user_role_assignment(server.services.db)
    user = await server.user_manager.create(
        username=username,
        password=body.password,
        role=assignment[0] if assignment else "user",
        display_name=body.display_name,
        email=body.email,
        pending_approval=True,
    )
    if assignment:
        server.services.user_repo.set_permissions(user.id, assignment[2])
        server.services.user_repo.set_role_name(user.id, assignment[1])
        server.services.user_policy_repo.merge(user.id, dict(assignment[3]))
    repo = server.services.enterprise_repo
    application = repo.create_registration_application(
        organization_id=organization.organization_id, user_id=user.id, supplement=body.supplement
    )
    repo.upsert_member(organization.organization_id, user.id, team.team_id, "member")
    if not organization.registration_review_required:
        application = repo.review_registration_application(
            application.application_id,
            status="approved",
            reviewer_id=None,
            note="auto-approved by deployment policy",
        )
        repo.upsert_member(organization.organization_id, user.id, team.team_id, "member")
    receipt = issue_receipt(server, application.application_id)
    response.set_cookie(
        COOKIE,
        receipt,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        max_age=604800,
        path="/api/auth/deployment",
    )
    server.services.audit_repo.write(
        actor=username, action="deployment.registration.submit", target=application.application_id
    )
    return {
        "status": application.status,
        "application_id": application.application_id,
        "name": organization.name,
    }


@router.get(
    "/deployment/registration/status",
    summary="Read own registration status using an HttpOnly receipt",
)
async def registration_status(
    yunmell_registration_receipt: str | None = Cookie(None), server: Any = Depends(get_server)
) -> dict[str, Any]:
    return receipt_status(server, yunmell_registration_receipt)


@router.post(
    "/deployment/login", summary="Sign in without enterprise codes or organization selection"
)
async def deployment_login(
    body: LoginBody, request: Request, server: Any = Depends(get_server)
) -> dict[str, Any]:
    deployment(server)
    return await login(body.model_copy(update={"enterprise_slug": None}), request, server)


@router.get("/deployment/session", summary="Read managed model metadata and local control policy")
async def context(
    user: User = Depends(current_user), server: Any = Depends(get_server)
) -> dict[str, Any]:
    return session_context(server, user)


def admin_payload(server: Any) -> dict[str, Any]:
    organization, team = deployment(server)
    return {
        **public_info(server),
        "team_id": team.team_id,
        "default_provider_name": organization.default_provider_name,
        "default_model": organization.default_model,
        "historical_organizations": len(server.services.enterprise_repo.list_organizations()),
        "historical_teams": sum(
            len(server.services.enterprise_repo.list_teams(row.organization_id))
            for row in server.services.enterprise_repo.list_organizations()
        ),
    }


@admin_router.get("/deployment", summary="Get fixed enterprise deployment settings")
async def admin_info(
    _: User = Depends(require_permission("users")), server: Any = Depends(get_server)
) -> dict[str, Any]:
    return admin_payload(server)


class DeploymentSettings(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    registration_open: bool
    review_required: bool


@admin_router.post("/deployment/default-team/migrate", summary="Explicitly consolidate retained accounts into the default team without deleting history")
async def migrate_team(actor: User = Depends(require_permission("users")), server: Any = Depends(get_server)) -> dict[str, Any]:
    organization, team = deployment(server)
    result = DeploymentRepo(server.services.db).consolidate_default_team(organization.organization_id, team.team_id)
    server.services.audit_repo.write(actor=actor.username,action="deployment.default_team.migrate",target=team.team_id,payload=f"members={result['members']};history=preserved")
    return result


@admin_router.put("/deployment", summary="Rename this enterprise and change registration policy")
async def update(
    body: DeploymentSettings,
    actor: User = Depends(require_permission("users")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    name = body.name.strip()
    if not name:
        raise OctopError(ErrorCode.SLASH_BAD_ARGS, "企业名称不能为空", status=400)
    organization, _ = deployment(server)
    DeploymentRepo(server.services.db).update_deployment(
        organization.organization_id,
        name=name,
        registration_open=body.registration_open,
        review_required=body.review_required,
    )
    server.services.audit_repo.write(
        actor=actor.username,
        action="deployment.settings.update",
        target=organization.organization_id,
    )
    return admin_payload(server)
