import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  List,
  Row,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
  message,
} from "antd";
import PageShell from "../../../layouts/PageShell";
import {
  enterpriseApi,
  type EnterpriseMember,
  type EnterpriseOrganization,
  type EnterpriseTeam,
  type TeamControls,
  type TeamQuota,
  type RegistrationApplication,
} from "../../../api/modules/enterprise";

const { Text } = Typography;

export default function EnterprisePage() {
  const [orgs, setOrgs] = useState<EnterpriseOrganization[]>([]);
  const [teams, setTeams] = useState<EnterpriseTeam[]>([]);
  const [members, setMembers] = useState<EnterpriseMember[]>([]);
  const [orgId, setOrgId] = useState("");
  const [teamId, setTeamId] = useState("");
  const [modelText, setModelText] = useState("");
  const [quota, setQuota] = useState<TeamQuota>({
    team_id: "",
    period: "monthly",
    token_limit: null,
    request_limit: null,
    concurrency_limit: null,
  });
  const [controls, setControls] = useState<TeamControls>({
    team_id: "",
    shell_enabled: false,
    browser_enabled: false,
    desktop_enabled: false,
    filesystem_enabled: true,
    network_enabled: true,
  });
  const [memberUserId, setMemberUserId] = useState<number | null>(null);
  const [memberRole, setMemberRole] = useState("member");
  const [applications, setApplications] = useState<RegistrationApplication[]>([]);
  const [defaultProvider, setDefaultProvider] = useState("");
  const [defaultModel, setDefaultModel] = useState("");
  const [reviewRequired, setReviewRequired] = useState(true);
  const selectedTeam = useMemo(
    () => teams.find((team) => team.team_id === teamId),
    [teams, teamId],
  );

  const loadOrgs = async () => {
    const data = await enterpriseApi.organizations();
    setOrgs(data);
    if (!orgId && data[0]) setOrgId(data[0].organization_id);
    const selected = data.find((item) => item.organization_id === orgId) || data[0];
    if (selected) {
      setDefaultProvider(selected.default_provider_name || "");
      setDefaultModel(selected.default_model || "");
      setReviewRequired(selected.registration_review_required ?? true);
    }
  };
  useEffect(() => {
    void loadOrgs().catch(() => message.error("企业列表加载失败"));
  }, []);
  useEffect(() => {
    if (!orgId) return;
    void Promise.all([
      enterpriseApi.teams(orgId),
      enterpriseApi.members(orgId),
      enterpriseApi.applications(orgId),
    ])
      .then(([nextTeams, nextMembers, nextApplications]) => {
        setTeams(nextTeams);
        setMembers(nextMembers);
        setApplications(nextApplications);
        if (!teamId && nextTeams[0]) setTeamId(nextTeams[0].team_id);
      })
      .catch(() => message.error("团队数据加载失败"));
  }, [orgId]);
  useEffect(() => {
    if (!orgId || !teamId) return;
    void Promise.all([
      enterpriseApi.models(orgId, teamId),
      enterpriseApi.quota(orgId, teamId),
      enterpriseApi.controls(orgId, teamId),
    ])
      .then(([models, nextQuota, nextControls]) => {
        setModelText(
          models
            .map((item) => `${item.provider_name}/${item.model}`)
            .join("\n"),
        );
        if (nextQuota) setQuota(nextQuota);
        if (nextControls) setControls(nextControls);
      })
      .catch(() => message.error("团队策略加载失败"));
  }, [orgId, teamId]);

  const savePolicies = async () => {
    if (!orgId || !teamId) return;
    const models = modelText
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((ref) => {
        const [provider_name, ...rest] = ref.split("/");
        return { provider_name, model: rest.join("/") };
      })
      .filter((item) => item.provider_name && item.model);
    await enterpriseApi.saveModels(orgId, teamId, models);
    await enterpriseApi.saveQuota(orgId, teamId, {
      period: quota.period,
      token_limit: quota.token_limit,
      request_limit: quota.request_limit,
      concurrency_limit: quota.concurrency_limit,
    });
    await enterpriseApi.saveControls(orgId, teamId, {
      shell_enabled: controls.shell_enabled,
      browser_enabled: controls.browser_enabled,
      desktop_enabled: controls.desktop_enabled,
      filesystem_enabled: controls.filesystem_enabled,
      network_enabled: controls.network_enabled,
    });
    message.success("团队策略已保存");
  };

  return (
    <PageShell
      title="企业管理"
      subtitle="组织、团队、模型限制、配额和本机控制边界"
    >
      <Space direction="vertical" size="large" style={{ width: "100%" }}>
        <Card title="企业与团队">
          <Space wrap>
            <Select
              value={orgId || undefined}
              placeholder="选择企业"
              style={{ width: 220 }}
              onChange={(value) => {
                setOrgId(value);
                setTeamId("");
              }}
              options={orgs.map((org) => ({
                value: org.organization_id,
                label: org.name,
              }))}
            />
            <Button
              onClick={async () => {
                const name = window.prompt("企业名称");
                if (name) {
                  await enterpriseApi.createOrganization(name);
                  await loadOrgs();
                }
              }}
            >
              新建企业
            </Button>
            <Select
              value={teamId || undefined}
              placeholder="选择团队"
              style={{ width: 220 }}
              onChange={setTeamId}
              options={teams.map((team) => ({
                value: team.team_id,
                label: team.name,
              }))}
            />
            <Button
              disabled={!orgId}
              onClick={async () => {
                const name = window.prompt("团队名称");
                if (name && orgId) {
                  await enterpriseApi.createTeam(orgId, name);
                  setTeams(await enterpriseApi.teams(orgId));
                }
              }}
            >
              新建团队
            </Button>
          </Space>
          {selectedTeam && (
            <Text type="secondary">当前团队：{selectedTeam.name}</Text>
          )}
        </Card>
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <Card title="团队模型白名单">
              <Input.TextArea
                value={modelText}
                onChange={(event) => setModelText(event.target.value)}
                placeholder="每行一个 provider/model，例如 openai/gpt-5"
                autoSize={{ minRows: 8, maxRows: 12 }}
              />
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card title="团队配额">
              <Form layout="vertical">
                <Form.Item label="周期">
                  <Select
                    value={quota.period}
                    onChange={(period) => setQuota({ ...quota, period })}
                    options={[
                      { value: "daily", label: "每日" },
                      { value: "weekly", label: "每周" },
                      { value: "monthly", label: "每月" },
                    ]}
                  />
                </Form.Item>
                <Form.Item label="Token 上限">
                  <InputNumber
                    style={{ width: "100%" }}
                    min={0}
                    value={quota.token_limit ?? undefined}
                    onChange={(value) =>
                      setQuota({ ...quota, token_limit: value ?? null })
                    }
                  />
                </Form.Item>
                <Form.Item label="请求次数上限">
                  <InputNumber
                    style={{ width: "100%" }}
                    min={0}
                    value={quota.request_limit ?? undefined}
                    onChange={(value) =>
                      setQuota({ ...quota, request_limit: value ?? null })
                    }
                  />
                </Form.Item>
                <Form.Item label="并发上限">
                  <InputNumber
                    style={{ width: "100%" }}
                    min={0}
                    value={quota.concurrency_limit ?? undefined}
                    onChange={(value) =>
                      setQuota({ ...quota, concurrency_limit: value ?? null })
                    }
                  />
                </Form.Item>
              </Form>
            </Card>
          </Col>
        </Row>
        <Card title="本机控制边界">
          <Space wrap>
            {(
              [
                "shell_enabled",
                "browser_enabled",
                "desktop_enabled",
                "filesystem_enabled",
                "network_enabled",
              ] as const
            ).map((key) => (
              <Tag key={key} style={{ padding: 8 }}>
                {key.replace("_enabled", "")}{" "}
                <Switch
                  size="small"
                  checked={controls[key]}
                  onChange={(checked) =>
                    setControls({ ...controls, [key]: checked })
                  }
                />
              </Tag>
            ))}
          </Space>
        </Card>
        <Card title="团队成员">
          <List
            size="small"
            dataSource={members.filter((member) => member.team_id === teamId)}
            renderItem={(member) => (
              <List.Item>
                <Text>User #{member.user_id}</Text>
                <Tag>{member.role}</Tag>
              </List.Item>
            )}
            locale={{ emptyText: "暂无成员" }}
          />
        </Card>
      <Card title="添加或调整成员">
        <Space wrap>
          <InputNumber
            min={1}
            placeholder="用户 ID"
            value={memberUserId ?? undefined}
            onChange={(value) => setMemberUserId(value)}
          />
          <Select
            value={memberRole}
            onChange={setMemberRole}
            options={[
              { value: "owner", label: "负责人" },
              { value: "admin", label: "管理员" },
              { value: "member", label: "成员" },
            ]}
          />
          <Button
            disabled={!orgId || !teamId || !memberUserId}
            onClick={async () => {
              if (!orgId || !teamId || !memberUserId) return;
              await enterpriseApi.upsertMember(orgId, {
                user_id: memberUserId,
                team_id: teamId,
                role: memberRole,
              });
              setMembers(await enterpriseApi.members(orgId));
              message.success("成员已更新");
            }}
          >
            保存成员
          </Button>
        </Space>
      </Card>
      <Card title="企业默认模型" extra={<Button type="primary" disabled={!orgId || !defaultProvider || !defaultModel} onClick={async () => { await enterpriseApi.saveDefaultModel(orgId, defaultProvider, defaultModel); await loadOrgs(); message.success("企业默认模型已保存"); }}>保存</Button>}>
        <Space wrap>
          <Input placeholder="Provider 名称，例如 openai" value={defaultProvider} onChange={(event) => setDefaultProvider(event.target.value)} />
          <Input placeholder="模型 ID，例如 gpt-5" value={defaultModel} onChange={(event) => setDefaultModel(event.target.value)} />
        </Space>
        <Typography.Paragraph type="secondary">审核通过的企业成员会继承此模型；模型不可用时运行请求会明确失败。</Typography.Paragraph>
      </Card>
      <Card title="注册审核策略" extra={<Switch checked={reviewRequired} checkedChildren="需要审核" unCheckedChildren="免审" onChange={async (checked) => { setReviewRequired(checked); if (orgId) { await enterpriseApi.saveRegistrationPolicy(orgId, checked); message.success(checked ? "已开启注册审核" : "已关闭注册审核"); } }} />}>
        <Typography.Paragraph type="secondary">开启时新用户进入待审核列表；关闭时注册申请会自动加入企业并可直接登录。</Typography.Paragraph>
      </Card>
      <Card title="待审核注册申请">
        <List
          size="small"
          dataSource={applications}
          locale={{ emptyText: "暂无待审核申请" }}
          renderItem={(application) => (
            <List.Item
              actions={[
                <Button
                  key="approve"
                  size="small"
                  type="primary"
                  onClick={async () => {
                    await enterpriseApi.reviewApplication(
                      orgId,
                      application.application_id,
                      "approved",
                    );
                    setApplications(await enterpriseApi.applications(orgId));
                  }}
                >
                  通过
                </Button>,
                <Button
                  key="reject"
                  size="small"
                  danger
                  onClick={async () => {
                    await enterpriseApi.reviewApplication(
                      orgId,
                      application.application_id,
                      "rejected",
                    );
                    setApplications(await enterpriseApi.applications(orgId));
                  }}
                >
                  驳回
                </Button>,
                <Button
                  key="info"
                  size="small"
                  onClick={async () => {
                    await enterpriseApi.reviewApplication(
                      orgId,
                      application.application_id,
                      "needs_info",
                      "请补充资料",
                    );
                    setApplications(await enterpriseApi.applications(orgId));
                  }}
                >
                  补充资料
                </Button>,
              ]}
            >
              <List.Item.Meta
                title={`用户 #${application.user_id}`}
                description={application.supplement || "未填写补充资料"}
              />
            </List.Item>
          )}
        />
      </Card>
        <Button
          type="primary"
          disabled={!selectedTeam}
          onClick={() => void savePolicies()}
        >
          保存团队策略
        </Button>
      </Space>
    </PageShell>
  );
}
