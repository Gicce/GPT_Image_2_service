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
    _migrate_v4_shared_token_refund, seed_defaults,
)
from app.models.user import User
from app.models.content import AIModel
from app.core.security import hash_password


@pytest.fixture(scope="session", autouse=True)
async def init_backend():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_columns(conn)
        await _ensure_indexes(conn)
        await _migrate_v4_single_model(conn)
        await _migrate_v4_shared_token_refund(conn)
    await seed_defaults()
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean_tables(init_backend):
    """每个测试前清空业务表并重置 Image2 配置。"""
    async with AsyncSessionLocal() as session:
        for table in [
            "billing_transactions", "admin_audit_logs", "usage_logs", "refund_requests",
            "orders", "runtime_token_assignments", "token_assignment_logs",
            "token_inventory", "users", "ai_models",
        ]:
            await session.execute(text(f"DELETE FROM {table}"))
        await session.execute(text(
            "INSERT INTO ai_models (id, name, display_name, provider, billing_type, "
            "is_enabled, trial_allowed, price_per_call, currency) "
            "VALUES ('m-image2', 'gpt-image-2', 'Image2', 'OpenAI', 'per_call', true, true, 0.070000, 'USD')"
        ))
        await session.commit()
    yield


async def make_user(username: str = "u1", balance: str = "0", trial: str = "0") -> User:
    async with AsyncSessionLocal() as session:
        user = User(
            username=username,
            email=f"{username}@test.local",
            password_hash=hash_password("x"),
            balance_usd=Decimal(balance),
            trial_credit_usd=Decimal(trial),
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
