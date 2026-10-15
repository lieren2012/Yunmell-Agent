"""Desktop settings preserve explicit addresses and inherit omitted defaults."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI

from octop.api.middleware.deployment_desktop import install
from octop.infra.deployment.connection import management_address
from octop.infra.errors import ErrorCode, OctopError

DEFAULT_ADDRESS = "https://agent-oc.yun.cab"


@pytest.fixture
def desktop_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("OCTOP_DESKTOP_CLIENT", "1")
    monkeypatch.delenv("OCTOP_YUNMELL_CONTROL_PLANE", raising=False)
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    monkeypatch.setenv("OCTOP_CONTROL_PLANE_URL", DEFAULT_ADDRESS)
    return tmp_path / "desktop-settings.json"


def test_absent_settings_inherit_shell_address(desktop_settings):
    assert management_address() == DEFAULT_ADDRESS
    assert not desktop_settings.exists()


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({"port": 18089, "locale": "zh"}, DEFAULT_ADDRESS),
        ({}, DEFAULT_ADDRESS),
        ({"controlPlaneUrl": ""}, ""),
        ({"controlPlaneUrl": None}, ""),
        ({"controlPlaneUrl": "https://custom.example/"}, "https://custom.example"),
        ({"controlPlaneUrl": "http://10.31.3.82:6602"}, "http://10.31.3.82:6602"),
    ],
)
def test_address_precedence_does_not_rewrite_settings(desktop_settings, settings, expected):
    desktop_settings.write_text(json.dumps(settings), encoding="utf-8")
    before = desktop_settings.read_bytes()
    assert management_address() == expected
    assert desktop_settings.read_bytes() == before


@pytest.mark.parametrize("environment", ["", "https://AGENT-OC.YUN.CAB:443/"])
def test_omitted_address_uses_normal_environment_rules(desktop_settings, monkeypatch, environment):
    desktop_settings.write_text('{"port":18089,"locale":"zh"}', encoding="utf-8")
    monkeypatch.setenv("OCTOP_CONTROL_PLANE_URL", environment)
    assert management_address() == (DEFAULT_ADDRESS if environment else "")


@pytest.mark.parametrize(
    "raw",
    [
        "{broken",
        "[]",
        "null",
        '{"controlPlaneUrl":false}',
        '{"controlPlaneUrl":123}',
        '{"controlPlaneUrl":{}}',
        '{"controlPlaneUrl":"ftp://invalid.example"}',
        '{"controlPlaneUrl":"http://user:password@invalid.example"}',
    ],
)
def test_invalid_settings_fail_without_using_another_authority(desktop_settings, raw):
    desktop_settings.write_text(raw, encoding="utf-8")
    with pytest.raises(OctopError) as error:
        management_address()
    assert error.value.status == 503
    assert error.value.code == ErrorCode.INTERNAL_ERROR
    assert desktop_settings.read_text(encoding="utf-8") == raw


def test_server_mode_does_not_read_desktop_settings(desktop_settings, monkeypatch):
    desktop_settings.write_text("{broken", encoding="utf-8")
    monkeypatch.delenv("OCTOP_DESKTOP_CLIENT")
    assert management_address() == ""


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({"port": 18089, "locale": "zh"}, DEFAULT_ADDRESS),
        ({"controlPlaneUrl": ""}, ""),
        ({"controlPlaneUrl": "https://custom.example"}, "https://custom.example"),
    ],
)
async def test_desktop_setup_and_connection_agree_on_effective_address(
    desktop_settings, settings, expected
):
    """Exercise the real middleware routes used before the login page mounts."""
    desktop_settings.write_text(json.dumps(settings), encoding="utf-8")
    app = FastAPI()
    install(app, object())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        connection = await client.get("/api/auth/connection")
        setup = await client.get("/api/setup/status")
    assert connection.status_code == 200
    assert connection.json()["address"] == expected
    assert setup.status_code == 200
    assert setup.json()["connection_required"] is (not bool(expected))
