# 云迈智能体部署边界与控制面

云迈智能体由三个边界组成：控制面服务、桌面端和通信接口。桌面端是用户电脑上的本地应用，控制面可以部署在企业内网服务器或云主机。

## 1. 三部分边界

| 部分 | 运行位置 | 负责内容 | 默认数据位置 |
| --- | --- | --- | --- |
| 控制面服务 | 企业内网或云端 | 企业、团队、用户、角色、权限、注册、登录、审核/免审、Provider/默认模型、配额、策略下发、审计和必要 API | 控制面数据目录或 PostgreSQL |
| 云迈智能体桌面端 | 用户 Windows/macOS/Linux 电脑 | 本地消息处理、会话、工具、工作区和本机控制权限 | 用户本机 `~/.octop` |
| 通信接口 | HTTPS/WSS | 登录令牌、企业身份、策略、模型引用、审计事件和健康检查 | 令牌由客户端安全存储；不通过接口上传本地工作区原文 |

控制面部署包是仓库的 `docker/` 目录和 `docker/docker-compose.yml`。它不包含也不安装 Wails 桌面程序。桌面程序由 GitHub Release 的各平台安装包交付。

## 2. 控制面启动

Linux 服务器上：

```bash
git clone --branch v1.0.7 https://github.com/lieren2012/Yunmell-Agent.git
cd Yunmell-Agent
cp docker/control-plane.env.example .env.deploy
# 编辑 .env.deploy，至少替换 OCTOP_DEFAULT_PASSWORD
docker compose --env-file .env.deploy -f docker/docker-compose.yml up -d --build
curl -fsS http://127.0.0.1:6602/api/health
```

生产环境应由 Nginx、Caddy 或云负载均衡器提供 HTTPS，并只向外暴露控制面地址。`OCTOP_DATA` 必须使用持久化磁盘；PostgreSQL 可通过 `OCTOP_DATABASE_URL` 接入外部数据库。

## 3. 桌面端连接配置

桌面端设置中的 **控制面地址** 用于保存企业管理/登录服务地址，例如：

```text
https://agent.example.com
```

留空表示使用桌面端内置的本地运行时。开发时也可以临时设置环境变量：

```bash
OCTOP_DESKTOP_URL=https://agent.example.com
```

客户端启动前会探测 `<地址>/api/health`，然后仍在本机启动桌面端内置运行时；桌面端的消息、会话、工具和工作区不会因为填写控制面地址而迁移到服务器。正式版本应使用 HTTPS；HTTP 只用于企业内网联调。桌面端发布包、绿色运行时和控制面 Docker 镜像分别交付，不能把桌面安装包当作云端服务镜像。

## 4. 验收边界

控制面验收：健康检查、管理员登录、企业创建、公开注册、审核/免审、成员/团队隔离、默认模型和 Provider 配置、配额/策略读取、审计记录。

桌面端验收：安装包启动、空控制面地址时本地运行、填写控制面地址后的连接探测、登录令牌安全存储、本地会话/工作区/工具运行，以及断开控制面后的本地数据不丢失。

通信验收：HTTPS/WSS 证书校验、过期令牌处理、企业越权返回 403、控制面不可达时的明确错误、策略变更下发和审计事件不携带本地工作区原文。

当前 v1.0.7 先固定上述发布与部署边界；桌面端与独立控制面之间的策略同步和本地执行协议按该接口边界继续迭代。
