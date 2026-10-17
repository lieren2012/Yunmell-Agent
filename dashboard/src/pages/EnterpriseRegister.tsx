import { useEffect, useRef, useState } from "react";
import { Alert, Button, Card, Form, Input, Space, Typography } from "antd";
import { useNavigate } from "react-router-dom";
import { deploymentApi, enrollmentError, type DeploymentInfo, type RegistrationStatus } from "../api/modules/deployment";

export default function EnterpriseRegisterPage() {
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [info, setInfo] = useState<DeploymentInfo | null>(null);
  const [address, setAddress] = useState("");
  const [status, setStatus] = useState<RegistrationStatus>({ status: "none" });
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [sendingCode, setSendingCode] = useState(false);
  const [codeCooldown, setCodeCooldown] = useState(0);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  useEffect(() => {
    if (codeCooldown <= 0) return;
    const timer = window.setTimeout(() => setCodeCooldown((n) => n - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [codeCooldown]);
  const load = async () => {
    setLoading(true); setError("");
    try {
      const [enterprise, connection, receipt] = await Promise.all([deploymentApi.info(), deploymentApi.connection(), deploymentApi.status()]);
      setInfo(enterprise); setAddress(connection.address || window.location.origin); setStatus(receipt);
    } catch (err) { setError(enrollmentError(err)); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);
  const sendCode = async () => {
    try {
      const email = String(form.getFieldValue("email") || "").trim();
      await form.validateFields(["email"]);
      setSendingCode(true);
      setError("");
      await deploymentApi.sendRegisterCode(email);
      setCodeCooldown(60);
    } catch (err) {
      if (err && typeof err === "object" && "errorFields" in err) return;
      setError(enrollmentError(err));
    } finally {
      setSendingCode(false);
    }
  };
  const submit = async (values: { username: string; password: string; display_name?: string; email: string; email_code?: string }) => {
    if (inFlight.current) return;
    inFlight.current = true; setSubmitting(true); setError("");
    try {
      const result = await deploymentApi.register({ ...values, username: values.username.trim() });
      form.setFieldValue("password", ""); setStatus(result);
    } catch (err) { setError(enrollmentError(err)); }
    finally { inFlight.current = false; setSubmitting(false); }
  };
  const messages = { pending: "申请已提交，正在等待管理员审核。审核通过后即可登录。", approved: "注册已通过，你现在可以返回登录。", rejected: "申请已被驳回，请联系管理员。", needs_info: "管理员要求补充资料，请联系管理员后再次查看状态。", none: "" };
  return <Space direction="vertical" style={{ width: "100%", maxWidth: 480, margin: "8vh auto", display: "flex" }}>
    <Typography.Title level={2}>云迈智能体</Typography.Title>
    <Card title={info ? `加入 ${info.name}` : "企业用户注册"} loading={loading}>
      <Space direction="vertical" style={{ width: "100%" }}>
        {address && <Typography.Text type="secondary">服务地址：{address}</Typography.Text>}
        {error && <Alert type="error" message={error} showIcon role="alert" />}
        {status.status !== "none" ? <>
          <Alert type={status.status === "approved" ? "success" : status.status === "rejected" ? "error" : "info"} message={messages[status.status]} description={status.review_note || undefined} showIcon role="status" />
          <Button onClick={() => void load()}>刷新审核状态</Button>
        </> : info && !info.registration_open ? <Alert type="warning" message="该企业暂未开放注册，请联系管理员。" showIcon /> : info && <Form form={form} layout="vertical" onFinish={values => void submit(values)} disabled={submitting} style={{ width: "100%" }}>
          <Form.Item name="username" label="账号" rules={[{ required: true, whitespace: true, message: "请填写账号" }, { max: 64 }]}><Input autoComplete="username" /></Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: "请填写密码" }, { min: 8, max: 200, message: "密码长度为 8–200 位" }, { pattern: /^(?=.*[A-Za-z])(?=.*\d).+$/, message: "密码必须同时包含字母和数字" }]}><Input.Password autoComplete="new-password" /></Form.Item>
          <Form.Item name="display_name" label="姓名" rules={[{ max: 128 }]}><Input /></Form.Item>
          <Form.Item name="email" label="企业邮箱" rules={[{ required: true, message: "请填写企业邮箱" }, { type: "email", message: "请填写有效邮箱" }, { max: 254 }]}><Input autoComplete="email" /></Form.Item>
          <Form.Item label="邮箱验证码">
            <Space.Compact style={{ width: "100%" }}>
              <Form.Item name="email_code" noStyle rules={[{ max: 12 }]}>
                <Input placeholder="6 位验证码" autoComplete="one-time-code" />
              </Form.Item>
              <Button onClick={() => void sendCode()} loading={sendingCode} disabled={codeCooldown > 0}>
                {codeCooldown > 0 ? `${codeCooldown}s 后重发` : "发送验证码"}
              </Button>
            </Space.Compact>
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={submitting}>{submitting ? "正在提交…" : info.review_required ? "提交注册申请" : "注册账号"}</Button>
        </Form>}
        {error && <Button onClick={() => void load()}>重新连接</Button>}
      </Space>
    </Card>
    <Space><Button onClick={() => navigate("/login", { replace: true })}>返回登录</Button><Button onClick={() => navigate("/connection", { replace: true })}>更换服务地址</Button></Space>
  </Space>;
}
