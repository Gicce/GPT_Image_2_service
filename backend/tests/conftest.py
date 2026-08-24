"""pytest 公共配置：真实 PostgreSQL/Redis 环境搭建。

在本机 PostgreSQL 17（127.0.0.1:5432, postgres/postgres）上创建独立测试库，
每个测试会话重建 schema（create_all + ensure + v4 migration + seed）。
"""

import asyncio
import os
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

TEST_DB = "cyimage_v4_test"
PG_DSN = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432"

os.environ["DATABASE_URL"] = f"{PG_DSN}/{TEST_DB}"
os.environ["REDIS_URL"] = "redis://127.0.0.1:6379/15"
os.environ["APP_ENV"] = "development"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin123"

import psycopg2


def _recreate_db(dbname: str) -> None:
    conn = psycopg2.connect(host="127.0.0.1", port=5432, user="postgres", password="postgres")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {dbname} WITH (FORCE)")
    cur.execute(f"CREATE DATABASE {dbname}")
    cur.close()
    conn.close()


# 防重入：pytest 以 `conftest` 加载本文件，测试模块又可能以 `tests.conftest` 二次加载，
# 若不加以区分，模块级的 _recreate_db 会在会话中途把刚建好的测试库整库删掉。
if os.environ.get("CY_TEST_DB_READY") != "1":
    os.environ["CY_TEST_DB_READY"] = "1"
    _recreate_db(TEST_DB)

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import engine, Base, AsyncSessionLocal
from app.main import (
    _ensure_columns, _ensure_indexes, _migrate_v4_single_model,
    _migrate_v4_shared_token_refund, _migrate_admin_accounts, seed_defaults,
)
from app.models.user import User
from app.models.content import AIModel
from app.core.security import hash_password, create_admin_token

# 测试管理员：固定 id/用户名，token 由 make_admin_headers() 构造，
# DB 行由 clean_tables 每个测试前重建（get_admin_user 会查库校验）
TEST_ADMIN_ID = "00000000-0000-0000-0000-0000000000aa"
TEST_ADMIN_USERNAME = "admin"
TEST_ADMIN_LOGIN_PASSWORD = "admin-test-password"


def make_admin_headers(role: str = "super_admin", admin_id: str = TEST_ADMIN_ID,
                       username: str = TEST_ADMIN_USERNAME) -> dict:
    return {"Authorization": f"Bearer {create_admin_token(admin_id, username, role)}"}


@pytest.fixture(scope="session", autouse=True)
async def init_backend():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_columns(conn)
        await _ensure_indexes(conn)
        await _migrate_v4_single_model(conn)
        await _migrate_v4_shared_token_refund(conn)
        await _migrate_admin_accounts(conn)
    await seed_defaults()
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean_tables(init_backend):
    """每个测试前清空业务表并重置 Image2 配置。"""
    async with AsyncSessionLocal() as session:
        for table in [
            # client_devices 有指向 users 的 FK，必须先于 users 删除
            "client_devices",
            "billing_transactions", "admin_audit_logs", "usage_logs", "refund_requests",
            "orders", "runtime_token_assignments", "token_assignment_logs",
            "token_inventory", "users", "ai_models", "admin_users",
            # V4.2 新表（user_id 为普通字符串列，无 FK，顺序不敏感）
            "trial_claims", "cost_margin_ledger", "pricing_rules", "system_config",
        ]:
            await session.execute(text(f"DELETE FROM {table}"))
        await session.execute(text(
            "INSERT INTO ai_models (id, name, display_name, provider, billing_type, "
            "is_enabled, trial_allowed, price_per_call, currency) "
            "VALUES ('m-image2', 'gpt-image-2', 'Image2', 'OpenAI', 'per_call', true, true, 0.070000, 'USD')"
        ))
        await session.execute(text(
            "INSERT INTO admin_users (id, username, display_name, password_hash, role, "
            "is_active, must_change_password, created_at, updated_at) "
            "VALUES (:id, :username, 'Test Admin', :pw, 'super_admin', true, false, now(), now())"
        ), {"id": TEST_ADMIN_ID, "username": TEST_ADMIN_USERNAME,
            "pw": hash_password(TEST_ADMIN_LOGIN_PASSWORD)})
        await session.commit()

    # 清理登录限流与在线设备相关 Redis key，避免测试间串扰
    from app.core.redis import get_redis
    redis = get_redis()
    for pattern in ("adminlogin:*", "userlogin:*", "online_device:*", "billing_quote:*"):
        async for key in redis.scan_iter(match=pattern):
            await redis.delete(key)
    yield


# 测试环境 legacy 兑换率（system_config 缺省同值）
TEST_LEGACY_RATE = 700


async def make_user(username: str = "u1", balance: str = "0", trial: str = "0") -> User:
    """构造用户：USD 参数按 legacy 率折算为点数（业务真相），镜像同步回写。"""
    async with AsyncSessionLocal() as session:
        paid = int((Decimal(balance) * Decimal(TEST_LEGACY_RATE)).to_integral_value())
        trial_cr = int((Decimal(trial) * Decimal(TEST_LEGACY_RATE)).to_integral_value())
        user = User(
            username=username,
            email=f"{username}@test.local",
            password_hash=hash_password("x"),
            paid_credits=paid,
            trial_credits=trial_cr,
            balance_usd=Decimal(paid) / Decimal(TEST_LEGACY_RATE),
            trial_credit_usd=Decimal(trial_cr) / Decimal(TEST_LEGACY_RATE),
        )
        session.add(user)
        await session.commit()
        return user


async def get_user(user_id: str) -> User:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT balance_usd, trial_credit_usd FROM users WHERE id = :id"), {"id": user_id}
        )
        row = result.one()
        return row
