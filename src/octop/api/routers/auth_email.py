"""Administrator endpoints for enterprise email delivery.

Mounted under ``/admin``: only holders of ``user_management`` (or the built-in
admin role) may read, change, or test the SMTP account.  The stored password is
never returned — the UI only learns whether one is configured.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from octop.api.deps import get_server, require_permission
from octop.infra.auth.email_verification import (
    EmailVerificationError,
    load_smtp_config,
    save_smtp_config,
    send_mail,
)
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.email import normalize_email
from octop.infra.users.identity import User

router = APIRouter()


class SmtpConfigBody(BaseModel):
    enabled: bool = False
    host: str = Field(default="", max_length=255)
    port: int = Field(default=587, ge=1, le=65535)
    username: str = Field(default="", max_length=255)
    # ``None`` keeps the stored password; send "" to clear it.
    password: str | None = Field(default=None, max_length=512)
    sender: str = Field(default="", max_length=254)
    sender_name: str = Field(default="云迈智能体", max_length=120)
    use_tls: bool = True
    use_ssl: bool = False


class SmtpTestBody(BaseModel):
    to: str = Field(min_length=3, max_length=254)


def _service(server: Any) -> tuple[Any, Any]:
    return server.services.settings_repo, server.services.secret_repo


@router.get("/email", summary="Read SMTP delivery settings")
async def read_email_config(
    server: Any = Depends(get_server),
    _: User = Depends(require_permission("users")),
) -> dict[str, Any]:
    settings_repo, secret_repo = _service(server)
    return load_smtp_config(settings_repo.get, secret_repo).public_dict()


@router.put("/email", summary="Update SMTP delivery settings")
async def update_email_config(
    body: SmtpConfigBody,
    server: Any = Depends(get_server),
    _: User = Depends(require_permission("users")),
) -> dict[str, Any]:
    settings_repo, secret_repo = _service(server)
    sender = body.sender.strip()
    if sender and normalize_email(sender) is None:
        raise OctopError(ErrorCode.EMAIL_INVALID, "sender address is not a valid email")
    if body.enabled and not (body.host.strip() and sender):
        raise OctopError(
            ErrorCode.EMAIL_INVALID,
            "host and sender are required when email delivery is enabled",
        )
    config = save_smtp_config(
        settings_repo.set,
        settings_repo.get,
        secret_repo,
        enabled=body.enabled,
        host=body.host,
        port=body.port,
        username=body.username,
        password=body.password,
        sender=sender,
        sender_name=body.sender_name,
        use_tls=body.use_tls,
        use_ssl=body.use_ssl,
    )
    server.services.audit_repo.write(
        actor=getattr(_, "username", "admin"),
        action="auth.email.config",
        target="smtp",
        payload=f"enabled={config.enabled} host={config.host}",
    )
    return config.public_dict()


@router.post("/email/test", summary="Send a test message through SMTP")
async def test_email_config(
    body: SmtpTestBody,
    request: Request,
    server: Any = Depends(get_server),
    _: User = Depends(require_permission("users")),
) -> dict[str, Any]:
    settings_repo, secret_repo = _service(server)
    config = load_smtp_config(settings_repo.get, secret_repo)
    target = normalize_email(body.to)
    if target is None:
        raise OctopError(ErrorCode.EMAIL_INVALID, "recipient address is not a valid email")
    try:
        send_mail(
            config,
            to=target,
            subject="云迈智能体 — SMTP 测试",
            body="这是一封来自云迈智能体企业管理后台的测试邮件。",
        )
    except EmailVerificationError as exc:
        raise OctopError(ErrorCode.AUTH_FAILED, str(exc), status=502) from exc
    return {"ok": True, "to": target}
