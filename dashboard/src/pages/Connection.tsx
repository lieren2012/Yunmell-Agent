import { useEffect, useRef, useState } from "react";
import { Alert, Button, Card, Input, Space, Typography } from "antd";
import { useNavigate } from "react-router-dom";
import { clearAuthToken } from "../api/request";
import { deploymentApi, enrollmentError } from "../api/modules/deployment";

export default function ConnectionPage() {
  const navigate = useNavigate();
  const [address, setAddress] = useState("");
  const [desktop, setDesktop] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submitting = useRef(false);
  useEffect(() => {
    void deploymentApi.connection().then(info => { setAddress(info.address); setDesktop(info.desktop); }).catch(err => setError(enrollmentError(err)));
  }, []);
  const connect = async () => {
    if (submitting.current) return;
    submitting.current = true; setBusy(true); setError("");
    try {
      if (!desktop) {
        const target = new URL(address);
        if (!/^https?:$/.test(target.protocol) || target.username || target.password || target.search || target.hash) throw new Error("invalid-address");
        clearAuthToken(); window.location.assign(target.href.replace(/\/$/, "") + "/login");
      } else {
        await deploymentApi.connect(address.trim()); clearAuthToken(); navigate("/login", { replace: true });
      }
    } catch (err) { setError(enrollmentError(err)); }
    finally { submitting.current = false; setBusy(false); }
  };
  return <Space direction="vertical" style={{ width: "100%", maxWidth: 480, margin: "10vh auto", display: "flex" }}>
    <Typography.Title level={2}>云迈智能体</Typography.Title>
    <Card title="连接企业服务"><Space direction="vertical" style={{ width: "100%" }}>
      <Typography.Paragraph>填写管理员提供的服务地址，连接后自动读取企业名称。</Typography.Paragraph>
      {error && <Alert type="error" message={error} showIcon role="alert" />}
      <Input aria-label="服务地址" placeholder="http://企业服务器:端口" value={address} disabled={busy} onChange={e => setAddress(e.target.value)} onPressEnter={() => void connect()} />
      <Button type="primary" loading={busy} disabled={!address.trim()} onClick={() => void connect()}>{busy ? "正在连接…" : "连接服务"}</Button>
      <Button type="link" onClick={() => navigate("/login", { replace: true })}>返回登录</Button>
    </Space></Card>
  </Space>;
}
