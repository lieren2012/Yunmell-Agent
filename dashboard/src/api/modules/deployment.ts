import { request } from "../request";
import { parseApiError } from "../../utils/apiError";

export interface DeploymentInfo {
  organization_id: string;
  name: string;
  registration_open: boolean;
  review_required: boolean;
}
export interface ConnectionInfo {
  desktop: boolean;
  address: string;
  management_only?: boolean;
}
export interface RegistrationStatus {
  status: "none" | "pending" | "approved" | "rejected" | "needs_info";
  application_id?: string;
  review_note?: string | null;
  name?: string;
}
const timeout = () => ({ signal: AbortSignal.timeout(12000) });
export const deploymentApi = {
  info: () => request<DeploymentInfo>("/auth/deployment", timeout()),
  connection: () => request<ConnectionInfo>("/auth/connection", timeout()),
  connect: (address: string) =>
    request<ConnectionInfo & { name: string }>("/auth/connection", {
      ...timeout(),
      method: "PUT",
      body: JSON.stringify({ address }),
    }),
  status: () =>
    request<RegistrationStatus>(
      "/auth/deployment/registration/status",
      timeout(),
    ),
  register: (body: {
    username: string;
    password: string;
    display_name?: string;
    email: string;
    email_code: string;
  }) =>
    request<RegistrationStatus>("/auth/deployment/register", {
      ...timeout(),
      method: "POST",
      body: JSON.stringify(body),
    }),
  sendEmailCode: (email: string) =>
    request<{ ok: boolean; expires_in: number }>("/auth/email/send-code", {
      ...timeout(),
      method: "POST",
      body: JSON.stringify({ email }),
    }),
};
export function enrollmentError(error: unknown): string {
  if (
    error instanceof Error &&
    ["AbortError", "TimeoutError"].includes(error.name)
  )
    return "连接超时，请重试或更换服务地址。";
  const parsed = parseApiError(error);
  const status = parsed?.details?.registration_status;
  if (status === "pending")
    return "注册申请正在等待管理员审核，审核通过后即可登录。";
  if (status === "rejected") return "注册申请已被驳回，请联系管理员。";
  if (status === "needs_info") return "注册申请需要补充资料，请联系管理员。";
  if (parsed?.code === "USERNAME_TAKEN")
    return "该账号已存在。若你已提交申请，请返回登录查看审核状态。";
  if (typeof parsed?.details?.reason === "string") return parsed.details.reason;
  if (parsed?.message) return parsed.message;
  if (error instanceof TypeError)
    return "无法连接管理服务，请检查网络、重试或更换地址。";
  return "操作失败，请检查填写内容并重试。";
}
