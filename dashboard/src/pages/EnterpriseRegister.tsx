import { useState } from "react";
import { Button, Card, Input, Space, Typography, message } from "antd";
import { useSearchParams } from "react-router-dom";
import { request } from "../api/request";

export default function EnterpriseRegisterPage() {
  const [params] = useSearchParams();
  const querySlug = params.get("enterprise") || "";
  const [slug, setSlug] = useState(querySlug);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const submit = async () => {
    if (!slug || !username || !password) return;
    await request(`/auth/enterprises/${encodeURIComponent(slug)}/register`, {
      method: "POST",
      body: JSON.stringify({ username, password, display_name: displayName || undefined, email: email || undefined }),
    });
    setSubmitted(true);
    message.success("注册申请已提交，请等待企业管理员审核");
  };

  return (
    <Space direction="vertical" style={{ width: "100%", maxWidth: 480, margin: "10vh auto", display: "flex" }}>
      <Typography.Title level={2}>云迈智能体</Typography.Title>
      <Card title={submitted ? "申请已提交" : slug ? `加入企业 ${slug}` : "企业注册"}>
        {submitted ? <Typography.Text>审核通过后，你才能使用该企业地址登录工作台。</Typography.Text> : <Space direction="vertical" style={{ width: "100%" }}>
          {!querySlug && <Input placeholder="企业地址代码" value={slug} onChange={(e) => setSlug(e.target.value.trim())} />}
          <Input placeholder="账号" value={username} onChange={(e) => setUsername(e.target.value)} />
          <Input.Password placeholder="密码（至少 8 位）" value={password} onChange={(e) => setPassword(e.target.value)} />
          <Input placeholder="姓名" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          <Input placeholder="邮箱（可选）" value={email} onChange={(e) => setEmail(e.target.value)} />
          <Button type="primary" onClick={() => void submit()} disabled={!slug || !username || !password}>提交注册申请</Button>
        </Space>}
      </Card>
    </Space>
  );
}
