"""Runtime checks for enterprise model policies."""

from __future__ import annotations

from typing import Any

from octop.infra.errors import ErrorCode, OctopError


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
