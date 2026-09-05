---
type: doc
module: server
lifecycle: current
authority: current
company_standard: 1.x
migrated_from: workspace docs/（无单一源，知识库拆分新建）
migrated_at: 2026-09-05
---

# 知识库拆分迁移映射（服务端侧）

> 2026-09-05 知识库拆分时新建：记录工作区根 `docs/`（`D:\ClaudeProject\GPT-Image\docs`）服务端内容到本仓库 `docs/` 的逐文件映射。原则：内容保真——复制原文，不做事实改写、不总结压缩；只删除不属于服务端侧的节、调整节标题层级、加出处说明。

## 迁移映射表

| 工作区源文件 | 本仓库目的地 | 说明 |
|---|---|---|
| `docs/03-BACKEND.md` | `current/backend.md` | 整文件迁移（本次拆分前已到位，未改动） |
| `docs/04-DATABASE.md` | `current/database.md` | 整文件迁移（本次拆分前已到位，未改动） |
| `docs/decisions/ADR-002 / 005 / 007 / 018` | `decisions/` 对应文件 | 整文件迁移（本次拆分前已到位，未改动） |
| `docs/02-FRONTEND.md` §二 管理后台 | `current/admin-frontend.md` | §一 客户端前端留在根工作区（客户端侧） |
| `docs/05-API.md` | `current/api.md` | 「客户端统一错误语义（serverApi.ts）」「上游 Provider API（客户端直连）」两节迁至客户端仓库 `docs/current/api-consumption.md`，本侧留一行指针；其余（客户端 API 端点表 / 管理 API / 客户删除与归档 / 社区 Skill 审核）原文保留 |
| `docs/06-MODELS.md` §一 上游 Provider | `current/models-server.md` | §二 客户端 BYOK/Transport/Vision 体系迁至客户端仓库 `docs/current/models.md` |
| `docs/07-DEPLOYMENT.md` §一 服务端 | `current/deployment.md` | 含 2026-08-28 SSH 实查状态原文；追加「2026-09-05 只读审计补充」（c16632f / 镜像 4.2.3 / 容器与卷 / 备份状态；不含任何密钥值）。§二 客户端留在根工作区 |
| `docs/current/release.md` | `current/release.md` | 服务端版本线原文保留；客户端版本线与双线对照说明以指针指向客户端仓库与根工作区 |
| `docs/current/testing.md` | `current/testing.md` | 服务端行与 Release 清单 `/health` 段保留；客户端行迁至客户端仓库 |
| `docs/15-SKILL-WORKSHOP.md` | `current/skill-catalog.md` | 服务端节（SkillPackage 发布侧 / 生成质检与计费 / Catalog 与后台 / V6.5 服务端小节）原文保留；客户端各节替换为一行指针指向客户端仓库 `docs/current/skill-workshop.md` |
| `docs/09-KNOWN-ISSUES.md` | `current/known-issues.md` | 仅服务端四节：#1 admin 密码 / #5 postprocess / #6 PackyAPI 价格 / #14 管理后台删除与布局；保留原编号 |
| `docs/10-TODO.md` §运维 | `current/todo.md` | 其余小节（文档清理 / 客户端 / 知识库）留在根工作区 |
| `docs/08-CHANGELOG.md` | `changelog/CHANGELOG.md` | 服务端条目原文保留；混合条目标注「（工作区混合条目，双侧镜像）」；纯客户端与文档工具链条目剔除；追加两条 2026-09-05 新条目（Gitea 接入 / 知识库拆分） |
| （无单一源） | `current/README.md` | 服务端知识库索引（拆分时新建） |
| （无单一源） | `docs/MIGRATION.md` | 本文件（拆分时新建） |

## 本仓库既有文件（本次拆分未改动）

- `docs/SKILL_CATALOG.md` — Skill Catalog 目录数据文档（拆分前已存在）
- `docs/client_api.md` — 旧交接文档，口径部分过时（拆分前已存在）

## 根工作区 docs/ 保留内容

- 工作区级导航与总索引（`00-PROJECT-OVERVIEW.md` 等）与客户端/服务端双线对照
- 客户端侧全部事实（客户端仓库迁移由客户端侧负责）
- 其余 ADR（客户端与工作区级决策）、`docs/prompts/`、`docs/ai-comic/`、`docs/archive/` 等历史证据
- RAGFlow 集成文档（`docs/12-RAGFLOW-INTEGRATION.md`，工作区级同步器配置）
