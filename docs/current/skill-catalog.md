---
type: skill
module: server
lifecycle: current
authority: current
company_standard: 1.x
migrated_from: workspace docs/15-SKILL-WORKSHOP.md
migrated_at: 2026-09-05
---

# ImagePro 技能工坊（v4.2.3）

> 迁移自工作区 docs/15-SKILL-WORKSHOP.md（2026-09-05 知识库拆分，出处保真）
>
> 本文件只保留服务端事实：合同分层中的 SkillPackage 发布侧、「生成、质检与计费」中的服务端报价/授权/结算、Catalog 与后台、V6.5 服务端小节。技能工坊客户端全部内容见客户端仓库 `GPT_Image_2_Application/docs/current/skill-workshop.md`。
>
> 与本目录已有的 `docs/SKILL_CATALOG.md` 的关系：二者主题相邻但不重复——`SKILL_CATALOG.md` 是 Skill Catalog API 的目录数据文档（Public/Admin API 端点与 `skill_packages` 表结构速查），本文件是自工作区知识库迁移的技能工坊服务端事实全量描述。

## 产品结构

> 客户端节：八步向导 Creator Workbench、首批目录可用性等见客户端仓库 `GPT_Image_2_Application/docs/current/skill-workshop.md`「产品结构」。

## 合同分层（SkillPackage 发布侧）

```text
SkillPackage（服务端发布的不可变版本）
├── Core Rules（领域硬规则）
├── Base Profile（默认完整基线）
├── Style / Theme / Platform Profiles（可组合配置）
├── Asset Roles（brand_logo/product/space/device/style_reference）
└── Review Rubric（质检维度）
```

> 客户端节：SkillProject / UserSkillDraft 两段本地合同与 Prompt 优先级见客户端仓库 `GPT_Image_2_Application/docs/current/skill-workshop.md`「合同分层」。

## Logo 资产

> 客户端节：Logo 分析、品牌卡与 SHA-256 失效机制见客户端仓库 `GPT_Image_2_Application/docs/current/skill-workshop.md`「Logo 资产」。

## 生成、质检与计费

工坊复用原有任务队列、图库和服务端报价/授权/结算流程。取消报价或创建任务失败会释放预留。生成后质检由用户主动触发，使用 `image_evaluation` 路由输出通过、警告或不通过以及证据；一键修正只创建新的编辑提案，必须再次确认报价才能生成，不覆盖原图。

## Catalog 与后台

- `GET /api/skills/catalog`：发布目录，支持 domain 过滤、ETag 和缓存。
- `GET /api/skills/{skill_id}/versions/{version}`：读取指定已发布版本。
- 后台“Skill 内容中心”：草稿、结构校验、预览、发布、停用、回滚和审计。
- 已发布版本不可原地修改；发布新版本会归档当前版本，回滚会产生管理员审计。

客户端在线读取失败时依次回退本地缓存和内置包（专业桌搭、UI 概念设计；其余方向回落桌搭）。现有模板、视觉理解 Runtime Skill、图片生成和 AI 智能体入口均保持兼容。

## 视觉项目通用化与社区发布（v4.2.3）

> 客户端节：五步 Skill 创作器与创作器交互规范见客户端仓库 `GPT_Image_2_Application/docs/current/skill-workshop.md`「视觉项目通用化与社区发布」。服务端侧的社区投稿 / 审核 API 与状态机事实见本仓库 `current/api.md`「客户端 API（按前缀）」skills 端点与「社区 Skill 审核（v4.2.3）」。

## 模板复用 Skill（Skill Recipe，V6 / 2026-08-28）

> 客户端节：SkillRecipe / 同源重建 / Skill Origin Guard / Prompt 对比视图见客户端仓库 `GPT_Image_2_Application/docs/current/skill-workshop.md`「模板复用 Skill」。

## V6.1 GUI 收口（2026-08-28）：Detail Repair 闭环 / 创作器几何 / Picker Portal / 技能删除

> 客户端节：见客户端仓库 `GPT_Image_2_Application/docs/current/skill-workshop.md`「V6.1 GUI 收口」。

## V6.2 产品成熟度（2026-08-28）：Skill 直接生成 / Repair 进度诚实 / Handoff 响应 / 语义参考图 / 自动保存

> 客户端节：见客户端仓库 `GPT_Image_2_Application/docs/current/skill-workshop.md`「V6.2 产品成熟度」（计费单一路径：autoStart 仍走服务端报价 + QuoteConfirmDialog）。

## V6.3 直接复用 UX 收口（2026-08-28）：严重级契约 / Preflight 四态 / 槽位合同 V2 / 人物替换紧凑化 / Skill 封面

> 客户端节：见客户端仓库 `GPT_Image_2_Application/docs/current/skill-workshop.md`「V6.3 直接复用 UX 收口」。

## V6.5 UI 概念设计方向做实与目录多方向点选（2026-08-28）——服务端小节

### 服务端（GPT_Image_2_service）

- `skill_catalog.py` 新增 `UI_PROFILES` + `UI_PAYLOAD`：base×1（现代产品界面）/ style×6（极简、暗色专业、玻璃拟态、大字编辑风、科技渐变、柔和圆角）/ theme×3 / platform×3（桌面 Web、移动 App、响应式通用）；asset_roles 复用 `brand_logo` + `style_reference`（**不新增 AssetRole**）；core_rules 覆盖信息层级、8pt 栅格、真实组件比例、界面文案防乱码、品牌卡保真、正面视口渲染。
- 新增可选 payload 键 **`default_negative_prompt`**（领域默认负面词基线），`validate_package_payload` 无需必填校验（额外键透传）。
- seed 按 `(skill_id, version)` 幂等插入 1.0.0；catalog 路由按 `published_at desc` 取每 skill 最新版，1.0.0 自动取代 0.1.0 占位，**无数据库迁移**。管理端 Skill 内容中心动态列表零改动。

> V6.5 客户端小节（builtinCatalog / catalogService / SkillWorkshop 点选）与验证数据见客户端仓库 `GPT_Image_2_Application/docs/current/skill-workshop.md`「V6.5」。

## 验证记录

> 服务端验证事实已分别收录于上列各服务端节与 `changelog/CHANGELOG.md`；本节客户端验证明细见客户端仓库 `GPT_Image_2_Application/docs/current/skill-workshop.md`「验证记录」。
