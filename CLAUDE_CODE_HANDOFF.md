# Claude Code 接手文档

## 1. 项目定位

这是一个前后端分离的 SaaS 管理后台项目，核心目标不是简单代理某个 AI 接口，而是提供一整套：

- 用户注册、登录、试用、找回密码
- 分组式 API Token 库存管理与用户分配
- 按模型或按调用量扣费
- 微信支付充值、订单管理、退款处理
- 模型配置、提示词库、公告、后台配置管理
- 管理后台可视化运维

可以把它理解为：

1. 平台维护一批上游 API Token
2. 用户注册后，被分配某个 `group` 下的 token 与余额
3. 用户端调用外部 AI 服务
4. 用户端将用量回传本系统
5. 本系统据此扣减余额、记录订单、控制访问权限


## 2. 技术栈

### 后端

- Python 3.12
- FastAPI
- SQLAlchemy 2.0 Async
- PostgreSQL
- Redis
- Pydantic v2
- JWT 认证
- passlib + bcrypt 密码哈希
- SMTP 邮件验证码
- WeChat Pay 支付
- Docker SDK（后台可触发容器重启）

后端依赖文件：

- [backend/requirements.txt](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/requirements.txt)

### 前端

- Vue 3
- Vite
- Vue Router
- Pinia
- Naive UI
- Axios

前端依赖文件：

- [frontend/package.json](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/frontend/package.json)

### 部署

- Docker Compose
- Nginx
- Backend 容器内同时承载 FastAPI 和已构建的前端静态文件

部署文件：

- [docker-compose.yml](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/docker-compose.yml)
- [backend/Dockerfile](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/Dockerfile)
- [nginx/nginx.conf](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/nginx/nginx.conf)


## 3. 目录结构

```text
Gcy_Platform_Server/
├─ backend/
│  ├─ app/
│  │  ├─ api/routes/        # FastAPI 路由
│  │  ├─ core/              # 配置、数据库、Redis、安全、支付、邮件、价格同步
│  │  ├─ models/            # SQLAlchemy 模型
│  │  └─ main.py            # 后端入口
│  ├─ requirements.txt
│  ├─ init_data.py
│  └─ Dockerfile
├─ frontend/
│  ├─ src/
│  │  ├─ api/
│  │  ├─ views/
│  │  ├─ router.js
│  │  └─ main.js
│  ├─ package.json
│  └─ vite.config.js
├─ nginx/
│  └─ nginx.conf
├─ docs/
│  └─ client_api.md
├─ docker-compose.yml
├─ .env
├─ .env.example
└─ README.md
```


## 4. 当前代码状态

当前工作区 **不是干净状态**，存在未提交变更和新增文件。

已修改文件包括：

- `backend/app/api/routes/admin.py`
- `backend/app/api/routes/auth.py`
- `backend/app/api/routes/models.py`
- `backend/app/api/routes/payment.py`
- `backend/app/api/routes/tokens.py`
- `backend/app/api/routes/usage.py`
- `backend/app/core/config.py`
- `backend/app/core/redis.py`
- `backend/app/main.py`
- `backend/app/models/content.py`
- `backend/app/models/token.py`
- `backend/init_data.py`
- `frontend/src/views/Dashboard.vue`
- `frontend/src/views/Groups.vue`
- `frontend/src/views/Models.vue`
- `frontend/src/views/Orders.vue`
- `frontend/src/views/Tokens.vue`
- `frontend/src/views/Users.vue`

未跟踪文件包括：

- `backend/app/core/packy_sync.py`
- `frontend/src/utils/`
- `dev.db`

接手时务必注意：

1. 不要默认工作区是干净的
2. 不要随意覆盖已有改动
3. 修改前先 `git status`，必要时先阅读当前差异


## 5. 关键架构说明

### 5.1 后端入口

后端入口文件：

- [backend/app/main.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/main.py)

它负责：

- 创建 FastAPI 应用
- 注册全局异常处理
- 配置 CORS
- 注册所有 API 路由
- 初始化 Redis
- 初始化数据库表
- 运行默认分组和默认模型灌库逻辑
- 启动价格同步后台任务
- 恢复待处理退款
- 启动 Redis keyspace listener 监听自动退款
- 挂载前端静态目录 `/admin`

### 5.2 非标准迁移方式

这个项目虽然安装了 `alembic`，但当前数据库演进方式并不规范，主要靠：

- `Base.metadata.create_all`
- 启动时手工补列 `_ensure_columns`
- 启动时 `seed_defaults`
- 启动时数据迁移 `_migrate_groups`

也就是说：

1. 这是一个“运行时修补 schema”的项目
2. 如果要改模型，不能只改 ORM，必须考虑线上已有表兼容
3. 不要假设 Alembic 已经接管数据库迁移


## 6. 配置与环境变量

配置入口：

- [backend/app/core/config.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/core/config.py)

主要配置项：

- `DATABASE_URL`
- `REDIS_URL`
- `SECRET_KEY`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `WECHAT_MCHID`
- `WECHAT_APPID`
- `WECHAT_APIV3_KEY`
- `WECHAT_CERT_SERIAL_NO`
- `WECHAT_PRIVATE_KEY_PATH`
- `WECHAT_NOTIFY_URL`
- `WECHAT_REFUND_NOTIFY_URL`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SERVER_BASE_URL`
- `EXCHANGE_RATE_API`
- `PACKYAPI_PRICING_URL`
- `PACKYAPI_SYNC_INTERVAL_MINUTES`
- `PACKYAPI_MARKUP_PERCENT`

注意：

- 配置通过 `.env` 加载
- 后台管理接口支持读取并写回 `.env`
- 后台管理接口还能触发 backend 容器重启


## 7. 数据库与核心数据模型

数据库连接：

- [backend/app/core/database.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/core/database.py)

项目实际使用的主数据库是：

- PostgreSQL

虽然根目录有 `dev.db`，但从代码来看主链路不是 SQLite。

### 7.1 用户模型

文件：

- [backend/app/models/user.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/models/user.py)

主要表：

- `users`
- `user_tokens`

`users` 负责：

- 用户名
- 邮箱
- 密码哈希
- 账户类型 `normal / trial / paid`
- 试用到期时间
- 启用状态

`user_tokens` 负责：

- 某个用户在某个 `group` 下绑定了哪个 token
- 当前余额 `balance_usd`
- 是否试用 token

唯一约束：

- 一个用户对一个 `group` 只能有一条 `user_tokens`

### 7.2 Token 与订单模型

文件：

- [backend/app/models/token.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/models/token.py)

主要表：

- `token_inventory`
- `orders`
- `usage_logs`

`token_inventory`：

- 平台原始 token 库存池
- 字段记录 token 值、所属 group、是否试用、是否已分配、分配给谁

`orders`：

- 充值订单
- 支付状态
- 退款状态
- 订单分组
- 人民币/美元金额
- 汇率
- 微信交易号

订单状态常量：

- `pending`
- `paid`
- `assigned`
- `closed`
- `refunding`
- `refunded`
- `refund_change`

`usage_logs`：

- 用户用量日志
- 记录 model、usage_type、token 数量、图片数量、费用

### 7.3 内容与模型配置

文件：

- [backend/app/models/content.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/models/content.py)

主要表：

- `groups`
- `ai_models`
- `prompts`
- `notices`

`groups`：

- 业务分组，不是单纯分类展示
- 它直接影响 token 分配、计费和可用模型权限

当前默认组：

- `image`
- `agent`
- `postprocess`

`ai_models`：

- 模型定义
- 所属 provider
- 计费方式 `per_call / per_token`
- 模型类型 `image / agent / postprocess`
- 所属 group
- 是否启用
- 是否允许试用
- 价格字段
- 上下文长度
- 是否支持 tools / vision


## 8. 业务核心概念

### 8.1 group 是一等公民

这个项目最关键的设计不是 model，而是 `group`。

用户权限、Token、余额、订单、计费几乎都围绕 `group` 进行。

可以理解为：

- `group` = 一类上游能力的购买与使用单位
- `model` = 这个组下面的具体模型

例如：

- `image` 组下面可能有图像生成模型
- `agent` 组下面可能有文本/工具型 agent 模型
- `postprocess` 组下面可能有后处理工具

### 8.2 计费方式

支持两种计费模式：

- `per_call`
- `per_token`

对应逻辑在：

- [backend/app/api/routes/usage.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/api/routes/usage.py)

规则：

- `per_call`：按调用次数乘单价
- `per_token`：按输入、输出、缓存 token 各自价格计算

### 8.3 用户实际使用流程

用户链路大致是：

1. 注册/登录
2. 获得某个 group 的 token 和余额
3. 用自己的客户端调用上游 AI
4. 成功后回调本系统 `/api/usage/*` 上报用量
5. 本系统扣减余额并记录日志

这意味着：

- 本系统并不是所有场景都直接转发 AI 请求
- 更多是“账号、额度、计费、资产管理平台”


## 9. API 模块说明

### 9.1 认证

文件：

- [backend/app/api/routes/auth.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/api/routes/auth.py)

主要能力：

- 用户注册
- 邮箱验证码注册
- 登录
- 管理员登录
- 忘记密码发码与重置
- 普通账户升级试用
- `/me` 返回用户信息

依赖 Redis 做：

- 验证码缓存
- 频率限制
- 输错次数锁定

### 9.2 用量上报与计费

文件：

- [backend/app/api/routes/usage.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/api/routes/usage.py)

主要接口：

- `/report/image`
- `/report/agent`
- `/report/chat`
- `/report/tool`
- `/estimate`
- `/records`

注意点：

- `chat` 是兼容层，底层已偏向 `agent`
- `tool` 上报有 Redis 幂等控制，key 基于 `tool_call_id`

### 9.3 支付与退款

文件：

- [backend/app/api/routes/payment.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/api/routes/payment.py)

主要能力：

- 创建微信支付订单
- 微信支付回调
- 订单支付状态查询
- 关闭订单
- 后台发起退款
- 用户申请退款
- 退款回调
- 查询退款状态
- 查询个人订单列表

重要特征：

- 订单支持多 group 混合充值，`items_json` 保存明细
- 金额汇率从外部 API 获取，并缓存在 Redis
- 退款有自动处理逻辑

### 9.4 Redis 与自动退款

文件：

- [backend/app/core/redis.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/core/redis.py)

主要逻辑：

- 初始化 Redis 客户端
- 监听 Redis keyspace 过期事件
- 自动批准超时退款
- 服务启动时恢复待处理退款任务

关键机制：

1. 用户申请退款后，写入一个 `refund:auto:{out_trade_no}` 的 Redis TTL key
2. key 过期后，由 keyspace listener 触发自动退款
3. 服务重启时还会恢复这批未完成退款

这块是项目里很重要的异步状态机，不要把它当成普通缓存逻辑。

### 9.5 管理后台

文件：

- [backend/app/api/routes/admin.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/api/routes/admin.py)

主要模块：

- Token 库存管理
- 分组管理
- 公告管理
- 提示词管理
- 模型管理
- 用户管理
- 订单管理
- 用户 token 与余额管理
- 管理员密码修改
- `.env` 配置读写
- backend 容器重启

这个文件很大，职责比较杂，接手改动时优先先看目标接口附近上下文。


## 10. 模型价格同步

文件：

- [backend/app/core/packy_sync.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/core/packy_sync.py)

这是一个后台循环任务：

- 定期从 `PACKYAPI_PRICING_URL` 拉价格
- 按配置 `PACKYAPI_MARKUP_PERCENT` 加价
- 写回 `ai_models`

说明：

- 这不是一次性脚本，而是服务生命周期内的异步 loop
- 如果你修改模型价格逻辑，需要同时考虑：
  - 初始默认价格
  - 后台手工修改价格
  - 自动同步是否会覆盖人工值


## 11. 前端结构与行为

前端入口：

- [frontend/src/main.js](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/frontend/src/main.js)

路由：

- [frontend/src/router.js](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/frontend/src/router.js)

HTTP 封装：

- [frontend/src/api/http.js](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/frontend/src/api/http.js)

主要页面：

- `Login.vue`
- `Layout.vue`
- `Dashboard.vue`
- `Tokens.vue`
- `Groups.vue`
- `Models.vue`
- `Orders.vue`
- `Users.vue`
- `Notice.vue`
- `Prompts.vue`
- `Settings.vue`

前端特点：

- 使用 hash 路由
- 管理员 token 放在 `localStorage.admin_token`
- 401 时会清 token 并跳到 `/admin/`
- Vite `base` 配置为 `/admin/`

Vite 配置文件：

- [frontend/vite.config.js](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/frontend/vite.config.js)


## 12. 部署与访问路径

### 本地开发

后端：

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

前端：

```powershell
cd frontend
npm install
npm run dev
```

前端 dev 默认通过 Vite 代理 `/api` 到 `http://localhost:8000`。

### Docker Compose

```powershell
docker compose up -d
```

服务包括：

- `postgres`
- `redis`
- `backend`
- `nginx`

### 生产访问

- `/admin/` -> 后台前端
- `/api/*` -> 后端接口
- `/health` -> 健康检查


## 13. 已确认的关键文件入口

### 后端入口与核心

- [backend/app/main.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/main.py)
- [backend/app/core/config.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/core/config.py)
- [backend/app/core/database.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/core/database.py)
- [backend/app/core/redis.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/core/redis.py)
- [backend/app/core/packy_sync.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/core/packy_sync.py)
- [backend/app/core/security.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/core/security.py)
- [backend/app/core/wechatpay.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/core/wechatpay.py)
- [backend/app/core/email.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/core/email.py)

### 路由

- [backend/app/api/routes/auth.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/api/routes/auth.py)
- [backend/app/api/routes/users.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/api/routes/users.py)
- [backend/app/api/routes/tokens.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/api/routes/tokens.py)
- [backend/app/api/routes/models.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/api/routes/models.py)
- [backend/app/api/routes/usage.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/api/routes/usage.py)
- [backend/app/api/routes/payment.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/api/routes/payment.py)
- [backend/app/api/routes/notice.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/api/routes/notice.py)
- [backend/app/api/routes/prompts.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/api/routes/prompts.py)
- [backend/app/api/routes/admin.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/api/routes/admin.py)

### 模型

- [backend/app/models/user.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/models/user.py)
- [backend/app/models/token.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/models/token.py)
- [backend/app/models/content.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/models/content.py)

### 前端

- [frontend/src/main.js](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/frontend/src/main.js)
- [frontend/src/router.js](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/frontend/src/router.js)
- [frontend/src/api/http.js](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/frontend/src/api/http.js)


## 14. 已识别的工程问题与风险

### 14.1 文档编码乱码

以下文件输出时出现明显乱码：

- `README.md`
- `docs/client_api.md`

处理建议：

- 不要完全依赖这两个文档理解业务
- 以源码逻辑为准
- 如果要修文档，先确认原始编码和目标编码，再统一转 UTF-8

### 14.2 admin.py 过大

[backend/app/api/routes/admin.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/api/routes/admin.py) 体积很大，职责过多，包含：

- Token
- 用户
- 订单
- 模型
- 提示词
- 公告
- 配置
- 容器重启

这是明显的维护风险点。修复 bug 时先局部改；做重构时要拆模块。

### 14.3 运行时 schema 修补

数据库 schema 不是迁移优先，而是启动时补。

风险：

- 新旧库兼容不透明
- 多实例部署时行为不够可控
- 线上升级可预测性差

### 14.4 Redis 不只是缓存

Redis 在项目里承担：

- 验证码缓存
- 频率限制
- 幂等控制
- 汇率缓存
- 自动退款调度

因此改 Redis 逻辑时不能只从缓存角度思考。

### 14.5 Docker socket 暴露

`docker-compose.yml` 中 backend 挂载了：

- `/var/run/docker.sock:/var/run/docker.sock`

这使后台接口具备控制宿主 Docker 的能力，功能上是为了重启 backend，但权限风险很高。


## 15. Claude Code 接手时的推荐检查顺序

如果你的任务是修 bug 或改功能，建议按这个顺序读：

1. 先看 [backend/app/main.py](D:/Pythontext/Gcy_Platform_Server/Gcy_Platform_Server/backend/app/main.py) 了解服务启动行为
2. 看相关路由文件，确认入口 API
3. 看对应模型文件，确认表结构与关系
4. 看 `core` 目录下相关公共逻辑
5. 如果涉及后台页面，再看对应 Vue 页面和 `http.js`
6. 最后检查当前 `git status`，避免覆盖别人的变更

如果任务涉及：

- 登录注册：先看 `auth.py`、`security.py`、`redis.py`
- 扣费/余额：先看 `usage.py`、`models/token.py`
- 支付退款：先看 `payment.py`、`wechatpay.py`、`redis.py`
- 模型/价格：先看 `content.py`、`models.py`、`packy_sync.py`
- 后台配置：先看 `admin.py` 中 config 区域和 `.env`


## 16. 可直接执行的接手提示词

下面这段可以直接发给 Claude Code：

```text
请先阅读项目交接文档：

D:\Pythontext\Gcy_Platform_Server\Gcy_Platform_Server\CLAUDE_CODE_HANDOFF.md

然后按文档里的关键入口理解项目，不要假设工作区是干净的。这个项目是 FastAPI + Vue3 + PostgreSQL + Redis 的 SaaS 管理后台，核心是 group 维度的 token/余额/计费/支付管理，不是单纯 AI 代理。

开始工作前请先：
1. 检查 git status
2. 不要覆盖现有未提交改动
3. 优先阅读与本次任务直接相关的 route / model / core 文件

本次需要你处理的问题是：
[在这里补充你的具体修复需求]
```


## 17. 如果要继续深挖，建议补的内容

如果后续要长期维护，建议继续补充这些文档：

- 数据库 ER 图
- 各接口请求响应示例
- 支付状态流转图
- 退款状态流转图
- group/model/billing_type 关系说明
- 后台页面与 API 的对应表
- `.env` 每个配置项的真实用途说明


## 18. 总结

一句话概括这个项目：

这是一个围绕 `group` 进行用户授权、Token 分配、余额计费、微信支付充值与后台管理的 AI SaaS 平台后端与管理前端。

真正接手时，最重要的不是先看 README，而是先看：

1. `backend/app/main.py`
2. 目标路由
3. 目标模型
4. Redis / payment / security 这些核心公共模块

