"""Tests for persisted mailbox verification codes and SMTP readiness."""

from __future__ import annotations

from pathlib import Path

import pytest

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.users import email_verification as verification


@pytest.fixture
def db(tmp_path: Path) -> SqlitePool:
    pool = SqlitePool(tmp_path / "octop.db")
    run_migrations(pool)
    return pool


def test_issue_persists_a_hashed_code_and_consumes_it_once(db: SqlitePool) -> None:
    code, ttl = verification.issue(db, "Alice@Example.com", "register")

    assert len(code) == 6
    assert code.isdecimal()
    assert ttl == verification.TTL_SECONDS
    with db.connect() as conn:
        row = conn.execute(
            "SELECT email, purpose, code_hash, consumed_at FROM email_verification_codes"
        ).fetchone()
    assert row is not None
    assert row["email"] == "alice@example.com"
    assert row["purpose"] == "register"
    assert row["code_hash"] != code
    assert row["consumed_at"] is None

    assert verification.verify(db, "ALICE@example.com", "register", code) is True
    assert verification.verify(db, "alice@example.com", "register", code) is False


def test_issue_applies_cooldown_and_verify_limits_wrong_attempts(db: SqlitePool) -> None:
    code, _ = verification.issue(db, "cooldown@example.com", "reset")
    wrong_code = "000000" if code != "000000" else "111111"

    with pytest.raises(ValueError, match="recently"):
        verification.issue(db, "cooldown@example.com", "reset")

    for _ in range(verification.MAX_ATTEMPTS):
        assert verification.verify(db, "cooldown@example.com", "reset", wrong_code) is False
    assert verification.verify(db, "cooldown@example.com", "reset", code) is False


def test_expired_code_is_rejected(db: SqlitePool, monkeypatch: pytest.MonkeyPatch) -> None:
    now = 2_000_000
    monkeypatch.setattr(verification.time, "time", lambda: now)
    code, _ = verification.issue(db, "expired@example.com", "register")

    monkeypatch.setattr(verification.time, "time", lambda: now + verification.TTL_SECONDS + 1)
    assert verification.verify(db, "expired@example.com", "register", code) is False


def test_smtp_config_requires_enablement_and_credentials() -> None:
    disabled = verification.SmtpConfig(
        host="smtp.example.com",
        port=587,
        tls=True,
        sender="sender@example.com",
        username="sender@example.com",
        password="secret",
        enabled=False,
    )
    enabled = verification.SmtpConfig(**{**disabled.__dict__, "enabled": True})

    assert disabled.ready is False
    assert enabled.ready is True
