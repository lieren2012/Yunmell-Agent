import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../context/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
}));

vi.mock("../../api/modules/auth", () => ({
  authApi: {
    getAuthStatus: () => Promise.resolve({ setup_required: false }),
    getOauthStatus: () => Promise.resolve({ providers: [] }),
    getCaptcha: () => Promise.resolve({ provider: "none" }),
  },
}));

vi.mock("../../utils/locale", () => ({
  applyGuestLocale: () => Promise.resolve(),
  applyUserLocale: () => Promise.resolve(),
}));

vi.mock("./CaptchaField", () => ({
  default: () => null,
}));

import LoginPage from "./index";

describe("Login forgot-password hint", () => {
  it("shows email reset guidance without exposing local CLI commands", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );

    expect(screen.queryByTestId("login-forgot-password")).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();

    await user.click(screen.getByTestId("login-forgot-password-toggle"));

    const dialog = await screen.findByRole("dialog");
    const hint = screen.getByTestId("login-forgot-password");
    expect(dialog).toContainElement(hint);
    expect(hint.textContent).toMatch(/邮箱验证码/);
    expect(hint.textContent).toMatch(/SMTP/);
    expect(hint.textContent).toMatch(/企业管理员/);
    expect(hint.textContent).not.toMatch(/octop user passwd|--password|docker exec|USERPROFILE/);
    expect(screen.queryByText("Windows")).toBeNull();
    expect(screen.queryByText("Docker")).toBeNull();
  });
});
