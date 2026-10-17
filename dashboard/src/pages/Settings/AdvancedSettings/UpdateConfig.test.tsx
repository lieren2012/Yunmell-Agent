import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getChannelStatuses: vi.fn(),
  checkChannel: vi.fn(),
  patchChannelSettings: vi.fn(),
  upgradeChannel: vi.fn(),
}));
vi.mock("../../../api/modules/update", () => ({ updateApi: api }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../../../components/Markdown/LazyMarkdown", () => ({
  default: () => null,
}));
import UpdateConfig from "./UpdateConfig";

beforeEach(() => {
  vi.clearAllMocks();
  api.getChannelStatuses.mockResolvedValue({
    official: {
      channel: "official",
      current_version: "1.0.2b9",
      latest_version: "1.0.3",
      stable_only: true,
    },
    yunmell: {
      channel: "yunmell",
      current_version: "1.0.9",
      latest_version: "1.0.9",
      stable_only: true,
    },
  });
});

it("shows the upstream baseline separately from the Yunmell product version", async () => {
  render(<UpdateConfig />);
  const official = screen.getByRole("region", {
    name: "OpenOct/Octop 官方更新",
  });
  const yunmell = screen.getByRole("region", { name: "云迈自研更新" });
  expect(await within(official).findByText("1.0.2b9")).toBeInTheDocument();
  expect(within(official).queryByText("1.0.9")).not.toBeInTheDocument();
  expect(within(yunmell).getAllByText("1.0.9")).toHaveLength(2);
});

it("an official check failure leaves the Yunmell check usable", async () => {
  api.checkChannel.mockImplementation((channel: string) =>
    channel === "official"
      ? Promise.reject(new Error("offline"))
      : Promise.resolve({
          channel,
          current_version: "1.0.9",
          latest_version: "1.0.10",
          has_update: true,
        }),
  );
  render(<UpdateConfig />);
  await screen.findByText("1.0.2b9");
  fireEvent.click(screen.getByRole("button", { name: "检查官方更新" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "官方更新检查失败",
  );
  fireEvent.click(screen.getByRole("button", { name: "检查云迈更新" }));
  expect(await screen.findByText("1.0.10")).toBeInTheDocument();
  expect(api.checkChannel).toHaveBeenCalledWith("official");
  expect(api.checkChannel).toHaveBeenCalledWith("yunmell");
});
