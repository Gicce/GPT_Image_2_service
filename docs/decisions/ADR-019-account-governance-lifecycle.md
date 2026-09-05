---
type: decision
module: server
visibility: internal
---

# ADR-019：客户账户治理——三段生命周期 + 会话撤销 + 管理员重置密码

日期：2026-09-06
状态：已实施（v1.0.0，develop，pending_release）
关联：ADR-018（CY Credits）、ADR-007（金额精度）、`current/security-assessment.md`、`current/api.md` 账户治理节

## 背景

v1.0.0 之前客户账户只有 is_active 开关与「干净账户物理删除 / 有历史只能归档」的二元口径，存在五个治理缺口：

1. 无恢复机制：归档即终点，误归档无法回退；
2. 「彻底删除」对有余额/有历史的账户没有合法出口——要么拒绝要么破坏账务 FK；
3. 无密码运维入口：客户忘记密码只能走自助邮件找回，管理员无法在电话核实时协助重置；
4. 会话不可撤销：改密/归档后旧 Bearer token 仍有效至自然过期；
5. 删除账户后邮箱是否可重注册、试用是否可重复领取，口径未定义。

## 决策

### 1. 三段生命周期：current → archived → purged

- **archived**（`archived_at/by`）：禁用 + 撤会话 + 释放 Runtime Token；业务与审计全保留；**可恢复**（restore），恢复不复活旧会话、不自动重绑 Token（按现行规则重新分配）。
- **purged**（`purged_at/by/reason` 三元组）：不可恢复的终态。入口 `POST /api/admin/users/{id}/hard-delete`，仅 super_admin。

### 2. 彻底删除双路径（关键取舍：账务 FK 不因删除断裂）

- **干净账户**（无订单/退款/流水/用量/经营记录且未处置余额）→ 物理 DELETE，事务内清理 client_devices 与 runtime_token_assignments；
- **有业务历史或处置过余额** → **脱敏账务主体**：username=`purged-{uuid12}`、email=`purged-{uuid12}@purged.invalid`、password_hash 随机重写（不可登录）、is_active=false。订单/流水/用量的 FK 指向保留，账务可永久追溯。

不采用「级联物理删除全部业务记录」：流水是收入/退款/经营账的法律与对账依据（ADR-018 单一真相源），删除账户不应连带删除账；也不采用「仅软删标记」：邮箱/用户名必须真实释放，否则客户以原邮箱重注册被占位符阻断。

### 3. 余额核销而非退款

非零余额（paid/trial/gift 三桶）逐桶写 `ADMIN_ADJUSTMENT` 流水（remark 注明账户与原因）后清零。核销流水本身即业务历史，因此**处置过余额的账户一律走脱敏路径**（即使原本无其他历史）。不自动发起微信退款：退款有独立审核链路（RefundRequest 状态机），删除流程不越权代客退款。

### 4. 进行中业务硬阻断，无 force 参数

RESERVED 预占 / 进行中退款 / PENDING、PAID 订单任一存在 → 409 `USER_HARD_DELETE_BLOCKED`（返回各类计数）。不提供强制绕过——一致性优先于操作便利。

### 5. 会话撤销：users.token_version + JWT tv

JWT payload 增加 `tv`；get_current_user / get_optional_user 每请求与库中 token_version 比对。**撤销事件**（管理员重置密码 / 自助改密 / 找回密码 / 归档 / 彻底删除）统一 `tv+1`。兼容窗口：v1.0.0 之前签发的无 tv token 视为 0，未发生撤销事件前继续有效（存量客户端不被登出）。恢复（restore）**不**递增 tv——归档时已 +1，旧 token 已死，无需二次撤销。

### 6. 管理员重置密码的安全合同

- 操作者登录密码二次确认（被盗管理员 token 不能单独完成重置）；
- 新密码可选：省略则服务端生成 12 位随机临时密码（去除 0/O/1/l/I 易混字符），**仅本次响应返回一次**，不落日志/审计/任何持久化状态；
- 审计只记 user_id/username/reason/generated 布尔，**不含新旧密码、哈希或可还原材料**；
- 详情接口对密码只暴露「已设置 + password_changed_at」（存量行 NULL=未记录，不编造时间）。

### 7. 邮箱释放与试用一次性

purged 后邮箱/用户名立即释放，可注册全新账户（新 ID、零资产、零历史）。`trial_claims` 以 normalized_email 唯一约束独立于 users 存在（ADR-018 已建），物理删除用户行不影响领取记录——同邮箱重注册不能重复领取试用。

### 8. 迟到/并发回调纵深防御

hard-delete 预检与提交之间存在窗口：回调可能并发把订单置 PAID。服务层 `assign_paid_order` 对 purged/非 active 账户抛 `PurgedAccountError` 拒绝入账（点数不变、订单不推进）——防护不依赖路由层时序，未来新增 assign 调用点自动受保护。

## 后果

- users 表新增 6 列（password_changed_at / token_version / purged_at / purged_by / purge_reason + 既有 archived_at/by），经 `_ensure_columns` 幂等补列，无正式迁移；
- 管理后台 Users 三标签（当前/归档/已删除）；purged 只读；
- stats 与列表口径全部排除 purged（`users_total = archived_at IS NULL AND purged_at IS NULL`）；
- 旧 `DELETE /api/admin/users/{id}` 保留但被 hard-delete 取代（不删余额、无确认链）；
- 专项测试 13 项（test_v100_account_governance.py）：撤销/恢复/双路径删除/阻断/幂等/迟到回调/权限/审计脱敏/兼容窗口。
