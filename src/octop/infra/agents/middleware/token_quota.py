"""Reject agent turns when the acting user has exhausted their token quota."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langgraph.config import get_config

from octop.infra.users.enterprise_policy import (
    acquire_team_concurrency,
    assert_team_quota_available,
    release_team_concurrency,
)
from octop.infra.users.resource_policy import assert_token_quota_available


def configurable_user_id() -> int | None:
    try:
        configurable = dict(get_config().get("configurable") or {})
    except RuntimeError:
        return None
    raw = configurable.get("user")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return None


class TokenQuotaMiddleware(AgentMiddleware[Any, Any]):
    """Check the acting user's lifetime token total before an agent turn."""

    def __init__(self, *, policy_repo: Any, usage_repo: Any, enterprise_repo: Any = None) -> None:
        super().__init__()
        self._policies = policy_repo
        self._usage = usage_repo
        self._enterprise = enterprise_repo
        self._active_teams: ContextVar[tuple[str, ...]] = ContextVar(
            "yunmell_active_team_turns", default=()
        )

    def _enforce(self) -> None:
        user_id = configurable_user_id()
        if user_id is not None:
            assert_token_quota_available(self._policies, self._usage, user_id)
            if self._enterprise is not None:
                assert_team_quota_available(self._enterprise, self._usage, user_id)
                self._active_teams.set(acquire_team_concurrency(self._enterprise, user_id))

    def after_agent(self, state: Any, runtime: Any) -> None:
        del state, runtime
        release_team_concurrency(self._active_teams.get())
        self._active_teams.set(())

    async def aafter_agent(self, state: Any, runtime: Any) -> None:
        del state, runtime
        release_team_concurrency(self._active_teams.get())
        self._active_teams.set(())

    def before_agent(self, state: Any, runtime: Any) -> None:
        del state, runtime
        self._enforce()

    async def abefore_agent(self, state: Any, runtime: Any) -> None:
        del state, runtime
        self._enforce()


__all__ = ["TokenQuotaMiddleware", "configurable_user_id"]
