"""HTTP behaviour for the local ONNX embedding service admin endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

MODEL = "BAAI/bge-small-zh-v1.5"


def _seed_cache(home: Path, model: str) -> None:
    """Lay down a cache that looks like a finished fastembed download."""
    from octop.infra.agents.providers.onnx_service import model_cache_dir

    snap = model_cache_dir(model) / "snapshots" / "abc123"
    (snap / "onnx").mkdir(parents=True)
    (snap / "onnx" / "model_optimized.onnx").write_bytes(b"onnx")


async def test_enable_without_weights_is_rejected(
    env: Any, tmp_octop_home: Path, monkeypatch: Any
) -> None:
    """Enabling a model that was never downloaded must not persist enabled=True."""
    client, _server, auth = env
    from octop.infra.agents.providers import onnx_service

    monkeypatch.setattr(onnx_service, "ensure_local_embedding_deps_async", _ready)

    resp = await client.put(
        "/api/onnx-models/config",
        headers=auth,
        json={"enabled": True, "model": MODEL, "download_if_missing": False},
    )
    assert resp.status_code == 409, resp.text
    assert "not downloaded" in resp.json()["detail"]

    status = await client.get("/api/onnx-models/status", headers=auth)
    assert status.json()["enabled"] is False


async def test_enable_succeeds_once_weights_are_present(
    env: Any, tmp_octop_home: Path, monkeypatch: Any
) -> None:
    client, _server, auth = env
    from octop.infra.agents.providers import onnx_service

    monkeypatch.setattr(onnx_service, "ensure_local_embedding_deps_async", _ready)
    monkeypatch.setattr(onnx_service, "local_embedding_deps_available", lambda: True)
    _seed_cache(tmp_octop_home, MODEL)

    resp = await client.put(
        "/api/onnx-models/config",
        headers=auth,
        json={"enabled": True, "model": MODEL, "download_if_missing": False},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enabled"] is True
    assert body["downloaded"] is True
    assert body["ready"] is True


async def test_activate_reports_downloaded_nested_weights(
    env: Any, tmp_octop_home: Path, monkeypatch: Any
) -> None:
    """Regression: nested per-tower weights used to fail activation."""
    client, _server, auth = env
    from octop.infra.agents.providers import onnx_service

    monkeypatch.setattr(onnx_service, "ensure_local_embedding_deps_async", _ready)
    monkeypatch.setattr(onnx_service, "local_embedding_deps_available", lambda: True)

    model = "jinaai/jina-clip-v1"
    catalog = await client.get("/api/onnx-models/catalog", headers=auth)
    if model not in {item["id"] for item in catalog.json()}:
        import pytest

        pytest.skip("fastembed not installed; jina-clip-v1 absent from catalog")

    snap = onnx_service.model_cache_dir(model) / "snapshots" / "abc123"
    (snap / "onnx").mkdir(parents=True)
    (snap / "onnx" / "text_model.onnx").write_bytes(b"onnx")

    resp = await client.post(
        "/api/knowledge-bases/onnx-activate", headers=auth, json={"model": model}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["downloaded"] is True


async def _ready(*_args: Any, **_kwargs: Any) -> str:
    return "ready"


async def test_knowledge_onnx_test_uses_knowledge_settings_permission(
    env: Any, tmp_octop_home: Path, monkeypatch: Any
) -> None:
    """The settings drawer's check must work for a knowledge-settings admin.

    ``/onnx-models/test`` is gated on ``onnx_models``, which that role need not
    hold, so the knowledge router carries its own probe.
    """
    from tests.support.auth import create_user

    client, _server, admin_auth = env
    from octop.infra.agents.providers import onnx_service

    monkeypatch.setattr(onnx_service, "ensure_local_embedding_deps_async", _ready)
    monkeypatch.setattr(onnx_service, "local_embedding_deps_available", lambda: True)
    monkeypatch.setattr(onnx_service, "embed_texts", lambda _m, _t: [[0.0] * 512])
    _seed_cache(tmp_octop_home, MODEL)

    kb_admin = await create_user(
        client,
        admin_auth,
        username="kb_probe_admin",
        permissions=["knowledge_bases", "knowledge_settings"],
    )

    denied = await client.post("/api/onnx-models/test", headers=kb_admin, json={"model": MODEL})
    assert denied.status_code == 403, denied.text

    allowed = await client.post(
        "/api/knowledge-bases/onnx-test", headers=kb_admin, json={"model": MODEL}
    )
    assert allowed.status_code == 200, allowed.text
    body = allowed.json()
    assert body["ok"] is True
    assert body["dim"] == 512


async def test_knowledge_onnx_test_reports_missing_weights(
    env: Any, tmp_octop_home: Path, monkeypatch: Any
) -> None:
    """A model with no weights yields a local message, never a remote error."""
    client, _server, auth = env
    from octop.infra.agents.providers import onnx_service

    monkeypatch.setattr(onnx_service, "ensure_local_embedding_deps_async", _ready)

    resp = await client.post("/api/knowledge-bases/onnx-test", headers=auth, json={"model": MODEL})
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is False
    assert "not downloaded" in resp.json()["error"]


async def test_personal_user_can_download_recommended_onnx_without_settings_permission(
    env: Any, monkeypatch: Any
) -> None:
    client, _server, admin_auth = env
    from octop.api.routers import knowledge_bases
    from tests.support.auth import create_user

    member_auth = await create_user(
        client,
        admin_auth,
        username="personal-onnx-user",
        permissions=["knowledge_bases"],
    )

    class _State:
        def to_dict(self) -> dict[str, object]:
            return {
                "status": "downloading",
                "progress": 0.1,
                "model_name": MODEL,
                "error": None,
            }

    async def start(model: str) -> _State:
        assert model == MODEL
        return _State()

    monkeypatch.setattr(knowledge_bases.DOWNLOAD_MANAGER, "start_download", start)
    response = await client.post(
        "/api/knowledge-bases/onnx-download",
        headers=member_auth,
        json={"model": MODEL},
    )

    assert response.status_code == 200, response.text
    assert response.json()["model_name"] == MODEL


async def test_personal_capability_is_local_when_enterprise_embedding_is_unconfigured(
    env: Any, monkeypatch: Any
) -> None:
    client, _server, admin_auth = env
    from octop.infra.knowledge import gate

    monkeypatch.setattr(gate, "local_embedding_deps_available", lambda: True)
    monkeypatch.setattr(gate, "is_model_downloaded", lambda _model: False)
    response = await client.get("/api/knowledge-bases/capability", headers=admin_auth)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["personal"]["backend"] == "onnx"
    assert body["personal"]["feature_enabled"] is True
    assert body["personal"]["download_required"] is True
