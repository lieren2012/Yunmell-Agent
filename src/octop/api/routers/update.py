"""Self-update API — mirrors finnie/octop dashboard update flow."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import urllib.request
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Query
from pydantic import BaseModel, Field

from octop.api.deps import current_user, get_server, require_permission
from octop.api.routers.update_store import (
    UpgradeTaskStatus,
    cache_status,
    create_task,
    get_cached_status,
    get_task,
    update_task,
)
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.server import OctopServer
from octop.infra.setup.release_identity import OFFICIAL_BASE_COMMIT, OFFICIAL_BASE_VERSION
from octop.infra.setup.self_update import (
    UpgradeResult,
    fetch_pypi_info,
    get_editable_path,
    get_local_version,
    green_packages_dir,
    is_newer,
    is_prerelease,
    parse_changelog_for_version,
    run_upgrade,
)
from octop.infra.setup.service import (
    ServiceRuntime,
    build_runtime,
    detect_service_mode,
    is_service_installed,
    restart_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/update", tags=["update"])

_STABLE_ONLY_KEY = "update.stable_only"
_CACHE_INTERNAL = frozenset({"latest_any", "latest_stable", "description"})
_CHANNEL_CACHE: dict[str, dict[str, Any]] = {}
_YUNMELL_REPO = os.environ.get("YUNMELL_RELEASE_REPO", "lieren2012/Yunmell-Agent")


class UpdateSettingsBody(BaseModel):
    stable_only: bool = Field(..., description="When true, automatic checks ignore pre-releases")


class UpgradeBody(BaseModel):
    version: str | None = Field(
        default=None,
        description="Pin this release. Defaults to the channel latest (stable when stable_only).",
    )


class ChannelUpgradeBody(BaseModel):
    version: str | None = Field(default=None)


def _read_stable_only(server: Any | None) -> bool:
    """Missing key defaults to true (only remind about stables)."""
    if server is None:
        return True
    raw = server.services.settings_repo.get(_STABLE_ONLY_KEY)
    if raw is None or not str(raw).strip():
        return True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _channel_latest(
    latest_any: str | None,
    latest_stable: str | None,
    *,
    include_prerelease: bool,
) -> str | None:
    if include_prerelease:
        return latest_any
    if latest_stable:
        return latest_stable
    if latest_any and not is_prerelease(latest_any):
        return latest_any
    return None


def _public_status(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in _CACHE_INTERNAL}


def _present_status(
    cached: dict[str, Any],
    *,
    stable_only: bool,
    include_prerelease: bool,
) -> dict[str, Any]:
    current = _channel_current_version("official")
    latest_any = cached.get("latest_any") or cached.get("latest_version")
    latest_stable = cached.get("latest_stable")
    latest = _channel_latest(latest_any, latest_stable, include_prerelease=include_prerelease)
    has_update = bool(latest and is_newer(latest, current))
    description = cached.get("description")
    notes = parse_changelog_for_version(description, latest) if has_update and latest else None
    return {
        "current_version": current,
        "latest_version": latest,
        "latest_any": latest_any,
        "latest_stable": latest_stable,
        "description": description,
        "has_update": has_update,
        "is_editable": get_editable_path() is not None,
        "service_mode": detect_service_mode(),
        "desktop": _is_desktop_process(),
        "error": cached.get("error"),
        "error_code": cached.get("error_code") if cached.get("error") else None,
        "source": cached.get("source") if latest_any is not None else None,
        "last_check_time": cached.get("last_check_time")
        or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "release_notes": notes,
        "stable_only": stable_only,
        "latest_is_prerelease": bool(latest and is_prerelease(latest)),
    }


def _auto_status(cached: dict[str, Any], *, stable_only: bool) -> dict[str, Any]:
    return _public_status(
        _present_status(cached, stable_only=stable_only, include_prerelease=not stable_only)
    )


def _build_status(
    *,
    latest: str | None = None,
    latest_any: str | None = None,
    latest_stable: str | None = None,
    error: str | None = None,
    error_code: str | None = None,
    source: str | None = None,
    description: str | None = None,
    stable_only: bool = True,
    include_prerelease: bool = False,
) -> dict[str, Any]:
    current = _channel_current_version("official")
    if latest_any is None:
        latest_any = latest
    if latest_any is None and error is None:
        info = fetch_pypi_info()
        if info is not None:
            latest_any = info.version
            latest_stable = info.latest_stable
            source = info.source
            description = info.description
    if latest_stable is None and latest_any and not is_prerelease(latest_any):
        latest_stable = latest_any
    payload = _present_status(
        {
            "current_version": current,
            "latest_any": latest_any,
            "latest_stable": latest_stable,
            "description": description,
            "error": error,
            "error_code": error_code,
            "source": source,
        },
        stable_only=stable_only,
        include_prerelease=include_prerelease,
    )
    cache_status(payload)
    return _public_status(payload)


def _resolve_upgrade_target(
    *,
    requested: str | None,
    latest_any: str | None,
    latest_stable: str | None,
    stable_only: bool,
) -> str | None:
    wanted = (requested or "").strip() or None
    if wanted:
        return wanted
    return _channel_latest(latest_any, latest_stable, include_prerelease=not stable_only)


@router.get("/status")
async def update_status(
    _: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Return last check result; re-probe PyPI when the server cache TTL expires."""
    stable_only = _read_stable_only(server)
    cached = get_cached_status()
    if cached is not None:
        return _auto_status(cached, stable_only=stable_only)
    return await asyncio.to_thread(
        _build_status,
        stable_only=stable_only,
        include_prerelease=not stable_only,
    )


@router.post("/check")
async def check_for_updates(
    _: Any = Depends(require_permission("update")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    stable_only = _read_stable_only(server)
    pypi_info = await asyncio.to_thread(fetch_pypi_info)
    if pypi_info is None:
        return await asyncio.to_thread(
            _build_status,
            latest=None,
            error="could not reach PyPI",
            error_code="pypi_unreachable",
            stable_only=stable_only,
            include_prerelease=True,
        )
    return await asyncio.to_thread(
        _build_status,
        latest_any=pypi_info.version,
        latest_stable=pypi_info.latest_stable,
        source=pypi_info.source,
        description=pypi_info.description,
        stable_only=stable_only,
        include_prerelease=True,
    )


@router.patch("/settings")
async def update_settings(
    body: UpdateSettingsBody,
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("update")),
) -> dict[str, Any]:
    """Persist whether automatic checks should ignore pre-release versions."""
    server.services.settings_repo.set(_STABLE_ONLY_KEY, "true" if body.stable_only else "false")
    cached = get_cached_status()
    if cached is None:
        return await asyncio.to_thread(
            _build_status,
            stable_only=body.stable_only,
            include_prerelease=not body.stable_only,
        )
    remapped = _present_status(
        cached, stable_only=body.stable_only, include_prerelease=not body.stable_only
    )
    cache_status(remapped)
    return _public_status(remapped)


async def _upgrade_worker(
    task_id: str,
    *,
    allow_prerelease: bool = False,
    version: str | None = None,
) -> None:
    await update_task(task_id, stage="downloading", percent=20)
    upgrade_task = asyncio.create_task(
        asyncio.to_thread(
            run_upgrade,
            verbose=False,
            allow_prerelease=allow_prerelease,
            version=version,
        )
    )
    percent = 20
    try:
        while True:
            try:
                result: UpgradeResult = await asyncio.wait_for(
                    asyncio.shield(upgrade_task),
                    timeout=5,
                )
                break
            except TimeoutError:
                percent = min(percent + 5, 85)
                await update_task(task_id, stage="installing", percent=percent)
    except Exception as exc:
        logger.exception("upgrade task %s failed unexpectedly", task_id)
        await update_task(
            task_id,
            status=UpgradeTaskStatus.ERROR,
            stage="error",
            percent=None,
            success=False,
            error=str(exc) or type(exc).__name__,
        )
        return
    mirror_errors = result.mirror_errors or None
    if not result.success:
        await update_task(
            task_id,
            status=UpgradeTaskStatus.ERROR,
            stage="error",
            percent=None,
            success=False,
            error=result.error or "upgrade failed",
            mirror_errors=mirror_errors,
        )
        return
    new_version = result.installed_version or version
    await update_task(
        task_id,
        status=UpgradeTaskStatus.COMPLETE,
        stage="complete",
        percent=100,
        new_version=new_version,
        success=True,
        error=None,
        mirror_errors=mirror_errors,
    )


@router.post("/upgrade")
async def trigger_upgrade(
    body: UpgradeBody = Body(default_factory=UpgradeBody),
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("update")),
) -> dict[str, Any]:
    if get_editable_path() is not None:
        raise OctopError(
            ErrorCode.FORBIDDEN,
            "editable installs must be upgraded manually (git pull / uv sync)",
        )
    stable_only = _read_stable_only(server)
    info = await asyncio.to_thread(fetch_pypi_info)
    requested = body.version if body is not None else None
    target = _resolve_upgrade_target(
        requested=requested,
        latest_any=info.version if info else None,
        latest_stable=info.latest_stable if info else None,
        stable_only=stable_only,
    )
    allow_prerelease = bool(target and is_prerelease(target))
    task = await create_task()
    asyncio.create_task(
        _upgrade_worker(task.task_id, allow_prerelease=allow_prerelease, version=target)
    )
    return {"task_id": task.task_id, "status": "started"}


@router.get("/progress")
async def upgrade_progress(
    task_id: str = Query(...),
    _: Any = Depends(require_permission("update")),
) -> dict[str, Any]:
    task = await get_task(task_id)
    if task is None:
        raise OctopError(ErrorCode.NOT_FOUND, "upgrade task not found")
    return {
        "task_id": task.task_id,
        "status": task.status.value,
        "stage": task.stage,
        "percent": task.percent,
        "new_version": task.new_version,
        "success": task.success,
        "error": task.error,
        "mirror_errors": task.mirror_errors,
    }


def _is_desktop_process() -> bool:
    if green_packages_dir() is not None:
        return True
    raw = (os.environ.get("OCTOP_DESKTOP") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _channel_current_version(channel: str) -> str:
    """Return the version owned by this channel, without cross-channel fallback."""
    if channel == "yunmell":
        return os.environ.get("YUNMELL_AGENT_VERSION", get_local_version())
    return OFFICIAL_BASE_VERSION


def _channel_payload(
    channel: str,
    *,
    latest: str | None = None,
    prerelease: bool = False,
    notes: str | None = None,
    source: str | None = None,
    source_url: str | None = None,
    error: str | None = None,
    checked_at: str | None = None,
    stable_only: bool = True,
) -> dict[str, Any]:
    current = _channel_current_version(channel)
    return {
        "channel": channel,
        "current_version": current,
        "latest_version": latest,
        "has_update": bool(latest and is_newer(latest, current)),
        "latest_is_prerelease": prerelease,
        "release_notes": notes,
        "source": source,
        "source_url": source_url,
        "error": error,
        "last_check_time": checked_at,
        "stable_only": stable_only,
        "is_editable": get_editable_path() is not None,
        "service_mode": detect_service_mode(),
        "desktop": _is_desktop_process(),
        "error_code": "source_unreachable" if error else None,
        "baseline_commit": OFFICIAL_BASE_COMMIT if channel == "official" else None,
        "upgrade_mode": "upstream_sync" if channel == "official" else "release",
    }


def _fetch_yunmell_release(*, stable_only: bool = True) -> dict[str, Any]:
    url = f"https://api.github.com/repos/{_YUNMELL_REPO}/releases?per_page=100"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "yunmell-agent-updater/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        releases = json.loads(response.read().decode("utf-8"))
    candidates = [
        release
        for release in releases
        if not release.get("draft")
        and release.get("tag_name")
        and (not stable_only or not release.get("prerelease"))
    ]
    if not candidates:
        raise ValueError("no releases available for this channel")
    data = candidates[0]
    for candidate in candidates[1:]:
        if is_newer(
            str(candidate["tag_name"]).removeprefix("v"), str(data["tag_name"]).removeprefix("v")
        ):
            data = candidate
    tag = str(data.get("tag_name") or "").strip()
    version = tag[1:] if tag.startswith("v") else tag
    return {
        "version": version or None,
        "prerelease": bool(data.get("prerelease")),
        "notes": data.get("body") or None,
        "source": f"github.com/{_YUNMELL_REPO}",
        "source_url": data.get("html_url") or f"https://github.com/{_YUNMELL_REPO}/releases",
    }


def _check_channel(channel: str, *, stable_only: bool = True) -> dict[str, Any]:
    if channel == "official":
        info = fetch_pypi_info()
        if info is None:
            result = _channel_payload(
                channel,
                error="could not reach official PyPI source",
                source="pypi.org",
                source_url="https://pypi.org/project/octop/",
            )
        else:
            latest = (
                (info.latest_stable or (info.version if not is_prerelease(info.version) else None))
                if stable_only
                else info.version
            )
            result = _channel_payload(
                channel,
                latest=latest,
                prerelease=bool(latest and is_prerelease(latest)),
                notes=parse_changelog_for_version(info.description, latest) if latest else None,
                source=info.source or "pypi.org",
                source_url="https://github.com/TencentCloud/Octop/releases",
            )
    elif channel == "yunmell":
        try:
            release = _fetch_yunmell_release(stable_only=stable_only)
            result = _channel_payload(
                channel,
                latest=release["version"],
                prerelease=release["prerelease"],
                notes=release["notes"],
                source=release["source"],
                source_url=release["source_url"],
            )
        except Exception as exc:
            result = _channel_payload(
                channel,
                error=f"could not reach Yunmell Release source: {exc}",
                source=f"github.com/{_YUNMELL_REPO}",
                source_url=f"https://github.com/{_YUNMELL_REPO}/releases",
            )
    else:
        raise OctopError(ErrorCode.SLASH_BAD_ARGS, "unknown update channel", status=400)
    result["stable_only"] = stable_only
    result["last_check_time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _CHANNEL_CACHE[channel] = result
    return result


@router.get("/channels/status")
async def update_channels_status(
    _: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, dict[str, Any]]:
    """Return independent official and Yunmell update lines."""
    return {
        channel: _CHANNEL_CACHE.get(channel)
        or _channel_payload(channel, stable_only=_read_channel_stable_only(server, channel))
        for channel in ("official", "yunmell")
    }


@router.post("/channels/{channel}/check")
async def check_update_channel(
    channel: str,
    _: Any = Depends(require_permission("update")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _check_channel, channel, stable_only=_read_channel_stable_only(server, channel)
    )


def _read_channel_stable_only(server: Any, channel: str) -> bool:
    if channel not in {"official", "yunmell"}:
        raise OctopError(ErrorCode.SLASH_BAD_ARGS, "unknown update channel", status=400)
    raw = server.services.settings_repo.get(f"update.{channel}.stable_only")
    return raw is None or str(raw).strip().lower() in {"1", "true", "yes", "on"}


@router.patch("/channels/{channel}/settings", summary="Set one update channel's release preference")
async def update_channel_settings(
    channel: str,
    body: UpdateSettingsBody,
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("update")),
) -> dict[str, Any]:
    _read_channel_stable_only(server, channel)
    server.services.settings_repo.set(
        f"update.{channel}.stable_only", str(body.stable_only).lower()
    )
    return await asyncio.to_thread(_check_channel, channel, stable_only=body.stable_only)


@router.post("/channels/{channel}/upgrade")
async def upgrade_update_channel(
    channel: str,
    body: ChannelUpgradeBody = Body(default_factory=ChannelUpgradeBody),
    _: Any = Depends(require_permission("update")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Return the channel's release action without overwriting the Yunmell fork.

    Yunmell control-plane Docker/source deployments are upgraded from their
    tagged Release; the API returns that exact source URL so it cannot silently
    run the official Octop updater against the wrong channel.
    """
    if channel in {"yunmell", "official"}:
        info = _CHANNEL_CACHE.get(channel)
        if info is None:
            info = await asyncio.to_thread(
                _check_channel, channel, stable_only=_read_channel_stable_only(server, channel)
            )
        if channel == "official":
            return {
                "channel": channel,
                "status": "upstream_sync_required",
                "source_url": "https://github.com/TencentCloud/Octop/releases",
                "version": body.version or info.get("latest_version"),
            }
        return {
            "channel": channel,
            "status": "release_required",
            "source_url": info.get("source_url"),
            "version": body.version or info.get("latest_version"),
        }
    raise OctopError(ErrorCode.SLASH_BAD_ARGS, "unknown update channel", status=400)


def _restart_desktop_process(server: OctopServer) -> None:
    time.sleep(0.4)

    # Flush SQLite WAL before replacing the process image, otherwise uncheckpointed
    # writes (common in WAL mode) are lost when the connection FD is closed by execv.
    if server.services is not None and getattr(server.services.db, "dialect", None) == "sqlite":
        try:
            with server.services.db.connect() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            server.services.db.close()
        except Exception:
            logger.exception("failed to checkpoint/close database before desktop restart")

    argv = list(getattr(sys, "orig_argv", None) or [sys.executable, *sys.argv])
    os.execv(argv[0], argv)


def _restart_service_task(runtime: ServiceRuntime) -> None:
    try:
        restart_service(runtime)
    except Exception:
        logger.exception("background service restart failed")


@router.post("/restart")
async def restart_service_endpoint(
    background_tasks: BackgroundTasks,
    server: OctopServer = Depends(get_server),
    _: Any = Depends(require_permission("update")),
) -> dict[str, Any]:
    if _is_desktop_process():
        background_tasks.add_task(_restart_desktop_process, server)
        return {"status": "restarting", "service_mode": "desktop"}
    mode = detect_service_mode()
    if mode is None:
        raise OctopError(
            ErrorCode.FORBIDDEN,
            "service restart is only available when OCTOP_SERVICE_MODE is set",
        )
    try:
        runtime = build_runtime(mode=mode)
        if not is_service_installed(
            runtime.mode,
            scope=runtime.scope,
            run_as_user=runtime.run_as_user,
        ):
            raise RuntimeError(
                f"octop system service is not installed (expected unit for mode={runtime.mode})"
            )
    except RuntimeError as exc:
        raise OctopError(ErrorCode.INTERNAL_ERROR, str(exc)) from exc
    except Exception as exc:
        raise OctopError(ErrorCode.INTERNAL_ERROR, str(exc)) from exc
    background_tasks.add_task(_restart_service_task, runtime)
    return {"status": "restarting", "service_mode": mode}
