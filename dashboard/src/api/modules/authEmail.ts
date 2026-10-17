import { request } from "../request";

export interface SmtpConfig {
  enabled: boolean;
  host: string;
  port: number;
  username: string;
  sender: string;
  sender_name: string;
  use_tls: boolean;
  use_ssl: boolean;
  password_configured: boolean;
}

export const authEmailApi = {
  get: () => request<SmtpConfig>("/admin/auth/email"),
  save: (body: Omit<SmtpConfig, "password_configured"> & { password?: string | null }) =>
    request<SmtpConfig>("/admin/auth/email", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  test: (to: string) =>
    request<{ ok: boolean; to: string }>("/admin/auth/email/test", {
      method: "POST",
      body: JSON.stringify({ to }),
    }),
};
