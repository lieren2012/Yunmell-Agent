import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Result, Spin } from "antd";
import { Settings } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { OctopEmptyMascot } from "../../../components/EmptyState";
import type { OctopAgent } from "../../../context/AgentContext";
import { useAgent } from "../../../context/AgentContext";
import { request } from "../../../api/request";
import {
  formatAgentError,
  isAgentModelConfigError,
} from "../../../utils/agentError";
import styles from "../index.module.less";

interface AgentNotReadyScreenProps {
  agent: OctopAgent | null;
  noAgents?: boolean;
  loading?: boolean;
}

export default function AgentNotReadyScreen({
  agent,
  noAgents = false,
  loading = false,
}: AgentNotReadyScreenProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { refresh: refreshAgents } = useAgent();
  const [localState, setLocalState] = useState(agent?.state ?? "unknown");
  const [localError, setLocalError] = useState(agent?.last_error ?? null);
  const [retrying, setRetrying] = useState(false);
  const autoStartedAgentRef = useRef<string | null>(null);

  useEffect(() => {
    setLocalState(agent?.state ?? "unknown");
    setLocalError(agent?.last_error ?? null);
  }, [agent?.agent_id, agent?.last_error, agent?.state]);

  const isDefaultExpert = Boolean(
    agent &&
      !agent.bridge &&
      agent.is_owner !== false &&
      agent.kind !== "team" &&
      (agent.config.is_default === true ||
        agent.agent_id === "main" ||
        agent.template_name === "general-assistant"),
  );

  const refreshDefaultStatus = useCallback(async () => {
    if (!agent || !isDefaultExpert) return;
    const status = await request<{
      state: string;
      last_error: string | null;
    }>(`/agents/${agent.agent_id}/status`);
    setLocalState(status.state);
    setLocalError(status.last_error);
    if (status.state === "running") {
      await refreshAgents({ silent: true, force: true });
    }
    return status.state;
  }, [agent, isDefaultExpert, refreshAgents]);

  const startDefaultExpert = useCallback(async () => {
    if (!agent || !isDefaultExpert || retrying) return;
    setRetrying(true);
    setLocalState("starting");
    setLocalError(null);
    try {
      await request(`/agents/${agent.agent_id}/start`, { method: "POST" });
      await refreshDefaultStatus();
    } catch (error) {
      setLocalState("failed");
      setLocalError(error instanceof Error ? error.message : String(error));
    } finally {
      setRetrying(false);
    }
  }, [agent, isDefaultExpert, refreshDefaultStatus, retrying]);

  useEffect(() => {
    if (!isDefaultExpert || !agent || localState !== "starting") return;
    let active = true;
    const poll = async () => {
      try {
        const status = await request<{
          state: string;
          last_error: string | null;
        }>(`/agents/${agent.agent_id}/status`);
        if (!active) return;
        setLocalState(status.state);
        setLocalError(status.last_error);
        if (status.state === "running") {
          await refreshAgents({ silent: true, force: true });
        }
      } catch (error) {
        if (!active) return;
        setLocalError(error instanceof Error ? error.message : String(error));
      }
    };
    const timer = window.setInterval(() => void poll(), 1000);
    void poll();
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [agent, isDefaultExpert, localState, refreshAgents]);

  // A default expert is a local runtime resource. Restore it as soon as the
  // authenticated dashboard sees it stopped, then let the same
  // status endpoint provide the real failure reason for the retry action.
  useEffect(() => {
    if (
      !isDefaultExpert ||
      !agent ||
      localState === "running" ||
      localState === "starting" ||
      localState === "failed" ||
      retrying ||
      autoStartedAgentRef.current === agent.agent_id
    ) {
      return;
    }
    autoStartedAgentRef.current = agent.agent_id;
    void startDefaultExpert();
  }, [agent, isDefaultExpert, localState, retrying, startDefaultExpert]);

  if (loading) {
    return (
      <div className={styles.agentNotReady}>
        <Spin />
      </div>
    );
  }

  if (noAgents) {
    return (
      <div className={styles.noAgentsEmpty}>
        <div className={styles.noAgentsEmptyInner}>
          <div className={styles.noAgentsEmptyIcon}>
            <OctopEmptyMascot className={styles.noAgentsEmptyMascot} />
          </div>
          <h1 className={styles.noAgentsEmptyTitle}>
            {t("chat.noAgentsTitle")}
          </h1>
          <p className={styles.noAgentsEmptyHint}>{t("chat.noAgentsHint")}</p>
          <Button
            type="primary"
            size="large"
            onClick={() => navigate("/experts")}
          >
            {t("chat.createExpert")}
          </Button>
        </div>
      </div>
    );
  }

  if (!agent) {
    return (
      <div className={styles.agentNotReady}>
        <Result status="info" title={t("chat.pickAgent")} />
      </div>
    );
  }

  const state = localState;
  const errorText = formatAgentError(localError, t);
  const isModelError = isAgentModelConfigError(localError);
  const disconnected = Boolean(agent.bridge && agent.bridge_disconnected);

  let title = t("chat.agentNotRunning");
  let subTitle = t("chat.agentNotRunningHint");

  if (disconnected) {
    const inbound = Boolean(agent.bridge_inbound);
    title = t("chat.remoteExpert.disconnectedTitle");
    subTitle = inbound
      ? agent.bridge_connection_name
        ? t("chat.remoteExpert.waitForPeerNamed", {
            name: agent.bridge_connection_name,
          })
        : t("chat.remoteExpert.waitForPeer")
      : agent.bridge_connection_name
      ? t("chat.remoteExpert.disconnectedHintNamed", {
          name: agent.bridge_connection_name,
        })
      : t("chat.remoteExpert.disconnectedHint");
  } else if (state === "failed") {
    title = t("chat.agentFailed");
    subTitle = errorText || t("chat.agentFailedHint");
  } else if (state === "stopped" || state === "created") {
    if (isDefaultExpert) {
      title = t("chat.agentStarting");
      subTitle = t("chat.agentStartingHint");
    }
  } else if (state === "starting" || state === "stopping") {
    title = t("chat.agentStarting");
    subTitle = t("chat.agentStartingHint");
  }

  return (
    <div className={styles.agentNotReady}>
      <Result
        status={
          disconnected
            ? "warning"
            : state === "failed"
            ? "error"
            : state === "stopped" || state === "created"
            ? "warning"
            : "info"
        }
        title={title}
        subTitle={subTitle}
        extra={
          disconnected ? (
            <Button type="primary" onClick={() => navigate("/bridge")}>
              {t(
                agent.bridge_inbound
                  ? "chat.remoteExpert.openBridge"
                  : "chat.remoteExpert.reconnect",
              )}
            </Button>
          ) : isDefaultExpert && state === "starting" ? (
            <Spin />
          ) : isDefaultExpert &&
            (state === "failed" ||
              state === "stopped" ||
              state === "created") ? (
            <Button
              type="primary"
              loading={retrying}
              onClick={() => void startDefaultExpert()}
            >
              {t("experts.retryStart", "重试启动")}
            </Button>
          ) : isModelError ? (
            <Button
              type="primary"
              icon={<Settings size={14} />}
              onClick={() => navigate("/admin/models")}
            >
              {t("modelConfig.configureButton")}
            </Button>
          ) : (
            <Button type="primary" onClick={() => navigate("/experts")}>
              {t("chat.goToExperts")}
            </Button>
          )
        }
      />
    </div>
  );
}
