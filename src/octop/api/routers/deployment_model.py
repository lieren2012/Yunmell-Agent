"""Stateless managed inference: provider credentials stay on the management host."""

from __future__ import annotations

import hmac
import json
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse

from octop.api.deps import current_user, get_server
from octop.infra.db.repos.deployment import DeploymentRepo
from octop.infra.db.repos.usage import resolve_usage_window
from octop.infra.deployment.connection import desktop_mode, management_address
from octop.infra.deployment.desktop import MODEL, bridge
from octop.infra.deployment.service import default_model
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.enterprise_policy import (
    acquire_team_concurrency,
    assert_team_quota_available,
    release_team_concurrency,
)
from octop.infra.users.identity import User
from octop.infra.users.permissions import user_has_permission
from octop.infra.users.resource_policy import assert_token_quota_available

router = APIRouter()
desktop_router = APIRouter()


class ManagedUsage:
    def __init__(self, services: Any) -> None:
        self.services = services

    def total_tokens_for_user(self, user_id: int) -> int:
        return self.totals_for_users([user_id])["total_tokens"]

    def totals_for_users(self, user_ids: list[int], window: str = "all") -> dict[str, int]:
        original = self.services.usage_repo.totals_for_users(user_ids, window=window)
        start, end = resolve_usage_window(window)
        managed = DeploymentRepo(self.services.db).model_totals(user_ids, start, end)
        return {
            "total_tokens": int(original["total_tokens"]) + managed["total_tokens"],
            "model_calls": int(original["model_calls"]) + managed["model_calls"],
        }


@router.post(
    "/deployment/inference/chat/completions",
    summary="Forward the managed default model without persisting conversations",
)
async def inference(
    request: Request, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> Any:
    provider, model = default_model(server, user)
    if provider.kind == "anthropic":
        raise OctopError(
            ErrorCode.FORBIDDEN,
            "当前转发接口需要 OpenAI 兼容模型",
            details={"reason": "请在管理端选择 OpenAI 兼容的默认模型"},
            status=503,
        )
    body = await request.json()
    if body.get("model") != MODEL:
        if not user_has_permission(user, "providers"):
            raise OctopError(ErrorCode.FORBIDDEN, "该角色只能调用企业默认模型", status=403)
        reference = str(body.get("model") or "")
        provider_name, _, model_id = reference.partition("/")
        chosen = server.services.provider_repo.get_by_name(provider_name)
        candidate = (
            next(
                (
                    item
                    for item in chosen.get_models()
                    if item.get("id") == model_id and item.get("enabled", True)
                ),
                None,
            )
            if chosen
            else None
        )
        if (
            not chosen
            or not chosen.enabled
            or not chosen.api_key
            or not candidate
            or not server.services.enterprise_repo.model_allowed_for_user(user.id, reference)
        ):
            raise OctopError(ErrorCode.FORBIDDEN, "所选模型不可用或未被授权", status=403)
        provider, model = chosen, candidate
    body["model"] = model["id"]
    if body.get("stream"):
        body["stream_options"] = {"include_usage": True}
    enterprise = server.services.enterprise_repo
    assert_token_quota_available(
        server.services.user_policy_repo, ManagedUsage(server.services), user.id
    )
    assert_team_quota_available(enterprise, ManagedUsage(server.services), user.id)
    teams = acquire_team_concurrency(enterprise, user.id)
    from octop.infra.agents.providers.probe import provider_headers

    client = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10), follow_redirects=False)
    try:
        response = await client.send(
            client.build_request(
                "POST",
                provider.base_url.rstrip("/") + "/chat/completions",
                json=body,
                headers={
                    "Authorization": f"Bearer {provider.api_key}",
                    "Content-Type": "application/json",
                    **provider_headers(provider),
                },
            ),
            stream=True,
        )
    except httpx.HTTPError:
        release_team_concurrency(teams)
        await client.aclose()
        raise OctopError(
            ErrorCode.INTERNAL_ERROR,
            "默认模型连接失败",
            details={"reason": "企业默认模型连接失败，请联系管理员检查 Provider"},
            status=502,
        ) from None
    if response.status_code != 200:
        status = response.status_code
        await response.aclose()
        await client.aclose()
        release_team_concurrency(teams)
        raise OctopError(
            ErrorCode.INTERNAL_ERROR,
            "默认模型调用失败",
            details={"reason": f"企业默认模型返回 HTTP {status}，请联系管理员"},
            status=502,
        )

    def record(usage: dict[str, Any]) -> None:
        DeploymentRepo(server.services.db).record_model_usage(
            user.id,
            f"{provider.name}/{model['id']}",
            int(usage.get("prompt_tokens") or 0),
            int(usage.get("completion_tokens") or 0),
        )

    if not body.get("stream"):
        try:
            content = await response.aread()
            record(dict(json.loads(content).get("usage") or {}))
            return Response(content, media_type="application/json")
        finally:
            await response.aclose()
            await client.aclose()
            release_team_concurrency(teams)

    async def stream() -> Any:
        usage: dict[str, Any] = {}
        try:
            async for line in response.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        frame = json.loads(line[6:])
                        if frame.get("usage"):
                            usage = dict(frame["usage"])
                    except ValueError:
                        pass
                yield (line + "\n").encode()
        finally:
            await response.aclose()
            await client.aclose()
            release_team_concurrency(teams)
            record(usage)

    return StreamingResponse(stream(), media_type="text/event-stream")


@desktop_router.post(
    "/{local_user_id}/chat/completions",
    summary="Local SDK relay authenticated by a per-user backend-only credential",
)
async def relay(local_user_id: int, request: Request, server: Any = Depends(get_server)) -> Any:
    if not desktop_mode() or not management_address():
        raise OctopError(ErrorCode.FORBIDDEN, "企业模型连接未配置", status=403)
    key = server.services.secret_repo.get(f"yunmell.relay:{local_user_id}")
    provided = request.headers.get("authorization", "").removeprefix("Bearer ")
    if key is None or not hmac.compare_digest(provided.encode(), key):
        raise OctopError(ErrorCode.AUTH_FAILED, "模型连接凭据无效", status=401)
    identity = bridge(server)
    authority, token = identity.bound_session(local_user_id)
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(150, connect=10), trust_env=False, follow_redirects=False
    )
    try:
        response = await client.send(
            client.build_request(
                "POST",
                authority + "/api/auth/deployment/inference/chat/completions",
                content=await request.body(),
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            ),
            stream=True,
        )
    except httpx.HTTPError:
        await client.aclose()
        raise OctopError(
            ErrorCode.INTERNAL_ERROR,
            "企业模型服务连接失败",
            details={"reason": "企业模型服务连接失败，请重试或更换地址"},
            status=503,
        ) from None
    if response.status_code != 200:
        content = await response.aread()
        await response.aclose()
        await client.aclose()
        return Response(content, status_code=response.status_code, media_type="application/json")

    async def stream() -> Any:
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return StreamingResponse(
        stream(), media_type=response.headers.get("content-type", "application/json")
    )
