"""Build GitHub Release download-section markdown from a version tag.

Same pattern as clash-verge-rev: interpolate TAG / VERSION into a fixed
filename table. Do not scrape the assets list.

    python3 scripts/release_download_links.py 0.9.31
    python3 scripts/release_download_links.py v0.9.31

The asset table depends on the publishing repository. Upstream Octop ships
``Octop-desktop-*`` installers and FnOS ``.fpk`` packages; the Yunmell fork
releases desktop installers as ``Yunmell-Agent-desktop-*`` and does not build
FnOS packages at all (its ``fnos-build-fpk.yml`` is restricted to
``TencentCloud/Octop``). The repository is taken from ``GITHUB_REPOSITORY``
when running inside Actions, so a fork's release notes never link to assets it
does not publish.
"""

from __future__ import annotations

import argparse
import os
import sys

DEFAULT_REPO = "lieren2012/Yunmell-Agent"
UPSTREAM_REPO = "TencentCloud/Octop"


def resolve_repo() -> str:
    """Repository whose assets the links must point at."""
    return os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO


def desktop_prefix(repo: str) -> str:
    """Asset prefix for the recommended desktop installers."""
    return "Octop-desktop" if repo == UPSTREAM_REPO else "Yunmell-Agent-desktop"


def publishes_fnos(repo: str) -> bool:
    """Only upstream Octop builds and uploads FnOS ``.fpk`` assets."""
    return repo == UPSTREAM_REPO


def split_tag(raw: str) -> tuple[str, str]:
    """Return ``(tag, version)`` — tag always has a leading ``v``."""
    text = raw.strip()
    if not text:
        raise ValueError("version is empty")
    version = text[1:] if text.startswith("v") else text
    return f"v{version}", version


def asset_url(tag: str, filename: str, repo: str) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/{filename}"


def md_link(label: str, tag: str, filename: str, repo: str) -> str:
    return f"[{label}]({asset_url(tag, filename, repo)})"


def desktop_name(os_name: str, arch: str, version: str, ext: str, repo: str) -> str:
    return f"{desktop_prefix(repo)}-{os_name}-{arch}-{version}.{ext}"


def portable_name(os_name: str, arch: str, version: str) -> str:
    return f"Octop-portable-{os_name}-{arch}-{version}.zip"


def render_download_section(raw_version: str, repo: str | None = None) -> str:
    repo = repo or resolve_repo()
    tag, version = split_tag(raw_version)

    def desktop(os_name: str, arch: str, ext: str) -> str:
        return desktop_name(os_name, arch, version, ext, repo)

    win64 = md_link("64-bit (Recommended)", tag, desktop("windows", "amd64", "exe"), repo)
    win_arm = md_link("ARM64", tag, desktop("windows", "arm64", "exe"), repo)
    win64_zip = md_link("64-bit", tag, portable_name("windows", "amd64", version), repo)
    win_arm_zip = md_link("ARM64", tag, portable_name("windows", "arm64", version), repo)
    mac_arm = md_link("Apple Silicon", tag, desktop("darwin", "arm64", "dmg"), repo)
    mac_intel = md_link("Intel", tag, desktop("darwin", "amd64", "dmg"), repo)
    mac_arm_zip = md_link("Apple Silicon", tag, portable_name("darwin", "arm64", version), repo)
    mac_intel_zip = md_link("Intel", tag, portable_name("darwin", "amd64", version), repo)
    linux64 = md_link("64-bit", tag, desktop("linux", "amd64", "tar.gz"), repo)
    linux_arm = md_link("ARM64", tag, desktop("linux", "arm64", "tar.gz"), repo)
    linux64_zip = md_link("64-bit", tag, portable_name("linux", "amd64", version), repo)
    linux_arm_zip = md_link("ARM64", tag, portable_name("linux", "arm64", version), repo)

    lines = [
        "",
        "## Downloads",
        "",
        "### Windows",
        "",
        "#### Desktop installer (Recommended)",
        f"- {win64} | {win_arm}",
        "",
        "#### Portable",
        f"- {win64_zip} | {win_arm_zip}",
        "",
        "### macOS",
        "",
        "#### Desktop installer (Recommended)",
        f"- {mac_arm} | {mac_intel}",
        "",
        "#### Portable",
        f"- {mac_arm_zip} | {mac_intel_zip}",
        "",
        "### Linux",
        "",
        "#### Desktop installer (Recommended)",
        f"- {linux64} | {linux_arm}",
        "",
        "#### Portable",
        f"- {linux64_zip} | {linux_arm_zip}",
        "",
    ]

    if publishes_fnos(repo):
        fnos_docker = md_link(
            "Docker (recommended; x86 and ARM)", tag, f"Octop-fnos-docker-{version}.fpk", repo
        )
        fnos_native = md_link("Native x86_64", tag, f"Octop-fnos-native-{version}.fpk", repo)
        fnos_native_arm = md_link(
            "Native ARM64 (no Docker)", tag, f"Octop-fnos-native-arm64-{version}.fpk", repo
        )
        lines += [
            "### fnOS NAS",
            f"- {fnos_docker} | {fnos_native} | {fnos_native_arm}",
            "",
        ]

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print Octop GitHub Release download markdown.")
    parser.add_argument("version", help="Package version, with or without a leading v")
    parser.add_argument(
        "--repo",
        default=None,
        help="Target repository owner/name (defaults to $GITHUB_REPOSITORY or the Yunmell fork)",
    )
    args = parser.parse_args(argv)
    sys.stdout.write(render_download_section(args.version, args.repo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
