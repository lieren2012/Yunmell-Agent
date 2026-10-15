import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

const desktop = vi.hoisted(() => ({ value: true }));
const showDesktopClientUpdates = vi.hoisted(() => vi.fn());
const userCan = vi.hoisted(() => vi.fn(() => false));

vi.mock("../../hooks/useUpdateStatus", () => ({
  useUpdateStatus: () => ({
    status: {
      current_version: "1.0.2b8",
      product_version: "1.0.10b13",
      latest_version: "1.0.10b14",
      has_update: true,
    },
    hasUpdate: true,
  }),
}));
vi.mock("../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ id: 7, username: "member", role: "user" }),
}));
vi.mock("../../utils/permissions", () => ({ userCan }));
vi.mock("../../utils/desktopChrome", () => ({
  isDesktopShell: () => desktop.value,
  showDesktopClientUpdates,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, options?: { defaultValue?: string }) =>
      options?.defaultValue ?? _key,
  }),
}));

import AppVersionBadge from "./index";

beforeEach(() => {
  desktop.value = true;
  userCan.mockReturnValue(false);
  showDesktopClientUpdates.mockReset();
});

it("opens the local client updater for a desktop ordinary user", () => {
  render(
    <MemoryRouter>
      <AppVersionBadge />
    </MemoryRouter>,
  );

  const button = screen.getByRole("button", {
    name: "云迈客户端 v1.0.10b13 有新版本可用，点击打开客户端更新",
  });
  fireEvent.click(button);
  expect(showDesktopClientUpdates).toHaveBeenCalledTimes(1);
});

it("keeps the server update page for an admin", () => {
  userCan.mockReturnValue(true);
  render(
    <MemoryRouter initialEntries={["/"]}>
      <AppVersionBadge />
    </MemoryRouter>,
  );

  fireEvent.click(screen.getByRole("button"));
  expect(showDesktopClientUpdates).not.toHaveBeenCalled();
});
