"""v1.0.0 数据库结构升级验证：旧结构 → _ensure_columns 幂等补列 + 历史数据保留。

新建空库测试（conftest create_all 全新表）不能替代升级验证——本文件模拟
v4.2.3 生产库（users 缺 v1.0.0 六列），跑生产同一条 _ensure_columns 路径，
验证：列补齐、存量行数据保留、重复执行幂等（不炸不丢）。
隔离边界：cyimage_v4_test 测试库，无生产连接。
"""

import uuid

import pytest
from sqlalchemy import text

from app.core.database import engine
from app.main import _ensure_columns

# v1.0.0 在 users 上新增的列（见 main.py _ensure_columns）
V100_USER_COLUMNS = [
    "password_changed_at", "token_version",
    "purged_at", "purged_by", "purge_reason",
]


async def _column_names(conn, table: str) -> set[str]:
    rows = await conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = :t"
    ), {"t": table})
    return {r[0] for r in rows}


@pytest.fixture
async def legacy_users_row():
    """造一行 v4.2.3 口径的存量用户，并 DROP 掉 v1.0.0 列模拟旧结构。"""
    user_id = str(uuid.uuid4())
    async with engine.begin() as conn:
        # 先 DROP（IF EXISTS 兼容全新环境），模拟未升级库
        for col in V100_USER_COLUMNS:
            await conn.execute(text(f"ALTER TABLE users DROP COLUMN IF EXISTS {col}"))
        # 存量数据：v4.2.3 口径（余额/点数列存在，v1.0.0 列不存在）
        await conn.execute(text(
            "INSERT INTO users (id, username, email, password_hash, account_type, "
            "is_active, balance_usd, trial_credit_usd, paid_credits, trial_credits, "
            "gift_credits, created_at) "
            "VALUES (:id, :u, :e, 'legacy-hash', 'normal', true, 0.428571, 0.214286, 300, 150, 50, now())"
        ), {"id": user_id, "u": f"legacy-{uuid.uuid4().hex[:8]}",
            "e": f"legacy-{uuid.uuid4().hex[:8]}@example.com"})
    yield user_id
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


async def test_ensure_columns_upgrades_legacy_schema_and_keeps_data(legacy_users_row):
    user_id = legacy_users_row

    # 升级前：v1.0.0 列不存在，存量数据在
    async with engine.connect() as conn:
        cols = await _column_names(conn, "users")
        assert not (set(V100_USER_COLUMNS) & cols)
        before = (await conn.execute(text(
            "SELECT username, paid_credits, trial_credits, gift_credits "
            "FROM users WHERE id = :id"
        ), {"id": user_id})).one()

    # 第一次执行 _ensure_columns（生产启动同一路径）
    async with engine.begin() as conn:
        await _ensure_columns(conn)

    async with engine.connect() as conn:
        cols = await _column_names(conn, "users")
        assert set(V100_USER_COLUMNS) <= cols, f"缺列: {set(V100_USER_COLUMNS) - cols}"
        after = (await conn.execute(text(
            "SELECT username, paid_credits, trial_credits, gift_credits, "
            "token_version FROM users WHERE id = :id"
        ), {"id": user_id})).one()
        # 历史数据完整保留；新列按 _ensure_columns 声明的 DEFAULT 生效
        assert (after.username, after.paid_credits, after.trial_credits, after.gift_credits) == \
            (before.username, before.paid_credits, before.trial_credits, before.gift_credits)
        assert after.token_version == 0  # INTEGER NOT NULL DEFAULT 0：旧 token 视为 tv=0
        # timestamp 列默认 NULL = 未记录（接口不编造时间）
        nulls = (await conn.execute(text(
            "SELECT password_changed_at IS NULL, purged_at IS NULL FROM users WHERE id = :id"
        ), {"id": user_id})).one()
        assert nulls == (True, True)

    # 重复执行幂等：列已存在时 ALTER 分支不触发，不抛错不丢数据
    async with engine.begin() as conn:
        await _ensure_columns(conn)
        await _ensure_columns(conn)  # 连续两次，覆盖启动重叠场景
    async with engine.connect() as conn:
        row = (await conn.execute(text(
            "SELECT paid_credits, token_version FROM users WHERE id = :id"
        ), {"id": user_id})).one()
        assert (row.paid_credits, row.token_version) == (300, 0)


async def test_ensure_columns_is_safe_for_fresh_schema():
    """全新结构（create_all 已含新列）下执行 _ensure_columns：无操作不报错。"""
    async with engine.begin() as conn:
        await _ensure_columns(conn)
    async with engine.connect() as conn:
        cols = await _column_names(conn, "users")
        assert set(V100_USER_COLUMNS) <= cols
