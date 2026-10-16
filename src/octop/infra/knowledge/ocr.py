"""Optional OCR backends for knowledge-base images and scanned PDFs."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from langchain_core.messages import HumanMessage

from octop.infra.agents.providers.model_flags import is_chat_eligible_model, is_vision_model
from octop.infra.agents.providers.probe import build_probe_chat_model
from octop.infra.utils.llm_text import llm_text_content
from octop.infra.utils.runtime_packages import PackageInstallSpec, install_packages

logger = logging.getLogger(__name__)

OCR_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})

_ENABLED_KEY = "knowledge_ocr_enabled"
_BACKEND_KEY = "knowledge_ocr_backend"
_MODEL_KEY = "knowledge_ocr_model"
_PROVIDER_ID_KEY = "knowledge_ocr_provider_id"
_LOCAL_PACKAGES = ("rapidocr>=3.4,<4", "onnxruntime>=1.17", "pymupdf>=1.24")
_LOCAL_SPEC = PackageInstallSpec(packages=_LOCAL_PACKAGES, extra_fallback="knowledge-ocr")
_PDF_SPEC = PackageInstallSpec(packages=("pymupdf>=1.24",), extra_fallback="knowledge-ocr")
_PERSONAL_STATUS_KEY = "knowledge_personal_ocr_status"
_PERSONAL_PROGRESS_KEY = "knowledge_personal_ocr_progress"
_PERSONAL_ERROR_KEY = "knowledge_personal_ocr_error"
_OCR_PROMPT = (
    "Transcribe all visible text in this image exactly. Preserve reading order, headings, "
    "lists, and table rows. Return only the transcription, without commentary."
)

# A remote vision model that never received the image answers with a refusal such as
# "No image was attached. Please upload an image.". That is not source text: indexing it
# poisons the knowledge base and still marks the document ready. Refusals are short and
# addressed to the caller, so require both a short answer and a refusal phrasing; a real
# page that merely mentions uploading an image stays well above the length bound.
_OCR_REFUSAL_MAX_CHARS = 400
_OCR_REFUSAL_RE = re.compile(
    r"no image (?:was |is |has been )?(?:attached|provided|found|received|included)"
    r"|(?:don'?t|do not|can'?t|cannot|unable to|didn'?t) "
    r"(?:see|find|detect|receive|locate)[^.\n]{0,30}(?:image|picture|photo|scan|attachment)"
    r"|please (?:attach|upload|provide|send|share)[^.\n]{0,40}"
    r"(?:image|picture|photo|scan|attachment|file)"
    r"|未(?:收到|看到|检测到|获取到)[^。\n]{0,10}(?:图片|图像|照片|附件)"
    r"|请(?:上传|提供|重新上传|发送)[^。\n]{0,10}(?:图片|图像|照片|附件|文件)",
    re.IGNORECASE,
)


def _is_no_image_refusal(text: str) -> bool:
    """Return ``True`` when OCR output is the model asking for an image, not a transcription."""
    stripped = text.strip()
    if not stripped or len(stripped) > _OCR_REFUSAL_MAX_CHARS:
        return False
    return _OCR_REFUSAL_RE.search(stripped) is not None


_local_engine: Any | None = None
_local_engine_lock = threading.Lock()


def personal_ocr_root() -> Path:
    """Return the persistent model directory for the local OCR runtime."""
    raw = os.environ.get("OCTOP_HOME", "").strip()
    home = Path(raw).expanduser() if raw else Path.home() / ".octop"
    return home / "ocr" / "rapidocr"


def _rapidocr_config_path(model_root: Path) -> Path:
    import rapidocr

    package_config = Path(rapidocr.__file__).resolve().parent / "config.yaml"
    config_path = model_root / "rapidocr-config.yaml"
    if not config_path.exists():
        text = package_config.read_text(encoding="utf-8")
        text = text.replace(
            "model_root_dir: null",
            f"model_root_dir: '{model_root.as_posix()}'",
            1,
        )
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(text, encoding="utf-8")
    return config_path


def rapidocr_models_ready(model_root: Path | None = None) -> bool:
    root = model_root or personal_ocr_root()
    # The default Chinese detector, recognizer, and classifier are all required.
    return len(list(root.glob("*.onnx"))) >= 3 and any(root.glob("*.txt"))


def personal_ocr_status(
    settings_get: Any, model_root: Path | None = None, *, installing: bool = False
) -> dict[str, Any]:
    root = model_root or personal_ocr_root()
    deps = local_ocr_deps_available()
    models = rapidocr_models_ready(root)
    saved = str(settings_get(_PERSONAL_STATUS_KEY) or "not_installed")
    error = str(settings_get(_PERSONAL_ERROR_KEY) or "")
    if deps and models:
        state = "ready"
    elif saved == "installing" and installing:
        state = "installing"
    elif saved == "installing":
        # A persisted installation marker cannot survive a process restart as
        # an active task. Surface it as retryable failure instead of claiming
        # that a dead installer is still running.
        state = "failed"
        if not error:
            error = "OCR 安装被中断，请重试"
    elif saved == "failed":
        state = "failed"
    else:
        state = "not_installed"
    try:
        progress = float(settings_get(_PERSONAL_PROGRESS_KEY) or (1 if state == "ready" else 0))
    except (TypeError, ValueError):
        progress = 0.0
    return {
        "status": state,
        "progress": max(0.0, min(1.0, progress)),
        "error": error or None,
        "deps_available": deps,
        "model_downloaded": models,
        "ready": state == "ready",
        "backend": "onnx",
        "model": "rapidocr",
    }


def set_personal_ocr_status(
    settings_set: Any, *, status: str, progress: float, error: str = ""
) -> None:
    settings_set(_PERSONAL_STATUS_KEY, status)
    settings_set(_PERSONAL_PROGRESS_KEY, str(max(0.0, min(1.0, progress))))
    settings_set(_PERSONAL_ERROR_KEY, error[:1000])


class OcrExtractor(Protocol):
    def __call__(self, path: Path) -> str: ...


@dataclass(frozen=True)
class OcrConfig:
    enabled: bool
    backend: str
    model: str
    provider_id: str


def _as_bool(value: str | None) -> bool:
    if value is None:
        return False
    try:
        decoded: Any = json.loads(value)
    except json.JSONDecodeError:
        decoded = value
    if isinstance(decoded, bool):
        return decoded
    return str(decoded).strip().lower() == "true"


def load_ocr_config(settings_get: Any) -> OcrConfig:
    backend = (settings_get(_BACKEND_KEY) or "onnx").strip().lower()
    return OcrConfig(
        enabled=_as_bool(settings_get(_ENABLED_KEY)),
        backend=backend if backend in {"onnx", "remote"} else "onnx",
        model=(settings_get(_MODEL_KEY) or "").strip(),
        provider_id=(settings_get(_PROVIDER_ID_KEY) or "").strip(),
    )


def local_ocr_deps_available() -> bool:
    try:
        import pymupdf  # noqa: F401
        import rapidocr  # noqa: F401
    except ImportError:
        return False
    return True


def pdf_ocr_deps_available() -> bool:
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        return False
    return True


def ensure_ocr_deps(*, backend: str, model_root: Path | None = None) -> str:
    if backend == "onnx":
        if local_ocr_deps_available():
            return "ready"
        outcome = install_packages(
            _LOCAL_SPEC,
            is_satisfied=local_ocr_deps_available,
            import_modules=("rapidocr", "onnxruntime", "pymupdf"),
        )
        if not local_ocr_deps_available():
            raise RuntimeError("Local OCR components were installed but could not be loaded")
        return outcome
    if pdf_ocr_deps_available():
        return "ready"
    outcome = install_packages(
        _PDF_SPEC,
        is_satisfied=pdf_ocr_deps_available,
        import_modules=("pymupdf",),
    )
    if not pdf_ocr_deps_available():
        raise RuntimeError("PDF OCR components were installed but could not be loaded")
    return outcome


async def ensure_ocr_deps_async(*, backend: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: ensure_ocr_deps(backend=backend))


def ensure_rapidocr_models(model_root: Path | None = None) -> str:
    """Download and verify the detector/classifier/Chinese recognizer models."""
    root = model_root or personal_ocr_root()
    if rapidocr_models_ready(root):
        return "ready"
    import rapidocr

    config_path = _rapidocr_config_path(root)
    rapidocr.download_models(str(config_path))
    if not rapidocr_models_ready(root):
        raise RuntimeError("RapidOCR 中文模型下载完成但校验未通过")
    return "installed"


async def ensure_rapidocr_models_async(model_root: Path | None = None) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: ensure_rapidocr_models(model_root))


def _provider_for_config(provider_repo: Any, config: OcrConfig) -> Any | None:
    if provider_repo is None or not config.provider_id.isdigit():
        return None
    return provider_repo.get(int(config.provider_id))


def _remote_ready(provider: Any | None, model_id: str) -> bool:
    if not (provider and provider.enabled and provider.api_key and provider.base_url and model_id):
        return False
    return any(
        str(model.get("id") or "").strip() == model_id
        and is_chat_eligible_model(
            model,
            provider_name=provider.name,
            provider_api_key=provider.api_key,
        )
        and is_vision_model(model)
        for model in provider.get_models()
    )


def get_ocr_capability(
    settings_get: Any, provider_repo: Any = None, model_root: Path | None = None
) -> dict[str, Any]:
    config = load_ocr_config(settings_get)
    provider = _provider_for_config(provider_repo, config)
    # On a fresh install OCR is disabled and no model is selected.  Loading
    # RapidOCR/ONNX just to populate a disabled status can take seconds and
    # makes the knowledge page appear stuck.  Defer the optional import until
    # the feature is enabled or a model has been selected.
    should_probe_local = config.backend == "onnx" and (config.enabled or bool(config.model))
    deps_available = local_ocr_deps_available() if should_probe_local else False
    models_available = rapidocr_models_ready(model_root) if should_probe_local else False
    prerequisites_ok = (
        deps_available and models_available
        if config.backend == "onnx"
        else _remote_ready(provider, config.model)
    )
    return {
        "enabled": config.enabled,
        "backend": config.backend,
        "model": config.model,
        "provider_id": config.provider_id,
        "prerequisites_ok": prerequisites_ok,
        "usable": config.enabled and prerequisites_ok,
        "checks": {
            "deps_available": (
                deps_available if config.backend == "onnx" else pdf_ocr_deps_available()
            ),
            "model_downloaded": models_available if config.backend == "onnx" else True,
            "provider_ready": _remote_ready(provider, config.model),
        },
    }


def set_ocr_settings(
    settings_set: Any,
    *,
    enabled: bool,
    backend: str | None,
    model: str | None,
    provider_id: str | None,
    provider_repo: Any = None,
) -> None:
    config = validate_ocr_settings(
        enabled=enabled,
        backend=backend,
        model=model,
        provider_id=provider_id,
        provider_repo=provider_repo,
    )
    settings_set(_ENABLED_KEY, "true" if enabled else "false")
    settings_set(_BACKEND_KEY, config.backend)
    settings_set(_MODEL_KEY, config.model if config.backend == "remote" else "rapidocr")
    settings_set(_PROVIDER_ID_KEY, config.provider_id if config.backend == "remote" else "")


def validate_ocr_settings(
    *,
    enabled: bool,
    backend: str | None,
    model: str | None,
    provider_id: str | None,
    provider_repo: Any = None,
) -> OcrConfig:
    selected_backend = (backend or "onnx").strip().lower()
    if selected_backend not in {"onnx", "remote"}:
        raise ValueError("knowledge OCR backend must be onnx or remote")
    selected_model = (model or "").strip()
    selected_provider_id = (provider_id or "").strip()
    # Package/model installation is performed by the caller before settings are
    # persisted. This validation only checks the selected backend and provider.
    if enabled and selected_backend == "remote":
        config = OcrConfig(True, selected_backend, selected_model, selected_provider_id)
        if not _remote_ready(_provider_for_config(provider_repo, config), selected_model):
            raise ValueError("knowledge remote OCR provider is not ready")
    return OcrConfig(enabled, selected_backend, selected_model, selected_provider_id)


def require_ocr_extractor(services: Any) -> OcrExtractor:
    config = load_ocr_config(services.settings_repo.get)
    if not config.enabled:
        raise RuntimeError("knowledge OCR is not enabled")
    if config.backend == "onnx":
        if not local_ocr_deps_available() or not rapidocr_models_ready():
            raise RuntimeError("knowledge local OCR prerequisites are not satisfied")
        return _extract_local
    provider = _provider_for_config(services.provider_repo, config)
    if not _remote_ready(provider, config.model):
        raise RuntimeError("knowledge remote OCR provider is not ready")
    return _RemoteOcr(provider, config.model)


def optional_ocr_extractor(services: Any, *, personal: bool = False) -> OcrExtractor | None:
    """Return an OCR extractor when available for the requested scope.

    Enterprise OCR remains explicitly enabled through the shared settings.
    Personal libraries may use the bundled local RapidOCR runtime without
    inheriting that enterprise switch; remote OCR is never selected locally.
    """
    if personal:
        if not local_ocr_deps_available() or not rapidocr_models_ready():
            return None
        return _extract_local
    if not load_ocr_config(services.settings_repo.get).enabled:
        return None

    def extract(path: Path) -> str:
        return require_ocr_extractor(services)(path)

    return extract


def _image_inputs(path: Path) -> Iterator[tuple[bytes, str]]:
    if path.suffix.lower() != ".pdf":
        media_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(path.suffix.lower(), "image/png")
        yield path.read_bytes(), media_type
        return

    import pymupdf

    pymupdf_api: Any = pymupdf
    document = pymupdf_api.open(path)
    try:
        for page in document:
            yield (
                page.get_pixmap(matrix=pymupdf_api.Matrix(2, 2), alpha=False).tobytes("png"),
                "image/png",
            )
    finally:
        document.close()


def _rapidocr_engine() -> Any:
    global _local_engine
    with _local_engine_lock:
        if _local_engine is None:
            from rapidocr import RapidOCR

            root = personal_ocr_root()
            _local_engine = RapidOCR(config_path=str(_rapidocr_config_path(root)))
        return _local_engine


def _extract_local(path: Path) -> str:
    engine = _rapidocr_engine()
    parts: list[str] = []
    for data, _media_type in _image_inputs(path):
        with _local_engine_lock:
            result = engine(data)
        text = getattr(result, "txts", None)
        if isinstance(text, (list, tuple)):
            page_text = "\n".join(str(line) for line in text if str(line).strip())
        else:
            page_text = str(text or "").strip()
        if page_text:
            parts.append(page_text)
    return "\n\n".join(parts)


class _RemoteOcr:
    def __init__(self, provider: Any, model_id: str) -> None:
        self._model = build_probe_chat_model(provider, model_id=model_id)

    def __call__(self, path: Path) -> str:
        parts: list[str] = []
        for data, media_type in _image_inputs(path):
            encoded = base64.b64encode(data).decode("ascii")
            message = HumanMessage(
                content=[
                    {"type": "text", "text": _OCR_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{encoded}"},
                    },
                ]
            )
            text = llm_text_content(self._model.invoke([message]))
            if not text:
                continue
            if _is_no_image_refusal(text):
                # Indexing a refusal would mark the document ready with junk chunks; an empty
                # result instead fails the document with "no extractable text".
                logger.warning(
                    "remote OCR returned a no-image refusal for %s; treating the page as empty",
                    path.name,
                )
                continue
            parts.append(text)
        return "\n\n".join(parts)
