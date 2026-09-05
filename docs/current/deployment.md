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
> 本文件仅收录源文档「§一 服务端」全文并追加 2026-09-05 只读审计补充与 CD 节；客户端发布（CyImagePro RELEASE_INFO / 版本守卫 / NSIS）见客户端仓库 `docs/current/release.md`；本地开发环境见根工作区 `docs/11-DEVELOPMENT-GUIDE.md`。

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

## CD：生产发布/回滚（2026-09-05 准备完成，开关默认关闭，未上线）

> 代码：`deploy/cd/{preflight,deploy,rollback}.sh` + `.gitea/workflows/{deploy-production,rollback-production}.yml`（develop 分支，随下次合入 main 生效）。**当前状态：准备完成但未启用**——仓库未设置 `PROD_DEPLOY_ENABLED` 变量、未配置任何 DEPLOY secrets，生产未发生任何变更。

- **入口与总开关**：Gitea → Actions → 「deploy-production」/「rollback-production」，仅 `workflow_dispatch` 手动触发（push/tag/PR 均不触发）；输入 = 40 位目标提交 SHA（回滚另接受 `last-good`）。deploy/rollback job 仅当仓库变量 **`PROD_DEPLOY_ENABLED == 'true'`** 时存在（未设置时只跑 explain-disabled 说明 job，任何部署动作都不会发生）；必需 secrets（`PROD_SSH_HOST` / `PROD_SSH_USER` / `PROD_SSH_KEY` / `PROD_DEPLOY_DIR` 等）缺失时 **fail-fast 退出而非跳过**。
- **deploy 门禁链**：① SHA 格式校验 + 必须属于受信 main/master 的祖先（`fetch-depth: 0` + `merge-base --is-ancestor`，经 env 传递不插值进 shell）；② 目标提交的 CI commit status 必须全绿（调 Gitea commit status API 复核）；③ 主机侧 `deploy.sh` 前置检查——必需配置（`docker-compose.yml` / 可读 `.env` / `certs/`）缺失 exit 3、工作区不干净 exit 4、SHA 非远端分支祖先 exit 5、`pg_dump` 备份失败（含 `gzip -t` 校验）exit 6；④ detached checkout 目标提交 → `docker compose build backend && up -d && restart nginx` → 健康轮询（30×2s，比对 `/api/health` 版本）→ `deploy-history.jsonl` 追加记录（last-good 供回滚解析）。
- **rollback 门禁链**：解析 `deploy-history.jsonl` last-good（无历史 exit 2）→ `pg_isready` → **破坏性 DDL 检查**：`git diff 目标..当前 -- backend/app/` 命中 `DROP TABLE/COLUMN`、`RENAME TO`、`TRUNCATE` 则 exit 6 阻断（需人工评估数据库兼容后另行处理）→ 重部署目标提交。**绝不自动恢复旧数据库备份**（项目迁移模型 = `main.py` lifespan 幂等加法迁移，无 alembic/降级脚本；前向迁移只做加法，回滚旧代码通常 DB 兼容，破坏性 DDL 检查是最后防线）。
- **回滚数据库兼容判定依据**（人工评估口径）：检查前向迁移范围内（目标提交→当前）`backend/app/` 是否存在破坏性 DDL——无 → 直接回滚应用层；有 → 先在测试库演练/人工决策，不得自动执行。
- **隔离测试**：CI job「cd scripts isolation test」在每次 push 时真实触发 5 条阻断路径（非法 SHA→2 / 缺配置→3 / 无历史回滚→2 / 破坏性 DDL→6 / 不存在 SHA→5；fixture 临时目录 + `CD_DRY_RUN=1`），不触碰任何主机。
- **启用前置（人工步骤）**：管理员在 Gitea 仓库 Settings → Actions 配置 `PROD_DEPLOY_ENABLED=true` 与 DEPLOY secrets；建议同时配好分支保护（main 禁直推、CI 四 check 必须绿）。普通发布只更新应用（backend/nginx），不动数据库卷；参照 CY-Official-Web 经验但**不照搬**其 SQLite 整库回滚/空库初始化/域名端口方案。
