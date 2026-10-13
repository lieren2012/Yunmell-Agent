"""Only account/management requests leave the desktop; runtime APIs stay local."""

from __future__ import annotations

from http.cookies import SimpleCookie
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from octop.api.deps import authenticate_request, is_jwt_exempt_request
from octop.infra.deployment.connection import (
    control_plane_only,
    desktop_mode,
    management_address,
    normalize_address,
    save_address,
)
from octop.infra.deployment.desktop import bridge
from octop.infra.errors import ErrorCode, OctopError

COOKIE = "yunmell_registration_receipt"
PUBLIC_AUTH = {
    "/api/auth/deployment",
    "/api/auth/deployment/register",
    "/api/auth/deployment/registration/status",
    "/api/auth/captcha",
    "/api/auth/oauth/status",
    "/api/auth/oidc/status",
    "/api/auth/ldap/status",
}
MANAGEMENT = (
    "/api/admin/",
    "/api/users",
    "/api/user-roles",
    "/api/enterprise/knowledge-bases",
)


def cookie_headers(request: Request, server: Any) -> dict[str, str]:
    cookies = SimpleCookie(request.headers.get("cookie", ""))
    entry = cookies.get(COOKIE)
    if entry:
        try:
            payload = bridge(server).decrypt(entry.value.encode())
            if payload.get("authority") == management_address():
                return {"Cookie": f"{COOKIE}={payload['receipt']}"}
        except OctopError:
            pass
    return {}


def forwarded_response(
    remote: httpx.Response, server: Any, *, authority: str | None = None
) -> Response:
    response = Response(
        remote.content,
        status_code=remote.status_code,
        media_type=remote.headers.get("content-type", "application/json"),
    )
    receipt = remote.cookies.get(COOKIE)
    if receipt:
        bound_authority = authority if authority is not None else management_address()
        encrypted = bridge(server).encrypt(
            {"authority": bound_authority, "receipt": receipt}
        ).decode()
        response.set_cookie(
            COOKIE,
            encrypted,
            httponly=True,
            samesite="strict",
            max_age=604800,
            path="/api/auth/deployment",
            secure=False,
        )
    return response


def require_loopback_settings(request: Request) -> None:
    try:
        local = request.client is not None and ip_address(request.client.host).is_loopback
    except ValueError:
        local = request.client is not None and request.client.host in {"localhost", "testclient"}
    origin = request.headers.get("origin")
    if not local or (origin is not None and urlsplit(origin).netloc != request.url.netloc):
        raise OctopError(ErrorCode.FORBIDDEN, "服务地址只能从本机客户端设置", status=403)


async def connection(request: Request, server: Any) -> Response:
    if request.method == "GET":
        return JSONResponse(
            {
                "desktop": desktop_mode(),
                "address": management_address(),
                "management_only": control_plane_only(),
            }
        )
    if request.method != "PUT" or not desktop_mode():
        raise OctopError(ErrorCode.FORBIDDEN, "该入口仅用于桌面客户端连接设置", status=403)
    require_loopback_settings(request)
    body = await request.json()
    address = normalize_address(str(body.get("address") or ""))
    try:
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=8) as client:
            probe = await client.get(address + "/api/auth/deployment")
        info = probe.json()
        if probe.status_code != 200 or not isinstance(info, dict) or not info.get("name"):
            raise ValueError
    except (httpx.HTTPError, ValueError):
        raise OctopError(
            ErrorCode.INTERNAL_ERROR,
            "服务地址不可用",
            details={"reason": "无法读取企业信息，请检查地址、网络并确认管理端已升级"},
            status=503,
        ) from None
    previous = management_address()
    save_address(address)
    response = JSONResponse({"desktop": True, "address": address, "name": info["name"]})
    if previous != address:
        response.delete_cookie(COOKIE, path="/api/auth/deployment")
    return response


def install(app: Any, server: Any) -> None:
    desktop_enabled = desktop_mode()
    management_only = control_plane_only()
    @app.middleware("http")  # type: ignore[untyped-decorator]
    async def desktop_adapter(request: Request, call_next: Any) -> Any:
        path = request.url.path
        try:
            if path == "/api/auth/connection":
                return await connection(request, server)
            if management_only and path.startswith(
                (
                    "/api/chat",
                    "/api/agents",
                    "/api/workspace",
                    "/api/terminal",
                    "/api/browser",
                    "/api/desktop",
                )
            ):
                raise OctopError(
                    ErrorCode.FORBIDDEN, "消息、会话及工具请在桌面客户端运行", status=403
                )
            if (
                not desktop_enabled
                or not path.startswith("/api/")
                or path.startswith("/api/desktop-model/")
                or path.startswith("/api/health")
            ):
                return await call_next(request)
            if path == "/api/setup/status":
                return JSONResponse(
                    {
                        "setup_required": False,
                        "database_bound": True,
                        "connection_required": not bool(management_address()),
                    }
                )
            if path.startswith("/api/setup/"):
                raise OctopError(
                    ErrorCode.FORBIDDEN, "企业账号在管理服务注册，无需本机初始化管理员", status=403
                )
            client = bridge(server)
            content_type = request.headers.get("content-type", "application/json")
            headers = {
                "Content-Type": content_type,
                "Accept-Language": request.headers.get("accept-language", "zh"),
            }
            headers.update(cookie_headers(request, server))
            if path == "/api/auth/login":
                authority = management_address()
                remote = await client.remote(
                    "POST", "/auth/deployment/login", content=await request.body(), headers=headers,
                    authority=authority,
                )
                if remote.status_code != 200:
                    return forwarded_response(remote, server, authority=authority)
                return JSONResponse(await client.adopt_login(dict(remote.json()), authority=authority))
            if path in PUBLIC_AUTH:
                authority = management_address()
                remote = await client.remote(
                    request.method,
                    path.removeprefix("/api"),
                    content=await request.body(),
                    headers=headers,
                    authority=authority,
                )
                if path == "/api/auth/deployment" and (
                    remote.status_code != 200
                    or "application/json" not in remote.headers.get("content-type", "")
                ):
                    raise OctopError(
                        ErrorCode.INTERNAL_ERROR,
                        "无法读取企业信息",
                        details={"reason": "无法读取企业信息，请确认管理端已升级并检查服务地址"},
                        status=503,
                    )
                return forwarded_response(remote, server, authority=authority)
            if is_jwt_exempt_request(request) and path != "/api/auth/deployment/session":
                return await call_next(request)
            user = authenticate_request(request, server)
            if (
                path in {"/api/auth/me", "/api/auth/deployment/session"}
                and request.method == "GET"
                and client.identity_refresh_needed(user.id)
            ):
                # A stale or missing snapshot must be refreshed before the
                # dashboard mounts.  This is the one protected request that
                # may wait briefly for the control plane; local runtime APIs
                # continue to use the cached projection and stay offline-first.
                try:
                    await client.validate(user.id)
                except OctopError as error:
                    if error.code in {ErrorCode.AUTH_FAILED, ErrorCode.USER_DISABLED}:
                        raise
            # Identity and deployment policy are refreshed on a soft TTL in
            # the background.  Local runtime APIs must never wait for a
            # control-plane /auth/me or /auth/deployment/session request.
            profile, context = client.cached_identity(user.id)
            if path == "/api/auth/deployment/session":
                return JSONResponse(context)
            if path == "/api/auth/me" and request.method == "GET":
                return JSONResponse({**profile, "id": user.id, "deployment": context})
            if path in {"/api/providers", "/api/providers/resolved", "/api/providers/active-model"}:
                from octop.api.routers.providers import _row_to_dict
                from octop.infra.agents.providers.resolved import list_resolved_models
                from octop.infra.deployment.desktop import MODEL

                name = f"yunmell-managed-{user.id}"
                provider = server.services.provider_repo.get_by_name(name)
                if path == "/api/providers/active-model":
                    if request.method != "GET":
                        raise OctopError(ErrorCode.FORBIDDEN, "默认模型由企业统一配置", status=403)
                    return JSONResponse({"provider_name": name, "model": MODEL})
                if path == "/api/providers/resolved":
                    return JSONResponse(list_resolved_models([provider] if provider else []))
                return JSONResponse([_row_to_dict(provider)] if provider else [])
            if (
                path.startswith(MANAGEMENT)
                or path in {"/api/auth/change-password", "/api/auth/logout"}
                or path.startswith("/api/auth/me/")
            ):
                remote_path = path.removeprefix("/api")
                if request.url.query:
                    remote_path += "?" + request.url.query
                authority, session_token = client.bound_session(user.id)
                try:
                    remote = await client.remote(
                        request.method,
                        remote_path,
                        token=session_token,
                        content=await request.body(),
                        headers=headers,
                        authority=authority,
                    )
                finally:
                    # Local logout must invalidate the encrypted session even
                    # when the management server is temporarily unavailable.
                    if path == "/api/auth/logout":
                        client.revoke_session(user.id)
                return forwarded_response(remote, server, authority=authority)
            # All other requests continue into the existing local JWT/runtime APIs.
            return await call_next(request)
        except OctopError as error:
            return JSONResponse(error.to_envelope(), status_code=error.status)
