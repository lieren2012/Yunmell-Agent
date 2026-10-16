"""tests/unit/test_release_download_links.py"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "release_download_links.py"


def _load():
    spec = importlib.util.spec_from_file_location("release_download_links", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_split_tag_accepts_with_or_without_v() -> None:
    mod = _load()
    assert mod.split_tag("0.9.31") == ("v0.9.31", "0.9.31")
    assert mod.split_tag("v0.9.31") == ("v0.9.31", "0.9.31")


def test_download_links_use_yunmell_agent_repository_by_default() -> None:
    mod = _load()
    assert mod.GITHUB_REPO == "lieren2012/Yunmell-Agent"
    assert mod.UPSTREAM_REPO == "TencentCloud/Octop"


def test_render_download_section_matches_github_asset_names(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    mod = _load()
    body = mod.render_download_section("0.9.31")
    base = "https://github.com/lieren2012/Yunmell-Agent/releases/download/v0.9.31"
    assert f"{base}/Yunmell-Agent-desktop-windows-amd64-0.9.31.exe" in body
    assert f"{base}/Yunmell-Agent-desktop-windows-arm64-0.9.31.exe" in body
    assert f"{base}/Octop-portable-windows-amd64-0.9.31.zip" in body
    assert f"{base}/Octop-portable-windows-arm64-0.9.31.zip" in body
    assert f"{base}/Yunmell-Agent-desktop-darwin-arm64-0.9.31.dmg" in body
    assert f"{base}/Yunmell-Agent-desktop-darwin-amd64-0.9.31.dmg" in body
    assert f"{base}/Octop-portable-darwin-arm64-0.9.31.zip" in body
    assert f"{base}/Octop-portable-darwin-amd64-0.9.31.zip" in body
    assert f"{base}/Yunmell-Agent-desktop-linux-amd64-0.9.31.tar.gz" in body
    assert f"{base}/Yunmell-Agent-desktop-linux-arm64-0.9.31.tar.gz" in body
    assert f"{base}/Octop-portable-linux-amd64-0.9.31.zip" in body
    assert f"{base}/Octop-portable-linux-arm64-0.9.31.zip" in body
    assert "pip install" not in body
    assert "## Downloads" in body


def test_yunmell_omits_fnos_section(monkeypatch) -> None:
    """The Yunmell fork publishes no FnOS ``.fpk`` assets, so listing them 404s."""
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    mod = _load()
    body = mod.render_download_section("0.9.31")
    assert "fnOS" not in body
    assert ".fpk" not in body


def test_upstream_octop_keeps_fnos_section(monkeypatch) -> None:
    """Upstream Octop does publish the fnOS packages; keep advertising them."""
    monkeypatch.setenv("GITHUB_REPOSITORY", "TencentCloud/Octop")
    mod = _load()
    assert mod.resolve_repo() == "TencentCloud/Octop"
    assert mod.publishes_fnos(mod.resolve_repo())
    body = mod.render_download_section("0.9.31")
    base = "https://github.com/TencentCloud/Octop/releases/download/v0.9.31"
    assert f"{base}/Octop-fnos-docker-0.9.31.fpk" in body
    assert f"{base}/Octop-fnos-native-0.9.31.fpk" in body
    assert f"{base}/Octop-fnos-native-arm64-0.9.31.fpk" in body
    assert "Docker (recommended; x86 and ARM)" in body
    assert "Native x86_64" in body
    assert "Native ARM64 (no Docker)" in body


def test_repo_resolution_follows_github_repository_env(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "lieren2012/Yunmell-Agent")
    mod = _load()
    assert mod.resolve_repo() == "lieren2012/Yunmell-Agent"
    assert not mod.publishes_fnos(mod.resolve_repo())
