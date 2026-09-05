---
type: doc
module: server
lifecycle: current
authority: current
company_standard: 1.x
migrated_from: workspace docs/（无单一源，知识库拆分新建）
migrated_at: 2026-09-05
---

# GPT_Image_2_service 服务端知识库索引

> 2026-09-05 知识库拆分时新建；内容出处为工作区根 `docs/` 的服务端部分与既有迁移文件，逐文件映射见 `docs/MIGRATION.md`。

本仓库 `docs/` 是 GPT_Image_2_service（FastAPI 后端 + Vue3/naive-ui 管理后台）的知识事实源，经 `scripts/ragflow_sync.py` 单向增量同步至 RAGFlow Dataset「GPT_Image_2_service」。工作区级导航与客户端/服务端双线对照保留在根工作区 `docs/`（`D:\ClaudeProject\GPT-Image\docs`）；客户端侧事实源在客户端仓库 `GPT_Image_2_Application/docs/`。

## current/（当前有效事实）

| 文件 | 主题 |
|---|---|
| `backend.md` | 后端架构与模块（v1.0.0 含账户治理/会话撤销/权限收紧） |
| `database.md` | 数据库结构（此前整文件迁移） |
| `api.md` | 客户端-服务端 API 契约权威定义（客户端消费约束在客户端仓库） |
| `models-server.md` | 上游 Provider（服务端调度） |
| `admin-frontend.md` | 管理后台（Vue3 + naive-ui）视图、信息架构与响应式 |
| `deployment.md` | 服务端部署（生产 124.221.205.221）与 2026-09-05 只读审计 |
| `release.md` | 服务端版本线（工作线 1.0.0 pending_release；生产仍 4.2.3） |
| `testing.md` | 测试规则（服务端行；当前全量口径 178 passed） |
| `skill-catalog.md` | 技能工坊服务端事实（SkillPackage 发布侧 / Catalog 与后台 / 计费） |
| `security-assessment.md` | v1.0.0 安全评估报告（已修复 S-1～S-5 / 良好项 / 缓期项） |
| `known-issues.md` | 已知问题（服务端侧；原编号 #1/#5/#6/#14 + v1.0.0 缓期项 #15–#17） |
| `todo.md` | 真实未完成事项（§运维） |
| `README.md` | 本索引 |

## decisions/（Accepted ADR）

- `ADR-002-unified-billing-ledger.md` — 统一计费账本
- `ADR-005-no-scheduler-framework.md` — 不引入调度框架
- `ADR-007-money-decimal-cents.md` — 金额 Decimal 分存储
- `ADR-018-cy-credits-billing.md` — CY 点数计费（V4.2）
- `ADR-019-account-governance-lifecycle.md` — 客户账户三段生命周期 + 会话撤销 + 管理员重置密码（v1.0.0）
- `ADR-020-ops-endpoints-super-admin.md` — .env 写入与容器重启收紧 super_admin（v1.0.0）

其余 ADR 属客户端与工作区级决策，保留在根工作区 `docs/decisions/`。

## changelog/

- `CHANGELOG.md` — 本仓库变更记录（服务端条目原文 + 工作区混合条目镜像；v1.0.0 条目置顶）

## archive/

- 历史证据归档目录（当前为空占位，后续归档内容放这里；不进入活跃 RAGFlow 检索范围）

## docs/ 根下既有文件

- `docs/SKILL_CATALOG.md` — Skill Catalog 目录数据文档（Public/Admin API 端点与 `skill_packages` 表结构速查），与 `current/skill-catalog.md` 互补（后者为迁移自工作区的技能工坊服务端事实全量描述）
- `docs/client_api.md` — 旧交接文档，**口径部分过时**，冲突时以源码与本 `docs/` 为准

## 建议阅读顺序

1. 本文件 → `backend.md` / `database.md`（架构与数据基础）
2. `api.md`（对外契约）→ `models-server.md`（上游模型调度）
3. `release.md` → `changelog/CHANGELOG.md`（版本事实：工作线 1.0.0 pending_release / 生产 4.2.3）
4. `deployment.md` → `known-issues.md` → `todo.md`（部署与运维面）
5. 专项：`skill-catalog.md`、`admin-frontend.md`、`testing.md`、`decisions/`
