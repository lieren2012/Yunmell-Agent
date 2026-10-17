"""Public single-enterprise enrollment and authenticated deployment context."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Cookie, Depends, Request, Response
from pydantic import BaseModel, Field

from octop.api.deps import current_user, get_server, require_admin, require_permission
from octop.api.routers.auth import (
    EmailCodeBody,
    EnterpriseRegistrationBody,
    LoginBody,
    _send_login_code,
    login,
)
from octop.infra.auth.email_verification import (
    EmailVerificationError,
    load_smtp_config,
    verify_code,
)
from octop.infra.db.repos.deployment import DeploymentRepo
from octop.infra.deployment.service import (
    deployment,
    issue_receipt,
    public_info,
    receipt_status,
    session_context,
)
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.knowledge.service import KnowledgeService
from octop.infra.users.email import normalize_email
from octop.infra.users.identity import User

router = APIRouter()
admin_router = APIRouter()
enterprise_router = APIRouter()


class EnterpriseKnowledgeBaseBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    icon_name: str = Field(default="", max_length=64)
    max_documents: int = Field(default=100, ge=0, le=10_000)


def _enterprise_kb_payload(row: Any) -> dict[str, Any]:
    """Serialize the control-plane metadata used by desktop projections."""
    return {
        "knowledge_base_id": row.id,
        "name": row.name,
        "description": row.description,
        "icon_name": row.icon_name,
        "embedding_model": row.embedding_model,
        "embedding_dim": row.embedding_dim,
        "doc_count": row.doc_count,
        "max_documents": row.max_documents,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "scope": "enterprise",
        "read_only": True,
    }


def _enterprise_kb(server: Any, kb_id: str) -> Any:
    row = server.services.knowledge_repo.get_base(kb_id)
    if row is None or not row.shared:
        raise OctopError(ErrorCode.NOT_FOUND, "enterprise knowledge base not found", status=404)
    return row


@enterprise_router.get("/knowledge-bases", summary="List enterprise knowledge-base projection")
async def list_enterprise_knowledge_bases(
    user: User = Depends(require_permission("knowledge_bases")),
    server: Any = Depends(get_server),
) -> list[dict[str, Any]]:
    del user
    return [_enterprise_kb_payload(row) for row in server.services.knowledge_repo.list_shared()]


@enterprise_router.get(
    "/knowledge-bases/{kb_id}", summary="Read enterprise knowledge-base projection"
)
async def get_enterprise_knowledge_base(
    kb_id: str,
    _user: User = Depends(require_permission("knowledge_bases")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    return _enterprise_kb_payload(_enterprise_kb(server, kb_id))


@enterprise_router.get(
    "/knowledge-bases/{kb_id}/documents", summary="List enterprise knowledge documents"
)
async def list_enterprise_knowledge_documents(
    kb_id: str,
    prefix: str | None = None,
    user: User = Depends(require_permission("knowledge_bases")),
    server: Any = Depends(get_server),
) -> list[dict[str, Any]]:
    _enterprise_kb(server, kb_id)
    service = KnowledgeService(server.services)
    rows = service.list_documents(kb_id, actor_user_id=user.id, is_admin=False, prefix=prefix)
    return [
        {
            "id": row.id,
            "document_id": row.id,
            "kb_id": row.kb_id,
            "path": row.path,
            "filename": row.filename,
            "is_dir": row.is_dir,
            "content_type": row.content_type,
            "byte_size": row.byte_size,
            "content_hash": row.content_hash,
            "status": row.status,
            "error_message": row.error_message,
            "chunk_count": row.chunk_count,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "scope": "enterprise",
            "read_only": True,
        }
        for row in rows
    ]


@enterprise_router.get(
    "/knowledge-bases/{kb_id}/documents/{doc_id}/preview",
    summary="Preview enterprise knowledge document",
)
async def preview_enterprise_knowledge_document(
    kb_id: str,
    doc_id: str,
    user: User = Depends(require_permission("knowledge_bases")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    _enterprise_kb(server, kb_id)
    service = KnowledgeService(server.services)
    preview = service.preview_document(kb_id, doc_id, actor_user_id=user.id, is_admin=False)
    return {**preview, "scope": "enterprise", "read_only": True}


COOKIE = "yunmell_registration_receipt"


@router.get("/deployment", summary="Get this service's enterprise name and registration policy")
async def info(server: Any = Depends(get_server)) -> dict[str, Any]:
    if server.user_manager is None or server.user_manager.count() == 0:
        raise OctopError(ErrorCode.SETUP_REQUIRED, "管理服务尚未完成管理员初始化", status=503)
    return public_info(server)


@router.post(
    "/deployment/register/email-code",
    summary="Send the registration verification code",
)
async def register_email_code(
    body: EmailCodeBody, server: Any = Depends(get_server)
) -> dict[str, Any]:
    organization, _team = deployment(server)
    if not organization.registration_open:
        raise OctopError(ErrorCode.FORBIDDEN, "该企业暂未开放注册，请联系管理员", status=403)
    if normalize_email(body.email) is None:
        raise OctopError(ErrorCode.EMAIL_INVALID, "请填写有效邮箱", status=400)
    return await _send_login_code(server, "register", body.email)


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
    # When the administrator configured SMTP, prove ownership of the recovery
    # address before the account exists.  Without SMTP the admin review is the
    # only gate, matching an on-prem deployment with no mail relay.
    smtp = load_smtp_config(server.services.settings_repo.get, server.services.secret_repo)
    email = normalize_email(body.email) if body.email else None
    if smtp.enabled:
        if email is None:
            raise OctopError(ErrorCode.EMAIL_INVALID, "请填写有效邮箱", status=400)
        if not body.email_code:
            raise OctopError(
                ErrorCode.AUTH_FAILED,
                "请填写邮箱验证码",
                details={"email_error": "EMAIL_CODE_REQUIRED"},
                status=400,
            )
        try:
            verify_code(
                server.services.settings_repo.get,
                server.services.settings_repo.set,
                "register",
                email,
                body.email_code,
            )
        except EmailVerificationError as exc:
            raise OctopError(
                ErrorCode.AUTH_FAILED, str(exc), details={"email_error": exc.code}, status=400
            ) from exc
    from octop.infra.db.repos.user_roles import seeded_user_role_assignment

    assignment = seeded_user_role_assignment(server.services.db)
    user = await server.user_manager.create(
        username=username,
        password=body.password,
        role=assignment[0] if assignment else "user",
        display_name=body.display_name,
        email=email,
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


@admin_router.get("/knowledge-bases", summary="List enterprise knowledge bases")
async def admin_list_enterprise_knowledge_bases(
    _admin: User = Depends(require_admin()),
    server: Any = Depends(get_server),
) -> list[dict[str, Any]]:
    return [_enterprise_kb_payload(row) for row in server.services.knowledge_repo.list_shared()]


@admin_router.post(
    "/knowledge-bases", status_code=201, summary="Create an enterprise knowledge base"
)
async def admin_create_enterprise_knowledge_base(
    body: EnterpriseKnowledgeBaseBody,
    request: Request,
    admin: User = Depends(require_admin()),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    try:
        row = KnowledgeService(server.services).create_base(
            owner_user_id=admin.id,
            name=body.name.strip(),
            description=body.description.strip(),
            shared=True,
            icon_name=body.icon_name.strip(),
            max_documents=body.max_documents,
            require_usable=True,
        )
        return _enterprise_kb_payload(row)
    except (RuntimeError, ValueError) as exc:
        raise OctopError(
            ErrorCode.KNOWLEDGE_PREREQUISITES_FAILED,
            "企业知识库未就绪，请先配置向量模型",
            details={"reason": str(exc)},
            status=503,
        ) from exc


@admin_router.patch("/knowledge-bases/{kb_id}", summary="Update an enterprise knowledge base")
async def admin_update_enterprise_knowledge_base(
    kb_id: str,
    body: EnterpriseKnowledgeBaseBody,
    _admin: User = Depends(require_admin()),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    _enterprise_kb(server, kb_id)
    try:
        updated = KnowledgeService(server.services).update_base(
            kb_id,
            actor_user_id=_admin.id,
            name=body.name.strip(),
            description=body.description.strip(),
            icon_name=body.icon_name.strip(),
            max_documents=body.max_documents,
            is_admin=True,
        )
    except (RuntimeError, ValueError, PermissionError) as exc:
        raise OctopError(ErrorCode.INTERNAL_ERROR, str(exc), status=400) from exc
    # An admin update must not accidentally convert the enterprise row back
    # into a personal base through the generic service.
    if not updated.shared:
        server.services.knowledge_repo.update_base(kb_id, shared=True)
    refreshed = server.services.knowledge_repo.get_base(kb_id)
    if refreshed is None:
        raise OctopError(ErrorCode.NOT_FOUND, "enterprise knowledge base not found", status=404)
    return _enterprise_kb_payload(refreshed)


@admin_router.delete(
    "/knowledge-bases/{kb_id}", status_code=204, summary="Delete an enterprise knowledge base"
)
async def admin_delete_enterprise_knowledge_base(
    kb_id: str,
    _admin: User = Depends(require_admin()),
    server: Any = Depends(get_server),
) -> None:
    _enterprise_kb(server, kb_id)
    try:
        KnowledgeService(server.services).delete_base(kb_id, actor_user_id=_admin.id, is_admin=True)
    except (RuntimeError, ValueError, PermissionError) as exc:
        raise OctopError(ErrorCode.INTERNAL_ERROR, str(exc), status=400) from exc


class DeploymentSettings(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    registration_open: bool
    review_required: bool


@admin_router.post(
    "/deployment/default-team/migrate",
    summary="Explicitly consolidate retained accounts into the default team without deleting history",
)
async def migrate_team(
    actor: User = Depends(require_permission("users")), server: Any = Depends(get_server)
) -> dict[str, Any]:
    organization, team = deployment(server)
    result = DeploymentRepo(server.services.db).consolidate_default_team(
        organization.organization_id, team.team_id
    )
    server.services.audit_repo.write(
        actor=actor.username,
        action="deployment.default_team.migrate",
        target=team.team_id,
        payload=f"members={result['members']};history=preserved",
    )
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
