"""Email verification codes for registration and password recovery.

Codes are stored as a short-lived, rate-limited record in the settings table:
the code is never written in clear text, and each purpose/address pair only
keeps the newest code.  SMTP credentials are encrypted with the existing
connector Fernet key, so this module never invents a second secret format.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any

from octop.infra.connectors.crypto import decrypt_credentials, encrypt_credentials
from octop.infra.users.email import normalize_email

CONFIG_KEY = "auth.email.smtp"
CODE_KEY_PREFIX = "auth.email.code"

CODE_TTL_SECONDS = 10 * 60
RESEND_COOLDOWN_SECONDS = 60
MAX_SENDS_PER_WINDOW = 5
SEND_WINDOW_SECONDS = 60 * 60
MAX_ATTEMPTS = 5

PURPOSES = frozenset({"register", "reset"})


class EmailVerificationError(RuntimeError):
    """Raised with a user-facing reason; the router maps it to HTTP."""

    def __init__(self, code: str, message: str, *, retry_after: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


@dataclass(frozen=True)
class SmtpConfig:
    enabled: bool = False
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    sender: str = ""
    sender_name: str = "云迈智能体"
    use_tls: bool = True
    use_ssl: bool = False

    def public_dict(self) -> dict[str, Any]:
        """Admin view: never returns the stored password."""
        return {
            "enabled": self.enabled,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "sender": self.sender,
            "sender_name": self.sender_name,
            "use_tls": self.use_tls,
            "use_ssl": self.use_ssl,
            "password_configured": bool(self.password),
        }


def load_smtp_config(settings_get: Any, secret_repo: Any) -> SmtpConfig:
    raw = settings_get(CONFIG_KEY)
    if not raw:
        return SmtpConfig()
    try:
        meta = json.loads(raw)
    except (TypeError, ValueError):
        return SmtpConfig()
    if not isinstance(meta, dict):
        return SmtpConfig()
    blob = secret_repo.get(f"{CONFIG_KEY}.password")
    password = ""
    if blob:
        try:
            password = str(decrypt_credentials(secret_repo, blob).get("password") or "")
        except Exception:  # corrupted key/blob must not break login
            password = ""
    return SmtpConfig(
        enabled=bool(meta.get("enabled")),
        host=str(meta.get("host") or ""),
        port=int(meta.get("port") or 587),
        username=str(meta.get("username") or ""),
        password=password,
        sender=str(meta.get("sender") or ""),
        sender_name=str(meta.get("sender_name") or "云迈智能体"),
        use_tls=bool(meta.get("use_tls", True)),
        use_ssl=bool(meta.get("use_ssl", False)),
    )


def save_smtp_config(
    settings_set: Any,
    settings_get: Any,
    secret_repo: Any,
    *,
    enabled: bool,
    host: str,
    port: int,
    username: str,
    password: str | None,
    sender: str,
    sender_name: str,
    use_tls: bool,
    use_ssl: bool,
) -> SmtpConfig:
    """Persist settings; ``password=None`` keeps the stored one."""
    settings_set(
        CONFIG_KEY,
        json.dumps(
            {
                "enabled": bool(enabled),
                "host": host.strip(),
                "port": int(port),
                "username": username.strip(),
                "sender": sender.strip(),
                "sender_name": sender_name.strip(),
                "use_tls": bool(use_tls),
                "use_ssl": bool(use_ssl),
            },
            ensure_ascii=False,
        ),
    )
    if password is not None:
        blob = encrypt_credentials(secret_repo, {"password": password})
        key = f"{CONFIG_KEY}.password"
        # ``rotate`` only updates an existing row; the first save must insert.
        if secret_repo.get(key) is None:
            secret_repo.get_or_create(key, lambda: blob)
        else:
            secret_repo.rotate(key, blob)
    return load_smtp_config(settings_get, secret_repo)


def send_mail(config: SmtpConfig, *, to: str, subject: str, body: str) -> None:
    if not config.enabled or not config.host or not config.sender:
        raise EmailVerificationError(
            "EMAIL_NOT_CONFIGURED", "email delivery is not configured by the administrator"
        )
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((config.sender_name, config.sender))
    message["To"] = to
    message.set_content(body)

    context = ssl.create_default_context()
    try:
        if config.use_ssl:
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                config.host, config.port, timeout=20, context=context
            )
        else:
            client = smtplib.SMTP(config.host, config.port, timeout=20)
        with client as smtp:
            smtp.ehlo()
            if config.use_tls and not config.use_ssl:
                smtp.starttls(context=context)
                smtp.ehlo()
            if config.username:
                smtp.login(config.username, config.password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailVerificationError(
            "EMAIL_SEND_FAILED", f"could not send the verification email: {exc}"
        ) from exc


def _code_key(purpose: str, email: str) -> str:
    return f"{CODE_KEY_PREFIX}.{purpose}.{email}"


def _digest(code: str, salt: str) -> str:
    return hmac.new(salt.encode(), code.encode(), hashlib.sha256).hexdigest()


def issue_code(settings_get: Any, settings_set: Any, purpose: str, email: str) -> str:
    """Create a fresh six-digit code, enforcing resend and hourly limits."""
    if purpose not in PURPOSES:
        raise EmailVerificationError("EMAIL_PURPOSE_INVALID", "unknown verification purpose")
    normalized = normalize_email(email)
    if normalized is None:
        raise EmailVerificationError("EMAIL_INVALID", "a valid email address is required")
    now = int(time.time())
    key = _code_key(purpose, normalized)
    raw = settings_get(key)
    if raw:
        try:
            previous = json.loads(raw)
        except (TypeError, ValueError):
            previous = {}
        last_sent = int(previous.get("sent_at") or 0)
        if now - last_sent < RESEND_COOLDOWN_SECONDS:
            raise EmailVerificationError(
                "EMAIL_TOO_FREQUENT",
                "please wait before requesting another code",
                retry_after=RESEND_COOLDOWN_SECONDS - (now - last_sent),
            )
        window = int(previous.get("window_start") or now)
        sends = int(previous.get("send_count") or 0)
    else:
        window = now
        sends = 0
    if now - window >= SEND_WINDOW_SECONDS:
        window, sends = now, 0
    if sends >= MAX_SENDS_PER_WINDOW:
        raise EmailVerificationError(
            "EMAIL_TOO_FREQUENT",
            "too many codes requested for this address",
            retry_after=max(1, window + SEND_WINDOW_SECONDS - now),
        )
    code = f"{secrets.randbelow(1_000_000):06d}"
    salt = secrets.token_hex(16)
    settings_set(
        key,
        json.dumps(
            {
                "salt": salt,
                "digest": _digest(code, salt),
                "expires_at": now + CODE_TTL_SECONDS,
                "attempts": 0,
                "sent_at": now,
                "window_start": window if sends else now,
                "send_count": sends + 1,
            }
        ),
    )
    return code


def verify_code(settings_get: Any, settings_set: Any, purpose: str, email: str, code: str) -> None:
    """Consume a code on success; count failures against a fixed budget."""
    normalized = normalize_email(email)
    if normalized is None:
        raise EmailVerificationError("EMAIL_INVALID", "a valid email address is required")
    key = _code_key(purpose, normalized)
    raw = settings_get(key)
    if not raw:
        raise EmailVerificationError("EMAIL_CODE_MISSING", "request a verification code first")
    try:
        record = json.loads(raw)
    except (TypeError, ValueError):
        record = {}
    now = int(time.time())
    if int(record.get("expires_at") or 0) <= now:
        settings_set(key, "")
        raise EmailVerificationError("EMAIL_CODE_EXPIRED", "the verification code expired")
    attempts = int(record.get("attempts") or 0)
    if attempts >= MAX_ATTEMPTS:
        settings_set(key, "")
        raise EmailVerificationError(
            "EMAIL_CODE_EXHAUSTED", "too many invalid attempts; request a new code"
        )
    expected = str(record.get("digest") or "")
    actual = _digest(code.strip(), str(record.get("salt") or ""))
    if not hmac.compare_digest(expected, actual):
        record["attempts"] = attempts + 1
        settings_set(key, json.dumps(record))
        raise EmailVerificationError("EMAIL_CODE_INVALID", "the verification code is incorrect")
    # One-shot: clear the code so a replay cannot reset a second password.
    settings_set(key, "")


def render_code_body(code: str, purpose: str) -> tuple[str, str]:
    action = "注册账号" if purpose == "register" else "重置密码"
    subject = f"云迈智能体 — {action}验证码"
    body = (
        f"您好：\n\n您正在进行{action}，验证码为：{code}\n\n"
        f"验证码 {CODE_TTL_SECONDS // 60} 分钟内有效，仅可使用一次。"
        "如非本人操作，请忽略本邮件。\n"
    )
    return subject, body
