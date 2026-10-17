"""The macOS installer must ship Yunmell branding, not upstream Octop copy.

The DMG background is a binary asset, so these assertions are the only
automated guard against upstream artwork coming back via a merge.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from PIL import Image

_ROOT = Path(__file__).resolve().parents[2]
_BACKGROUND = _ROOT / "desktop/src/build/darwin/dmg-background.jpeg"
_RENDER = _ROOT / "scripts/render_dmg_background.py"


def _load_renderer():
    spec = importlib.util.spec_from_file_location("render_dmg_background", _RENDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dmg_background_keeps_finder_window_geometry() -> None:
    # Taskfile resamples 1200x800 @144dpi; a different ratio would crop.
    with Image.open(_BACKGROUND) as image:
        assert image.size == (2560, 1696)


def test_renderer_outputs_yunmell_branding() -> None:
    renderer = _load_renderer()
    source = _RENDER.read_text(encoding="utf-8")
    assert "云迈智能体" in source
    assert "拖入「应用程序」文件夹" in source
    # Upstream copy must not be rendered (the docstring explains the rule).
    assert 'headline = "拖入「应用程序」文件夹"' in source
    assert 'subtitle = "Drag 云迈智能体 into Applications to install"' in source
    assert renderer.WIDTH == 2560
    assert renderer.HEADER_HEIGHT > 0


def test_renderer_regenerates_a_comparable_asset(tmp_path) -> None:
    renderer = _load_renderer()
    out = tmp_path / "background.jpeg"
    renderer.render(out)
    assert out.stat().st_size > 10_000
    with Image.open(out) as image:
        assert image.size == (renderer.WIDTH, renderer.HEIGHT)
