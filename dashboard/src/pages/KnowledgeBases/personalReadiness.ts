import type {
  KnowledgeCapability,
  KnowledgeOnnxDownloadState,
  KnowledgeOnnxModel,
} from "../../api/modules/knowledgeBases";

/**
 * The enterprise knowledge feature and a user's local library have different
 * lifecycles.  Keep the local decision in one small, testable function so a
 * disabled enterprise switch does not accidentally disable personal uploads.
 *
 * ``personal_local`` is optional for compatibility with older servers.  On
 * those servers we only trust the old capability when it explicitly reports a
 * usable local ONNX backend; ``feature_enabled`` alone is never enough.
 */
export type PersonalLocalCapability = {
  backend?: "onnx" | "remote";
  model?: string | null;
  selected_model?: string | null;
  downloaded?: boolean;
  deps_available?: boolean;
  usable?: boolean;
  prerequisites_ok?: boolean;
  download_required?: boolean;
  checks?: {
    model_selected?: boolean;
    model_downloaded?: boolean;
    deps_available?: boolean;
    provider_ready?: boolean;
  };
  ocr?: {
    enabled?: boolean;
    backend?: "onnx" | "remote";
    model?: string | null;
    status?: "not_installed" | "installing" | "ready" | "failed";
    progress?: number;
    error?: string | null;
    deps_available?: boolean;
    usable?: boolean;
  };
};

export type PersonalReadiness = {
  model: string | null;
  downloaded: boolean;
  depsAvailable: boolean;
  usable: boolean;
  ocrUsable: boolean;
  ocrStatus: "not_installed" | "installing" | "ready" | "failed";
  ocrProgress: number;
  ocrError: string | null;
  /** A local model can be downloaded or activated from the personal page. */
  canDownload: boolean;
  canActivate: boolean;
  downloadInProgress: boolean;
};

export function resolvePersonalReadiness(
  capability: KnowledgeCapability | null | undefined,
  catalog: KnowledgeOnnxModel[] = [],
  downloadState?: KnowledgeOnnxDownloadState | null,
): PersonalReadiness {
  const local = capability?.personal_local;
  const legacyModel =
    capability?.backend === "onnx" ? capability.selected_model : null;
  const selectedModel =
    local?.model || local?.selected_model || legacyModel || null;
  const catalogModel = selectedModel
    ? catalog.find((entry) => entry.id === selectedModel)
    : (catalog.find((entry) => entry.downloaded) ??
      catalog.find((entry) => entry.recommended) ??
      catalog[0]);
  const model = selectedModel || catalogModel?.id || null;
  const downloaded = Boolean(
    local?.downloaded ??
    local?.checks?.model_downloaded ??
    catalogModel?.downloaded ??
    (capability?.backend === "onnx" && capability.checks.model_downloaded),
  );
  const depsAvailable = Boolean(
    local?.deps_available ??
    local?.checks?.deps_available ??
    (capability?.backend === "onnx" && capability.checks.deps_available),
  );
  const usable = Boolean(
    local?.usable ??
    (capability?.backend === "onnx" &&
      capability?.usable &&
      downloaded &&
      depsAvailable),
  );
  const ocrUsable = Boolean(
    local?.ocr?.usable ??
    (local?.ocr
      ? local.ocr.backend === "onnx" &&
        Boolean(local.ocr.deps_available ?? local.ocr.checks?.deps_available)
      : capability?.ocr?.backend === "onnx" && capability?.ocr?.usable),
  );
  const ocrStatus =
    local?.ocr?.status ?? (ocrUsable ? "ready" : "not_installed");
  const ocrProgress = Number(local?.ocr?.progress ?? (ocrUsable ? 1 : 0));
  const ocrError = local?.ocr?.error ?? null;
  const activeDownload =
    downloadState?.status === "downloading" ||
    downloadState?.status === "loading";
  return {
    model,
    downloaded,
    depsAvailable,
    usable,
    ocrUsable,
    ocrStatus,
    ocrProgress,
    ocrError,
    canDownload:
      Boolean(model || catalogModel) && !downloaded && !activeDownload,
    canActivate: downloaded && !usable && !activeDownload,
    downloadInProgress: activeDownload,
  };
}

