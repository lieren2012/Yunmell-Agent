import { request } from "../request";

export interface EnterpriseOrganization {
  organization_id: string;
  name: string;
  login_slug?: string | null;
  default_provider_name?: string | null;
  default_model?: string | null;
  registration_review_required?: boolean;
}
export interface EnterpriseTeam {
  team_id: string;
  organization_id: string;
  name: string;
}
export interface EnterpriseMember {
  id: number;
  user_id: number;
  team_id: string | null;
  role: string;
}
export interface TeamQuota {
  team_id: string;
  period: "daily" | "weekly" | "monthly";
  token_limit: number | null;
  request_limit: number | null;
  concurrency_limit: number | null;
}
export interface TeamControls {
  team_id: string;
  shell_enabled: boolean;
  browser_enabled: boolean;
  desktop_enabled: boolean;
  filesystem_enabled: boolean;
  network_enabled: boolean;
}
export interface RegistrationApplication {
  application_id: string;
  organization_id: string;
  user_id: number;
  status: "pending" | "approved" | "rejected" | "needs_info";
  submitted_at: number;
  reviewed_at: number | null;
  reviewed_by: number | null;
  review_note: string | null;
  supplement: string | null;
}

const json = (body: unknown): RequestInit => ({
  method: "PUT",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const enterpriseApi = {
  organizations: () =>
    request<EnterpriseOrganization[]>("/admin/enterprise/organizations"),
  createOrganization: (name: string) =>
    request<EnterpriseOrganization>("/admin/enterprise/organizations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
  saveDefaultModel: (org: string, provider_name: string, model: string) =>
    request<EnterpriseOrganization>(
      `/admin/enterprise/organizations/${org}/default-model`,
      json({ provider_name, model }),
    ),
  saveRegistrationPolicy: (org: string, review_required: boolean) =>
    request<EnterpriseOrganization>(
      `/admin/enterprise/organizations/${org}/registration-policy`,
      json({ review_required }),
    ),
  teams: (org: string) =>
    request<EnterpriseTeam[]>(`/admin/enterprise/organizations/${org}/teams`),
  createTeam: (org: string, name: string) =>
    request<EnterpriseTeam>(`/admin/enterprise/organizations/${org}/teams`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
  members: (org: string) =>
    request<EnterpriseMember[]>(
      `/admin/enterprise/organizations/${org}/members`,
    ),
  upsertMember: (org: string, body: Omit<EnterpriseMember, "id">) =>
    request<EnterpriseMember>(
      `/admin/enterprise/organizations/${org}/members`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  models: (org: string, team: string) =>
    request<{ provider_name: string; model: string }[]>(
      `/admin/enterprise/organizations/${org}/teams/${team}/models`,
    ),
  saveModels: (
    org: string,
    team: string,
    models: { provider_name: string; model: string }[],
  ) =>
    request(
      `/admin/enterprise/organizations/${org}/teams/${team}/models`,
      json({ models }),
    ),
  quota: (org: string, team: string) =>
    request<TeamQuota | null>(
      `/admin/enterprise/organizations/${org}/teams/${team}/quota`,
    ),
  saveQuota: (org: string, team: string, body: Omit<TeamQuota, "team_id">) =>
    request<TeamQuota>(
      `/admin/enterprise/organizations/${org}/teams/${team}/quota`,
      json(body),
    ),
  controls: (org: string, team: string) =>
    request<TeamControls | null>(
      `/admin/enterprise/organizations/${org}/teams/${team}/controls`,
    ),
  saveControls: (
    org: string,
    team: string,
    body: Omit<TeamControls, "team_id">,
  ) =>
    request<TeamControls>(
      `/admin/enterprise/organizations/${org}/teams/${team}/controls`,
      json(body),
    ),
  applications: (org: string, status = "pending") =>
    request<RegistrationApplication[]>(
      `/admin/enterprise/organizations/${org}/registration-applications?status=${status}`,
    ),
  reviewApplication: (
    org: string,
    application: string,
    status: RegistrationApplication["status"],
    note?: string,
  ) =>
    request<RegistrationApplication>(
      `/admin/enterprise/organizations/${org}/registration-applications/${application}/review`,
      json({ status, note }),
    ),
};
