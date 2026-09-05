---
type: api
module: server
lifecycle: current
authority: current
company_standard: 1.x
migrated_from: workspace docs/05-API.md
migrated_at: 2026-09-05
---

# API 设计

> 迁移自工作区 docs/05-API.md（2026-09-05 知识库拆分，出处保真）

**权威声明**：本文件是客户端-服务端 API 契约的权威定义（由服务端维护）；客户端仓库只维护消费约束；契约变更必须先改这里。

生产 Base URL：`https://www.zjcypc.com`（客户端 `serverApi.ts`）；本地开发 `http://localhost:4001`。鉴权：`Authorization: Bearer <JWT>`（用户）；管理端独立 JWT（admin_users）。

> 详细字段级文档见 `GPT_Image_2_service/docs/client_api.md`（671 行）。**注意该文档部分口径已过时**（如"双 API Key 体系 image_api_token/chat_api_token"是旧版；V4 实际为 runtime config 三组临时 token），冲突时以源码为准。

## 客户端 API（按前缀）

| 前缀/端点 | 说明 |
|---|---|
| `/api/auth/*` | 注册/登录/验证码/找回密码（登录限流：nginx 10r/m + Redis 双防线） |
| `/api/users/me` | 用户信息/余额 |
| `/api/users/me/runtime-config` | **核心**：下发 image/agent/postprocess 三组 `{token, base_url, expires_in, model}`；优先用户绑定 Token，未绑定回落 Master Token |
| `/api/users/me/runtime-token(/replace)` | 查询/更换绑定的 runtime token；409 `NO_AVAILABLE_RUNTIME_TOKEN` 时旧绑定不变 |
| `/api/models` | 模型目录 + 价格字段 |
| `/api/usage` | 用量上报/结算（request_id 幂等；authorize 可携 quote_id 按报价冻结价；402 = 点数不足，统一文案「点数不足，请充值后继续使用」） |
| `/api/billing/quote`（V4.2） | 生成前报价：quote_id + unit_credits + estimated_credits + balance_snapshot（Redis 600s 冻结）；所有付费生成入口提交前必调 |
| `/api/billing/wallet` / `/api/billing/ledger`（V4.2） | 三类点数余额 / 点数流水（充值/消费/释放/退款/试用/赠送，中文标签服务端下发） |
| `/api/trial/status` / `/api/trial/claim`（V4.2） | 试用可用性（trial_available）/ 一次性领取（同邮箱 claim ledger；重复 409 TRIAL_ALREADY_CLAIMED） |
| `/api/tokens/trial-stock`（V4.2.1） | 公开试用策略：available/reason/grant_credits/valid_days/campaign_version；remaining=0/1 仅供旧客户端兼容 |
| `/api/pay/create_order_cny`（V4.2 标准） | 人民币直购：¥N → N×credits_per_cny 点（订单快照 credits_granted）；`/api/pay/create_order`(USD) 兼容窗口保留（$N → N×700 点） |
| `/api/notice` + SSE | 公告查询 + text/event-stream 实时流 |
| `/api/client/heartbeat` | 心跳；服务端从 X-Forwarded-For 记录 IP |
| `GET /api/skills/catalog` / `GET /api/skills/{id}/versions/{version}` | 官方与审核通过的社区 Skill 公共目录；ETag 缓存、已发布版本不可变 |
| `POST /api/skills/submissions` | 用户提交 AI 通用化后的不可变 Skill 快照；服务端二次检查路径、服务器地址和凭据。`source_facts` 为结构化数组（`key/label/value/immutable`，旧 dict 合同 422），`value` 同样过净化扫描 |
| `POST /api/skills/submissions/{id}/samples` | 上传用户主动授权的成功生成样例；仅 PNG/JPEG/WebP，默认 ≤10MB（413 `SKILL_SAMPLE_TOO_LARGE`）；原子写入（`.uploading` 临时文件 + fsync + `os.replace`），失败不残留半成品 |
| `GET /api/skills/mine` / `GET /api/skills/submissions/{id}` | 当前用户的投稿和审核意见 |
| `POST /api/skills/submissions/{id}/withdraw` / `revisions` | 撤回未审核投稿，或对需修改/拒绝/撤回投稿创建递增修订 |

**零样例投稿恢复**（2026-08-28）：投稿创建成功但样例上传失败（sample_count=0 且状态 submitted/changes_requested）时，同一 `(user, local_skill_id, revision)` 以相同内容重发 → 返回已有投稿（200，追加 resumed 事件）；内容不一致 → 结构化 409 `SKILL_SUBMISSION_DUPLICATE`。用户/管理端全部错误统一 `detail={code, message中文}`；管理端 Skills.vue `errorText` 兼容旧字符串 detail。

## 管理 API（/api/admin/*）

用户管理（点数调整 paid/trial/gift、runtime-token 分配、Token 脱敏展示）、Token 池（录入返回 `{total, added, duplicate, invalid, details}` 统计；默认徽章区分 正式默认/试用默认）、订单/退款审核（点数冲正按 credits_granted 比例）、账务流水、**定价规则（pricing/rules + preview；Price Guard：低于目标毛利 403，super_admin force+reason 留痕）**、**成本与毛利（margin/ledger：时间/分类/RequestID 筛选 + 汇总）**、**业务配置（system-config K-V）**、**客户端设备（devices：历史保留 + 服务器计算 seconds_since_seen 恒 ≥0 + 在线/离线筛选）**、**旧余额迁移（billing/credits-migration：preview/apply，super_admin）**、公告、管理员账户与登录记录、Settings（业务配置 + 服务端环境配置 / 触发容器重启；v1.0.0 起 `.env` 写入 `PUT /config` 与容器重启 `POST /config/restart` 均仅 super_admin，读取保持全部管理员且敏感值脱敏）。

### 客户账户治理（v1.0.0：归档 / 恢复 / 彻底删除 / 密码重置）

| 端点 | 说明 |
|---|---|
| `GET /api/admin/users/{id}/deletion-preview` | 返回 `mode=purge|archive`、`has_business_history` 及 orders/refunds/billing/usage/margin 关联计数，并写预检审计 |
| `DELETE /api/admin/users/{id}` | （旧入口，v1.0.0 起由 hard-delete 取代）仅干净账户物理删除；有关联记录返回 `409`，`detail.code=USER_PURGE_BLOCKED`、`suggested_action=archive` |
| `POST /api/admin/users/{id}/archive` | 禁用登录、设置 archived_at/by、释放有效 Runtime Token、`token_version+1` 撤销全部存量会话，保留业务和审计记录 |
| `POST /api/admin/users/{id}/restore` | 恢复归档账户（`reason` 必填写审计）；**不复活旧会话**（归档时 tv 已 +1），原密码重新登录可用；purged 账户 409 `USER_PURGED` 不可恢复 |
| `POST /api/admin/users/{id}/reset-password` | 管理员重置客户密码：`admin_password`（操作者登录密码二次确认，错则 401）+ 可选 `new_password`（≥8 位，省略则服务端生成 12 位无易混字符临时密码）+ `reason`；成功后 `token_version+1` 撤销目标全部会话；临时密码仅本次响应返回一次；审计不含任何密码材料；归档/purged 账户 409 |
| `POST /api/admin/users/{id}/hard-delete` | **仅 super_admin**。`admin_password` + `confirm_identity`（须与目标用户名/邮箱完全一致，否则 400 `CONFIRM_MISMATCH`）+ `reason`。进行中业务（RESERVED 预占/进行中退款/PENDING、PAID 订单）409 `USER_HARD_DELETE_BLOCKED` 硬阻断、无 force 绕过；非零余额按「核销」清零并写 ADMIN_ADJUSTMENT 流水（不构成收入、不自动退款）；有业务历史或处置过余额 → 脱敏账务主体（`purged-{uuid12}` / `@purged.invalid` / 哈希重写 / is_active=False，FK 保留可追溯）；干净账户 → 物理删除。两者邮箱/用户名立即释放可重注册；幂等（重复调用返回 `already_purged=true` 无副作用） |
| `GET /api/admin/admin-login-logs` | 超级管理员专用；支持 result、username、start_date、end_date、page、page_size |

`GET /api/admin/users` 支持 `archive_scope=current|archived|purged|all`（v1.0.0 新增 `purged`：脱敏账务主体只读追溯）；管理后台以「当前客户 / 归档记录 / 已删除账户」三标签分别读取。`GET /api/admin/stats` 的 `users_total` 只统计 `archived_at IS NULL AND purged_at IS NULL`。

**邮箱重注册与试用一次性**：hard-delete 后原邮箱立即可注册新账户（新 ID、零资产、零历史）；`trial_claims` 以 email 为准独立保留，同邮箱重注册不能重复领取试用。

**迟到/重复支付回调防护**：purged 账户的 PAID 订单补入账被服务层拒绝（`assign_paid_order` 抛 `PurgedAccountError`，点数不变、订单不推进）——覆盖 hard-delete 预检通过后回调并发的窗口终态。

### 版本接口（v1.0.0）

| 端点 | 说明 |
|---|---|
| `GET /api/health` | 含 `version` 字段（构建注入 APP_VERSION，未注入如实回退包内声明） |
| `GET /api/admin/version` | 管理员登录：`version` / `environment` / `version_status`（`released`｜`pending_release`）/ `build_commit` / `build_time`（未注入为 null，不伪造）/ `version_log[]`（version/date/status/features/fixes/notes 纯文本数组，无富文本） |

业务配置新增 `trial_valid_days`（默认 2），与 `trial_feature_enabled`、`trial_grant_credits`、`trial_campaign_version` 共同构成唯一试用策略。注册试用和账户内领取均以这些配置为准。

### 社区 Skill 审核（v4.2.3）

`GET /api/admin/skill-submissions`、详情接口和受保护样例读取供普通管理员审阅。`start-review` 要求至少一张授权样例；`request-changes` 与 `reject` 必须填写审核意见。`approve` 仅超级管理员可调用，在同一事务内创建 `source=community` 的已发布 `SkillPackage`、确定公共封面并写管理员审计。

`GET /api/admin/stats` 新增 `total_recharged_credits`（只汇总成功 RECHARGE 的 `amount_credits`）。兼容字段 `total_revenue_usd` 和 `token_stats` 继续返回，但新版概览不消费。

## 客户端统一错误语义（serverApi.ts）

> 本节属客户端消费行为，已迁至客户端仓库 `GPT_Image_2_Application/docs/current/api-consumption.md`。

## 上游 Provider API（客户端直连）

> 本节属客户端直连行为，已迁至客户端仓库 `GPT_Image_2_Application/docs/current/api-consumption.md`。
