---
type: backend
module: server
visibility: internal
---

# 服务端架构（GPT_Image_2_service/backend，FastAPI）

## 路由清单（main.py 注册，前缀即职责）

| 前缀 | 文件 | 职责 |
|---|---|---|
| `/api/auth` | auth.py | 注册/登录/验证码/找回密码（Redis 登录限流） |
| `/api/users` | users.py | 用户信息、余额、runtime-config/runtime-token |
| `/api/tokens` | tokens.py（薄） | 转发 |
| `/api/pay` | pay.py | 微信 Native 支付 create_order/notify/query/close/refund_* |
| `/api/notice` | notice.py | 公告 CRUD + **SSE 实时流**（text/event-stream） |
| `/api/models` | models.py / content.py | 模型目录与价格（V4 仅 seed `gpt-image-2`） |
| `/api/usage` | usage.py | 用量上报/结算（request_id 幂等） |
| `/api/admin` | admin.py | 大后台：用户/订单/流水/Token/公告/在线设备等 |
| `/api/admin` | admin_accounts.py | 管理员账户管理（V4.0.2 数据库化） |
| `/api/client` | client.py | 心跳 heartbeat（Redis online + client_devices 历史持久化） |
| `/api/billing` | billing.py（V4.2） | 报价 quote（10 分钟冻结）/ wallet / ledger 点数流水 |
| `/api/trial` | trial.py（V4.2） | 试用状态 / 一次性领取（trial_claims email 唯一） |

## services 层（业务核心）

- **billing.py**：两阶段扣费 RESERVED→SUCCESS/FAILED（settle 按实际成功数重算、CAS 幂等）；试用额度优先、现金兜底（`_split_charge`）；Decimal 全链路；`release_stale_reservations` 释放超时预占（供 reservation GC 调用）
- **runtime_token.py**：共享 Token 池下发核心；`assign_runtime_token` 事务（行锁旧+新 Token、skip_locked 抢目标、失败整体回滚）
- **refund.py**：退款状态机、微信退款调用、金额校验（人民币分为精确基准，见 [decisions/ADR-007](decisions/ADR-007-money-decimal-cents.md)）
- **order_assignment.py**：支付成功后自动绑定 runtime token；purged 账户拒绝入账（PurgedAccountError 纵深防御）

## core 模块

`config`（.env 读取）、`database`（SQLAlchemy 会话）、`security`（JWT/密码哈希/get_current_user）、`redis`（连接 + 启动时 `recover_processing_refunds`）、`email`（SMTP 验证码）、`wechatpay`（微信支付 SDK 封装）。

## 鉴权体系

1. **用户**：JWT Bearer（`core/security.py` 的 get_current_user）；payload 含 `tv`（token_version），密码重置/自助改密/归档/彻底删除均 `tv+1` 撤销全部存量会话；v1.0.0 之前签发的无 `tv` 旧 token 视为 0，未发生撤销事件前继续有效（兼容窗口有测试）
2. **管理员**：数据库 `admin_users` 表（V4.0.2 起与 users 严格隔离，must_change_password 强制改密；此前为 .env 静态账号）；两级角色 `admin` / `super_admin`，`get_super_admin_user` 守卫高危入口（hard-delete、.env 写入、容器重启、余额迁移、定价 force）
3. **防线**：nginx 对 `/api/auth/admin/login` 限流 10r/m + 应用层 Redis IP+用户名限流
4. **runtime token**：`/api/users/me/runtime-config` 下发，即"给客户端的上游 API Key"（内存态、带过期）

## 客户账户治理（v1.0.0）

三段生命周期：**current**（正常）→ **archived**（归档：禁用+撤会话+释放 Token，可恢复，恢复不复活旧会话）→ **purged**（彻底删除：不可恢复）。

- **hard-delete 双路径**：干净账户物理 DELETE（设备/绑定运行数据一并清理，trial_claims / token_assignment_logs 永久保留防重复试用）；有业务历史或处置过余额 → 脱敏账务主体（`purged-{uuid12}` / `@purged.invalid` / 密码哈希随机重写 / is_active=False / purged 三元组），订单/流水/用量 FK 不断可追溯
- **余额核销**：非零桶逐条写 `ADMIN_ADJUSTMENT` 流水（remark 注明原因）后清零；不构成收入、不自动微信退款
- **进行中业务硬阻断**：RESERVED 预占 / 进行中退款 / PENDING、PAID 订单 → 409，无 force 参数
- **PurgedAccountError**（order_assignment.py）：服务层纵深防御，purged 账户的订单拒绝入账（防 hard-delete 预检后回调并发置 PAID 的窗口终态）
- **管理员重置密码**：操作者登录密码二次确认 + 临时密码一次性返回（10–14 位、去 0O1lI）+ 审计脱敏（不记新旧密码/哈希/令牌）
- v1.0.0 安全收紧：`PUT /api/admin/config`（.env 写入）与 `POST /api/admin/config/restart`（容器重启）从普通管理员收紧为 super_admin——封堵「改 SECRET_KEY → 自签 super_admin JWT」提权链（详见 [current/security-assessment.md](current/security-assessment.md) S-1/S-2 与 ADR-020）

## 启动流程（lifespan）

启动时依次（lifespan，main.py）：init_redis → `create_all` → `_ensure_columns` / `_ensure_indexes`（如 `uq_token_value`、`trade_no`，有历史重复数据时跳过）→ 三个一次性迁移（`schema_migrations` 表记账：v4_single_model〔含旧 `user_tokens` 分组余额搬入统一余额〕/ v4_shared_token_refund / v402_admin_accounts）→ seed（ai_models 等）→ 启动即清理一次超时预占并拉起 reservation GC 周期循环 → `recover_processing_refunds` 恢复卡死退款。

**无 apscheduler/celery/cron 调度框架**；唯一周期任务为内建 reservation GC（asyncio 循环，每 10 分钟释放超时 RESERVED 预占，见 [decisions/ADR-005](decisions/ADR-005-no-scheduler-framework.md)）；在线状态靠 Redis TTL，公告靠 SSE 推送。

## 状态机

- 订单：已支付订单含 ASSIGNED 状态（自动绑 token），退款有状态校验与冲正
- 退款申请：`refund_requests` 部分唯一索引保证一单至多一个未终态申请；`out_refund_no` 幂等
- 计费事务：RESERVED → SUCCESS / FAILED（两阶段）；超时未结算由 reservation GC 释放为 RELEASED（全额退回）

## 测试

`backend/tests/`：conftest（测试库 `cyimage_v4_test` 会话重建，**防重入守卫** `CY_TEST_DB_READY` env）+ test_admin_auth、test_admin_tokens_users、test_billing_core、test_heartbeat、test_http_billing、test_migration、test_payment_amount、test_payment_credit、test_refund_flow、test_runtime_token。
