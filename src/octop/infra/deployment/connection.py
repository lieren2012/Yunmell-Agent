"""Desktop connection configuration, separate from the deployment display name."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from octop.infra.errors import ErrorCode, OctopError


def desktop_mode() -> bool:
    return os.environ.get("OCTOP_DESKTOP_CLIENT") == "1"


def control_plane_only() -> bool:
    return os.environ.get("OCTOP_YUNMELL_CONTROL_PLANE") == "1"


def normalize_address(value: str) -> str:
    value = value.strip()
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
        valid = (
            parsed.scheme in {"http", "https"}
            and hostname
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
            and not any(character.isspace() or ord(character) < 32 for character in value)
            and "\\" not in value
        )
    except ValueError:
        valid = False
    if not valid:
        raise OctopError(
            ErrorCode.SLASH_BAD_ARGS,
            "请填写完整的 http(s) 服务地址，不包含企业代码、密码或查询参数",
            status=400,
        )
    assert hostname is not None
    host = f"[{hostname.lower()}]" if ":" in hostname else hostname.lower()
    if port is not None and (parsed.scheme, port) not in {("http", 80), ("https", 443)}:
        host += f":{port}"
    return urlunsplit((parsed.scheme, host, parsed.path.rstrip("/"), "", ""))


def management_address() -> str:
    if not desktop_mode():
        return ""
    path = Path(os.environ.get("OCTOP_HOME") or Path.home() / ".octop") / "desktop-settings.json"
    if path.exists():
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(settings, dict):
                raise ValueError
            # Older desktop settings may contain only port/locale. In that
            # case the shell supplies its default in the launch environment;
            # an explicit saved empty value must still mean "disconnected".
            if "controlPlaneUrl" in settings:
                value = settings["controlPlaneUrl"]
                if value is not None and not isinstance(value, str):
                    raise ValueError
                return normalize_address(value) if value else ""
        except (ValueError, OSError, OctopError):
            raise OctopError(
                ErrorCode.INTERNAL_ERROR, "连接设置文件无效，请更换服务地址", status=503
            ) from None
    value = os.environ.get("OCTOP_CONTROL_PLANE_URL", "")
    return normalize_address(value) if value else ""


def save_address(value: str) -> str:
    address = normalize_address(value)
    path = Path(os.environ.get("OCTOP_HOME") or Path.home() / ".octop") / "desktop-settings.json"
    try:
        settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(settings, dict):
            raise ValueError
    except (ValueError, OSError):
        # Repair a broken connection file without touching runtime or account data.
        settings = {}
    settings["controlPlaneUrl"] = address
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, filename = tempfile.mkstemp(prefix=".desktop-settings-", dir=path.parent)
    temporary = Path(filename)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(settings, stream, ensure_ascii=False, indent=2)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return address
