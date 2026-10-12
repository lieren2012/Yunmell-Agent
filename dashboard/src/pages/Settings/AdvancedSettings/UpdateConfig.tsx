import { useEffect, useState } from "react";
import { App, Collapse, Switch } from "antd";
import { useTranslation } from "react-i18next";
import { Info, RefreshCw, Sparkles, XCircle } from "lucide-react";
import {
  updateApi,
  type UpdateChannel,
  type UpdateChannelStatus,
} from "../../../api/modules/update";
import Markdown from "../../../components/Markdown/LazyMarkdown";
import { TabPanelHeader } from "./TabPanelHeader";
import styles from "./UpdateConfig.module.less";

const titles = { official: "OpenOct/Octop 官方更新", yunmell: "云迈自研更新" };

function ChannelPanel({
  channel,
  initial,
}: {
  channel: UpdateChannel;
  initial?: UpdateChannelStatus;
}) {
  const { message } = App.useApp();
  const [status, setStatus] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const official = channel === "official";
  useEffect(() => {
    if (initial) setStatus(initial);
  }, [initial]);

  async function check(stableOnly?: boolean) {
    setBusy(true);
    setError(null);
    try {
      const next =
        stableOnly === undefined
          ? await updateApi.checkChannel(channel)
          : await updateApi.patchChannelSettings(channel, stableOnly);
      setStatus(next);
    } catch {
      setError(`${titles[channel]}检查失败，请稍后重试`);
    } finally {
      setBusy(false);
    }
  }

  async function openRelease() {
    try {
      const result = await updateApi.upgradeChannel(
        channel,
        status?.latest_version,
      );
      if (result.source_url)
        window.open(result.source_url, "_blank", "noopener,noreferrer");
    } catch {
      void message.error(`${titles[channel]}来源无法打开`);
    }
  }

  return (
    <section className={styles.panel} aria-label={titles[channel]}>
      <div className={styles.panelTitleRow}>
        <span className={styles.panelTitleIcon}>
          <Sparkles size={16} />
        </span>
        <h3 className={styles.panelTitle}>{titles[channel]}</h3>
      </div>
      <p className={styles.panelDesc}>
        {official
          ? "当前版本表示云迈已集成的官方基线；上游同步通过适配和测试后更新。"
          : "云迈智能体的产品版本，更新来源为云迈 GitHub Release。"}
      </p>
      <div className={styles.stableOnlyRow}>
        <Switch
          aria-label={`${titles[channel]}只检查稳定版`}
          checked={status?.stable_only !== false}
          onChange={(value) => void check(value)}
          disabled={busy}
        />
        <div className={styles.stableOnlyCopy}>
          <p className={styles.stableOnlyLabel}>只检查稳定版</p>
          <p className={styles.stableOnlyHint}>
            关闭后包含测试版。此设置仅影响本条更新线。
          </p>
        </div>
      </div>
      <div className={styles.versionGrid}>
        <div className={styles.versionCard}>
          <span className={styles.versionLabel}>
            {official ? "已集成官方版本" : "云迈当前版本"}
          </span>
          <span className={styles.versionValue}>
            {status?.current_version ?? "—"}
          </span>
        </div>
        <div className={styles.versionCard}>
          <span className={styles.versionLabel}>
            {official ? "官方最新版本" : "云迈最新版本"}
          </span>
          <span className={styles.versionValue}>
            {status?.latest_version ?? "尚未检查"}
          </span>
          <div className={styles.versionBadges}>
            {status?.latest_is_prerelease && (
              <span className={styles.betaBadge}>测试版</span>
            )}
            {status?.has_update && (
              <span className={styles.badge}>有新版本</span>
            )}
            {status?.latest_version && !status.has_update && !status.error && (
              <span className={styles.badge}>已是最新版本</span>
            )}
          </div>
        </div>
      </div>
      {(error || status?.error) && (
        <div role="alert" className={`${styles.alert} ${styles.alertError}`}>
          <XCircle size={15} />
          <span>
            {error ||
              (official
                ? "官方更新源暂时无法访问，请重试。"
                : "云迈 Release 暂时无法访问，请重试。")}
          </span>
        </div>
      )}
      <div className={`${styles.alert} ${styles.alertInfo}`}>
        <Info size={15} />
        <span>
          来源：
          <a
            href={
              status?.source_url ||
              (official
                ? "https://github.com/TencentCloud/Octop/releases"
                : "https://github.com/lieren2012/Yunmell-Agent/releases")
            }
            target="_blank"
            rel="noreferrer"
          >
            {status?.source ||
              (official ? "Octop 官方 / PyPI" : "云迈 GitHub Release")}
          </a>
        </span>
      </div>
      <div className={styles.actions}>
        <button
          type="button"
          className={styles.btnSecondary}
          onClick={() => void check()}
          disabled={busy}
        >
          <RefreshCw size={14} className={busy ? styles.spinning : undefined} />
          {busy ? "检查中" : official ? "检查官方更新" : "检查云迈更新"}
        </button>
        <button
          type="button"
          className={styles.btnSecondary}
          onClick={() => void openRelease()}
          disabled={!status?.latest_version || !!status?.error}
        >
          {official ? "查看官方更新与同步" : "下载 / 安装云迈新版"}
        </button>
      </div>
      {status?.release_notes && (
        <Collapse
          className={styles.releaseNotes}
          items={[
            {
              key: `${channel}-notes`,
              label: official ? "官方更新说明" : "云迈更新说明",
              children: <Markdown content={status.release_notes} />,
            },
          ]}
        />
      )}
    </section>
  );
}

export default function UpdateConfig() {
  const { t } = useTranslation();
  const [statuses, setStatuses] = useState<
    Partial<Record<UpdateChannel, UpdateChannelStatus>>
  >({});
  useEffect(() => {
    let cancelled = false;
    void updateApi
      .getChannelStatuses()
      .then((next) => {
        if (!cancelled) setStatuses(next);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);
  return (
    <div className={styles.container}>
      <TabPanelHeader
        icon={<RefreshCw size={22} />}
        title={t("advancedSettings.update.title")}
        description="官方基线与云迈产品版本分别检查和更新"
      />
      <div className={styles.layout}>
        <ChannelPanel channel="official" initial={statuses.official} />
        <ChannelPanel channel="yunmell" initial={statuses.yunmell} />
      </div>
      <section
        className={styles.panel}
        style={{ marginTop: 20 }}
        aria-label="更新方式"
      >
        <h3 className={styles.panelTitle}>更新方式</h3>
        <p className={styles.panelDesc}>
          桌面端下载云迈安装包升级；企业管理服务器使用云迈版本构建并更新容器。官方上游更新先进入同步分支，完成企业功能兼容验证后随云迈版本发布。
        </p>
      </section>
    </div>
  );
}
