import { useState } from "react";
import { Alert, Button, Input, Modal, Space, Typography } from "antd";
import { useTranslation } from "react-i18next";

import { authApi } from "../../api/modules/auth";
import styles from "./ForgotPasswordModal.module.less";

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function ForgotPasswordModal({ open, onClose }: Props) {
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const sendCode = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await authApi.requestPasswordReset(email.trim());
      setNotice("验证码已发送，请检查邮箱（10 分钟内有效）。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "邮箱验证码发送失败，请联系管理员手动重置。");
    } finally {
      setBusy(false);
    }
  };

  const resetPassword = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await authApi.confirmPasswordReset(email.trim(), code.trim(), newPassword);
      setNotice("密码已重置，请返回登录。");
      setCode("");
      setNewPassword("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "密码重置失败，请联系管理员手动重置。");
    } finally {
      setBusy(false);
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
        <Typography.Title level={5} style={{ marginTop: 0 }}>
          邮箱验证码重置
        </Typography.Title>
        <Space.Compact style={{ width: "100%" }}>
          <Input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="注册邮箱"
            autoComplete="email"
          />
          <Button onClick={() => void sendCode()} loading={busy} disabled={!email.trim()}>
            发送验证码
          </Button>
        </Space.Compact>
        <Space.Compact style={{ width: "100%", marginTop: 8 }}>
          <Input
            value={code}
            onChange={(event) => setCode(event.target.value)}
            placeholder="6 位验证码"
            inputMode="numeric"
            maxLength={6}
          />
          <Input.Password
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            placeholder="新密码（至少 8 位，含字母和数字）"
            autoComplete="new-password"
          />
          <Button
            type="primary"
            onClick={() => void resetPassword()}
            loading={busy}
            disabled={!email.trim() || code.length !== 6 || !newPassword}
          >
            重置密码
          </Button>
        </Space.Compact>
        {notice && <Alert style={{ marginTop: 8 }} type="success" message={notice} showIcon />}
        {error && <Alert style={{ marginTop: 8 }} type="warning" message={error} showIcon />}
        <p className={styles.help}>
          {t(
            "login.forgotPasswordHelp",
            "请使用注册邮箱接收验证码完成重置。若未收到验证码，或企业未配置 SMTP，请联系企业管理员处理密码重置或邀请。",
          )}
        </p>
      </div>
    </Modal>
  );
}
