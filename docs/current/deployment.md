---
type: deployment
module: server
lifecycle: current
authority: current
company_standard: 1.x
migrated_from: workspace docs/07-DEPLOYMENT.md
migrated_at: 2026-09-05
---

# 一、服务端（生产 124.221.205.221）

> 迁移自工作区 docs/07-DEPLOYMENT.md（2026-09-05 知识库拆分，出处保真）
>
> 本文件仅收录源文档「§一 服务端」全文并追加 2026-09-05 只读审计补充；客户端发布（CyImagePro RELEASE_INFO / 版本守卫 / NSIS）、本地开发环境与 RAGFlow 知识库见根工作区 `docs/07-DEPLOYMENT.md` 与客户端仓库文档。

- 登录：`ssh ubuntu@124.221.205.221`（id_ed25519 已登记；**docker 需 sudo**）
- 目录：`/opt/GPT_Image_2_service`；`deploy.sh`：`git pull → docker compose build backend → up -d → restart nginx → ps`
- docker compose 4 服务：`postgres:16-alpine`、`redis:7-alpine`、`backend`（8000 仅 expose，挂载 certs/.env/docker.sock）、`nginx:alpine`（80 端口，安全响应头 + HSTS，TLS 在云 LB 终止）
- 配置快照：工作区 `server_config_124.221.205.221/`（nginx/systemd/服务目录，2026-06-19，含 sha256）
- 外部依赖：PostgreSQL、Redis、微信支付 API、汇率 API（EXCHANGE_RATE_API）、SMTP、上游 OpenAI 兼容 API

## 当前部署状态（2026-08-28 SSH 实查）

生产 = **f333fcb**（V4.2.3 Skill 公开投稿链路；`/opt/GPT_Image_2_service` 已切 `master` 分支，origin/master 同步；compose 4 容器在线）。部署前备份 `/opt/GPT_Image_2_service/backups/pg-pre-v423-20260828-0148.sql.gz`（gzip 校验通过）。实测：`/api/health` → 4.2.3；未登录 `GET/POST /api/skills/mine|submissions*` → 401（部署前为 404，根因是投稿路由从未上线——功能此前只存在于本地工作区）；迁移 `v423_skill_submissions` 已落库（4 张 skill_* 表）；`skill_samples` 命名卷挂载 `/app/data/skill_samples` 且容器内可写；重启后 backend/nginx 日志无 404/422/权限/写入错误。

上一版 9a78c9f（V4.2.2 技能工坊目录）备份为 `pre-9a78c9f-20260827.sql.gz`。

## 2026-09-05 只读审计补充

> 以下为 2026-09-05 只读审计核实事实（已核实，直接采用；不记录任何密钥值 / 密码 / 证书内容）。

- **生产 HEAD = c16632f**（`fix(image): switch runtime image endpoint to cf.api.fan`，提交时间 2026-09-04 17:19；与 GitHub origin/master 同步，tracked 文件零改动）。
- **运行镜像**：`gpt_image_2_service-backend:latest` 构建于 2026-09-04 17:25，`APP_VERSION=4.2.3`。
- **容器与 compose**：4 容器（backend / nginx / postgres / redis），compose 项目名 `gpt_image_2_service`，卷 `pgdata` / `redisdata` / `skill_samples`。
- **backend 挂载**：`certs`（ro）/ `.env`（rw）/ `docker.sock`（rw，**安全观察项**）/ `skill_samples`。
- **配置文件**：`.env` 权限 600、共 29 个变量（微信支付 + SMTP + SECRET_KEY 等）；`certs/` 仅含 `apiclient_key.pem` 与 `wechatpay_public_key.pem` 两个证书文件。
- **备份**：无自动定时备份；最近手工 pg dump 为 2026-08-28；`backups/` 目录另有 8/27–28 三份备份与 9/4 的 env-only 备份。
- **端口暴露**：仅 nginx 发布 80 端口；backend / postgres / redis 均不暴露宿主机端口。
- **健康检查**：`/api/health` 返回 4.2.3。
