---
type: changelog
module: server
lifecycle: current
authority: current
company_standard: 1.x
migrated_from: workspace docs/08-CHANGELOG.md
migrated_at: 2026-09-05
---

# 变更记录（GPT_Image_2_service）

> 迁移自工作区 docs/08-CHANGELOG.md（2026-09-05 知识库拆分，出处保真）
>
> 本文件由工作区 `docs/08-CHANGELOG.md` 按条目拆分而来：服务端条目原文保留；工作区混合条目（双侧均有事实）收录并在标题后标注「（工作区混合条目，双侧镜像）」；纯客户端条目与文档工具链条目已剔除。完整工作区级变更见根工作区 `docs/08-CHANGELOG.md`；客户端详细变更见 `GPT_Image_2_Application/CHANGELOG.md`。本仓库重要修改必须追加本文件。

## 2026-09-05 服务端接入内网 Gitea（Cy-image-service）：main=c16632f / develop 建线，CI 四 job 全绿，CD 准备完成（未启用）

- **接入**：remote `gitea` = SSH alias `gitea-cy:gcy/Cy-image-service.git`（GitHub origin 保留不动，仅新增远端）；**main = c16632f**（`fix(image): switch runtime image endpoint to cf.api.fan`，2026-09-04 17:19，与 GitHub origin/master 及生产 HEAD 一致），**develop** 建线 = main + CI/CD/知识库基建（docs/ + scripts/ragflow_sync.py + .gitea/workflows + deploy/cd/）；推送前敏感扫描通过（工作区 + 全部可达历史：无生产 .env / 支付私钥 / 令牌 / 数据库备份）。推送采用 temp-index 提交法，未触碰工作区未提交改动。
- **CI 落地并实跑全绿**（`.gitea/workflows/ci.yml`，Runner `gpt-image-service-ci`，本机 host 模式）：`sensitive & config guard`（git ls-files 敏感文件零跟踪 + `.env.example` 占位值判定 + deploy.sh/compose 静态校验）→ `backend pytest`（**165 项全过**；专用测试库 cyimage_v4_test + Redis db15 + 支付链路全 monkeypatch，不连生产库不发生真实收费）→ `admin frontend build`（npm ci + vite build）→ `cd scripts isolation test`（5 条阻断路径真实触发）。修复记录：首跑 guard 误判 `.env.example` 的 `SECRET_KEY=change-this-secret-key-in-production` 为真实密钥——占位值判定改为「非空且不以 change/your/replace/example/placeholder/dummy 前缀开头」。
- **CD 准备（未启用）**：`deploy/cd/{preflight,deploy,rollback}.sh` + `deploy-production` / `rollback-production` 两 workflow（手动触发；`PROD_DEPLOY_ENABLED` 开关默认关闭；发布 = pg_dump 前置备份 + 受信 main 祖先 + CI 绿 + 健康轮询；回滚 = last-good + 破坏性 DDL 阻断，绝不自动恢复旧整库）。详见 `docs/current/deployment.md` CD 节。**本轮生产未发生任何变更**。
- **隔离边界（如实标注）**：Docker 镜像构建验证因 CI 机无 Docker 未覆盖；分支保护配置因 Gitea HTTP 凭据临时不可用转人工清单（main 禁直推 + 四 check 必须绿）。

## 2026-09-05 知识库拆分：服务端事实源迁移至本仓库 docs/，RAGFlow Dataset GPT_Image_2_service 建立

- 服务端知识事实源从工作区根 `docs/` 迁移至本仓库 `docs/`（`current/` 按主题 + `decisions/` ADR + `changelog/` + `archive/`）；迁移映射见 `docs/MIGRATION.md`。
- 本仓库 `docs/` 经 `scripts/ragflow_sync.py` 单向增量同步至 RAGFlow Dataset「GPT_Image_2_service」；客户端侧事实源迁移由客户端仓库负责；工作区根 `docs/` 保留工作区级导航与双线对照。

## 2026-08-28 V6.5 技能工坊 UI 概念设计方向做实 + ZCode 接入 RAGFlow MCP（工作区混合条目，双侧镜像）

- **服务端**（GPT_Image_2_service）：`skill_catalog.py` 新增 `UI_PROFILES`/`UI_PAYLOAD`，`ui_concept` 从 planned 占位升级 **1.0.0 availability=ready**——base（现代产品界面）/ style×6（极简、暗色专业、玻璃拟态、大字编辑风、科技渐变、柔和圆角）/ theme×3 / platform×3（桌面 Web、移动 App、响应式通用）；asset_roles 复用 `brand_logo`+`style_reference` 不新增枚举；core_rules 覆盖信息层级、8pt 栅格、真实组件比例、界面文案防乱码、品牌卡保真、正面视口渲染；新增**可选** payload 键 `default_negative_prompt`（领域负面词基线，校验零改动）。seed 幂等插入 + catalog 按 published_at 取最新版，0.1.0 自动被取代，无迁移、API 形状不变。
- **客户端**（GPT_Image_2_Application）：工坊目录条 ready 项开放点选（ADR-028 多方向目录）——`selectCatalogSkill` 加载包并校验返回一致（离线错包明确报错不顶替）；`createProject(settings, pkg)` 由包驱动（项目名/风格/主题/平台/负面词）；`catalogService` 通用化（分包缓存键、defaults 按 `default_profile_ids` 实际存在者解析、`negative_prompt` 映射、离线回退表含 UI）；`builtinCatalog` 新增 `BUILTIN_UI_PACKAGE` 并把 ui 目录条统一命名「UI 概念设计」置 ready；步骤 0 模板卡与右栏 hero 去桌搭写死文案；`SkillPackage` 类型加可选 `negative_prompt`。
- **Rust / 管理后台**：零改动（domain 走 data_json 透传；Skills.vue 动态列表自动展示新包）。
- **工具链**：根仓库新增 `.zcode/config.json`，以工作区级 MCP 注册 `ragflow-project`（http://192.168.110.91:9382/mcp，与 Claude Code `.mcp.json` 同址同服务；ZCode 工作区 server 自动信任连接，重启会话生效）。子仓库单独作为工作区打开时需各自补配（见 docs/12）。
- **验证**：服务端 pytest **168**（+3：UI payload 校验 / catalog 最新版晋升 / 详情合同）；客户端 typecheck + Vitest **1635**（+7：catalogService 多方向 4 / compiler UI 包 2 / 页面点选契约 1）。详见 docs/15 与 ADR-028。

## 2026-08-28 Skill 创作器五项修复、投稿服务端加固与生产部署（f333fcb）（工作区混合条目，双侧镜像）

- **Skill 创作器弹窗重做**：三段式布局（固定头部 + `auto minmax(0,1fr)` 可滚动正文 + 固定底栏），1024×768 下上一步/下一步/保存/提交永不出视口；打开锁背景滚动、Escape 关闭（图片库选择器打开时不抢）。
- **来源事实页**：紧凑分组列表 + 只读徽标 + 长内容两行折叠（展开/收起）；确定性事实全程只读，AI 通用化不触碰。
- **检查规则页**：三个行级编辑卡片（核心规则/阻断条件/质检标准，增删改+上下移+空态+校验），`skillRules.ts` 纯函数层；任何编辑使 `confirmed` 回落 `ai_candidate`，只有显式"确认当前规则"才 confirmed；AI 候选状态与实际执行模型固定在标题区。
- **保存与发布页**：样例双入口（本地文件 + 共享 `ImageLibraryPicker`——从 ImageStudio 两处弹窗抽取的唯一实现）；选中后展示缩略图/文件名/来源徽标/尺寸格式/更换/移除/查看大图；强制公开展示授权勾选；本地保存零网络行为。
- **投稿错误处理**：`submissionService.ts` 统一映射（401 登录失效 / 404·405 服务端未部署 / 409 已投稿 / 413 样例过大 / 422 格式不兼容 / 5xx 稍后重试），不再透出原始 Not Found/JSON；投稿前 `GET /mine` 能力预检；创建成功即记 ID，样例失败重试不重复创建；全部上传完成才标记本地 submitted。
- **服务端**：`source_facts` 改结构化数组合同（value 过净化扫描，旧 dict 422）；零样例投稿恢复（同内容 200 复用 / 内容冲突 409 `SKILL_SUBMISSION_DUPLICATE`）；样例原子写入（临时文件+fsync+replace，失败清理）；正式迁移 `v423_skill_submissions` + `skill_samples` 持久卷；管理端错误全结构化 `{code, message}`。
- **生产部署**：服务端仓库提交 f333fcb（master 与 codex/skill-workshop-4.2.2 同步推送），服务器 pg-dump 备份后重建 backend；实测 `/api/health`=4.2.3、投稿端点 401（原 404 根因=功能未部署）、迁移落库、卷可写、日志干净。
- 验证：客户端 typecheck + Vitest 1467（新增 skillRules/submissionErrors/结构守卫 45 项）+ 生产构建通过；服务端 pytest 165（投稿专项 8 项）通过。

## 2026-08-28 视觉项目通用化、社区 Skill 与 v4.2.3（工作区混合条目，双侧镜像）

- 视觉理解新增五步 Skill 创作器：确定性提取来源事实，使用独立 `skill_authoring` 模型角色生成通用化候选，用户确认后保存到技能工坊“我的技能”。
- 客户端新增本地 `UserSkillDraft` 存储；项目模板、通用 Skill 与生成实例互不污染。
- 服务端新增用户投稿、授权样例、不可变修订、审核事件和社区发布模型/API；普通管理员负责审阅、退修和拒绝，超级管理员批准后发布到公共 Catalog。
- 单张图生图复用共享 `@` 图片 Mention：真实图片侧车绑定、显式人物/背景/风格角色、视觉优化多模态顺序和最终 Prompt 引用合同保持一致。
- 客户端与服务端版本统一为 4.2.3。验证：客户端 typecheck、1422 Vitest、218 Rust 测试通过；管理前端构建、服务端 Catalog 4 项与投稿 2 项专项通过。

## 2026-08-27 ImagePro 技能工坊与 v4.2.2（工作区混合条目，双侧镜像）

- 客户端新增一级入口“技能工坊”，首个生产级 Skill 为专业桌搭；领域目录、八步向导、专业模式、本地项目、离线回退和确定性 Prompt 编译已落地。
- Logo 素材采用用户主动分析、人工确认和 SHA-256 失效机制；生成携带原图，品牌硬冲突阻断生成。
- 生成后评价改为用户主动触发；结果给出通过/警告/不通过、证据与修正提案，修正必须重新报价。
- 服务端新增版本化 Skill Catalog 与管理端内容中心，支持草稿、校验、预览、发布、停用、回滚和审计。
- 版本字段统一为 4.2.2；Vitest 1411、Rust 218、后端专项 4 项与两套生产构建通过。
- 服务端以部署前 PostgreSQL 备份 `pre-9a78c9f-20260827.sql.gz` 上线提交 `9a78c9f`，公网健康与 Skill Catalog 正常；客户端 tag `v4.2.2` 指向 `e57baba`，GitHub Actions Run `33068420066` success，正式 Release、官方镜像、NSIS/MSI 下载、哈希与签名验收全部通过。

## 2026-08-26（第二轮）GPT-Image-2 API Contract Hotfix Phase 1

- **根因**：gpt-image-2 Provider（packyapi / cf.api.fan）不接受 `response_format` 参数（实测 400 `unknown_parameter` / `packy_invalid_request_error`），客户端三处发送 `response_format=b64_json` 导致 Images API 全面 400；删除后 Provider 固定返回 `data[0].b64_json`。
- **修复（仅删参数，零行为外扩）**：`task_runner.rs` generations JSON body / edits multipart / `commands.rs` `generate_test_image` 三处删除 `response_format`；响应解析（`data[0].b64_json` -> decode -> 落盘）保持不变；`image[]` 多文件部件名**未改**（真实验证 200 兼容，见下）。
- **防回归**：请求体构造收敛为纯函数（`generations_request_body` / `edits_text_fields` + `EDITS_IMAGE_PART_NAME` 常量），`ApiRequestBody` 加 `deny_unknown_fields` 严格契约；新增 4 个契约测试锁死「必需字段存在 / `response_format`+`stream`+`partial_images`+`style`+`input_fidelity` 禁入」。
- **诊断补全**：`extract_error_parts` 提取上游 `error.type` 并持久化到 `SubTaskErrorDetail.provider_type`（Rust + TS 接口同步，serde default 兼容旧 tasks.json）。
- **真实验证（cf.api.fan + www.packyapi.com 经系统代理）**：generations（App 同构请求体）HTTP 200 / b64_json / 有效 PNG；edits `image[]` 单参考图 HTTP 200（**兼容性 PASS，实现保持不变**）；生产 `PACKYAPI_IMAGE_BASE_URL` 无环境变量覆盖 = 默认 `https://www.packyapi.com`，删参后 200 -> **无需切域名**。
- **验证**：cargo test **218 全绿**（含 4 个新契约测试）；typecheck / frontend build / vitest **1406 全绿**（同步更新 `personReplacementPayload.test.ts` 源码守卫断言适配 `EDITS_IMAGE_PART_NAME` 常量）。
- 测试基建：工作区根 `gpt-image-2-api-test/`（独立零依赖 Node 真实 API 冒烟/对照程序，Key 只存本地 `.env` 不入库）。

## 2026-08-26 管理后台整理、客户归档与响应式修复

- 概览改为五项点数口径核心指标，移除 Token 卡和重复快捷入口；后端新增成功充值点数汇总，同时保留旧兼容字段。
- 左侧导航按四个业务域折叠；系统设置集中业务参数、基础设施和运维，旧环境变量管理员登录配置退出界面；管理员页新增仅超级管理员可看的登录记录及结果/账号/日期/分页过滤。
- 1024–1199px 使用 72px 侧栏，≥1200px 恢复完整侧栏；客户表窄桌面降级核心列、操作列固定；弹窗统一视口约束和内部滚动。
- 用户表新增 archived_at/archived_by。新增删除预检：干净账户清理设备/Runtime Token 绑定后物理删除；业务历史账户返回结构化 409 并归档，禁登录、释放 Token、保留流水/用量/试用领取/分配与管理员审计。
- 验证：管理前端 production build 通过；服务端 **150 pytest 全绿**（新增 4 组生命周期/审计/统计回归）。

## 2026-08-24（第八轮）CY Credits Billing V1 + Trial Entitlement + Cost & Margin Ledger + Device History（V4.2.0，ADR-018）（工作区混合条目，双侧镜像）

- **状态**：三仓库同步落地（服务端 + 管理后台 + 客户端），服务端 145 pytest / 客户端 1165 vitest + 213 cargo / 双端 build 全绿。版本：服务端 4.0.2 → 4.2.0；客户端 4.0.9 → 4.2.0（内含第七轮 V4.1 视觉工作流一并发布）。
- **CY 点数计费（ADR-018）**：¥1=100 点（system_config.credits_per_cny），users 三类点数列（paid/trial/gift INT），消费顺序 trial→gift→paid 唯一入口 consume_credits；USD 列降级为兼容镜像（700 点/$ 回写，旧客户端继续可用）；旧余额迁移 v4.2_credits_billing 三步走（preview→核对→super_admin apply，非生产自动，幂等）。
- **报价冻结**：POST /api/billing/quote（quote_id Redis 600s）→ authorize 携 quote_id 按冻结价计费；流水快照 unit_credits/pricing_rule_id/version；客户端全局 QuoteConfirmDialog（模式/数量/单张/预计/余额/剩余），禁止自行 数量×单价。
- **定价引擎 + Price Guard**：pricing_rules 表（每 feature/model 唯一生效）；毛利公式 revenue=unit/credits_per_cny、effective_cost=nominal×(1+buffer)、min_unit=ceil_step(cost/(1-target)×rate)（¥0.20+10%+70% → 80 点）；低于目标普通管理员 403、super_admin force+reason 留痕；采购成本以 RMB 记账（上游 $1≈¥1 业务事实）。
- **经营账**：cost_margin_ledger settle 成功冻结快照；收入只计 paid 部分，trial/gift 记 promotional_value（获客成本口径，不污染付费毛利）；后台「成本与毛利」页（时间/分类/RequestID 筛选 + 汇总）。
- **试用一次性领取**：trial_claims（normalized_email 唯一，trim+lower），删号重注册不可再领，并发双击 DB 约束兜底；trial_available = 总开关 AND 试用默认 Token 有效 AND 未领取；POST /api/trial/claim 自动 +500 点 + 绑试用 Token；注册流 / upgrade-trial 对齐同一 claim ledger。
- **Token 默认角色**：后台徽章改「正式默认 / 试用默认」（每类型至多一个默认的原有部分唯一索引不变）；路由隔离原有（ensure_paid_assignment / resolve_default_token(is_trial)）。
- **设备历史 + 心跳修复**：client_devices 表（user_id+device_id 唯一 upsert，永久保留）；GET /api/admin/devices 返回服务器计算的 seconds_since_seen（恒 ≥0）——「-28 秒前」根因（管理员浏览器时钟与服务端求差且无 max(0,·)）根除；后台页改「客户端设备」（在线/历史统计 + 全部/在线/离线筛选）。
- **汇率语义**：packages 返回 exchange_rate_source + updated_at（realtime_cached→「参考汇率 · 每小时更新」）；点数体系下汇率退出用户侧主展示。
- **客户端**：账户页点数化（可用点数 + 正式/试用/赠送分列；¥ 档位充值实时点数预览；点数流水面板；试用入口服务端判定）；任务卡计费列（预计→实际（退回））；UI Skill 13.0.0→14.0.0（规则 22 + patterns §21-§24）。
- **兼容窗口**：旧 USD create_order 继续可用（$N→N×700 点）；users/me、authorize/settle 保留镜像字段；usage_logs.cost_usd 镜像维持（Token 配额聚合依赖）。

## 2026-08-21 客户端 v4.0.6 视觉模型服务彻底拆分 + 智谱模型同步 + GLM-5V-Turbo 接入（工作区混合条目，双侧镜像）

- **根因修复（三处）**：① `registry/glm.json` 停留在 12 模型时代（视觉仅 2 个 deprecated），对齐智谱官方模型概览更新为 24 模型；② 目录只在使用时合并落库、`hydrate()` 不合并 → 升级用户一直看旧列表；③ `AgentProviderSettings` 编辑页标题硬编码「AI 模型服务」且模型中心无 category 概念 → 视觉档案列表与 AI 页一致
- **Registry 数据**：新增视觉模型 `glm-5v-turbo`（推荐默认）、`glm-4.6v`、`glm-4.6v-flash`、`glm-4.1v-thinking-flashx`、`glm-4.1v-thinking-flash`、`glm-4v-flash`（均 capabilities 含 vision，走同一 chat/completions，无新 adapter）；补文本模型 glm-4.7-flashx/-flash、glm-4.5-airx、glm-4-long、glm-4-flashx/flash-250414；不收录 glm-ocr（专用文档解析）与 autoglm-phone（Computer Use 框架）
- **启动合并**：`store.hydrate()` 经 `mergeBuiltinRegistryIntoProfile` 幂等合并内置 Registry（顶层 + mode_states 双层），误标 missing 恢复、custom/默认模型不动；解决旧缓存
- **UI 类别化**：编辑/添加页标题按 category（视觉模型服务/AI 模型服务）；ModelCenterSection 接 serviceCategory（vision 档案默认「视觉模型」tab、计数「N 个支持视觉理解」、空态引导）；ModelConfigDialog vision 档案只显示「默认视觉理解模型」默认位（禁写 agent 用途默认）；custom 新增模型 vision 档案默认勾选图片理解；列表卡片 vision 档案显示视觉模型数
- **category 感知默认**：`buildEmptyModeState(type, category)` —— 新建视觉档案默认模型 = Registry 首个视觉模型（glm-5v-turbo），不再是文本 recommended
- **测试**：model-registry.smoke 新增 4 段（视觉 Registry / category 默认 / hydrate 升级合并 / AI-Vision 双默认位独立+能力守卫）；修复 `_ts_loader.mjs` 缺图片 loader 导致的 smoke 回归；vitest 276 / cargo 131 / tsc 全绿
- **未验证项**：UI 走查与 glm-5v-turbo 真实 API 调用待打包环境验收（代码链路：VisionUnderstanding → resolveByokVisionConfig → vision_analyze_image → chat/completions 已静态核验）

## 客户端版本摘要（详见客户端 CHANGELOG.md）（工作区混合条目，双侧镜像）

- **v4.0.4**（acf090d，tag 已推远端）：官方更新镜像设为主更新通道（zjcypc `/client-updates/` 主源、GitHub 备用）；生产镜像 latest.json 仍指 4.0.3，发布链路待确认（见 09-KNOWN-ISSUES #2）
- **v4.0.3**（2026-08-19）：Server Runtime Gate（runtimeReady 门控）、回环地址防护、SSE 重建、任务终态对账（reconciliation）、服务器模型同步单一来源化
- **v4.0.2**：应用内更新链修复（八态状态机）、自动心跳调度、稳定设备标识、发布链路四处版本校验
- **v4.0.1**：Planner 截断重试（planner_output_truncated）、图生图源图固定（taskSourceImage/active_image_set_at）

## 服务端版本摘要（git log）

- **c27f2dc**（2026-08-19 部署生产）：客户端官方更新镜像 `/client-updates/`（APP_VERSION 仍 4.0.2）
- **V4.0.2**（ed74cda，2026-08-18 部署生产）：admin_users 数据库化、登录加固（nginx+Redis 双限流）、自动心跳、安全基线
- **V4.1 特性**（823557d）：共享 runtime token 池、退款审核工作流、SSE 实时通知
- 更早：V4 后端统一余额与计费（ba48e89）、订单生命周期重构（ASSIGNED 状态 + 退款冲正，7e63f8c）等
