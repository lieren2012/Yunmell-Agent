import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Tooltip } from "antd";
import { useUpdateStatus } from "../../hooks/useUpdateStatus";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { userCan } from "../../utils/permissions";
import styles from "./index.module.less";

interface CurrentVersionBadgeProps {
  isMobile?: boolean;
}

export default function CurrentVersionBadge({
  isMobile,
}: CurrentVersionBadgeProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const user = useCurrentUser();
  const { status } = useUpdateStatus();

  const version = status?.product_version ?? status?.current_version;
  const officialBaseline =
    status?.official_baseline_version ?? status?.current_version;
  if (!version) return null;

  const canUpdate = userCan(user, "update");
  const tooltip = canUpdate
    ? t("header.currentProductVersionAdmin", {
        version,
        baseline: officialBaseline,
        defaultValue: `云迈产品 v${version}，官方基线 v${officialBaseline}，点击查看更新`,
      })
    : t("header.currentProductVersion", {
        version,
        baseline: officialBaseline,
        defaultValue: `云迈产品 v${version}（官方基线 v${officialBaseline}）`,
      });
  const label = `v${version}`;
  const baselineLabel = officialBaseline
    ? `官方基线 v${officialBaseline}`
    : null;

  if (canUpdate) {
    return (
      <Tooltip title={tooltip} mouseEnterDelay={0.35}>
        <button
          type="button"
          className={`${styles.versionBadge} ${
            isMobile ? styles.versionBadgeMobile : ""
          } ${styles.versionBadgeClickable}`}
          onClick={() => navigate("/admin/advanced?tab=updates")}
          aria-label={tooltip}
        >
          <span>{label}</span>
          {baselineLabel && (
            <span className={styles.baselineBadge}>{baselineLabel}</span>
          )}
        </button>
      </Tooltip>
    );
  }

  return (
    <Tooltip title={tooltip} mouseEnterDelay={0.35}>
      <span
        className={`${styles.versionBadge} ${
          isMobile ? styles.versionBadgeMobile : ""
        }`}
        aria-label={tooltip}
      >
        <span>{label}</span>
        {baselineLabel && (
          <span className={styles.baselineBadge}>{baselineLabel}</span>
        )}
      </span>
    </Tooltip>
  );
}
