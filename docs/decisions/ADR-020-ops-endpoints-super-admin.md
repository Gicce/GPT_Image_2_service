---
type: decision
module: server
visibility: internal
---

# ADR-020：运维入口权限收紧——.env 写入与容器重启仅 super_admin

日期：2026-09-06
状态：已实施（v1.0.0，develop，pending_release）
关联：ADR-019（账户治理同版）、`current/security-assessment.md` S-1/S-2、V4.0.2 管理员数据库化（admin_users 两级角色）

## 背景

v1.0.0 安全评估发现一条完整提权链：`PUT /api/admin/config` 允许**任意普通管理员**（role=admin）写服务端 `.env`，其中包含 `SECRET_KEY`（JWT 签名密钥）。攻击者（或越权的低权限管理员）只需：

1. 以普通管理员身份把 `SECRET_KEY` 改为已知值（如 `attacker-known`）；
2. 用该密钥自签 payload `role=super_admin` 的管理员 JWT；
3. 通过 `get_super_admin_user` 校验，获得全部超管能力（重置他人密码、余额迁移、定价 force 保存、再写 .env 持久化）。

同文件路由 `POST /api/admin/config/restart` 经 docker.sock 重启 backend 容器，此前同样对普通管理员开放——容器级运维能力下放给最低权限角色。

该链路的本质：**写密钥配置的权限 = 签发任意角色 token 的权限**，不能留在「普通管理员」层级。

## 决策

1. `PUT /api/admin/config`（.env 写入）依赖从 `get_admin_user` 收紧为 `get_super_admin_user`；
2. `POST /api/admin/config/restart`（容器重启）同样收紧；
3. 读取 `GET /api/admin/config` 保持全部管理员可用（SECRET_KEY/支付密钥/SMTP 密码等敏感值早已以 `********` 脱敏返回，不因读取权限泄漏）；
4. 前端 Settings.vue 按 `/api/admin/admins/me` 角色隐藏写入/重启按钮并显示只读提示（体验层，后端为权威）；
5. 回归测试固化：普通 admin 403 / 未登录 401 / 超管正向写入（ENV_FILE_PATH 隔离到 tmp 文件）/ 攻击者自造密钥签发的 super_admin token 401（test_config_write_and_restart_require_super_admin）。

## 不做的事

- 不移除 docker.sock 挂载与 restart 功能：运维入口有真实价值，权限收紧已消除越权面；socket proxy 等部署硬化另行专项（security-assessment.md 第四节）；
- 不为「普通管理员改非敏感配置」开细分白名单：当前后台无此需求，避免增加一个仍需审计的半开放面；未来需要时再按 key 分类。

## 后果

- 破坏性变更：已存在的普通管理员登录态将无法保存 .env/重启（前端显示只读视图）；超管不受影响。变更随 v1.0.0 发布说明明示。
- 管理端高危入口自此统一为 super_admin 守卫集合：hard-delete、.env 写入、容器重启、余额迁移 apply、定价 force 保存、管理员账户管理。
