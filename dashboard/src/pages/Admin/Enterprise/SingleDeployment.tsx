import { useEffect, useState } from "react";
import { Alert, Button, Card, Form, Input, InputNumber, List, Select, Space, Switch, Tabs, Typography, message } from "antd";
import PageShell from "../../../layouts/PageShell";
import UsersListPanel from "../Users/UsersListPanel";
import RolesPanel from "../Users/RolesPanel";
import { request } from "../../../api/request";
import { enterpriseApi, type EnterpriseSmtp, type RegistrationApplication, type TeamControls, type TeamQuota } from "../../../api/modules/enterprise";
import { deploymentApi, enrollmentError, type DeploymentInfo } from "../../../api/modules/deployment";
import { useCurrentUser } from "../../../hooks/useCurrentUser";
import { userCan } from "../../../utils/permissions";
import type { ProviderRow } from "../../Settings/Models/useProviders";

interface Deployment extends DeploymentInfo { team_id: string; default_provider_name?: string | null; default_model?: string | null; }
const initialControls: TeamControls = { team_id: "", shell_enabled: false, browser_enabled: false, desktop_enabled: false, filesystem_enabled: true, network_enabled: true };
export default function SingleDeploymentPage() {
  const [form] = Form.useForm();
  const canManageModels = userCan(useCurrentUser(), "providers");
  const [info, setInfo] = useState<Deployment | null>(null);
  const [address, setAddress] = useState("");
  const [providers, setProviders] = useState<ProviderRow[]>([]);
  const [model, setModel] = useState("");
  const [applications, setApplications] = useState<RegistrationApplication[]>([]);
  const [quota, setQuota] = useState<TeamQuota>({ team_id: "", period: "monthly", token_limit: null, request_limit: null, concurrency_limit: null });
  const [controls, setControls] = useState(initialControls);
  const [smtp, setSmtp] = useState<EnterpriseSmtp>({ host: "", port: 587, tls: true, sender: "", username: "", password_configured: false, enabled: false });
  const [smtpPassword, setSmtpPassword] = useState("");
  const [smtpRecipient, setSmtpRecipient] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = async () => {
    try {
      const value = await request<Deployment>("/admin/enterprise/deployment");
      setInfo(value); form.setFieldsValue({ name: value.name, registration_open: value.registration_open, review_required: value.review_required });
      setModel(value.default_provider_name && value.default_model ? `${value.default_provider_name}/${value.default_model}` : "");
      const [pending, limits, policy, connection, smtpConfig] = await Promise.all([enterpriseApi.applications(value.organization_id), enterpriseApi.quota(value.organization_id, value.team_id), enterpriseApi.controls(value.organization_id, value.team_id), deploymentApi.connection(), enterpriseApi.smtp(value.organization_id)]);
      setApplications(pending); if (limits) setQuota(limits); setControls(policy || initialControls); setAddress(connection.address || window.location.origin);
      setSmtp(smtpConfig);
      if (canManageModels) setProviders(await request<ProviderRow[]>("/admin/providers"));
      setError("");
    } catch (err) { setError(enrollmentError(err)); }
  };
  useEffect(() => { void load(); }, []);
  const run = async (operation: () => Promise<unknown>) => {
    if (busy) return; setBusy(true); setError("");
    try { await operation(); message.success("已保存"); await load(); } catch (err) { setError(enrollmentError(err)); } finally { setBusy(false); }
  };
  const settings = <Space direction="vertical" style={{ width: "100%" }} size="large">
    <Card title="企业设置"><Typography.Paragraph type="secondary">服务地址：{address} · 默认团队</Typography.Paragraph>
      <Form form={form} layout="vertical" disabled={busy} onFinish={values => void run(() => request("/admin/enterprise/deployment", { method: "PUT", body: JSON.stringify(values) }))}>
        <Form.Item name="name" label="企业 / 团队显示名称" rules={[{ required: true, whitespace: true }]}><Input /></Form.Item>
        <Form.Item name="registration_open" label="开放注册" valuePropName="checked"><Switch /></Form.Item>
        <Form.Item name="review_required" label="注册需审核（关闭为免审）" valuePropName="checked"><Switch /></Form.Item>
        <Button type="primary" htmlType="submit" loading={busy}>保存企业设置</Button>
      </Form>
    </Card>
    {canManageModels && <Card title="企业默认模型"><Typography.Paragraph type="secondary">成员及新建智能体自动继承；与管理员个人默认模型分开管理。</Typography.Paragraph>
      <Select aria-label="企业默认模型" showSearch style={{ width: "100%" }} value={model || undefined} onChange={setModel} placeholder="从统一模型管理选择" options={providers.filter(provider => provider.enabled).flatMap(provider => provider.models.filter(item => item.enabled !== false).map(item => ({ value: `${provider.name}/${item.id}`, label: `${provider.name} / ${item.name || item.id}` })))} />
      <Button style={{ marginTop: 12 }} loading={busy} disabled={!info || !model} onClick={() => void run(() => { const [provider, ...parts] = model.split("/"); return enterpriseApi.saveDefaultModel(info!.organization_id, provider, parts.join("/")); })}>保存企业默认模型</Button>
    </Card>}
    <Card title="默认团队配额与本机权限"><Space wrap>
      <Select value={quota.period} onChange={period => setQuota({ ...quota, period })} options={[{ value: "monthly", label: "每月" }, { value: "weekly", label: "每周" }, { value: "daily", label: "每日" }]} />
      {(["token_limit", "request_limit", "concurrency_limit"] as const).map((key, index) => <InputNumber key={key} min={0} aria-label={["Token 配额", "请求次数", "并发数量"][index]} placeholder={["Token 不限", "请求不限", "并发不限"][index]} value={quota[key]} onChange={value => setQuota({ ...quota, [key]: value })} />)}
    </Space><Space wrap style={{ display: "flex", marginTop: 16 }}>{(["shell", "browser", "desktop", "filesystem", "network"] as const).map(kind => {
      const key = `${kind}_enabled` as keyof TeamControls; const labels = { shell: "终端工具", browser: "浏览器工具", desktop: "本机桌面", filesystem: "文件工具", network: "网络工具" };
      return <Space key={kind}>{labels[kind]}<Switch checked={!!controls[key]} onChange={checked => setControls({ ...controls, [key]: checked })} /></Space>;
    })}</Space><Button loading={busy} style={{ marginTop: 16 }} disabled={!info} onClick={() => void run(async () => {
      await enterpriseApi.saveQuota(info!.organization_id, info!.team_id, { period: quota.period, token_limit: quota.token_limit, request_limit: quota.request_limit, concurrency_limit: quota.concurrency_limit });
      await enterpriseApi.saveControls(info!.organization_id, info!.team_id, { shell_enabled: controls.shell_enabled, browser_enabled: controls.browser_enabled, desktop_enabled: controls.desktop_enabled, filesystem_enabled: controls.filesystem_enabled, network_enabled: controls.network_enabled });
    })}>保存配额与本机权限</Button></Card>
    <Card title="企业邮箱 SMTP" extra={<Switch checked={smtp.enabled} onChange={enabled => setSmtp({ ...smtp, enabled })} checkedChildren="启用" unCheckedChildren="停用" />}>
      <Typography.Paragraph type="secondary">用于注册验证码和忘记密码。密码或授权码只写入服务端密钥存储，不会回显。</Typography.Paragraph>
      <Space direction="vertical" style={{ width: "100%" }}>
        <Space wrap>
          <Input aria-label="SMTP 服务器" placeholder="smtp.example.com" value={smtp.host} onChange={event => setSmtp({ ...smtp, host: event.target.value })} />
          <InputNumber aria-label="SMTP 端口" min={1} max={65535} value={smtp.port} onChange={port => setSmtp({ ...smtp, port: Number(port || 587) })} />
          <Space>STARTTLS<Switch checked={smtp.tls} onChange={tls => setSmtp({ ...smtp, tls })} /></Space>
        </Space>
        <Input aria-label="发件人" placeholder="发件人邮箱" value={smtp.sender} onChange={event => setSmtp({ ...smtp, sender: event.target.value })} />
        <Input aria-label="SMTP 账号" placeholder="SMTP 账号" value={smtp.username} onChange={event => setSmtp({ ...smtp, username: event.target.value })} />
        <Input.Password aria-label="SMTP 密码或授权码" placeholder={smtp.password_configured ? "已配置，留空保持不变" : "SMTP 密码或授权码"} value={smtpPassword} onChange={event => setSmtpPassword(event.target.value)} />
        <Space wrap>
          <Button loading={busy} disabled={!info} onClick={() => void run(async () => {
            await enterpriseApi.saveSmtp(info!.organization_id, { host: smtp.host, port: smtp.port, tls: smtp.tls, sender: smtp.sender, username: smtp.username, password: smtpPassword || undefined, enabled: smtp.enabled });
            setSmtpPassword("");
          })}>保存 SMTP 配置</Button>
          <Input aria-label="测试收件人" placeholder="测试收件人邮箱" value={smtpRecipient} onChange={event => setSmtpRecipient(event.target.value)} />
          <Button disabled={!info || !smtpRecipient.trim()} onClick={() => void run(() => enterpriseApi.testSmtp(info!.organization_id, smtpRecipient.trim()))}>测试发送</Button>
        </Space>
      </Space>
    </Card>
  </Space>;
  const approvals = <Card title="注册审核" extra={<Button onClick={() => void load()}>刷新</Button>}><Typography.Paragraph type="secondary">申请人使用现有账号与角色库；审核通过后自动归属默认团队。</Typography.Paragraph>
    <List dataSource={applications} locale={{ emptyText: "暂无待审核申请" }} renderItem={application => <List.Item actions={(["approved", "rejected", "needs_info"] as const).map((status, index) => <Button key={status} disabled={busy} onClick={() => void run(() => enterpriseApi.reviewApplication(info!.organization_id, application.application_id, status))}>{["通过", "驳回", "补充资料"][index]}</Button>)}>账号 ID {application.user_id} · 申请 {application.application_id}</List.Item>} />
  </Card>;
  return <PageShell title="企业管理" subtitle={info?.name || "企业设置、成员、角色与注册审核"}>
    {error && <Alert type="error" message={error} showIcon action={<Button onClick={() => void load()}>重试</Button>} />}
    <Tabs items={[{ key: "settings", label: "企业设置", children: settings }, { key: "members", label: "成员管理", children: <UsersListPanel /> }, { key: "approvals", label: `注册审核${applications.length ? ` (${applications.length})` : ""}`, children: approvals }, { key: "roles", label: "角色权限", children: <RolesPanel /> }]} />
  </PageShell>;
}
