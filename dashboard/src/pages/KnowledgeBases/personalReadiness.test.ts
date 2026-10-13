import { describe, expect, it } from "vitest";
import type { KnowledgeCapability } from "../../api/modules/knowledgeBases";
import { resolvePersonalReadiness } from "./personalReadiness";

function capability(
  overrides: Partial<KnowledgeCapability> = {},
): KnowledgeCapability {
  return {
    feature_enabled: false,
    backend: "onnx",
    selected_model: "",
    provider_id: "",
    prerequisites_ok: false,
    usable: false,
    checks: {
      model_selected: false,
      model_downloaded: false,
      deps_available: false,
      provider_ready: false,
    },
    ocr: {
      enabled: false,
      backend: "onnx",
      model: "rapidocr",
      provider_id: "",
      prerequisites_ok: false,
      usable: false,
      checks: { deps_available: false, provider_ready: false },
    },
    ...overrides,
  };
}

describe("resolvePersonalReadiness", () => {
  it("keeps personal local readiness independent from enterprise feature switch", () => {
    const result = resolvePersonalReadiness(
      capability({
        personal_local: {
          backend: "onnx",
          selected_model: "bge-small",
          checks: { model_downloaded: true, deps_available: true },
          usable: true,
        },
      }),
    );
    expect(result.usable).toBe(true);
    expect(result.canDownload).toBe(false);
  });

  it("offers download when a default local model is listed but not cached", () => {
    const result = resolvePersonalReadiness(
      capability({ personal_local: { selected_model: "bge-small" } }),
      [{ id: "bge-small", name: "BGE Small", downloaded: false }],
    );
    expect(result.downloaded).toBe(false);
    expect(result.canDownload).toBe(true);
    expect(result.usable).toBe(false);
  });

  it("does not offer a second action while a model download is active", () => {
    const result = resolvePersonalReadiness(
      capability({ personal_local: { model: "bge-small" } }),
      [{ id: "bge-small", name: "BGE Small", downloaded: false }],
      { status: "downloading", progress: 0.4, model_name: "bge-small" },
    );
    expect(result.canDownload).toBe(false);
    expect(result.canActivate).toBe(false);
  });

  it("falls back to the legacy capability only when it explicitly reports usable ONNX", () => {
    const result = resolvePersonalReadiness(
      capability({
        feature_enabled: true,
        usable: true,
        prerequisites_ok: true,
        checks: {
          model_selected: true,
          model_downloaded: true,
          deps_available: true,
          provider_ready: true,
        },
      }),
    );
    expect(result.usable).toBe(true);
  });
});
