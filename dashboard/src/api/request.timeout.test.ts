import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

vi.mock("./config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
}));

vi.mock("../i18n", () => ({
  default: { language: "zh" },
}));

describe("request timeouts", () => {
  let mod: typeof import("./request");

  beforeEach(async () => {
    vi.useFakeTimers();
    vi.resetModules();
    localStorage.clear();
    sessionStorage.clear();
    mod = await import("./request");
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("bounds a stalled JSON request with a typed timeout", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, options: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            options.signal?.addEventListener("abort", () => {
              reject(
                new DOMException("The operation was aborted.", "AbortError"),
              );
            });
          }),
      ),
    );

    const pending = expect(mod.request("/agents")).rejects.toMatchObject({
      name: "TimeoutError",
      timeoutMs: mod.DEFAULT_REQUEST_TIMEOUT_MS,
    });
    await vi.advanceTimersByTimeAsync(mod.DEFAULT_REQUEST_TIMEOUT_MS);
    await pending;
  });

  it("keeps an explicit caller abort as AbortError", async () => {
    const controller = new AbortController();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, options: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            options.signal?.addEventListener("abort", () => {
              reject(
                new DOMException("The operation was aborted.", "AbortError"),
              );
            });
          }),
      ),
    );

    const pending = expect(
      mod.request("/agents", { signal: controller.signal }),
    ).rejects.toMatchObject({ name: "AbortError" });
    controller.abort();
    await pending;
  });

  it("fails control-plane paths faster than local runtime paths", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, options: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            options.signal?.addEventListener("abort", () => {
              reject(
                new DOMException("The operation was aborted.", "AbortError"),
              );
            });
          }),
      ),
    );

    const pending = expect(mod.request("/auth/me")).rejects.toMatchObject({
      name: "TimeoutError",
      timeoutMs: mod.CONTROL_PLANE_REQUEST_TIMEOUT_MS,
    });
    await vi.advanceTimersByTimeAsync(mod.CONTROL_PLANE_REQUEST_TIMEOUT_MS);
    await pending;
  });

  it("bounds FormData uploads", async () => {
    class TimeoutXHR {
      timeout = 0;
      upload = {} as XMLHttpRequest["upload"];
      ontimeout: (() => void) | null = null;
      onabort: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onload: (() => void) | null = null;

      open() {}
      setRequestHeader() {}
      send() {
        window.setTimeout(() => this.ontimeout?.(), this.timeout);
      }
    }
    vi.stubGlobal(
      "XMLHttpRequest",
      TimeoutXHR as unknown as typeof XMLHttpRequest,
    );

    const pending = expect(
      mod.requestUpload("/auth/me/avatar", new FormData()),
    ).rejects.toMatchObject({
      name: "TimeoutError",
      timeoutMs: mod.DEFAULT_UPLOAD_TIMEOUT_MS,
    });
    await vi.advanceTimersByTimeAsync(mod.DEFAULT_UPLOAD_TIMEOUT_MS);
    await pending;
  });
});
