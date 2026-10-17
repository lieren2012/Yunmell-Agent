import { useEffect, useState } from "react";
import { Alert, Button, Form, Input, Modal, Segmented, Space, Typography } from "antd";
import { useTranslation } from "react-i18next";

import { deploymentApi, enrollmentError } from "../../api/modules/deployment";
import styles from "./ForgotPasswordModal.module.less";

type Platform = "linux" | "mac" | "windows" | "docker";

function CopyCommand({ text }: { text: string }) {
  return (
    <Typography.Paragraph copyable className={styles.command}>
      {text}
    </Typography.Paragraph>
  );
}

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function ForgotPasswordModal({ open, onClose }: Props) {
  const { t } = useTranslation();
  const [platform, setPlatform] = useState<Platform>("linux");
  const [form] = Form.useForm();
  const [sending, setSending] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setTimeout(() => setCooldown((n) => n - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [cooldown]);

  const sendCode = async () => {
    try {
      await form.validateFields(["email"]);
      setSending(true);
      setError("");
      await deploymentApi.sendResetCode(String(form.getFieldValue("email")).trim());
      setCooldown(60);
    } catch (err) {
      if (err && typeof err === "object" && "errorFields" in err) return;
      setError(enrollmentError(err));
    } finally {
      setSending(false);
    }
  };

  const reset = async (values: { email: string; code: string; new_password: string }) => {
    setSubmitting(true);
    setError("");
    try {
      await deploymentApi.resetPassword({
        email: String(values.email).trim(),
        code: String(values.code).trim(),
        new_password: values.new_password,
      });
      setDone(true);
    } catch (err) {
      setError(enrollmentError(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      title={t("login.forgotPasswordTitle", "Reset password")}
      onCancel={onClose}
      footer={
        <Button type="primary" onClick={onClose}>
          {t("login.forgotPasswordOk", "Got it")}
        </Button>
      }
      width={520}
      centered
      destroyOnHidden
    >
      <div className={styles.body} data-testid="login-forgot-password">
        {done ? (
          <Alert
            type="success"
            showIcon
            message={t("login.resetPasswordDone", "密码已重置，请使用新密码登录。")}
          />
        ) : (
          <Form form={form} layout="vertical" onFinish={(v) => void reset(v)}>
            {error && <Alert type="error" showIcon message={error} />}
            <Form.Item
              name="email"
              label={t("login.resetEmail", "企业邮箱")}
              rules={[
                { required: true, message: t("login.resetEmailRequired", "请填写企业邮箱") },
                { type: "email", message: t("login.resetEmailInvalid", "请填写有效邮箱") },
              ]}
            >
              <Input autoComplete="email" />
            </Form.Item>
            <Form.Item label={t("login.resetCode", "邮箱验证码")}>
              <Space.Compact style={{ width: "100%" }}>
                <Form.Item
                  name="code"
                  noStyle
                  rules={[{ required: true, message: t("login.resetCodeRequired", "请填写验证码") }]}
                >
                  <Input autoComplete="one-time-code" />
                </Form.Item>
                <Button loading={sending} disabled={cooldown > 0} onClick={() => void sendCode()}>
                  {cooldown > 0
                    ? t("login.resetResendIn", "{{seconds}}s 后重发", { seconds: cooldown })
                    : t("login.resetSendCode", "发送验证码")}
                </Button>
              </Space.Compact>
            </Form.Item>
            <Form.Item
              name="new_password"
              label={t("login.resetNewPassword", "新密码")}
              rules={[
                { required: true, message: t("login.resetNewPasswordRequired", "请填写新密码") },
                { min: 8, max: 200, message: t("login.resetNewPasswordLength", "密码长度为 8–200 位") },
                {
                  pattern: /^(?=.*[A-Za-z])(?=.*\d).+$/,
                  message: t("login.resetNewPasswordRule", "密码必须同时包含字母和数字"),
                },
              ]}
            >
              <Input.Password autoComplete="new-password" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={submitting}>
              {t("login.resetSubmit", "重置密码")}
            </Button>
          </Form>
        )}
        <Typography.Title level={5} style={{ marginTop: 24 }}>
          {t("login.forgotPasswordFallback", "未配置企业邮箱时")}
        </Typography.Title>
        <p className={styles.help}>
          {t(
            "login.forgotPasswordHelp",
            "Ask an administrator to reset it under Users. If you manage this host, run the command below on the machine where Octop is installed, using the same OS account that runs the service.",
          )}
        </p>
        <CopyCommand
          text={t(
            "login.forgotPasswordCommand",
            "octop user passwd <username> --password <new-password>",
          )}
        />
        <p className={styles.hint}>
          {t(
            "login.forgotPasswordHint",
            "You can omit --password to enter it interactively. New password: at least 8 characters with letters and digits.",
          )}
        </p>
        <Segmented<Platform>
          block
          value={platform}
          onChange={setPlatform}
          options={[
            { label: "Linux", value: "linux" },
            { label: "macOS", value: "mac" },
            { label: "Windows", value: "windows" },
            { label: "Docker", value: "docker" },
          ]}
        />
        <PlatformHelp platform={platform} />
      </div>
    </Modal>
  );
}

function PlatformHelp({ platform }: { platform: Platform }) {
  const { t } = useTranslation();

  if (platform === "docker") {
    return (
      <div className={styles.platform}>
        <p className={styles.note}>
          {t("login.forgotPasswordDocker", "Enter the container, then run:")}
        </p>
        <CopyCommand
          text={t(
            "login.forgotPasswordDockerCommand",
            "docker exec -it <container> octop user passwd <username> --password <new-password>",
          )}
        />
      </div>
    );
  }

  if (platform === "windows") {
    return (
      <div className={styles.platform}>
        <p className={styles.note}>
          {t(
            "login.forgotPasswordWindows",
            "Open PowerShell or Command Prompt, then run the command above. If octop is not found:",
          )}
        </p>
        <div className={styles.fallback}>
          <p className={styles.label}>PowerShell</p>
          <CopyCommand
            text={t(
              "login.forgotPasswordWindowsPs",
              '& "$env:USERPROFILE\\.octop\\bin\\octop.cmd" user passwd <username> --password <new-password>',
            )}
          />
          <p className={styles.label}>
            {t("login.forgotPasswordWindowsCmdLabel", "Command Prompt")}
          </p>
          <CopyCommand
            text={t(
              "login.forgotPasswordWindowsCmd",
              "%USERPROFILE%\\.octop\\bin\\octop.cmd user passwd <username> --password <new-password>",
            )}
          />
        </div>
      </div>
    );
  }

  return (
    <div className={styles.platform}>
      <p className={styles.note}>
        {platform === "mac"
          ? t(
              "login.forgotPasswordMac",
              "Open Terminal (Applications → Utilities → Terminal), then run the command above. If octop is not found:",
            )
          : t(
              "login.forgotPasswordLinux",
              "Open Terminal, then run the command above. If octop is not found:",
            )}
      </p>
      <CopyCommand
        text={t(
          "login.forgotPasswordUnixPath",
          "~/.octop/bin/octop user passwd <username> --password <new-password>",
        )}
      />
    </div>
  );
}
