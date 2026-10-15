import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

const status = vi.hoisted(() => ({
  current_version: "1.0.2b8",
  official_baseline_version: "1.0.2b8",
  product_version: "1.0.10b12",
}));

vi.mock("../../hooks/useUpdateStatus", () => ({
  useUpdateStatus: () => ({ status: status, hasUpdate: false }),
}));
vi.mock("../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ id: 1, username: "member", role: "user" }),
}));
vi.mock("../../utils/permissions", () => ({
  userCan: () => false,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, options?: { defaultValue?: string }) =>
      options?.defaultValue ?? _key,
  }),
}));

import CurrentVersionBadge from "./index";

beforeEach(() => {
  vi.clearAllMocks();
});

it("shows the Yunmell product version and official baseline separately", () => {
  render(
    <MemoryRouter>
      <CurrentVersionBadge />
    </MemoryRouter>,
  );

  expect(screen.getByText("v1.0.10b12")).toBeInTheDocument();
  expect(screen.getByText("官方基线 v1.0.2b8")).toBeInTheDocument();
  expect(
    screen.getByLabelText("云迈产品 v1.0.10b12（官方基线 v1.0.2b8）"),
  ).toBeInTheDocument();
});
