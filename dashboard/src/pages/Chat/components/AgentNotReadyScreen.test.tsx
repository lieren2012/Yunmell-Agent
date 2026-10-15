import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { OctopAgent } from "../../../context/AgentContext";

const { request, refresh, navigate, t } = vi.hoisted(() => ({
  request: vi.fn(),
  refresh: vi.fn(async () => {}),
  navigate: vi.fn(),
  t: (key: string) => key,
}));

vi.mock("../../../api/request", () => ({ request }));
vi.mock("../../../context/AgentContext", () => ({
  useAgent: () => ({ refresh }),
}));
vi.mock("../../../components/EmptyState", () => ({
  OctopEmptyMascot: () => <span />,
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t }) }));
vi.mock("react-router-dom", () => ({ useNavigate: () => navigate }));

import AgentNotReadyScreen from "./AgentNotReadyScreen";

function agent(overrides: Partial<OctopAgent> = {}): OctopAgent {
  return {
    id: 1,
    agent_id: "local-default",
    name: "My assistant",
    description: null,
    persona_mbti: null,
    default_model: null,
    system_prompt: null,
    template_name: null,
    state: "starting",
    last_error: null,
    icon: null,
    icon_name: null,
    icon_url: null,
    color: null,
    config: { is_default: true },
    is_owner: true,
    ...overrides,
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  request.mockReset();
});
afterEach(() => vi.useRealTimers());

describe("desktop default expert recovery", () => {
  it("polls a marked default and refreshes chat readiness after background startup", async () => {
    request
      .mockResolvedValueOnce({ state: "starting", last_error: null })
      .mockResolvedValueOnce({ state: "running", last_error: null });
    const { unmount } = render(<AgentNotReadyScreen agent={agent()} />);
    await act(async () => {});
    expect(screen.getByText("chat.agentStarting")).toBeInTheDocument();
    expect(screen.queryByText("chat.goToExperts")).not.toBeInTheDocument();
    expect(request).toHaveBeenCalledWith("/agents/local-default/status");
    await act(async () => vi.advanceTimersByTimeAsync(1000));
    expect(refresh).toHaveBeenCalledWith({ silent: true, force: true });
    unmount();
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(request).toHaveBeenCalledTimes(2);
  });

  it("keeps a background failure visible until the user retries", async () => {
    request
      .mockResolvedValueOnce({ state: "starting", last_error: null })
      .mockResolvedValueOnce({
        state: "failed",
        last_error: "Workspace initialization failed",
      });
    render(<AgentNotReadyScreen agent={agent()} />);
    await act(async () => {});
    await act(async () => vi.advanceTimersByTimeAsync(1000));
    expect(
      screen.getByText("Workspace initialization failed"),
    ).toBeInTheDocument();
    expect(request).toHaveBeenCalledTimes(2);
    request.mockImplementation(
      async (_path: string, options?: { method?: string }) =>
        options?.method === "POST"
          ? undefined
          : { state: "running", last_error: null },
    );
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: "experts.retryStart" }),
      );
    });
    expect(request).toHaveBeenCalledWith("/agents/local-default/start", {
      method: "POST",
    });
    expect(refresh).toHaveBeenCalledWith({ silent: true, force: true });
    expect(
      screen.queryByText("Workspace initialization failed"),
    ).not.toBeInTheDocument();
  });

  it("does not auto-start ordinary or remote experts", async () => {
    const { rerender } = render(
      <AgentNotReadyScreen agent={agent({ config: {}, state: "stopped" })} />,
    );
    await act(async () => {});
    expect(request).not.toHaveBeenCalled();
    rerender(
      <AgentNotReadyScreen agent={agent({ state: "stopped", bridge: true })} />,
    );
    await act(async () => {});
    expect(request).not.toHaveBeenCalled();
  });
});
