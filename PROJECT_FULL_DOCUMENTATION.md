# CyImagePro 项目完整技术文档

> AI API Token 分发、计费与支付 SaaS 管理平台  
> 版本：1.0.0 | 最后更新：2026-05-31

---

## 目录

1. [项目概述](#1-项目概述)
2. [技术栈](#2-技术栈)
3. [项目结构](#3-项目结构)
4. [数据库设计](#4-数据库设计)
5. [后端架构与源码](#5-后端架构与源码)
6. [前端架构与源码](#6-前端架构与源码)
7. [配置与部署](#7-配置与部署)
8. [API 接口文档](#8-api-接口文档)
9. [业务流程](#9-业务流程)
10. [环境变量说明](#10-环境变量说明)

---

## 1. 项目概述

CyImagePro 是一个 AI API Token 分发、计费与支付管理的 SaaS 平台。系统核心概念是 **"分组"（group）** 作为一等公民，每个用户在每个分组下拥有一个 `UserToken`，通过余额制进行计费。

### 核心特性

- **三分组体系**：`image`（图片生成）、`agent`（Agent 对话）、`postprocess`（后处理工具）
- **双计费模式**：`per_call`（按次计费，图片/后处理）和 `per_token`（按量计费，Agent 模型）
- **微信支付**：Native 二维码扫码支付，支持退款流程
- **15分钟自动退款**：Redis keyspace 通知实现超时自动批准退款
- **PackyAPI 价格同步**：定期同步上游定价，自动加价 15%
- **试用系统**：新用户可申请试用，分配 image 分组 Token，2天有效期，$1 余额
- **管理后台**：Vue 3 + Naive UI 暗色主题管理面板

---

## 2. 技术栈

| 层级 | 技术 | 版本 |
|------|------|------|
| 后端框架 | FastAPI | 0.115.0 |
| 语言 | Python | 3.12 |
| ORM | SQLAlchemy (async) | 2.0.35 |
| 数据验证 | Pydantic v2 | 2.9.2 |
| 数据库 | PostgreSQL | 16 Alpine |
| 缓存/队列 | Redis | 7 Alpine |
| 前端框架 | Vue 3 | 3.5.0 |
| UI 组件库 | Naive UI | 2.39.0 |
| 构建工具 | Vite | 5.4.0 |
| 状态管理 | Pinia | 2.2.0 |
| 路由 | Vue Router (Hash 模式) | 4.4.0 |
| 支付 | 微信支付 v3 (Native) | wechatpayv3 2.0.2 |
| 部署 | Docker Compose + Nginx | - |
| ASGI | Uvicorn | 0.30.6 |

---

## 3. 项目结构

```
GPT_Image_2_service/
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── init_data.py                  # 独立种子脚本
│   └── app/
│       ├── main.py                   # FastAPI 应用入口
│       ├── core/
│       │   ├── config.py             # Pydantic Settings 配置
│       │   ├── database.py           # SQLAlchemy 异步引擎
│       │   ├── security.py           # JWT + bcrypt 认证
│       │   ├── redis.py              # Redis 客户端 + 自动退款
│       │   ├── wechatpay.py          # 微信支付 v3 封装
│       │   ├── email.py              # SMTP 邮件发送
│       │   └── packy_sync.py         # PackyAPI 价格同步
│       ├── models/
│       │   ├── user.py               # User, UserToken 模型
│       │   ├── token.py              # TokenInventory, Order, UsageLog 模型
│       │   └── content.py            # Group, AIModel, Notice, Prompt 模型
│       └── api/
│           └── routes/
│               ├── admin.py          # 管理后台 API
│               ├── auth.py           # 认证 API
│               ├── payment.py        # 支付 API
│               ├── usage.py          # 用量上报 API
│               ├── users.py          # 用户自服务 API
│               ├── tokens.py         # Token 库存 API
│               ├── models.py         # 模型列表 API
│               ├── notice.py         # 通知 API
│               └── prompts.py        # 提示词 API
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.js                   # Vue 应用入口
│       ├── App.vue                   # 根组件（暗色主题配置）
│       ├── router.js                 # 路由配置（Hash 模式）
│       ├── api/
│       │   └── http.js               # Axios HTTP 客户端
│       ├── utils/
│       │   └── time.js               # 时间格式化工具
│       └── views/
│           ├── Login.vue             # 管理员登录
│           ├── Layout.vue            # 侧边栏布局
│           ├── Dashboard.vue         # 仪表盘
│           ├── Tokens.vue            # Token 库存管理
│           ├── Groups.vue            # 分组管理
│           ├── Models.vue            # 模型管理
│           ├── Orders.vue            # 订单管理
│           ├── Users.vue             # 用户管理
│           ├── Notice.vue            # 通知栏
│           ├── Prompts.vue           # 提示词库
│           └── Settings.vue          # 系统配置
├── nginx/
│   └── nginx.conf                    # Nginx 反向代理配置
├── docker-compose.yml                # Docker Compose 编排
├── .env.example                      # 环境变量模板
└── deploy.sh                         # 部署脚本
```
---

## 4. 数据库设计

### 4.1 users 表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | String(36) | PK | UUID 字符串 |
| username | String(64) | UNIQUE, NOT NULL | 用户名 |
| email | String(128) | UNIQUE, NOT NULL | 邮箱 |
| password_hash | String(256) | NOT NULL | bcrypt 哈希 |
| account_type | String(16) | 默认 "normal" | normal / trial / paid |
| trial_expires_at | DateTime(tz) | 可空 | 试用到期时间 |
| is_active | Boolean | 默认 True | 是否启用 |
| created_at | DateTime(tz) | 默认 utcnow | 创建时间 |

### 4.2 user_tokens 表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | String(36) | PK | UUID |
| user_id | String(36) | FK → users.id | 用户 ID |
| token_id | String(36) | FK → token_inventory.id | Token 库存 ID |
| group | String(32) | NOT NULL | 分组名 |
| balance_usd | Numeric(10,6) | 默认 0.0 | 美元余额 |
| is_trial | Boolean | 默认 False | 是否试用 |
| created_at | DateTime(tz) | 默认 utcnow | 创建时间 |

**唯一约束**：`UniqueConstraint('user_id', 'group', name='uq_user_group')` — 每个用户每个分组只能有一个 UserToken

### 4.3 token_inventory 表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | String(36) | PK | UUID |
| token_value | String(512) | NOT NULL | API Token 值（sk-xxx） |
| group | String(32) | NOT NULL | 分组名 |
| is_trial | Boolean | 默认 False | 是否试用 Token |
| is_assigned | Boolean | 默认 False | 是否已分配 |
| assigned_to | String(36) | 可空 | 分配给的用户 ID |
| assigned_at | DateTime(tz) | 可空 | 分配时间 |
| created_at | DateTime(tz) | 默认 utcnow | 创建时间 |

**唯一约束**：`UniqueConstraint('token_value', 'group', name='uq_token_value_group')`

### 4.4 orders 表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | String(36) | PK | UUID |
| user_id | String(36) | FK → users.id | 用户 ID |
| out_trade_no | String(64) | UNIQUE, NOT NULL | 商户订单号（CY开头） |
| trade_no | String(64) | 可空 | 微信支付交易号 |
| group | String(128) | NOT NULL | 分组（逗号分隔多分组） |
| amount_usd | Numeric(10,2) | NOT NULL | 美元金额 |
| amount_cny | Numeric(10,2) | NOT NULL | 人民币金额 |
| exchange_rate | Numeric(10,4) | NOT NULL | 汇率 |
| items_json | Text | 可空 | JSON 明细 |
| pay_type | String(16) | 可空 | 支付方式（wxpay） |
| status | String(16) | 默认 "pending" | 订单状态 |
| out_refund_no | String(64) | 可空 | 退款单号（RF开头） |
| token_id | String(36) | 可空 | 关联的 Token ID |
| created_at | DateTime(tz) | 默认 utcnow | 创建时间 |
| paid_at | DateTime(tz) | 可空 | 支付时间 |
| refunded_at | DateTime(tz) | 可空 | 退款时间 |
| refund_requested_at | DateTime(tz) | 可空 | 退款申请时间 |
| status_before_refund | String(16) | 可空 | 退款前状态（用于冲正） |

**订单状态流转**：

```
PENDING ──→ PAID ──→ ASSIGNED ──→ (终态)
  │           │          │
  ↓           ↓          ↓
CLOSED    REFUNDING ←────┘
              │
    ┌─────────┼─────────┐
    ↓         ↓         ↓
 REFUNDED    PAID    ASSIGNED
 (拒绝退款后恢复原状态)
```

**OrderStatus.TRANSITIONS 定义**：
- `PENDING → {PAID, CLOSED}`
- `PAID → {ASSIGNED, REFUNDING}`
- `ASSIGNED → {REFUNDING}`
- `REFUNDING → {REFUNDED, PAID, ASSIGNED}`
- `CLOSED → {}`（终态）
- `REFUNDED → {}`（终态）
- `REFUND_CHANGE → {REFUNDED}`

### 4.5 usage_logs 表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | String(36) | PK | UUID |
| user_id | String(36) | FK → users.id | 用户 ID |
| model | String(64) | NOT NULL | 模型名 |
| usage_type | String(16) | NOT NULL | image/agent/chat/postprocess |
| image_count | Integer | 默认 0 | 图片数量 |
| input_tokens | Integer | 默认 0 | 输入 Token 数 |
| output_tokens | Integer | 默认 0 | 输出 Token 数 |
| cached_tokens | Integer | 默认 0 | 缓存 Token 数 |
| cost_usd | Numeric(10,6) | NOT NULL | 费用（美元） |
| created_at | DateTime(tz) | 默认 utcnow | 创建时间 |

### 4.6 groups 表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | String(36) | PK | UUID |
| name | String(32) | UNIQUE, NOT NULL | 分组名 |
| description | String(128) | 默认 "" | 描述 |
| sort_order | Integer | 默认 0 | 排序 |
| created_at | DateTime(tz) | 默认 utcnow | 创建时间 |

**默认数据**：
- `image` — 图片生成组 (sort_order: 1)
- `agent` — Agent 对话组 (sort_order: 2)
- `postprocess` — 后处理工具组 (sort_order: 3)

### 4.7 ai_models 表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | String(36) | PK | UUID |
| name | String(64) | NOT NULL | 模型标识 |
| display_name | String(128) | NOT NULL | 显示名称 |
| provider | String(32) | 默认 "OpenAI" | 供应商 |
| billing_type | String(16) | NOT NULL | per_call / per_token |
| model_type | String(16) | NOT NULL | image / agent / postprocess |
| group | String(32) | NOT NULL | 所属分组 |
| is_enabled | Boolean | 默认 True | 是否启用 |
| trial_allowed | Boolean | 默认 False | 试用可用 |
| price_input | String(32) | 可空 | 输入价格 $/1K tokens |
| price_output | String(32) | 可空 | 输出价格 $/1K tokens |
| price_cached | String(32) | 可空 | 缓存价格 $/1K tokens |
| price_per_call | String(32) | 可空 | 单次调用价格 $ |
| sort_order | Integer | 默认 0 | 排序 |
| context_window | Integer | 默认 32768 | 上下文窗口 |
| supports_tools | Boolean | 默认 False | 支持工具调用 |
| supports_vision | Boolean | 默认 False | 支持视觉 |

**唯一约束**：`UniqueConstraint('name', 'group', name='uq_model_group')`

### 4.8 notices 表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | String(36) | PK | UUID |
| content | Text | NOT NULL, 默认 "" | 通知内容 |
| is_active | Boolean | 默认 True | 是否启用 |
| updated_at | DateTime(tz) | 默认 utcnow, onupdate=utcnow | 更新时间 |

### 4.9 prompts 表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | String(36) | PK | UUID |
| category | String(64) | NOT NULL | 分类 |
| title | String(128) | NOT NULL | 标题 |
| content | Text | NOT NULL | 提示词内容 |
| sort_order | Integer | 默认 0 | 排序 |
| is_active | Boolean | 默认 True | 是否启用 |
| created_at | DateTime(tz) | 默认 utcnow | 创建时间 |

**默认分类**：抖音商品图、电商详情图、商品白底图、去除背景、图片修图、提取图片、分镜、商品标注、跨境电商图、跨境电商A+图

---

## 5. 后端架构与源码

### 5.1 核心模块

#### 5.1.1 config.py — 配置管理

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://cyimage:cyimage123@postgres:5432/cyimage"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # JWT
    SECRET_KEY: str = "change-this-secret-key-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Admin
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin123"

    # 微信支付
    WECHAT_MCHID: str = ""
    WECHAT_APPID: str = ""
    WECHAT_APIV3_KEY: str = ""
    WECHAT_CERT_SERIAL_NO: str = ""
    WECHAT_PRIVATE_KEY_PATH: str = "/app/certs/apiclient_key.pem"
    WECHAT_NOTIFY_URL: str = ""
    WECHAT_REFUND_NOTIFY_URL: str = ""
    WECHAT_PUBLIC_KEY_PATH: str = ""
    WECHAT_PUBLIC_KEY_ID: str = ""

    # Server
    SERVER_BASE_URL: str = "https://www.zjcypc.com"

    # SMTP / Email
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_NAME: str = "CyImagePro"
    SMTP_USE_SSL: bool = True

    # Payment limits
    PAYMENT_MIN_TOTAL_USD: float = 1.0
    PAYMENT_MAX_TOTAL_USD: float = 1000.0
    PAYMENT_MIN_PER_ITEM_USD: float = 0.01

    # Exchange rate API (free tier)
    EXCHANGE_RATE_API: str = "https://open.er-api.com/v6/latest/USD"

    # PackyAPI price sync
    PACKYAPI_PRICING_URL: str = "https://www.packyapi.com/api/pricing"
    PACKYAPI_SYNC_INTERVAL_MINUTES: int = 60
    PACKYAPI_MARKUP_PERCENT: float = 15.0

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
```

#### 5.1.2 database.py — 数据库连接

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings


engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

#### 5.1.3 security.py — 认证与安全

```python
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()


def _validate_bcrypt_password(password: str) -> None:
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="密码过长，请使用 72 字节以内的密码")


def hash_password(password: str) -> str:
    _validate_bcrypt_password(password)
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    _validate_bcrypt_password(plain)
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": user_id, "exp": expire}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = jwt.decode(credentials.credentials, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的认证信息")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的认证信息")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    return user


async def get_admin_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    try:
        payload = jwt.decode(credentials.credentials, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("role") != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限")
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的认证信息")


def create_admin_token() -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=12)
    return jwt.encode({"sub": "admin", "role": "admin", "exp": expire}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


async def get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional["User"]:
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if not user_id:
            return None
    except JWTError:
        return None
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()
```

**JWT Token 设计**：
- 用户 Token：`{sub: user_id, exp: 7天后}` — 7 天有效
- 管理员 Token：`{sub: "admin", role: "admin", exp: 12小时后}` — 12 小时有效
- 可选用户：`get_optional_user` — 解析 Bearer Token，失败不报错返回 None

#### 5.1.4 redis.py — Redis 客户端与自动退款

```python
import asyncio
import json
import logging

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


async def init_redis():
    """Initialize Redis connection"""
    get_redis()


async def auto_approve_refund(out_trade_no: str):
    """自动批准退款（15分钟超时后调用）"""
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.token import Order, OrderStatus, UserToken, TokenInventory
    from app.core.wechatpay import wechatpay_request

    logger.info(f"Auto-approving refund for order {out_trade_no}")

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(Order).where(Order.out_trade_no == out_trade_no))
            order = result.scalar_one_or_none()
            if not order or order.status != OrderStatus.REFUNDING:
                logger.info(f"Order {out_trade_no} not in REFUNDING state, skipping auto-approve")
                return

            # 冲正：如果原状态为 ASSIGNED，扣除余额
            if order.status_before_refund == OrderStatus.ASSIGNED:
                items = json.loads(order.items_json) if order.items_json else [{"group": order.group, "amount_usd": float(order.amount_usd)}]
                for item in items:
                    ut_result = await db.execute(
                        select(UserToken).where(UserToken.user_id == order.user_id, UserToken.group == item["group"])
                    )
                    ut = ut_result.scalar_one_or_none()
                    if ut:
                        new_balance = float(ut.balance_usd) - item["amount_usd"]
                        if new_balance <= 0:
                            # 余额归零，释放 Token
                            tok_result = await db.execute(select(TokenInventory).where(TokenInventory.id == ut.token_id))
                            tok = tok_result.scalar_one_or_none()
                            if tok:
                                tok.is_assigned = False
                                tok.assigned_to = None
                                tok.assigned_at = None
                            await db.delete(ut)
                        else:
                            ut.balance_usd = new_balance

            # 调用微信退款 API
            from datetime import datetime, timezone
            import uuid
            out_refund_no = f"RF{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"
            total_fee = int(round(float(order.amount_cny) * 100))
            refund_data = {
                "out_refund_no": out_refund_no,
                "out_trade_no": out_trade_no,
                "reason": "auto approved (15min timeout)",
                "amount": {"refund": total_fee, "total": total_fee, "currency": "CNY"},
            }
            if settings.WECHAT_REFUND_NOTIFY_URL:
                refund_data["notify_url"] = settings.WECHAT_REFUND_NOTIFY_URL

            code, wx_result = await wechatpay_request("/v3/refund/domestic/refunds", method="POST", data=refund_data)
            if code != 200:
                logger.error(f"Auto-approve WeChat refund failed for {out_trade_no}: {wx_result}")
                return

            order.status = OrderStatus.REFUNDED
            order.out_refund_no = out_refund_no
            order.refunded_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info(f"Auto-approved refund for order {out_trade_no}")
        except Exception:
            await db.rollback()
            logger.exception(f"Auto-approve refund error for {out_trade_no}")


async def start_keyspace_listener():
    """监听 Redis keyspace 过期事件，触发自动退款"""
    r = get_redis()
    try:
        await r.config_set("notify-keyspace-events", "Ex")
    except Exception as e:
        logger.warning(f"Failed to set Redis keyspace config: {e}")

    pubsub = r.pubsub()
    await pubsub.psubscribe("__keyevent@0__:expired")

    logger.info("Redis keyspace listener started for refund auto-approve")

    async for message in pubsub.listen():
        if message["type"] == "pmessage":
            key = message["data"]
            if isinstance(key, str) and key.startswith("refund:auto:"):
                out_trade_no = key[len("refund:auto:"):]
                try:
                    await auto_approve_refund(out_trade_no)
                except Exception as e:
                    logger.error(f"Auto-approve refund error for {out_trade_no}: {e}")


async def recover_pending_refunds():
    """服务器启动时恢复未处理的退款（超时的立即自动退款，未超时的重新设置过期键）"""
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.token import Order, OrderStatus
    from datetime import datetime, timezone

    logger.info("Recovering pending refunds...")

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(Order).where(Order.status == OrderStatus.REFUNDING)
            )
            orders = result.scalars().all()

            now = datetime.now(timezone.utc)
            r = get_redis()

            for order in orders:
                elapsed = (now - order.refund_requested_at).total_seconds() if order.refund_requested_at else 9999
                if elapsed >= 900:
                    try:
                        await auto_approve_refund(order.out_trade_no)
                    except Exception as e:
                        logger.error(f"Recovery auto-approve error for {order.out_trade_no}: {e}")
                else:
                    remaining = int(900 - elapsed)
                    await r.setex(f"refund:auto:{order.out_trade_no}", remaining, "1")
                    logger.info(f"Recovery: set refund:auto:{order.out_trade_no} TTL={remaining}s")

            logger.info(f"Recovery complete, processed {len(orders)} pending refunds")
        except Exception:
            logger.exception("Error in recover_pending_refunds")
```

**Redis 使用场景汇总**：

| Key 模式 | TTL | 用途 |
|----------|-----|------|
| `exchange_rate_usd_cny` | 3600s (1h) | 汇率缓存 |
| `notice_content` | 180s (3min) | 通知内容缓存 |
| `refund:auto:{out_trade_no}` | 900s (15min) | 自动退款定时 |
| `reg:rate:{email}` | 60s | 注册验证码发送频率限制 |
| `reg:code:{email}` | 300s (5min) | 注册验证码 |
| `reg:attempts:{email}` | 300s | 验证码尝试次数 |
| `reg:lockout:{email}` | 900s (15min) | 验证码尝试锁定 |
| `pwd:rate:{email}` | 60s | 密码重置发送频率限制 |
| `pwd:code:{email}` | 300s | 密码重置验证码 |
| `pwd:attempts:{email}` | 300s | 密码重置尝试次数 |
| `pwd:lockout:{email}` | 900s | 密码重置锁定 |
| `tool_report:{user_id}:{tool_call_id}` | 86400s (24h) | 工具用量上报幂等 |


---

## 5.2 数据模型 (源码见项目文件)

#### 5.2.1 user.py — User + UserToken

- **User**: 用户表，id(UUID str), username, email, password_hash, account_type(normal/trial/paid), trial_expires_at, is_active
- **UserToken**: 用户Token关联表，user_id + group 唯一约束，balance_usd(Numeric 10,6), is_trial
- 关系：User.user_tokens <-> UserToken.user, User.orders <-> Order.user, User.usage_logs <-> UsageLog.user

#### 5.2.2 token.py — OrderStatus + TokenInventory + Order + UsageLog

- **OrderStatus**: 状态常量类，TRANSITIONS 字典定义合法状态转换
- **TokenInventory**: Token库存表，token_value + group 唯一约束，is_trial, is_assigned, assigned_to
- **Order**: 订单表，out_trade_no 唯一，支持多分组（group 逗号分隔），items_json JSON明细
- **UsageLog**: 用量日志表，model, usage_type, image_count, input/output/cached tokens, cost_usd

#### 5.2.3 content.py — Group + AIModel + Notice + Prompt

- **Group**: 分组表，name 唯一
- **AIModel**: 模型表，name + group 唯一约束，含计费参数和能力标记
- **Notice**: 通知表，单条记录，content + is_active
- **Prompt**: 提示词表，category + title + content

### 5.3 API 路由

#### 5.3.1 auth.py（/api/auth）

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | /register/send-code | 无 | 发送注册验证码（60s频率限制，5min有效，5次错误锁定15min） |
| POST | /register/verify | 无 | 验证码注册（创建用户+试用分配+返回JWT） |
| POST | /register | 无 | 直接注册（无验证码） |
| POST | /login | 无 | 用户登录（返回7天JWT） |
| POST | /admin/login | 无 | 管理员登录（返回12h JWT） |
| POST | /forgot-password/send-code | 无 | 发送密码重置验证码 |
| POST | /forgot-password/reset | 无 | 密码重置 |
| POST | /upgrade-trial | 用户 | 升级为试用账户（分配image试用Token+1美元余额+3天有效期） |
| GET | /me | 用户 | 获取当前用户信息+Token列表 |

#### 5.3.2 users.py（/api/users）

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | /me | 用户 | 获取用户信息 |
| GET | /me/usage | 用户 | 获取用量记录（limit/offset分页） |

#### 5.3.3 tokens.py（/api/tokens）

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | /stock | 无 | 各分组可用Token库存 |
| GET | /trial-stock | 无 | image试用Token库存 |

#### 5.3.4 payment.py（/api/pay）

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | /create_order | 用户 | 创建支付订单（微信Native二维码） |
| POST | /notify | 微信 | 微信支付回调（验签+更新状态） |
| GET | /query/{out_trade_no} | 用户 | 查询订单状态（主动查微信） |
| POST | /close/{out_trade_no} | 用户 | 关闭待支付订单 |
| POST | /refund/{out_trade_no} | 管理员 | 管理员直接退款（含冲正） |
| GET | /refund/query/{out_refund_no} | 管理员 | 查询退款状态 |
| POST | /refund/notify | 微信 | 退款回调 |
| POST | /refund_order/{out_trade_no} | 用户 | 客户端申请退款（设REFUNDING+Redis 15min TTL） |
| GET | /refund_status/{out_trade_no} | 用户 | 查询退款状态 |
| GET | /orders | 用户 | 用户订单列表 |
| GET | /packages | 无 | 套餐信息+汇率 |

订单号格式：CY{UTC时间戳}{8位UUID十六进制}  退款单号格式：RF{UTC时间戳}{8位UUID十六进制}

#### 5.3.5 notice.py（/api/notice）

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | | 无 | 获取通知（Redis缓存3分钟） |

#### 5.3.6 prompts.py（/api/prompts）

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | | 无 | 获取提示词（按分类分组） |

#### 5.3.7 models.py（/api/models）

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | | 可选 | 模型列表（含user_has_access标记） |

#### 5.3.8 usage.py（/api/usage）

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | /report/image | 用户 | 图片用量上报（per_call计费） |
| POST | /report/agent | 用户 | Agent用量上报（per_token计费） |
| POST | /report/chat | 用户 | Chat用量上报（兼容->agent） |
| POST | /report/tool | 用户 | 工具用量上报（幂等，Redis 24h TTL） |
| POST | /estimate | 用户 | 费用估算（不扣费） |
| GET | /records | 用户 | 用量记录（分页） |

计费公式：per_call: cost = price_per_call * quantity；per_token: cost = price_input*input/1K + price_output*output/1K + price_cached*cached/1K

#### 5.3.9 admin.py（/api/admin，全部需管理员认证）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /tokens/batch | 批量导入Token（自动提取sk-开头） |
| GET | /tokens/stock | 库存统计（含试用） |
| GET | /tokens/available | 可用Token列表 |
| GET/POST/PUT/DELETE | /groups | 分组CRUD |
| GET/PUT | /notice | 通知管理（更新时清除Redis缓存） |
| GET/POST/PUT/DELETE | /prompts | 提示词CRUD |
| GET/POST/PUT/DELETE | /models | 模型CRUD |
| GET/GET/PUT/DELETE | /users | 用户管理（含Token/用量详情） |
| POST | /users/{id}/tokens | 添加/更新用户Token |
| PUT | /users/{id}/tokens/{group}/balance | 更新余额 |
| DELETE | /users/{id}/tokens/{group} | 删除用户Token |
| GET | /orders | 订单列表（含用户名、Token值） |
| POST | /orders/{id}/assign | 分配Token+充值余额 |
| POST | /orders/{id}/close | 关闭订单 |
| POST | /orders/{id}/refund/approve | 批准退款（冲正+微信退款API） |
| POST | /orders/{id}/refund/reject | 拒绝退款（恢复原状态） |
| PUT/DELETE | /orders/{id} | 更新/删除订单 |
| POST | /orders/create | 创建订单（管理员，含二维码） |
| GET | /orders/query_pay/{out_trade_no} | 查询支付状态 |
| GET/PUT | /config | .env配置编辑（6分类，敏感字段遮蔽） |
| POST | /config/restart | Docker容器重启 |
| PUT | /password | 修改管理员密码（内存，重启失效） |

管理员配置编辑器6个分类：数据库、认证与安全、微信支付、邮件服务、支付限额、服务器


---

## 6. 前端架构与源码

### 6.1 main.js

```javascript
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import naive from 'naive-ui'
import App from './App.vue'
import router from './router'

createApp(App).use(createPinia()).use(router).use(naive).mount('#app')
```

### 6.2 App.vue — 暗色主题配置

Naive UI darkTheme 配置：主色调 #00d4aa，字体 DM Sans/Space Mono，Card背景 #1e1e2e

全局 CSS 变量：--cy-bg: #16161e, --cy-bg-elevated: #1e1e2e, --cy-accent: #00d4aa, --cy-text: #e4e4ef

### 6.3 router.js

Hash路由模式(createWebHashHistory)，9个子路由，路由守卫检查 localStorage.admin_token

### 6.4 http.js

Axios HTTP客户端，请求拦截器注入 admin_token，401响应自动清除token并跳转 /admin/

### 6.5 time.js

formatTime(): 后端UTC时间转UTC+8显示；getTodayChina(): 获取中国时区今日日期

### 6.6 视图组件概览

| 组件 | 功能 | 关键交互 |
|------|------|---------|
| Login.vue | 管理员登录 | 动画背景、表单提交到 /api/auth/admin/login |
| Layout.vue | 侧边栏导航 | SVG图标菜单（9项）、退出登录 |
| Dashboard.vue | 仪表盘 | 5个统计卡片（用户总数、今日订单、3类Token库存） |
| Tokens.vue | 试用Token管理 | 批量录入（粘贴sk-xxx列表）、image试用库存显示 |
| Groups.vue | 分组CRUD | 名称、描述、排序编辑，删除前检查关联模型/Token |
| Models.vue | 模型CRUD | 计费参数配置(per_call/per_token)、能力标记、分组筛选 |
| Orders.vue | 订单管理 | 创建/查看/分配/退款/关闭、二维码支付(qrcode库)、退款15分钟倒计时 |
| Users.vue | 用户管理 | 查看/编辑/Token管理/余额编辑、Token复制、用量查看 |
| Notice.vue | 通知编辑 | 内容编辑、推送提示（客户端3分钟轮询） |
| Prompts.vue | 提示词管理 | 按分类管理(10个分类)、CRUD |
| Settings.vue | 系统配置 | 6分类配置编辑、Docker重启+健康检查轮询(15次*2s) |


---

## 7. 配置与部署

### 7.1 docker-compose.yml — 4个服务

1. **postgres** — PostgreSQL 16 Alpine，健康检查 pg_isready，数据卷 pgdata
2. **redis** — Redis 7 Alpine，健康检查 redis-cli ping，数据卷 redisdata
3. **backend** — 多阶段构建（Node 20构建前端 -> Python 3.12运行后端）
   - 环境变量：DATABASE_URL, REDIS_URL（从.env和docker-compose环境注入）
   - 挂载：certs/(只读), .env(读写), docker.sock(容器重启)
   - 依赖：postgres + redis 健康检查通过
4. **nginx** — Nginx Alpine 反向代理，监听80端口
   - 挂载：nginx.conf(只读)
   - 依赖：backend

### 7.2 Dockerfile — 多阶段构建

第一阶段(Node 20 Alpine)：安装前端依赖 -> npm run build
第二阶段(Python 3.12 slim)：安装Python依赖 -> 复制后端代码 -> 复制前端dist到/app/static -> CMD uvicorn

pip使用腾讯镜像源加速安装。

### 7.3 nginx.conf — 反向代理配置

路由规则：
- /admin/ -> 代理到backend（FastAPI服务前端静态文件）
- /api/api/ -> 重写为/api/（兼容双重前缀）
- /api/ -> 代理到backend
- /(auth|users|tokens|pay|notice|prompts|models|usage)/ -> 重写为/api/前缀（客户端兼容）
- /health -> 代理健康检查
- / -> 301重定向到/admin/

gzip启用，client_max_body_size 20m，proxy_read_timeout 120s

### 7.4 requirements.txt

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
sqlalchemy==2.0.35
alembic==1.13.3
asyncpg==0.29.0
psycopg2-binary==2.9.9
redis==5.1.0
pydantic==2.9.2
pydantic-settings==2.5.2
email-validator==2.2.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
bcrypt<5
python-multipart==0.0.12
httpx==0.27.2
aiohttp==3.10.8
aiofiles==24.1.0
cryptography==43.0.1
wechatpayv3==2.0.2
aiosmtplib==3.0.2
docker==7.0.0
```

### 7.5 frontend/package.json

```json
{
  "name": "cyimage-admin",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "@vicons/ionicons5": "^0.12.0",
    "axios": "^1.7.0",
    "naive-ui": "^2.39.0",
    "pinia": "^2.2.0",
    "qrcode": "^1.5.4",
    "vue": "^3.5.0",
    "vue-router": "^4.4.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.1.0",
    "vite": "^5.4.0"
  }
}
```

### 7.6 vite.config.js

```javascript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  base: '/admin/',
  build: { outDir: 'dist' },
  server: { proxy: { '/api': 'http://localhost:8000' } }
})
```

### 7.7 .env.example

```
POSTGRES_DB=cyimage
POSTGRES_USER=cyimage
POSTGRES_PASSWORD=change-me

SECRET_KEY=change-me

ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-me

WECHAT_MCHID=
WECHAT_APPID=
WECHAT_APIV3_KEY=
WECHAT_CERT_SERIAL_NO=
WECHAT_PRIVATE_KEY_PATH=/app/certs/apiclient_key.pem
WECHAT_PUBLIC_KEY_PATH=/app/certs/wechatpay_public_key.pem
WECHAT_PUBLIC_KEY_ID=

WECHAT_NOTIFY_URL=https://www.zjcypc.com/api/pay/notify
WECHAT_REFUND_NOTIFY_URL=https://www.zjcypc.com/api/pay/refund/notify
SERVER_BASE_URL=https://www.zjcypc.com

SMTP_HOST=
SMTP_PORT=465
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM_NAME=CyImagePro
SMTP_USE_SSL=true

PAYMENT_MIN_TOTAL_USD=1.0
PAYMENT_MAX_TOTAL_USD=1000.0
PAYMENT_MIN_PER_ITEM_USD=0.01
```

### 7.8 deploy.sh

```bash
#!/usr/bin/env bash
set -euo pipefail

cd /opt/GPT_Image_2_service

git pull

sudo docker compose build backend
sudo docker compose up -d
sudo docker compose restart nginx

sudo docker compose ps
```

### 7.9 init_data.py — 独立种子脚本

安全种子脚本，仅插入不存在的数据：
1. 创建所有表（Base.metadata.create_all）
2. 迁移新列（_ensure_columns）
3. 插入默认分组（image, agent, postprocess）
4. 插入默认模型（13个）
5. 用法：cd backend && python init_data.py


---

## 8. API 接口文档

### 8.1 公开端点（无需认证）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/ | API索引 |
| GET | /health | 健康检查 |
| GET | /api/tokens/stock | 各分组Token库存 |
| GET | /api/tokens/trial-stock | image试用Token库存 |
| GET | /api/notice | 获取通知 |
| GET | /api/prompts | 获取提示词库 |
| GET | /api/models | 模型列表（可选认证，含访问权限） |
| GET | /api/pay/packages | 套餐信息+汇率 |
| POST | /api/auth/register/send-code | 发送注册验证码 |
| POST | /api/auth/register/verify | 验证码注册 |
| POST | /api/auth/register | 直接注册 |
| POST | /api/auth/login | 用户登录 |
| POST | /api/auth/admin/login | 管理员登录 |
| POST | /api/auth/forgot-password/send-code | 发送密码重置验证码 |
| POST | /api/auth/forgot-password/reset | 密码重置 |
| POST | /api/pay/notify | 微信支付回调 |
| POST | /api/pay/refund/notify | 退款回调 |

### 8.2 用户端点（需 Bearer Token）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/auth/me | 当前用户信息 |
| POST | /api/auth/upgrade-trial | 升级试用 |
| GET | /api/users/me | 用户信息 |
| GET | /api/users/me/usage | 用户用量 |
| POST | /api/pay/create_order | 创建支付订单 |
| GET | /api/pay/query/{out_trade_no} | 查询订单 |
| POST | /api/pay/close/{out_trade_no} | 关闭订单 |
| POST | /api/pay/refund_order/{out_trade_no} | 申请退款 |
| GET | /api/pay/refund_status/{out_trade_no} | 退款状态 |
| GET | /api/pay/orders | 用户订单列表 |
| POST | /api/usage/report/image | 图片用量上报 |
| POST | /api/usage/report/agent | Agent用量上报 |
| POST | /api/usage/report/chat | Chat用量上报 |
| POST | /api/usage/report/tool | 工具用量上报 |
| POST | /api/usage/estimate | 费用估算 |
| GET | /api/usage/records | 用量记录 |

### 8.3 管理员端点（需 Admin Bearer Token）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/admin/tokens/batch | 批量导入Token |
| GET | /api/admin/tokens/stock | 库存统计 |
| GET | /api/admin/tokens/available | 可用Token列表 |
| GET | /api/admin/groups | 分组列表 |
| POST | /api/admin/groups | 创建分组 |
| PUT | /api/admin/groups/{id} | 更新分组 |
| DELETE | /api/admin/groups/{id} | 删除分组 |
| PUT | /api/admin/notice | 更新通知 |
| GET | /api/admin/notice | 获取通知 |
| GET | /api/admin/prompts | 提示词列表 |
| POST | /api/admin/prompts | 创建提示词 |
| PUT | /api/admin/prompts/{id} | 更新提示词 |
| DELETE | /api/admin/prompts/{id} | 删除提示词 |
| GET | /api/admin/models | 模型列表 |
| POST | /api/admin/models | 创建模型 |
| PUT | /api/admin/models/{id} | 更新模型 |
| DELETE | /api/admin/models/{id} | 删除模型 |
| GET | /api/admin/users | 用户列表 |
| GET | /api/admin/users/{id} | 用户详情 |
| PUT | /api/admin/users/{id} | 更新用户 |
| DELETE | /api/admin/users/{id} | 删除用户 |
| POST | /api/admin/users/{id}/tokens | 管理UserToken |
| PUT | /api/admin/users/{id}/tokens/{group}/balance | 更新余额 |
| DELETE | /api/admin/users/{id}/tokens/{group} | 删除UserToken |
| GET | /api/admin/orders | 订单列表 |
| POST | /api/admin/orders/create | 创建订单 |
| GET | /api/admin/orders/query_pay/{out_trade_no} | 查询支付状态 |
| POST | /api/admin/orders/{id}/assign | 分配Token |
| POST | /api/admin/orders/{id}/close | 关闭订单 |
| POST | /api/admin/orders/{id}/refund/approve | 批准退款 |
| POST | /api/admin/orders/{id}/refund/reject | 拒绝退款 |
| PUT | /api/admin/orders/{id} | 更新订单 |
| DELETE | /api/admin/orders/{id} | 删除订单 |
| POST | /api/pay/refund/{out_trade_no} | 管理员直接退款 |
| GET | /api/pay/refund/query/{out_refund_no} | 退款查询 |
| GET | /api/admin/config | 获取.env配置 |
| PUT | /api/admin/config | 更新.env配置 |
| POST | /api/admin/config/restart | 重启后端容器 |
| PUT | /api/admin/password | 修改管理员密码 |


---

## 9. 业务流程

### 9.1 注册流程

1. 用户填写 username/email/password/account_type
2. 直接注册(POST /api/auth/register)：创建用户 -> 试用账户分配image Token -> 返回JWT
3. 验证码注册：
   a. POST /api/auth/register/send-code：60秒频率限制 -> 生成6位验证码 -> Redis(5min TTL) -> 发送邮件
   b. POST /api/auth/register/verify：验证码校验(5次错误锁定15min) -> 创建用户 -> 试用分配 -> 返回JWT

### 9.2 支付流程

1. 用户选择分组和金额 -> POST /api/pay/create_order
2. 验证金额范围(1美元~1000美元) -> 获取汇率(Redis缓存1h/API获取) -> 计算人民币金额
3. 创建Order(status=pending) -> 调用微信支付Native下单 -> 返回code_url(二维码链接)
4. 用户扫码支付 -> 微信回调POST /api/pay/notify -> 验签 -> 更新Order status=paid -> 更新User account_type=paid
5. 管理员分配Token POST /api/admin/orders/{id}/assign -> 解析items_json -> 每个分组增加余额/创建UserToken -> 更新Order status=assigned

### 9.3 退款流程

1. 客户端申请退款 POST /api/pay/refund_order/{out_trade_no}
   - 保存status_before_refund -> 设置status=REFUNDING -> 设置Redis key refund:auto:{out_trade_no} TTL=900s
2. 三种后续路径：
   a. 管理员批准 POST /api/admin/orders/{id}/refund/approve：冲正(若原ASSIGNED则扣除余额/撤销Token) -> 调用微信退款API -> 清除Redis自动退款Key -> 更新status=REFUNDED
   b. 管理员拒绝 POST /api/admin/orders/{id}/refund/reject：恢复到status_before_refund -> 清除Redis Key
   c. 15分钟超时：Redis keyspace expired事件 -> auto_approve_refund()：同批准逻辑
3. 启动恢复：recover_pending_refunds()处理所有REFUNDING订单（超时立即退款，未超时重设Redis Key）

### 9.4 用量计费流程

1. 客户端上报用量(图片/Agent/工具)
2. 查找模型配置 + 用户Token
3. 计算费用：
   - per_call: cost = price_per_call * quantity
   - per_token: cost = price_input*input_tokens/1K + price_output*output_tokens/1K + price_cached*cached_tokens/1K
4. 工具上报幂等检查(Redis tool_report:{user_id}:{tool_call_id} 24h TTL)
5. 检查余额 -> 余额不足返回402 -> 余额充足扣除余额 + 记录UsageLog
6. 返回费用 + 剩余余额

### 9.5 PackyAPI价格同步流程

1. 后台任务start_price_sync_loop()每隔60分钟执行
2. GET PackyAPI pricing URL
3. 遍历模型列表，过滤SYNCED_MODELS + 支持openai endpoint
4. per_token模型：PackyAPI价格(每1M tokens) / 1000 * 1.15 = 每1K tokens价格
5. per_call模型：model_price * 1.15 = 每次调用价格
6. 更新AIModel表对应记录

---

## 10. 环境变量说明

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| DATABASE_URL | postgresql+asyncpg://cyimage:cyimage123@postgres:5432/cyimage | PostgreSQL连接串 |
| REDIS_URL | redis://redis:6379/0 | Redis连接串 |
| SECRET_KEY | change-this-secret-key-in-production | JWT签名密钥 |
| ALGORITHM | HS256 | JWT算法 |
| ACCESS_TOKEN_EXPIRE_MINUTES | 10080 (7天) | 用户Token有效期(分钟) |
| ADMIN_USERNAME | admin | 管理员用户名 |
| ADMIN_PASSWORD | admin123 | 管理员密码 |
| WECHAT_MCHID | - | 微信支付商户号 |
| WECHAT_APPID | - | 微信应用ID |
| WECHAT_APIV3_KEY | - | 微信APIv3密钥 |
| WECHAT_CERT_SERIAL_NO | - | 微信证书序列号 |
| WECHAT_PRIVATE_KEY_PATH | /app/certs/apiclient_key.pem | 微信私钥路径 |
| WECHAT_NOTIFY_URL | - | 微信支付回调URL |
| WECHAT_REFUND_NOTIFY_URL | - | 微信退款回调URL |
| WECHAT_PUBLIC_KEY_PATH | - | 微信公钥路径 |
| WECHAT_PUBLIC_KEY_ID | - | 微信公钥ID |
| SERVER_BASE_URL | https://www.zjcypc.com | 服务器地址 |
| SMTP_HOST | - | SMTP服务器地址 |
| SMTP_PORT | 465 | SMTP端口 |
| SMTP_USER | - | SMTP用户名 |
| SMTP_PASSWORD | - | SMTP密码 |
| SMTP_FROM_NAME | CyImagePro | 发件人名称 |
| SMTP_USE_SSL | true | 是否使用SSL |
| PAYMENT_MIN_TOTAL_USD | 1.0 | 最低总金额(美元) |
| PAYMENT_MAX_TOTAL_USD | 1000.0 | 最高总金额(美元) |
| PAYMENT_MIN_PER_ITEM_USD | 0.01 | 单项最低金额(美元) |
| EXCHANGE_RATE_API | https://open.er-api.com/v6/latest/USD | 汇率API |
| PACKYAPI_PRICING_URL | https://www.packyapi.com/api/pricing | PackyAPI定价URL |
| PACKYAPI_SYNC_INTERVAL_MINUTES | 60 | 价格同步间隔(分钟) |
| PACKYAPI_MARKUP_PERCENT | 15.0 | 加价百分比 |
| POSTGRES_DB | cyimage | PostgreSQL数据库名(Docker) |
| POSTGRES_USER | cyimage | PostgreSQL用户名(Docker) |
| POSTGRES_PASSWORD | changeme | PostgreSQL密码(Docker) |

---

## 默认模型与定价

| 模型 | 供应商 | 分组 | 计费 | 输入$/1K | 输出$/1K | 缓存$/1K | 单次$ | 试用 |
|------|--------|------|------|----------|----------|----------|-------|------|
| gpt-image-2 | OpenAI | image | per_call | - | - | - | 0.046 | 是 |
| qwen3.5-flash | Alibaba | agent | per_token | 0.000115 | 0.001150 | 0.0000115 | - | 否 |
| qwen3.5-plus | Alibaba | agent | per_token | 0.00046 | 0.00276 | 0.000046 | - | 否 |
| qwen3.6-plus | Alibaba | agent | per_token | 0.00115 | 0.0069 | 0.000115 | - | 否 |
| qwen-max | Alibaba | agent | per_token | 0.001438 | 0.00575 | 0.000288 | - | 否 |
| deepseek-v4-flash | DeepSeek | agent | per_token | 0.000575 | 0.00115 | 0.0000115 | - | 否 |
| deepseek-v4-pro | DeepSeek | agent | per_token | 0.0069 | 0.0138 | 0.0000575 | - | 否 |
| glm-5 | Zhipu | agent | per_token | 0.0023 | 0.01035 | 0.00046 | - | 否 |
| kimi-k2.5 | Moonshot | agent | per_token | 0.0023 | 0.012075 | 0.0004025 | - | 否 |
| gpt-5.4-mini | OpenAI | agent | per_token | 0.000431 | 0.002588 | 0.0000431 | - | 否 |
| gpt-5.4 | OpenAI | agent | per_token | 0.001438 | 0.008625 | 0.0001438 | - | 否 |
| claude-sonnet-4-6 | Anthropic | agent | per_token | 0.001725 | 0.008625 | 0.0001725 | - | 否 |
| remove_bg | Internal | postprocess | per_call | - | - | - | 0.010 | 否 |

> 注意：以上价格为初始种子数据。PackyAPI后台任务会定期同步并加价15%，实际价格以数据库为准。

---

## 部署步骤

1. 克隆项目到服务器 /opt/GPT_Image_2_service
2. 复制 .env.example 为 .env，填写所有配置项
3. 将微信支付证书放入 certs/ 目录
4. 运行 docker compose up -d --build
5. 默认管理员：admin / admin123（首次登录后请修改）
6. 后续更新：运行 bash deploy.sh

---

*文档结束*
