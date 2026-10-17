import { useState } from "react";
import { Alert, Button, Input, Modal, Segmented, Space, Typography } from "antd";
import { useTranslation } from "react-i18next";

import { authApi } from "../../api/modules/auth";
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
