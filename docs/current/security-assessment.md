# v1.0.0 安全评估报告（2026-09-06）

> 本报告覆盖 v1.0.0 专项（客户账户完善 / 版本日志 / 安全与代码评估）执行的前后端安全评估与代码评估。
> 评估环境：worktree `GPT_Image_2_service_v1`（develop@8bd6495 基线 + v1.0.0 变更）；
> 全部验证在隔离测试环境（cyimage_v4_test 库 + Redis db15）完成，未触达生产。

## 一、评估范围与方法

| 项 | 方法 | 工具与执行结果 |
|---|---|---|
| 后端依赖 | 声明依赖审计 + 环境级审计 | pip-audit 2.10.1（`-r requirements.txt --no-deps` + 环境全量），均成功执行 |
| 前端依赖 | 依赖树审计 | npm audit（npm 11.x），成功执行 |
| 权限与认证 | 逐路由人工源码审查 + 攻击路径推演 + 隔离环境攻击模拟 | admin.py / admin_accounts.py / security.py / auth.py 全文 |
| 注入与 XSS | 模板扫描（v-html / innerHTML）+ 参数化查询核查 | Vue SFC 全量 + SQLAlchemy 参数绑定核查 |
| 支付链路 | 回调验签链 + 入账路径审查 | payment.py / order_assignment.py 全文 |
| 上传链路 | 类型/大小/路径/写盘核查 | skill_submissions.py 全文 |
| 会话与密码 | token 生命周期 + 哈希存储 + 审计内容核查 | security.py / auth.py / admin.py |

工具失败如实记录：pip-audit `-r` 在 Windows GBK locale 下读取含中文注释的 requirements.txt 报 UnicodeDecodeError 一次（已将注释改为 ASCII 后成功执行）；除此之外无工具失败，本报告不依赖任何未执行的扫描结果。

## 二、已修复（本轮确认并修复）

### S-1〔高〕SECRET_KEY 篡改 → 伪造 super_admin JWT 提权链

- **位置**：`backend/app/api/routes/admin.py` `PUT /api/admin/config`（修复前 `Depends(get_admin_user)`）
- **触发条件**：任意普通管理员（role=admin）登录态调用 `PUT /api/admin/config`，把 `SECRET_KEY` 改为攻击者已知值；随后用该密钥自签 `role=super_admin` 的 JWT，通过 `get_super_admin_user` 校验，获得全部超管能力（含他人密码重置、余额迁移、再写 .env 持久化）。
- **影响**：角色隔离完全失效；等价于单普通管理员账户泄露 → 全系统接管。
- **验证证据**：隔离环境实测——修复前权限模型下普通管理员可提交该请求；用自造密钥 `"attacker-known-secret"` 签发的 super_admin token 在修复后调 restart 返回 401（验签失败）。
- **修复方式**：`PUT /config` 收紧为 `Depends(get_super_admin_user)`（admin.py:1963-1970，docstring 说明安全边界）；读取 `GET /config` 保持全部管理员（敏感值已脱敏 `********`）。
- **回归测试**：`tests/test_v100_account_governance.py::test_config_write_and_restart_require_super_admin`（未登录 401 / 普通 admin 403 / 超管正向写入 tmp 文件 / 伪造 token 401）。

### S-2〔高〕后端容器重启入口对普通管理员开放（docker.sock 面）

- **位置**：`backend/app/api/routes/admin.py` `POST /api/admin/config/restart`
- **触发条件**：普通管理员登录态直接调用即可经 docker.sock 重启 backend 容器（造成计划内/计划外服务中断；结合 S-1 曾构成容器级攻击面）。
- **影响**：拒绝服务能力下放给最低权限管理员角色；容器级运维操作越权。
- **修复方式**：同 S-1 收紧为 `get_super_admin_user`；前端 Settings.vue 对非超管隐藏重启按钮并显示只读提示（`frontend/src/views/Settings.vue`）。
- **回归测试**：同 S-1 测试（普通 admin restart 403 / 未登录 401）。

### S-3〔高〕运行时依赖 CVE 集群（6 个声明依赖共 20+ 条 PYSEC advisory）

- **位置**：`backend/requirements.txt`
- **修复前版本 → 修复后版本**（均在本轮验证）：

| 依赖 | 修复前 | 修复后 | 涉及 advisory（节选） |
|---|---|---|---|
| fastapi | 0.115.0 | 0.141.1 | PYSEC-2026 系列 |
| starlette | （传递） | 1.6.0（显式 pin） | PYSEC-2026 系列 |
| aiohttp | 3.10.8 | 3.14.3 | PYSEC-2026 系列 |
| cryptography | 43.0.1 | 50.0.0 | PYSEC-2026-3552 等 |
| python-jose[cryptography] | 3.3.0 | 3.5.0 | PYSEC-2026 系列（3.5.0 同时使 pyasn1 解析到已修复的 0.6.4） |
| aiosmtplib | 3.0.2 | 5.1.2 | PYSEC-2026 系列 |
| python-multipart | 0.0.12 | 0.0.31 | PYSEC-2026-3039/3040 |

- **验证证据**：升级后 `pip check` 无冲突；`pip-audit -r requirements.txt --no-deps` 与环境级 `pip-audit` 均仅剩 ecdsa（见第四节）；`python -c "from app.main import app"` 导入冒烟通过。
- **回归测试**：全量 `python -m pytest tests/` **178 passed**（升级前后各跑一轮，零回归；警告 271 → 3）。
- 附带清理：本地环境残留的 matplotlib+pillow（非 requirements 声明、业务代码零引用、不进生产镜像）已卸载，避免审计噪声；环境工具 pip 25.0.1 → 26.2.1。

### S-4〔中〕迟到/重复支付回调对已删除账户入账（并发窗口纵深防御）

- **位置**：`backend/app/services/order_assignment.py` `assign_paid_order` → `PurgedAccountError`
- **触发条件**：hard-delete 预检通过后、事务提交前，支付回调并发把订单置 PAID（正常时序下 PENDING/PAID 订单会被 `incomplete_orders` 阻断）；或未来新增的 assign 调用点未检查账户状态。
- **影响**：已删除（脱敏）账户凭空入账点数，账实不符。
- **修复方式**：服务层统一防护——assign 前检查用户 `purged_at`/`is_active`，purged 账户拒绝入账并抛 `PurgedAccountError`。
- **回归测试**：`test_late_payment_callback_refuses_credit_for_purged_account`（构造并发窗口终态：purged + PAID 未入账订单 → assign 抛错、点数不变、订单状态不被推进）。

### S-5〔中〕前端依赖高危集群（axios 等 8 条 high）

- **位置**：`frontend/package-lock.json`
- **修复方式**：`npm audit fix`（semver 范围内，非 `--force`），6 → 2 条残留（残留项见第四节）。
- **回归测试**：`npm run build` 成功（7.79s）。

## 三、评估确认良好项（未发现问题，列出依据）

1. **登录暴力破解防护**：管理员登录失败限流 user 10 次/900s + IP 30 次/900s（`admin_accounts.py`），客户登录同口径（`auth.py`），命中后锁定并写审计。
2. **JWT 会话校验**：`get_admin_user`/`get_super_admin_user` 每请求校验 role + admin_id + is_active + token_version；伪造/过期/降级 token 均 401（专项测试覆盖）。
3. **会话撤销完备性**：v1.0.0 新增 `users.token_version` 后，密码重置/自助改密/归档/彻底删除四条路径全部 `token_version += 1`；旧 token（无 tv 字段视为 0）在撤销事件后立即失效，兼容窗口有测试。
4. **密码治理**：bcrypt 存储无明文/可逆副本；任何接口不返回哈希；管理端详情仅显示「已设置 + 最近修改时间」；审计记录不含新旧密码/哈希/重置令牌（专项断言覆盖）；临时密码仅一次性返回，前端仅存内存 ref 且对话框 after-leave 清空。
5. **上传安全**：skill 样例上传白名单 MIME + 大小上限 + uuid 文件名 + resolve 路径逃逸检查 + 临时文件原子 rename（`skill_submissions.py`）。
6. **支付回调**：微信 v3 验签链完整（证书/时间戳/nonce），金额以订单为准不以回调为准；退款走统一 RefundService 状态机。
7. **XSS**：管理后台全量扫描无 `v-html`/`innerHTML`；版本日志等新页面纯文本插值（Vue 默认转义），测试断言日志内容不含 `<script`。
8. **SQL 注入**：全程 SQLAlchemy 参数绑定/表达式构造，抽查无字符串拼接 SQL。
9. **彻底删除防护**：进行中业务（RESERVED 预占/进行中退款/未完成订单）硬阻断且无 force 参数；非零余额核销写 ADMIN_ADJUSTMENT 流水不构成收入；有业务历史者保留脱敏账务主体（FK 不断）；trial_claims 独立保留防重复试用。

## 四、缓期与不修项（含理由）

| 项 | 严重度 | 理由 | 后续 |
|---|---|---|---|
| ecdsa PYSEC-2026-1325 | 低 | 0.19.2 已是最新版本，无上游修复；python-jose 传递依赖；本项目 JWT 全部使用 HS256，ECDSA 签名验证不在任何请求路径上，攻击面不成立 | 跟踪上游发布 |
| vite <=6.4.2（high）+ esbuild <=0.24.2（moderate） | 低（对本项目） | 两条均仅影响 `vite dev` 开发服务器（dev server path traversal / server.fs.deny 绕过 / launch-editor NTLM 泄露）；生产管理后台只发布 `dist/` 静态产物，不经 vite 服务器。修复需 vite 4→8 大版本升级，破坏性变更超出本轮范围 | 单独排期 vite 8 升级 |
| docker.sock 挂载进 backend 容器 | 中（部署面） | restart 运维功能依赖；入口已收紧 super_admin（S-2）；替代方案（socket proxy / 独立运维容器）属部署架构改造，本轮不动生产部署配置 | 部署硬化专项 |
| CORS 默认 `*` | 低 | 认证全部走 Authorization Bearer、无 Cookie，浏览器不会携带凭据，`*` 无法被利用读取需认证响应；生产已支持 `CORS_ORIGINS` 白名单配置 | 建议生产 .env 配置白名单（人工部署时） |
| 无自定义安全响应头（CSP/X-Frame-Options 等） | 低 | 管理后台为纯文本插值 SPA（无 v-html），点击劫持/注入风险低；响应头由 nginx 层下发更合适 | 部署硬化专项 |

## 五、结论

本轮确认并修复高危 3 类（S-1 提权链、S-2 容器重启越权、S-3/S-5 依赖 CVE 集群）+ 中危 2 类（S-4 迟到回调防护、S-5 前端高危依赖）；全部修复均有隔离环境回归测试（专项 13 测 + 全量 178 passed + 前端构建）。缓期项 5 条均给出攻击面分析与后续路径，无一静默放过。

评估工具全部成功执行（pip-audit / npm audit），本报告不存在「工具未跑完即记无漏洞」的情况。
