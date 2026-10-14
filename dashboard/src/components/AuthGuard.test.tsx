import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { useEffect } from "react";
import AuthGuard from "./AuthGuard";

vi.mock("../api/modules/auth", () => ({
  authApi: {
    getAuthStatus: vi.fn(),
    me: vi.fn(),
  },
}));

vi.mock("../api/request", () => ({
  AUTH_TOKEN_CHANGED_EVENT: "octop:auth-token-changed",
  AUTH_TOKEN_STORAGE_KEY: "auth_token",
  getAuthToken: vi.fn(() => null),
  clearAuthToken: vi.fn(),
}));

vi.mock("../utils/locale", () => ({
  applyUserLocale: vi.fn(() => Promise.resolve()),
}));

import { authApi } from "../api/modules/auth";
import { getAuthToken } from "../api/request";

describe("AuthGuard offline boot", () => {
  beforeEach(() => {
    vi.mocked(authApi.getAuthStatus).mockReset();
    vi.mocked(authApi.me).mockReset();
    vi.mocked(getAuthToken).mockReset();
    vi.mocked(getAuthToken).mockReturnValue(null);
    localStorage.clear();
    sessionStorage.clear();
  });

  it("shows offline panel instead of the protected shell when setup/status fails", async () => {
    vi.mocked(authApi.getAuthStatus).mockRejectedValue(
      new TypeError("Failed to fetch"),
    );

    render(
      <MemoryRouter>
        <AuthGuard>
          <div>protected-shell</div>
        </AuthGuard>
      </MemoryRouter>,
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(alert.textContent).toMatch(
      /errors\.offlineTitle|Cannot reach|无法连接/,
    );
    expect(
      screen.getByRole("button", { name: /errors\.retry|Retry|重试/ }),
    ).toBeInTheDocument();
    expect(screen.queryByText("protected-shell")).not.toBeInTheDocument();
  });

  it("keeps the authenticated shell mounted across in-app navigations", async () => {
    vi.mocked(getAuthToken).mockReturnValue("tok");
    vi.mocked(authApi.getAuthStatus).mockResolvedValue({
      setup_required: false,
      has_admin: true,
    } as never);
    vi.mocked(authApi.me).mockResolvedValue({
      user_id: 1,
      username: "admin",
      role: "admin",
      locale: "zh",
    } as never);

    function NavProbe() {
      const navigate = useNavigate();
      useEffect(() => {
        navigate("/b");
      }, [navigate]);
      return <div>protected-shell</div>;
    }

    render(
      <MemoryRouter initialEntries={["/a"]}>
        <AuthGuard>
          <Routes>
            <Route path="/a" element={<NavProbe />} />
            <Route path="/b" element={<div>protected-shell</div>} />
          </Routes>
        </AuthGuard>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(authApi.me).toHaveBeenCalledTimes(1);
      expect(screen.getByText("protected-shell")).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(authApi.getAuthStatus).toHaveBeenCalledTimes(1);
    });
    // Give route-driven navigate identity churn a tick; gate must not re-run.
    await waitFor(() => {
      expect(screen.getByText("protected-shell")).toBeInTheDocument();
    });
    expect(authApi.getAuthStatus).toHaveBeenCalledTimes(1);
    expect(authApi.me).toHaveBeenCalledTimes(1);
  });

  it("retries auth from the offline panel without leaving a blank shell", async () => {
    vi.mocked(authApi.getAuthStatus)
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValue({
        setup_required: false,
        has_admin: true,
      } as never);
    vi.mocked(getAuthToken).mockReturnValue("tok");
    vi.mocked(authApi.me).mockResolvedValue({
      user_id: 1,
      username: "admin",
      role: "admin",
      locale: "zh",
    } as never);

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AuthGuard>
          <div>protected-shell</div>
        </AuthGuard>
      </MemoryRouter>,
    );

    const retry = await screen.findByRole("button", {
      name: /errors\.retry|Retry|重试/,
    });
    await user.click(retry);
    await waitFor(() => {
      expect(screen.getByText("protected-shell")).toBeInTheDocument();
    });
  });

  it("mounts the cached local shell when the control plane times out", async () => {
    vi.mocked(getAuthToken).mockReturnValue("tok");
    vi.mocked(authApi.getAuthStatus).mockResolvedValue({
      setup_required: false,
      has_admin: true,
    } as never);
    const cachedUser = {
      id: 7,
      username: "member",
      role: "user",
      locale: "zh",
    };
    localStorage.setItem("octop:cached-user", JSON.stringify(cachedUser));
    const timeout = new Error("Request timed out after 15000ms");
    timeout.name = "TimeoutError";
    vi.mocked(authApi.me)
      .mockRejectedValueOnce(timeout)
      .mockResolvedValueOnce({
        ...cachedUser,
        display_name: null,
      } as never);

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <AuthGuard>
          <div>protected-shell</div>
        </AuthGuard>
      </MemoryRouter>,
    );

    expect(await screen.findByText("protected-shell")).toBeInTheDocument();
    expect(screen.getByTestId("auth-offline-banner")).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "重新同步" }));
    await waitFor(() => {
      expect(authApi.me).toHaveBeenCalledTimes(2);
      expect(
        screen.queryByTestId("auth-offline-banner"),
      ).not.toBeInTheDocument();
    });
  });

  it("drops the protected projection when the same tab replaces its token", async () => {
    vi.mocked(getAuthToken).mockReturnValue("admin-token");
    vi.mocked(authApi.getAuthStatus).mockResolvedValue({
      setup_required: false,
      has_admin: true,
    } as never);
    vi.mocked(authApi.me).mockResolvedValue({
      id: 1,
      username: "admin",
      role: "admin",
      locale: "zh",
    } as never);

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <AuthGuard>
          <div>protected-shell</div>
        </AuthGuard>
      </MemoryRouter>,
    );

    expect(await screen.findByText("protected-shell")).toBeInTheDocument();
    act(() => {
      window.dispatchEvent(
        new CustomEvent("octop:auth-token-changed", {
          detail: {
            previous: "admin-token",
            next: "member-token",
            reason: "set",
          },
        }),
      );
    });
    await waitFor(() => {
      expect(screen.queryByText("protected-shell")).not.toBeInTheDocument();
    });
  });
});
