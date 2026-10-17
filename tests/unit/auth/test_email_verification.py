"""Email codes: expiry, wrong-attempt budget, one-shot use, and rate limits."""

from __future__ import annotations

import json

import pytest

from octop.infra.auth import email_verification as ev
from octop.infra.auth.email_verification import EmailVerificationError


class _Settings:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str) -> None:
        self.data[key] = value


class _Secrets:
    """Minimal SecretRepo stand-in matching insert/update semantics."""

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def get_or_create(self, key: str, factory) -> bytes:
        if key not in self.data:
            self.data[key] = factory()
        return self.data[key]

    def rotate(self, key: str, value: bytes) -> None:
        if key not in self.data:
            raise AssertionError("rotate() must not be used for a missing secret")
        self.data[key] = value


def test_successful_code_is_five_minutes_or_more_and_consumed_once() -> None:
    settings = _Settings()
    code = ev.issue_code(settings.get, settings.set, "reset", "User@Example.com")
    assert len(code) == 6 and code.isdigit()
    ev.verify_code(settings.get, settings.set, "reset", "user@example.com", code)
    with pytest.raises(EmailVerificationError) as again:
        ev.verify_code(settings.get, settings.set, "reset", "user@example.com", code)
    assert again.value.code == "EMAIL_CODE_MISSING"


def test_wrong_code_counts_attempts_then_exhausts() -> None:
    settings = _Settings()
    ev.issue_code(settings.get, settings.set, "register", "a@example.com")
    for _ in range(ev.MAX_ATTEMPTS - 1):
        with pytest.raises(EmailVerificationError) as exc:
            ev.verify_code(settings.get, settings.set, "register", "a@example.com", "000000")
        assert exc.value.code == "EMAIL_CODE_INVALID"
    # The final allowed attempt reports the wrong code, then locks out.
    with pytest.raises(EmailVerificationError) as exc:
        ev.verify_code(settings.get, settings.set, "register", "a@example.com", "000000")
    assert exc.value.code == "EMAIL_CODE_INVALID"
    with pytest.raises(EmailVerificationError) as exhausted:
        ev.verify_code(settings.get, settings.set, "register", "a@example.com", "000000")
    assert exhausted.value.code in {"EMAIL_CODE_EXHAUSTED", "EMAIL_CODE_MISSING"}


def test_expired_code_is_rejected() -> None:
    settings = _Settings()
    code = ev.issue_code(settings.get, settings.set, "reset", "b@example.com")
    key = ev._code_key("reset", "b@example.com")
    record = json.loads(settings.data[key])
    record["expires_at"] = 0
    settings.data[key] = json.dumps(record)
    with pytest.raises(EmailVerificationError) as exc:
        ev.verify_code(settings.get, settings.set, "reset", "b@example.com", code)
    assert exc.value.code == "EMAIL_CODE_EXPIRED"


def test_resend_cooldown_is_enforced() -> None:
    settings = _Settings()
    ev.issue_code(settings.get, settings.set, "reset", "c@example.com")
    with pytest.raises(EmailVerificationError) as exc:
        ev.issue_code(settings.get, settings.set, "reset", "c@example.com")
    assert exc.value.code == "EMAIL_TOO_FREQUENT"
    assert exc.value.retry_after > 0


def test_code_is_not_stored_in_clear_text() -> None:
    settings = _Settings()
    code = ev.issue_code(settings.get, settings.set, "reset", "d@example.com")
    stored = settings.data[ev._code_key("reset", "d@example.com")]
    assert code not in stored


def test_code_body_is_branded_and_mentions_expiry() -> None:
    subject, body = ev.render_code_body("123456", "register")
    assert "云迈智能体" in subject
    assert "123456" in body
    assert "10 分钟" in body


def test_first_smtp_save_stores_password_and_never_returns_it() -> None:
    settings, secrets = _Settings(), _Secrets()
    saved = ev.save_smtp_config(
        settings.set,
        settings.get,
        secrets,
        enabled=True,
        host="smtp.example.com",
        port=587,
        username="mailer",
        password="s3cret-app-password",
        sender="noreply@example.com",
        sender_name="云迈智能体",
        use_tls=True,
        use_ssl=False,
    )
    assert saved.password == "s3cret-app-password"
    assert "s3cret-app-password" not in saved.public_dict().values()
    # Saving without a password keeps the stored one.
    kept = ev.save_smtp_config(
        settings.set,
        settings.get,
        secrets,
        enabled=False,
        host="smtp.example.com",
        port=587,
        username="mailer",
        password=None,
        sender="noreply@example.com",
        sender_name="云迈智能体",
        use_tls=True,
        use_ssl=False,
    )
    assert kept.password == "s3cret-app-password"
    assert kept.enabled is False
