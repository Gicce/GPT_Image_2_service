---
type: database
module: server
visibility: internal
---

# 数据库设计（PostgreSQL 16 + Redis 7）

无 alembic；迁移为 main.py 内置一次性迁移（`schema_migrations` 表记账、幂等可重入）：v4_single_model（含旧 `user_tokens` 分组余额搬移）、v4_shared_token_refund、v402_admin_accounts。列/索引按需补建（`_ensure_columns` / `_ensure_indexes`，有历史重复数据时跳过创建并告警）。

## 表清单（backend/app/models.py）

### users
用户主表：id/username/email/password_hash/account_type/**balance_usd**/**trial_credit_usd**（Numeric(18,6)；V4.2 起降级为**兼容镜像**——业务真相为三类点数列，见下，每次点数变动后按 legacy_usd_to_credits=700 回写，供 V4.0.x 旧客户端展示）/ **paid_credits**/**trial_credits**/**gift_credits**（INTEGER，V4.2 CY Credits 业务真相，消费顺序 trial→gift→paid 唯一入口 billing.consume_credits）/**archived_at**/**archived_by**（业务历史账户归档标记）；旧 `user_tokens` 表已废弃。

客户移除规则：无订单、退款、账务、用量、成本经营记录的账户才可物理删除；事务内清理 `client_devices` 与 `runtime_token_assignments`。存在任一业务历史时只允许归档（`is_active=false` 并释放有效 Token）。`trial_claims` 和 `token_assignment_logs` 始终保留，防止删号后重复试用并维持分配审计链。

### billing_transactions —— 账务审计单一真相源
统一账务流水（**资金变动的唯一审计/对账依据**；当前余额状态另存于 users 行，见上）。关键字段：
- `type`：IMAGE2_CHARGE / IMAGE2_REFUND / RECHARGE / RECHARGE_REFUND / ADMIN_ADJUSTMENT / MIGRATION
- `status`（RESERVED/SUCCESS/FAILED/RELEASED）、`request_id`（唯一约束 `uq_billing_request_id`，幂等基石）
- 前后余额快照（balance_before/after、trial_before/after，每条流水可独立对账）
- `trial_amount`/`balance_amount`/`billing_source`（来源拆分）

### token_inventory —— 上游 API Key 库存
token_value（唯一索引 `uq_token_value`）、name/is_default/quota_usd/expires_at/is_assigned/is_disabled/assigned_to。
**token_value 明文只在服务端**；token_value 从不直接参与上游调用——上游凭证通过 runtime-config 下发。

### runtime_token_assignments / token_assignment_logs
Token↔User 多对多分配关系 + 操作日志（token_id/user_id/action/source）。分配走 `assign_runtime_token` 事务：行锁旧+新 Token、skip_locked 抢目标、失败整体回滚。

### orders —— 充值订单
金额快照：amount_usd（V4.2 起为镜像）/ amount_cny / **credits_granted**（本单到账点数快照，退款按此比例冲正）/ exchange_rate / refunded_*；微信支付单号（trade_no 唯一）；含 ASSIGNED 状态（支付成功自动绑 token）。

### refund_requests —— 退款申请
状态机；**一单至多一个未终态申请**（部分唯一索引）；人民币"分"为精确基准；`out_refund_no` 幂等。

### usage_logs —— Image2 用量
unit_price/cost_usd（V4.2 起为镜像 = 点数/700，Token 配额聚合依赖）/ unit_credits/cost_credits（点数真相）快照、request_id 幂等（部分唯一索引 `uq_usage_logs_request_id`，WHERE request_id IS NOT NULL）。售价以 pricing_rules 为准（ai_models.price_per_call 仅回退与展示）。

### pricing_rules（V4.2 定价引擎）
每 (feature, model) 至多一条 enabled（部分唯一索引 `uq_pricing_rule_active`）。字段：unit_credits（售价）+ 成本侧 nominal_unit_cost_rmb / target_margin / safety_buffer / rounding_step + override 留痕（低于目标毛利强制保存）。编辑原地升版本；历史任务经流水快照锁定原价。种子：image/gpt-image-2 = 80 点，成本 ¥0.20，目标 70%，安全垫 10%。

### cost_margin_ledger（V4.2 经营账）
settle 成功时冻结快照：reserved/charged/released_credits、category（paid/trial/gift/mixed）、revenue_rmb（只计 paid 部分）、promotional_value_rmb（trial+gift 获客口径）、actual/effective_cost_rmb、gross_profit/margin、token_inventory_id 归因、成功/失败张数。对账键：billing_transaction_id。

### trial_claims（V4.2 试用领取）
normalized_email（trim+lowercase）唯一约束 `uq_trial_claim_email`——同邮箱一生一次，删号重注册不可再领；user_id_at_claim/grant_credits/campaign_version/status。

### client_devices（V4.2 设备历史）
user_id+device_id 唯一（upsert）；first/last_seen_at（服务器时钟）、platform/client_version/last_ip/last_user_agent/heartbeat_count；永久保留，离线不删；online 判定 = Redis TTL key，不落库。

### system_config（V4.2 业务配置 K-V）
credits_per_cny（100）/ legacy_usd_to_credits（700）/ trial_feature_enabled / trial_grant_credits（500）/ trial_campaign_version / target_margin（0.70）/ cost_safety_buffer（0.10）/ recharge_min_cny / recharge_max_cny。管理后台可改（值校验 + 审计）。

### admin_users / admin_audit_logs
V4.0.2 数据库化管理员（与 users 严格隔离、must_change_password、登录限流）+ 审计日志。

### notices / ai_models
公告（SSE 推送源）/ 模型价格目录（V4 仅 seed `gpt-image-2`，$0.046/call）。

### skill_packages / skill_submissions（V4.2.3）

`skill_packages` 是公共目录的不可变版本，新增 `source`（official/community）、作者展示名、公共预览样例和来源投稿字段。`skill_submissions` 保存用户投稿时的 Skill 快照、来源事实（`source_facts` 为 JSON **结构化数组** `[{key,label,value,immutable}]`，与客户端 SkillSourceFact 一致）、AI 整理元数据、状态和审核意见；`(user_id, local_skill_id, revision)` 唯一，防止同一项目修订重复投稿。四张表由正式迁移 `_migrate_skill_submissions`（版本号 `v423_skill_submissions`，记入 schema_migrations）在启动时创建，不依赖测试建表；样例文件存 `SKILL_SAMPLE_DIR=/app/data/skill_samples`（compose 命名卷 `skill_samples` 持久化，容器重建不丢）。

`skill_submission_samples` 只记录用户主动授权的生成样例、SHA-256、生成参数和公共封面选择；文件存储在受控目录，审核前仅作者与管理员可见。`skill_submission_events` 追加提交、样例、审核、退修、拒绝和批准事件，不覆盖历史。

客户端另有 SQLite `user_skills`，只存 `UserSkillDraft` JSON 和列表索引字段，与具体生成用的 `skill_projects` 严格分离。

## 关系与约束要点

```
users 1─N billing_transactions（前后余额快照对账）
users N─N token_inventory（经 runtime_token_assignments + logs）
orders 1─N refund_requests（部分唯一索引）
orders 1─N billing_transactions（RECHARGE / RECHARGE_REFUND 冲正）
users 1─N usage_logs（request_id 幂等）
admin_users 1─N admin_audit_logs
users 1─N skill_submissions 1─N skill_submission_samples/events
```

幂等三支柱：`billing_transactions.request_id`、`usage_logs.request_id`、`refund_requests.out_refund_no` 均唯一约束。

## Redis 用途

- `online_device:{user_id}:{device_id}`：心跳在线状态，TTL 180s
- 登录限流（IP + 用户名）、tool 上报幂等
- 启动时 `recover_processing_refunds`

## 本地测试库

PostgreSQL 17（127.0.0.1:5432 postgres/postgres），测试库 `cyimage_v4_test` 会话重建；**conftest 防重入守卫**（`CY_TEST_DB_READY`）：pytest 以 `conftest` 与 `tests.conftest` 双路径二次 import 时无守卫会整库 drop（已踩坑）。
