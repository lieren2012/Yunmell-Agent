"""Short lived email verification codes for public auth flows."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass


@dataclass
class _Code:
    value: str
    expires_at: float
    purpose: str


_CODES: dict[tuple[str, str], _Code] = {}
TTL_SECONDS = 600


def issue(email: str, purpose: str) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    _CODES[(email.strip().lower(), purpose)] = _Code(code, time.time() + TTL_SECONDS, purpose)
    return code


def verify(email: str, purpose: str, code: str) -> bool:
    key = (email.strip().lower(), purpose)
    item = _CODES.get(key)
    if (
        item is None
        or item.expires_at < time.time()
        or not secrets.compare_digest(item.value, code.strip())
    ):
        return False
    _CODES.pop(key, None)
    return True
