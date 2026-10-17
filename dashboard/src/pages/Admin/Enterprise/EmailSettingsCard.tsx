import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Space,
  Switch,
  Typography,
  message,
} from "antd";

import { authEmailApi, type SmtpConfig } from "../../../api/modules/authEmail";
import { apiErrorMessage } from "../../../utils/apiError";

interface FormValues {
  enabled: boolean;
  host: string;
  port: number;
  username: string;
  password?: string;
  sender: string;
  sender_name: string;
  use_tls: boolean;
  use_ssl: boolean;
}

export default function EmailSettingsCard() {
  const [form] = Form.useForm<FormValues>();
  const [config, setConfig] = useState<SmtpConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testTo, setTestTo] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const value = await authEmailApi.get();
      setConfig(value);
      form.setFieldsValue({
        enabled: value.enabled,
        host: value.host,
        port: value.port,
        username: value.username,
        sender: value.sender,
        sender_name: value.sender_name,
        use_tls: value.use_tls,
        use_ssl: value.use_ssl,
        password: undefined,
      });
    } catch (err) {
      setError(apiErrorMessage(err, "读取邮件设置失败"));
    } finally {
      setLoading(false);
    }
  }, [form]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async (values: FormValues) => {
    setSaving(true);
    setError("");
    try {
      const next = await authEmailApi.save({
        ...values,
        // Undefined keeps the stored password; null would clear it.
        password: values.password ? values.password : undefined,
      });
      setConfig(next);
      form.setFieldValue("password", undefined);
      message.success("邮件设置已保存");
    } catch (err) {
      setError(apiErrorMessage(err, "保存邮件设置失败"));
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    setError("");
    try {
      await authEmailApi.test(testTo.trim());
      message.success("测试邮件已发送");
    } catch (err) {
      setError(apiErrorMessage(err, "测试邮件发送失败"));
    } finally {
      setTesting(false);
    }
  };

  return (
    <Card title="企业邮箱与验证码" loading={loading}>
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          用于普通用户注册时的邮箱验证、忘记密码重置。未启用时仍可注册，由管理员在「注册审核」中人工把关，
          忘记密码保持管理员手动重置。
        </Typography.Paragraph>
        {error && <Alert type="error" showIcon message={error} />}
        <Form form={form} layout="vertical" onFinish={(v) => void save(v)}>
          <Form.Item name="enabled" label="启用邮箱验证码" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Space size="middle" wrap>
            <Form.Item
              name="host"
              label="SMTP 服务器"
              rules={[{ max: 255 }]}
              style={{ minWidth: 260 }}
            >
              <Input placeholder="例如 smtp.qq.com" autoComplete="off" />
            </Form.Item>
            <Form.Item name="port" label="端口" rules={[{ required: true }]}>
              <InputNumber min={1} max={65535} style={{ width: 120 }} />
            </Form.Item>
            <Form.Item name="use_tls" label="STARTTLS" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item name="use_ssl" label="SSL" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Space>
          <Form.Item name="username" label="账号" rules={[{ max: 255 }]}>
            <Input autoComplete="username" />
          </Form.Item>
          <Form.Item
            name="password"
            label={config?.password_configured ? "密码 / 授权码（留空则保持不变）" : "密码 / 授权码"}
            rules={[{ max: 512 }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Space size="middle" wrap>
            <Form.Item
              name="sender"
              label="发件地址"
              rules={[{ type: "email", message: "请填写有效邮箱" }, { max: 254 }]}
              style={{ minWidth: 260 }}
            >
              <Input placeholder="noreply@example.com" />
            </Form.Item>
            <Form.Item name="sender_name" label="发件人名称" rules={[{ max: 120 }]}>
              <Input />
            </Form.Item>
          </Space>
          <Button type="primary" htmlType="submit" loading={saving}>
            保存设置
          </Button>
        </Form>
        <Card size="small" title="发送测试邮件">
          <Space.Compact style={{ width: "100%" }}>
            <Input
              value={testTo}
              onChange={(event) => setTestTo(event.target.value)}
              placeholder="接收测试邮件的地址"
              autoComplete="email"
            />
            <Button
              onClick={() => void test()}
              loading={testing}
              disabled={!testTo.trim() || !config?.enabled}
            >
              发送测试
            </Button>
          </Space.Compact>
        </Card>
      </Space>
    </Card>
  );
}
