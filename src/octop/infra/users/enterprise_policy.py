"""Runtime checks for enterprise model policies."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from typing import Any

from octop.infra.errors import ErrorCode, OctopError

_CONCURRENCY_LOCK = Lock()
_ACTIVE_TEAM_TURNS: dict[str, int] = {}


def assert_model_allowed(server: Any, user: Any, model_ref: str | None) -> None:
    """Reject a model outside the user's team allowlist."""
    if not model_ref or bool(getattr(user, "is_admin", False)):
        return
    if not server.services.enterprise_repo.model_allowed_for_user(int(user.id), model_ref):
        raise OctopError(
            ErrorCode.FORBIDDEN,
            "the selected model is not allowed for your team",
            status=403,
        )


def assert_team_quota_available(enterprise_repo: Any, usage_repo: Any, user_id: int) -> None:
    """Enforce configured team token and request ceilings before a turn."""
    for quota, user_ids in enterprise_repo.quotas_for_user(user_id):
        window = {
            "daily": "today",
            "weekly": "last_7d",
            "monthly": f"month:{datetime.now(UTC):%Y-%m}",
        }.get(quota.period, "all")
        totals = usage_repo.totals_for_users(user_ids, window=window)
        if quota.token_limit is not None and totals["total_tokens"] >= quota.token_limit:
            raise OctopError(
                ErrorCode.FORBIDDEN, "your team token quota has been exhausted", status=429
            )
        if quota.request_limit is not None and totals["model_calls"] >= quota.request_limit:
            raise OctopError(
                ErrorCode.FORBIDDEN, "your team request quota has been exhausted", status=429
            )


def acquire_team_concurrency(enterprise_repo: Any, user_id: int) -> tuple[str, ...]:
    """Reserve one active turn for every configured team concurrency limit."""
    quotas = [
        quota
        for quota, _ in enterprise_repo.quotas_for_user(user_id)
        if quota.concurrency_limit is not None
    ]
    if not quotas:
        return ()
    with _CONCURRENCY_LOCK:
        blocked = [
            quota.team_id
            for quota in quotas
            if _ACTIVE_TEAM_TURNS.get(quota.team_id, 0) >= quota.concurrency_limit
        ]
        if blocked:
            raise OctopError(
                ErrorCode.FORBIDDEN,
                "your team concurrency quota has been exhausted",
                status=429,
            )
        for quota in quotas:
            _ACTIVE_TEAM_TURNS[quota.team_id] = _ACTIVE_TEAM_TURNS.get(quota.team_id, 0) + 1
    return tuple(quota.team_id for quota in quotas)


def release_team_concurrency(team_ids: tuple[str, ...]) -> None:
    if not team_ids:
        return
    with _CONCURRENCY_LOCK:
        for team_id in team_ids:
            current = _ACTIVE_TEAM_TURNS.get(team_id, 0)
            if current <= 1:
                _ACTIVE_TEAM_TURNS.pop(team_id, None)
            else:
                _ACTIVE_TEAM_TURNS[team_id] = current - 1
