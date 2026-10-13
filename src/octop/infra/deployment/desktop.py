"""Remote identity validation with local users, workspaces and encrypted sessions."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken

from octop.infra.db.repos.deployment import DeploymentRepo
from octop.infra.deployment.connection import management_address
from octop.infra.deployment.service import deployment
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User
from octop.infra.users.permissions import ALL_PERMISSION_KEYS

MODEL = "yunmell-default"
IDENTITY_SNAPSHOT_TTL_SECONDS = 300
IDENTITY_SNAPSHOT_PREFIX = "yunmell.identity-snapshot:"
REMOTE_TIMEOUT = httpx.Timeout(5.0, connect=2.0)


class DesktopIdentityBridge:
    def __init__(self, server: Any) -> None:
        self.server = server
        self.lock = asyncio.Lock()
        # Refreshes are deliberately detached from request handling.  A local
        # runtime request must never wait for the control plane to answer.
        self._refresh_tasks: dict[int, asyncio.Task[None]] = {}
        self._offline_users: set[int] = set()

    def cipher(self) -> Fernet:
        path = self.server.paths.root / ".yunmell-session.key"
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(Fernet.generate_key())
        return Fernet(path.read_bytes())

    def encrypt(self, value: dict[str, Any]) -> bytes:
        return self.cipher().encrypt(json.dumps(value).encode())

    def decrypt(self, value: bytes) -> dict[str, Any]:
        try:
            result = json.loads(self.cipher().decrypt(value))
            if not isinstance(result, dict):
                raise ValueError
        except (InvalidToken, ValueError, TypeError, OSError):
            raise OctopError(
                ErrorCode.AUTH_FAILED, "登录状态失效，请重新登录", status=401
            ) from None
        return dict(result)

    async def remote(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        authority: str | None = None,
    ) -> httpx.Response:
        address = authority if authority is not None else management_address()
        if not address:
            raise OctopError(
                ErrorCode.AUTH_FAILED,
                "请先填写企业管理服务地址",
                details={"reason": "请先填写企业管理服务地址"},
                status=401,
            )
        self.require_authority(address)
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("remote path must be relative to the API root")
        outgoing = dict(headers or {})
        if token:
            outgoing["Authorization"] = f"Bearer {token}"
        try:
            async with httpx.AsyncClient(
                trust_env=False, follow_redirects=False, timeout=REMOTE_TIMEOUT
            ) as client:
                response = await client.request(
                    method, address + "/api" + path, content=content, headers=outgoing
                )
        except httpx.HTTPError:
            raise OctopError(
                ErrorCode.INTERNAL_ERROR,
                "无法连接企业管理服务",
                details={"reason": "无法连接企业管理服务，请重试或更换服务地址"},
                status=503,
            ) from None
        self.require_authority(address)
        return response

    @staticmethod
    def require_authority(authority: str) -> None:
        if not authority or authority != management_address():
            raise OctopError(
                ErrorCode.AUTH_FAILED, "服务地址已更换，请在当前企业重新登录", status=401
            )

    def session(self, local_user_id: int) -> dict[str, Any]:
        services = self.server.services
        authority = DeploymentRepo(services.db).identity_authority(local_user_id)
        encrypted = services.secret_repo.get(f"yunmell.remote-session:{local_user_id}")
        if authority != management_address() or not authority or encrypted is None:
            raise OctopError(
                ErrorCode.AUTH_FAILED, "服务地址已更换或登录状态失效，请重新登录", status=401
            )
        payload = self.decrypt(encrypted)
        if payload.get("authority") != authority or not isinstance(payload.get("token"), str) or not payload.get("token"):
            raise OctopError(ErrorCode.AUTH_FAILED, "登录状态与当前服务不匹配", status=401)
        # b7 stored the same Fernet envelope without a session generation.  Add
        # one in place so an upgrade keeps the account projection while making
        # subsequent logout and address changes immediately effective.
        if not isinstance(payload.get("session_id"), str) or not payload.get("session_id"):
            # Derive the migration value from the existing token so two
            # concurrent first requests cannot mint competing generations.
            payload["session_id"] = hashlib.sha256(
                f"{authority}\0{payload['token']}".encode()
            ).hexdigest()
            services.secret_repo.rotate(
                f"yunmell.remote-session:{local_user_id}", self.encrypt(payload)
            )
        return payload

    def bound_session(self, local_user_id: int) -> tuple[str, str]:
        """Return one address/token snapshot; callers must never reread the address."""
        payload = self.session(local_user_id)
        return str(payload["authority"]), str(payload["token"])

    def token_for(self, local_user_id: int) -> str:
        return self.bound_session(local_user_id)[1]

    def save_token(
        self, local_user_id: int, token: str, *, authority: str, new_session: bool = False
    ) -> None:
        self.require_authority(authority)
        repo = self.server.services.secret_repo
        key = f"yunmell.remote-session:{local_user_id}"
        session_id = secrets.token_urlsafe(32) if new_session else self.session(local_user_id)["session_id"]
        value = self.encrypt({"authority": authority, "token": token, "session_id": session_id})
        repo.get_or_create(key, lambda: value)
        repo.rotate(key, value)

    def issue_local_token(self, user: User) -> str:
        services = self.server.services
        payload = self.session(user.id)
        now = int(time.time())
        return str(jwt.encode({
            "sub": str(user.id), "uname": user.username, "role": user.role,
            "iat": now, "exp": now + services.config.access_token_ttl_seconds,
            "yunmell_session": payload["session_id"],
        }, services.secret_repo.get("jwt"), algorithm="HS256"))

    def assert_local_session(self, local_id: int, claims: dict[str, Any]) -> None:
        expected = str(self.session(local_id)["session_id"])
        provided = claims.get("yunmell_session")
        if not isinstance(provided, str) or not hmac.compare_digest(expected, provided):
            raise OctopError(ErrorCode.AUTH_FAILED, "登录会话已结束，请重新登录", status=401)

    def revoke_session(self, local_id: int) -> None:
        """Invalidate even when the management host is offline, retaining all user data."""
        task = self._refresh_tasks.pop(local_id, None)
        self._offline_users.discard(local_id)
        try:
            current_task = asyncio.current_task()
        except RuntimeError:
            current_task = None
        if task is not None and task is not current_task and not task.done():
            task.cancel()
        with self.server.services.db.transaction() as connection:
            connection.execute("DELETE FROM secrets WHERE k = ?", (f"yunmell.remote-session:{local_id}",))
        # Do not continue using a previously refreshed identity after logout or
        # a remote revocation.  The local JWT session check is the hard gate;
        # dropping the snapshot also prevents stale profile data resurfacing
        # after a subsequent login.
        with self.server.services.db.transaction() as connection:
            connection.execute(
                "DELETE FROM secrets WHERE k = ?",
                (f"{IDENTITY_SNAPSHOT_PREFIX}{local_id}",),
            )

    @staticmethod
    def response_object(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError
            return dict(payload)
        except (ValueError, TypeError):
            raise OctopError(
                ErrorCode.INTERNAL_ERROR, "企业管理服务返回了无效数据，请检查服务地址或重试", status=503
            ) from None

    async def adopt_login(
        self, payload: dict[str, Any], *, authority: str | None = None
    ) -> dict[str, Any]:
        authority = authority if authority is not None else management_address()
        self.require_authority(authority)
        profile = self.profile(payload.get("user"))
        if not isinstance(payload.get("access_token"), str) or not payload["access_token"]:
            raise OctopError(ErrorCode.AUTH_FAILED, "企业登录响应无效，请重试", status=503)
        services = self.server.services
        repo = DeploymentRepo(services.db)
        async with self.lock:
            self.require_authority(authority)
            local_id = repo.local_identity(authority, int(profile["id"]))
            if local_id is None:
                internal_name = (
                    "yunmell_"
                    + hashlib.sha256(authority.encode()).hexdigest()[:12]
                    + "_"
                    + str(profile["id"])
                )
                existing = services.user_repo.get_by_username(internal_name)
                # Reuse only a passwordless projection from an interrupted first login.
                if existing is not None and existing.password_hash is not None:
                    raise OctopError(ErrorCode.AUTH_FAILED, "本机身份冲突，请联系管理员", status=409)
                local_id = existing.id if existing is not None else services.user_repo.create(
                    username=internal_name,
                    password_hash=None,
                    role="user",
                    display_name=profile.get("display_name") or profile["username"],
                    locale=profile.get("locale") or "zh",
                    permissions=profile.get("permissions") or [],
                )
                repo.add_identity(authority, int(profile["id"]), local_id)
            repo.update_profile(local_id, profile)
            self.save_token(local_id, str(payload["access_token"]), authority=authority, new_session=True)
            try:
                context = await self._refresh_context(local_id)
            except Exception:
                self.revoke_session(local_id)
                raise
            services.user_repo.set_permissions(local_id, self.local_permissions(profile, context))
            self._store_snapshot(local_id, profile, context)
            user = self.cache_user(local_id)
            ttl = services.config.access_token_ttl_seconds
            token = self.issue_local_token(user)
            return {
                "access_token": token,
                "token_type": "Bearer",
                "expires_in": ttl,
                "user": {**profile, "id": local_id, "deployment": context},
            }

    @staticmethod
    def profile(value: Any) -> dict[str, Any]:
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("id"), int)
            or not isinstance(value.get("username"), str)
            or not isinstance(value.get("permissions", []), list)
            or any(not isinstance(key, str) for key in value.get("permissions", []))
        ):
            raise OctopError(ErrorCode.AUTH_FAILED, "企业身份响应无效，请重试", status=503)
        return dict(value)

    def cache_user(self, local_id: int) -> User:
        row = self.server.services.user_repo.get(local_id)
        assert row is not None
        user = User(
            row.id, row.username, str(row.role), row.display_name, row.locale, list(row.permissions)
        )
        self.server.user_manager.register_cached_user(user)
        return user

    def _store_snapshot(
        self, local_id: int, profile: dict[str, Any], context: dict[str, Any]
    ) -> None:
        """Persist the last trusted control-plane projection locally.

        The value is encrypted with the desktop session key and is only used
        for local UI/runtime responses.  It is never accepted as a replacement
        for the encrypted remote session token in ``session()``.
        """
        payload = {
            "profile": dict(profile),
            "context": dict(context),
            "refreshed_at": time.time(),
        }
        key = f"{IDENTITY_SNAPSHOT_PREFIX}{local_id}"
        value = self.encrypt(payload)
        self.server.services.secret_repo.get_or_create(key, lambda: value)
        self.server.services.secret_repo.rotate(key, value)

    def _load_snapshot(self, local_id: int) -> tuple[dict[str, Any], dict[str, Any], float] | None:
        value = self.server.services.secret_repo.get(f"{IDENTITY_SNAPSHOT_PREFIX}{local_id}")
        if value is None:
            return None
        try:
            payload = self.decrypt(value)
            profile = self.profile(payload.get("profile"))
            context = payload.get("context")
            refreshed_value = payload.get("refreshed_at")
            if not isinstance(refreshed_value, (int, float, str)):
                raise ValueError
            refreshed_at = float(refreshed_value)
            if not isinstance(context, dict) or refreshed_at <= 0:
                raise ValueError
        except (OctopError, TypeError, ValueError, OverflowError):
            return None
        return profile, dict(context), refreshed_at

    def _local_snapshot(self, local_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
        """Build a minimal offline projection for pre-snapshot installations."""
        row = self.server.services.user_repo.get(local_id)
        if row is None:
            raise OctopError(ErrorCode.AUTH_FAILED, "本机身份不存在，请重新登录", status=401)
        profile = {
            "id": local_id,
            "username": row.username,
            "role": row.role,
            "display_name": row.display_name,
            "locale": row.locale,
            "permissions": list(row.permissions),
        }
        # The context is only a compatibility response for installations
        # upgraded before snapshots were introduced.  The actual model/policy
        # projection is refreshed in the background after the first request.
        context: dict[str, Any] = {
            "name": "云迈智能体",
            "controls": {
                "shell": False,
                "browser": False,
                "desktop": False,
                "filesystem": True,
                "network": True,
            },
            "resource_policy": {},
            "allowed_models": [],
            "default_model": None,
            "offline": True,
        }
        return profile, context

    def _sync_local_projection(
        self, local_id: int, profile: dict[str, Any], context: dict[str, Any]
    ) -> None:
        """Apply a trusted remote projection before permission-gated routing.

        The desktop JWT identifies a passwordless local row.  Older clients
        could keep a cached ``User`` object with empty permissions even after
        the control plane had granted channels, skills, or knowledge access.
        Refreshing the encrypted snapshot alone was insufficient because
        ``current_user`` resolves the in-memory row before middleware runs.
        Keep the row and the manager cache aligned whenever a snapshot is
        served.
        """
        row = self.server.services.user_repo.get(local_id)
        if row is None:
            return
        permissions = self.local_permissions(profile, context)
        role = "admin" if profile.get("role") == "admin" else "user"
        if row.role != role or sorted(row.permissions) != sorted(permissions):
            DeploymentRepo(self.server.services.db).update_profile(local_id, profile)
            self.server.services.user_repo.set_permissions(local_id, permissions)
        self.cache_user(local_id)

    async def _background_refresh(self, local_id: int) -> None:
        try:
            await self.validate(local_id)
            self._offline_users.discard(local_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Keep serving the last trusted local projection while offline.
            # A 401/403 from validate() revokes the encrypted session, so the
            # next local request will still fail closed.
            self._offline_users.add(local_id)
            return

    def _schedule_refresh(self, local_id: int) -> None:
        task = self._refresh_tasks.get(local_id)
        if task is not None and not task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._background_refresh(local_id))
        self._refresh_tasks[local_id] = task

        def done(completed: asyncio.Task[None]) -> None:
            if self._refresh_tasks.get(local_id) is completed:
                self._refresh_tasks.pop(local_id, None)
            try:
                completed.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        task.add_done_callback(done)

    def cached_identity(self, local_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return the local identity snapshot without a control-plane request.

        Snapshots are soft-TTL: stale data is served while a single detached
        refresh runs.  This keeps local agents/chat/usage pages responsive
        during slow or unavailable management services while still allowing a
        later refresh to revoke disabled accounts and update policy.
        """
        snapshot = self._load_snapshot(local_id)
        if snapshot is None:
            profile, context = self._local_snapshot(local_id)
            self._schedule_refresh(local_id)
            return profile, context
        profile, context, refreshed_at = snapshot
        self._sync_local_projection(local_id, profile, context)
        if time.time() - refreshed_at >= IDENTITY_SNAPSHOT_TTL_SECONDS:
            self._schedule_refresh(local_id)
        if local_id in self._offline_users:
            context = {**context, "offline": True}
        return profile, context

    def identity_refresh_needed(self, local_id: int) -> bool:
        snapshot = self._load_snapshot(local_id)
        return snapshot is None or time.time() - snapshot[2] >= IDENTITY_SNAPSHOT_TTL_SECONDS

    @staticmethod
    def local_permissions(profile: dict[str, Any], context: dict[str, Any]) -> list[str]:
        """Project runtime permissions separately from management privileges.

        ``local_permissions`` is an explicit policy when present.  Older
        management services sent an empty list for admins, so an empty admin
        projection falls back to the complete local catalog; this keeps the
        desktop administrator from receiving 403s on channels/skills while
        still allowing a newer service to send a narrowed non-empty list.
        """
        explicit = context.get("local_permissions")
        policy_version = context.get("local_permissions_version")
        if (
            isinstance(explicit, list)
            and all(isinstance(key, str) for key in explicit)
            and explicit
            and (profile.get("role") != "admin" or explicit)
        ):
            return list(dict.fromkeys(explicit))
        if (
            isinstance(explicit, list)
            and not explicit
            and policy_version == 1
            and profile.get("role") != "admin"
        ):
            return []
        if profile.get("role") == "admin":
            return sorted(ALL_PERMISSION_KEYS)
        permissions = profile.get("permissions")
        if not isinstance(permissions, list):
            return []
        return list(dict.fromkeys(key for key in permissions if isinstance(key, str)))

    async def validate(self, local_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
        async with self.lock:
            return await self._validate(local_id)

    async def _validate(self, local_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
        authority, token = self.bound_session(local_id)
        response = await self.remote("GET", "/auth/me", token=token, authority=authority)
        if response.status_code in {401, 403}:
            self.revoke_session(local_id)
            raise OctopError(
                ErrorCode.AUTH_FAILED, "企业账号已停用、尚未审核或登录过期，请重新登录", status=401
            )
        if response.status_code != 200:
            raise OctopError(
                ErrorCode.INTERNAL_ERROR,
                "企业身份检查失败",
                details={"reason": "企业身份检查失败，请重试或更换服务地址"},
                status=503,
            )
        self.require_authority(authority)
        profile = self.profile(self.response_object(response))
        repo = DeploymentRepo(self.server.services.db)
        if repo.local_identity(authority, profile["id"]) != local_id:
            self.revoke_session(local_id)
            raise OctopError(ErrorCode.AUTH_FAILED, "企业身份与本机会话不匹配，请重新登录", status=401)
        renewed = response.headers.get("X-Octop-Access-Token")
        if renewed:
            self.save_token(local_id, renewed, authority=authority)
        context = await self._refresh_context(local_id)
        repo.update_profile(local_id, profile)
        self.server.services.user_repo.set_permissions(
            local_id, self.local_permissions(profile, context)
        )
        self.cache_user(local_id)
        self._store_snapshot(local_id, profile, context)
        return profile, context

    async def refresh_context(self, local_id: int) -> dict[str, Any]:
        async with self.lock:
            return await self._refresh_context(local_id)

    async def _refresh_context(self, local_id: int) -> dict[str, Any]:
        authority, token = self.bound_session(local_id)
        response = await self.remote(
            "GET", "/auth/deployment/session", token=token, authority=authority
        )
        if response.status_code in {401, 403}:
            self.revoke_session(local_id)
            raise OctopError(ErrorCode.AUTH_FAILED, "企业账号权限已变更，请重新登录", status=401)
        if response.status_code != 200:
            raise OctopError(
                ErrorCode.INTERNAL_ERROR,
                "企业模型与权限下发失败",
                details={"reason": "企业模型与权限下发失败，请重试"},
                status=503,
            )
        self.require_authority(authority)
        context = self.response_object(response)
        if not isinstance(context.get("name"), str) or not isinstance(context.get("controls"), dict):
            raise OctopError(ErrorCode.INTERNAL_ERROR, "企业模型与权限响应无效，请重试", status=503)
        await self._apply_context(local_id, context)
        self.require_authority(authority)
        return context

    async def apply_context(self, local_id: int, context: dict[str, Any]) -> None:
        async with self.lock:
            await self._apply_context(local_id, context)

    async def _apply_context(self, local_id: int, context: dict[str, Any]) -> None:
        services = self.server.services
        name = f"yunmell-managed-{local_id}"
        provider = services.provider_repo.get_by_name(name)
        metadata = context.get("default_model")
        policy = context.get("resource_policy") or {}
        services.user_policy_repo.merge(
            local_id,
            {
                key: str(policy[key]) if policy.get(key) is not None else None
                for key in ["token_quota", "max_agents"]
            },
        )
        relay_key = services.secret_repo.get_or_create(
            f"yunmell.relay:{local_id}", lambda: secrets.token_urlsafe(32).encode()
        ).decode()
        if metadata:
            models = [
                {
                    "id": MODEL,
                    "name": f"{context['name']} / {metadata['name']}",
                    "enabled": True,
                    "input": metadata.get("input") or ["text"],
                    "context_window": metadata.get("context_window"),
                    "max_tokens": metadata.get("max_tokens"),
                }
            ]
            for option in context.get("allowed_models") or []:
                models.append(
                    {
                        "id": f"{option['provider_name']}/{option['model']}",
                        "name": option.get("name") or option["model"],
                        "enabled": True,
                        "input": option.get("input") or ["text"],
                    }
                )
            base = f"http://127.0.0.1:{services.config.port}/api/desktop-model/{local_id}"
            if provider is None:
                services.provider_repo.create(
                    name=name,
                    kind="openai-compatible",
                    base_url=base,
                    api_key=relay_key,
                    models_json=json.dumps(models),
                )
                await self.server.app_runtime.agent_registry.on_provider_changed(provider_name=name)
            elif (
                provider.models_json != json.dumps(models) or not provider.enabled
                or provider.base_url != base or provider.api_key != relay_key
            ):
                services.provider_repo.update(
                    provider.id, models_json=json.dumps(models), enabled=True,
                    base_url=base, api_key=relay_key,
                )
                await self.server.app_runtime.agent_registry.on_provider_changed(provider_name=name)
        elif provider is not None and provider.enabled:
            services.provider_repo.update(provider.id, enabled=False)
            await self.server.app_runtime.agent_registry.on_provider_changed(provider_name=name)
        enterprise = services.enterprise_repo
        org, team = deployment(self.server)
        enterprise.upsert_member(org.organization_id, local_id, team.team_id, "member")
        membership = next(
            item
            for item in enterprise.list_memberships_for_user(local_id)
            if item.organization_id == org.organization_id
        )
        if membership.team_id:
            existing_models = enterprise.list_allowed_models(membership.team_id)
            additions = [(name, MODEL)] + [
                (name, f"{option['provider_name']}/{option['model']}")
                for option in context.get("allowed_models") or []
            ]
            enterprise.replace_allowed_models(
                membership.team_id,
                [(item["provider_name"], item["model"]) for item in existing_models]
                + additions,
            )
            controls = context["controls"]
            current = enterprise.get_control_policy(membership.team_id)
            if current is not None:
                controls = {
                    kind: bool(getattr(current, f"{kind}_enabled")) and bool(controls.get(kind))
                    for kind in ["shell", "browser", "desktop", "filesystem", "network"]
                }
            enterprise.upsert_control_policy(
                membership.team_id,
                **{
                    f"{kind}_enabled": bool(controls.get(kind))
                    for kind in ["shell", "browser", "desktop", "filesystem", "network"]
                },
            )
        if metadata:
            if policy.get("max_agents") == 0:
                return
            agents = self.server.app_runtime.agent_registry.list_agents(local_id)
            if not agents:
                from octop.infra.agents.manager import AgentCreateSpec

                await self.server.app_runtime.agent_registry.create(
                    AgentCreateSpec(
                        name="我的智能体", user_id=local_id, default_model=f"{name}/{MODEL}"
                    )
                )


def bridge(server: Any) -> DesktopIdentityBridge:
    existing = getattr(server, "_yunmell_desktop_bridge", None)
    if existing is None:
        existing = DesktopIdentityBridge(server)
        server._yunmell_desktop_bridge = existing
    return existing
