import { request } from "../request";

export interface UpdateStatus {
  current_version: string;
  /** Yunmell product version; ``current_version`` remains official for API compatibility. */
  product_version?: string;
  /** OpenOct/Octop baseline integrated by this build. */
  official_baseline_version?: string;
  latest_version: string | null;
  has_update: boolean;
  is_editable: boolean;
  /** Non-null when the process was launched via `octop service start` (systemd or launchd). */
  service_mode: "systemd" | "launchd" | null;
  /** True when Octop is spawned by the Wails desktop shell (or ``OCTOP_DESKTOP=1``). */
  desktop?: boolean;
  error: string | null;
  /** Stable error code (e.g. "pypi_unreachable") for localized UI messages; null on success. */
  error_code: string | null;
  /** Mirror that served the version info (null/`pypi.org` = official source). */
  source: string | null;
  last_check_time: string | null;
  /** Markdown changelog for latest_version, null if not available. */
  release_notes: string | null;
  /** When true (default), automatic checks ignore pre-releases. */
  stable_only?: boolean;
  /** True when latest_version is a PEP 440 pre-release. */
  latest_is_prerelease?: boolean;
}

export type UpdateChannel = "official" | "yunmell";

export interface UpdateChannelStatus {
  channel: UpdateChannel;
  current_version: string;
  latest_version: string | null;
  has_update: boolean;
  latest_is_prerelease: boolean;
  release_notes: string | null;
  source: string | null;
  source_url: string | null;
  error: string | null;
  last_check_time: string | null;
  stable_only: boolean;
  baseline_commit: string | null;
  upgrade_mode: "upstream_sync" | "release";
}

export interface UpgradeStarted {
  task_id: string;
  status: "started";
}

export interface UpgradeProgress {
  task_id: string;
  status: "running" | "complete" | "error";
  stage: string | null;
  percent: number | null;
  new_version: string | null;
  success: boolean | null;
  error: string | null;
  mirror_errors: string[] | null;
}

export interface RestartResponse {
  status: "restarting";
  service_mode: string;
}

export const updateApi = {
  getChannelStatuses: () =>
    request<Record<UpdateChannel, UpdateChannelStatus>>(
      "/update/channels/status",
    ),
  checkChannel: (channel: UpdateChannel) =>
    request<UpdateChannelStatus>(`/update/channels/${channel}/check`, {
      method: "POST",
    }),
  patchChannelSettings: (channel: UpdateChannel, stableOnly: boolean) =>
    request<UpdateChannelStatus>(`/update/channels/${channel}/settings`, {
      method: "PATCH",
      body: JSON.stringify({ stable_only: stableOnly }),
    }),
  upgradeChannel: (channel: UpdateChannel, version?: string | null) =>
    request<{
      channel: UpdateChannel;
      status: string;
      task_id?: string;
      source_url?: string | null;
      version?: string | null;
    }>(`/update/channels/${channel}/upgrade`, {
      method: "POST",
      body: JSON.stringify({ version: version || null }),
    }),
  getUpdateStatus: () => request<UpdateStatus>("/update/status"),
  checkForUpdates: () =>
    request<UpdateStatus>("/update/check", { method: "POST" }),
  patchSettings: (stableOnly: boolean) =>
    request<UpdateStatus & { stable_only: boolean }>("/update/settings", {
      method: "PATCH",
      body: JSON.stringify({ stable_only: stableOnly }),
    }),
  triggerUpgrade: (version?: string | null) =>
    request<UpgradeStarted>("/update/upgrade", {
      method: "POST",
      body: JSON.stringify({ version: version || null }),
    }),
  getUpgradeProgress: (taskId: string) =>
    request<UpgradeProgress>(
      `/update/progress?task_id=${encodeURIComponent(taskId)}`,
    ),
  restartService: () =>
    request<RestartResponse>("/update/restart", { method: "POST" }),
};
