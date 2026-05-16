# CyImagePro 客户端 API 对接文档

> Base URL: `https://www.zjcypc.com`
> 所有后端接口路径都以 `/api` 开头，例如 `https://www.zjcypc.com/api/auth/login`。
> 认证方式: Bearer Token（JWT），放在 Header `Authorization: Bearer <token>` 中

---

## 一、整体架构

```
客户端 ──注册/登录──▶ 后端（获取 JWT + OpenAI API Key）
客户端 ──直连──▶ OpenAI API（用获取到的 Key 生成图片/对话）
客户端 ──上报用量──▶ 后端（扣费）
客户端 ──余额不足──▶ 后端（创建支付订单 → 充值）
```

**核心逻辑：** 客户端直连 OpenAI，后端只负责发放 API Key、计费扣费、充值支付。

**双 Token 体系：** 图片模型和对话模型使用不同的 OpenAI API Key，分别计费。
- `image_api_token`：用于调用图片生成模型（如 gpt-image-2）
- `chat_api_token`：用于调用对话模型（如 gpt-4.5）
- 两种 Token 独立购买、独立余额、互不影响

---

## 二、认证模块

### 2.1 用户注册

```
POST /api/auth/register
```

**请求体：**
```json
{
  "username": "testuser",
  "email": "test@example.com",
  "password": "123456",
  "account_type": "normal"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| username | string | 是 | 用户名 |
| email | string | 是 | 邮箱 |
| password | string | 是 | 密码 |
| account_type | string | 否 | `trial`（试用）或 `normal`（普通），默认 `normal` |

**account_type 说明：**
- `trial`：自动分配一个图片 Token，`image_balance_usd=1.0`，有效期 3 天。不分配对话 Token。
- `normal`：不分配任何 Token，两个余额均为 0，需购买套餐后使用。

**成功响应 200：**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "user": {
    "id": "uuid",
    "username": "testuser",
    "email": "test@example.com",
    "account_type": "normal",
    "image_balance_usd": 0.0,
    "chat_balance_usd": 0.0,
    "image_api_token": null,
    "chat_api_token": null,
    "trial_expires_at": null,
    "trial_expired": false
  }
}
```

**试用用户响应示例：**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "user": {
    "id": "uuid",
    "username": "testuser",
    "email": "test@example.com",
    "account_type": "trial",
    "image_balance_usd": 1.0,
    "chat_balance_usd": 0.0,
    "image_api_token": "sk-xxxxxxx",
    "chat_api_token": null,
    "trial_expires_at": "2025-05-11T12:00:00+00:00",
    "trial_expired": false
  }
}
```

**错误：**
- 400: `用户名或邮箱已存在`
- 400: `试用名额已满，请直接购买套餐`

---

### 2.2 用户登录

```
POST /api/auth/login
```

**请求体：**
```json
{
  "username": "testuser",
  "password": "123456"
}
```

**成功响应 200：** 同注册返回格式

**错误：**
- 401: `用户名或密码错误`
- 403: `账号已被禁用`

---

### 2.3 升级为试用账户

```
POST /api/auth/upgrade-trial
Authorization: Bearer <token>
```

**说明：** 仅 `account_type == "normal"` 的用户可调用。成功后获得图片 Token + $1 余额 + 3 天有效期。

**成功响应 200：**
```json
{
  "user": {
    "id": "uuid",
    "username": "testuser",
    "email": "test@example.com",
    "account_type": "trial",
    "image_balance_usd": 1.0,
    "chat_balance_usd": 0.0,
    "image_api_token": "sk-xxxxxxx",
    "chat_api_token": null,
    "trial_expires_at": "2025-05-14T12:00:00+00:00",
    "trial_expired": false
  }
}
```

**错误：**
- 400: `仅普通账户可申请试用`
- 400: `试用名额已满，请直接购买套餐`

---

## 三、用户信息

### 3.1 获取当前用户信息

```
GET /api/users/me
Authorization: Bearer <token>
```

**响应：**
```json
{
  "id": "uuid",
  "username": "testuser",
  "email": "test@example.com",
  "account_type": "trial",
  "image_balance_usd": 0.96,
  "chat_balance_usd": 0.0,
  "image_api_token": "sk-xxxxxxx",
  "chat_api_token": null,
  "trial_expires_at": "2025-05-11T12:00:00+00:00",
  "trial_expired": false
}
```

**字段说明：**
| 字段 | 说明 |
|------|------|
| image_balance_usd | 图片模型剩余余额（美元） |
| chat_balance_usd | 对话模型剩余余额（美元） |
| image_api_token | 图片模型的 OpenAI API Key（null 表示未购买） |
| chat_api_token | 对话模型的 OpenAI API Key（null 表示未购买） |
| trial_expired | 试用是否已过期 |

---

### 3.2 获取用量记录

```
GET /api/users/me/usage
Authorization: Bearer <token>
```

**响应：**
```json
[
  {
    "model": "gpt-image-2",
    "usage_type": "image",
    "image_count": 1,
    "cost_usd": 0.04,
    "created_at": "2025-05-09T10:30:00+00:00"
  }
]
```

---

## 四、用量上报（核心接口）

客户端每次调用 OpenAI API 成功后，必须向后端上报用量，后端据此扣费。

**重要：** 图片用量从 `image_balance_usd` 扣费，对话用量从 `chat_balance_usd` 扣费。

### 4.1 上报图片生成用量

```
POST /api/usage/report/image
Authorization: Bearer <token>
```

**请求体：**
```json
{
  "model": "gpt-image-2",
  "image_count": 1
}
```

**成功响应 200：**
```json
{
  "cost_usd": 0.04,
  "balance_usd": 0.96,
  "account_type": "paid"
}
```

> `balance_usd` 返回的是 `image_balance_usd` 扣费后的值。
> `account_type` 返回当前账户状态，如果两个余额都耗尽会自动变为 `"normal"`。

**错误：**
- 400: `未知模型: xxx`
- 402: `余额不足`
- 403: `未购买图片套餐`（用户没有 image_api_token）
- 403: `试用期已过期，请购买套餐`
- 403: `试用账号仅支持图片模型`

---

### 4.2 上报对话用量

```
POST /api/usage/report/chat
Authorization: Bearer <token>
```

**请求体：**
```json
{
  "model": "gpt-4.5",
  "input_tokens": 1500,
  "output_tokens": 800,
  "cached_tokens": 0
}
```

**成功响应 200：**
```json
{
  "cost_usd": 0.0063,
  "balance_usd": 9.9937,
  "account_type": "paid"
}
```

> `balance_usd` 返回的是 `chat_balance_usd` 扣费后的值。
> `account_type` 返回当前账户状态，如果两个余额都耗尽会自动变为 `"normal"`。

**错误：**
- 400: `未知模型: xxx`
- 402: `余额不足`
- 403: `未购买对话套餐`（用户没有 chat_api_token）
- 403: `试用账号不支持对话模型`

**计费公式：**
```
cost = input_tokens / 1,000,000 * input_price
     + output_tokens / 1,000,000 * output_price
     + cached_tokens / 1,000,000 * cache_price
```

---

## 五、Token 库存查询

### 5.1 查询套餐库存

```
GET /api/tokens/stock
```

**响应：**
```json
{
  "image": {
    "10": 5,
    "20": 3,
    "50": 2,
    "100": 1
  },
  "chat": {
    "10": 4,
    "20": 2,
    "50": 1,
    "100": 0
  }
}
```

> 按 token_type 和 package_usd 分组，值为可用数量。

### 5.2 查询试用库存

```
GET /api/tokens/trial-stock
```

**响应：**
```json
{
  "remaining": 10,
  "available": true
}
```

> 试用 Token 只有 image 类型。`available=false` 时注册试用账号会失败。

---

## 六、支付充值

### 6.1 获取套餐列表

```
GET /api/pay/packages
```

**响应：**
```json
[
  {"package_usd": 10, "name": "$10 图片套餐", "token_type": "image", "price_cny": 72.50, "exchange_rate": 7.25},
  {"package_usd": 20, "name": "$20 图片套餐", "token_type": "image", "price_cny": 145.00, "exchange_rate": 7.25},
  {"package_usd": 50, "name": "$50 图片套餐", "token_type": "image", "price_cny": 362.50, "exchange_rate": 7.25},
  {"package_usd": 100, "name": "$100 图片套餐", "token_type": "image", "price_cny": 725.00, "exchange_rate": 7.25},
  {"package_usd": 10, "name": "$10 对话套餐", "token_type": "chat", "price_cny": 72.50, "exchange_rate": 7.25},
  {"package_usd": 20, "name": "$20 对话套餐", "token_type": "chat", "price_cny": 145.00, "exchange_rate": 7.25},
  {"package_usd": 50, "name": "$50 对话套餐", "token_type": "chat", "price_cny": 362.50, "exchange_rate": 7.25},
  {"package_usd": 100, "name": "$100 对话套餐", "token_type": "chat", "price_cny": 725.00, "exchange_rate": 7.25}
]
```

---

### 6.2 创建支付订单

```
POST /api/pay/create_order
Authorization: Bearer <token>
```

**请求体：**
```json
{
  "package_usd": 10,
  "token_type": "image",
  "pay_type": "alipay",
  "client_ip": "192.168.1.100"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| package_usd | int | 是 | 套餐金额：10/20/50/100 |
| token_type | string | 是 | `image` 或 `chat` |
| pay_type | string | 是 | `alipay`（支付宝）或 `wxpay`（微信） |
| client_ip | string | 是 | 客户端 IP |

**成功响应 200：**
```json
{
  "out_trade_no": "CY20250509120000ABCD1234",
  "amount_cny": 72.50,
  "exchange_rate": 7.25,
  "pay_type": "alipay",
  "pay_info": "https://支付链接或二维码URL",
  "package_usd": 10,
  "token_type": "image"
}
```

**客户端处理：** 用 `pay_info` 展示支付二维码或跳转支付页面。

**错误：**
- 400: `无效的套餐`
- 400: `不支持的支付方式`
- 400: `当前套餐暂时缺货，请联系客服`

---

### 6.3 查询订单状态

```
GET /api/pay/query/{out_trade_no}
Authorization: Bearer <token>
```

**响应：**
```json
{
  "out_trade_no": "CY20250509120000ABCD1234",
  "status": "pending|paid",
  "package_usd": 10,
  "token_type": "image",
  "amount_cny": 72.50,
  "paid_at": "2025-05-09T12:05:00+00:00",
  "image_api_token": "sk-newtoken...",
  "chat_api_token": null
}
```

**客户端处理：** 创建订单后轮询此接口（建议 3 秒一次），当 `status` 变为 `paid` 时：
1. 更新本地对应类型的余额
2. 如果返回了新的 `image_api_token` 或 `chat_api_token`，替换本地存储的对应 Key

---

## 七、内容接口

### 7.1 获取提示词库

```
GET /api/prompts
```

**响应：**
```json
[
  {
    "id": "uuid",
    "category": "风景",
    "title": "赛博朋克城市",
    "content": "A cyberpunk city at night with neon lights..."
  }
]
```

---

### 7.2 获取公告（跑马灯）

```
GET /api/notice
```

**响应：**
```json
{
  "content": "系统维护通知：今晚 22:00-23:00 暂停服务",
  "is_active": true
}
```

**客户端显示逻辑：**
- 显示条件：`content` 非空 且 `is_active !== false`（有内容就显示，只有后端明确返回 `is_active: false` 才隐藏）
- 滚动动画：基于实际文字宽度动态计算起止位置和速度（建议 80px/s），短文字不会滚太慢，长文字不会滚太快

---

### 7.3 获取可用模型列表

```
GET /api/models
```

**响应：**
```json
[
  {
    "name": "gpt-image-2",
    "display_name": "GPT Image 2",
    "model_type": "image",
    "trial_allowed": true,
    "price_per_image": "0.04"
  },
  {
    "name": "gpt-4.5",
    "display_name": "GPT-4.5",
    "model_type": "chat",
    "trial_allowed": false,
    "price_input_per_m": "1.0",
    "price_output_per_m": "6.0",
    "price_cached_per_m": "0.1"
  }
]
```

**客户端逻辑：**
- `model_type=image` 的模型使用 `image_api_token` 调用
- `model_type=chat` 的模型使用 `chat_api_token` 调用
- `trial_allowed=false` 的模型试用用户不可使用

---

## 八、当前定价

| 模型 | 类型 | input ($/M tokens) | output ($/M tokens) | cached ($/M tokens) | 图片 ($/张) |
|------|------|-----|--------|---------|------|
| gpt-image-2 | image | - | - | - | $0.04 |
| gpt-4.5 | chat | $1.0 | $6.0 | $0.1 | - |

---

## 九、错误码约定

| HTTP 状态码 | 含义 |
|------------|------|
| 400 | 请求参数错误 |
| 401 | 未认证 / Token 过期（客户端应跳转登录页） |
| 402 | 余额不足（客户端应引导充值） |
| 403 | 权限不足（试用限制 / 未购买对应套餐） |
| 404 | 资源不存在 |

---

## 十、账户状态流转

```
注册(normal) ────────────────────────▶ normal（无 Token、无余额）
normal ──申请试用──▶ trial（图片 Token + $1，3天有效期）
normal ──充值──▶ paid
trial ──充值──▶ paid
trial ──到期/额度用完──▶ normal（自动降级）
paid ──两个余额都耗尽──▶ normal（自动降级，Token 保留）
paid ──再次充值──▶ paid（使用原有 Token）
```

**自动降级规则：**
- 付费用户：`image_balance_usd` 和 `chat_balance_usd` 都 ≤ 0 时自动降级为 normal
- 试用用户：`trial_expires_at` 过期后首次调用时自动降级为 normal
- 降级后 Token 保留不回收，充值后可继续使用同一个 Key

---

## 十一、客户端对接 Checklist

- [ ] 注册/登录，本地持久化 `access_token`、`image_api_token`、`chat_api_token`
- [ ] 根据模型类型选择对应的 API Key 调用 OpenAI
  - 图片模型 → 使用 `image_api_token`
  - 对话模型 → 使用 `chat_api_token`
- [ ] 每次 AI 调用成功后，立即上报用量（`/api/usage/report/image` 或 `/chat`）
- [ ] 上报返回的 `account_type` 如果变为 `normal`，提示用户"余额已耗尽，请充值"
- [ ] 处理 402 余额不足，引导用户充值对应类型的套餐
- [ ] 处理 403 未购买套餐（token 为 null 时提示用户购买）
- [ ] 处理 401 Token 过期，跳转登录
- [ ] 处理 403 试用限制（过期、对话模型不可用）
- [ ] 普通用户界面增加"申请试用"按钮，调 `POST /api/auth/upgrade-trial`
- [ ] 支付流程：获取套餐 → 选择类型（图片/对话）→ 创建订单 → 展示支付码 → 轮询状态 → 更新余额和 Token
- [ ] 启动时调用 `/api/users/me` 刷新用户状态（双余额 + 双 Token + account_type）
- [ ] 注册前调用 `/api/tokens/trial-stock` 检查试用是否可用
- [ ] 展示提示词库和公告
