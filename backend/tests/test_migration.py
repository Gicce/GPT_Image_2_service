"""V4 启动迁移测试（独立 legacy 库）：分组余额 → 统一余额、单模型收敛、历史数据保留。"""

import asyncio
import os
import sys
from decimal import Decimal

import psycopg2
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

PG = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432"
LEGACY_DB = "cyimage_v4_legacy"

LEGACY_DDL = [
    """CREATE TABLE users (
        id VARCHAR(36) PRIMARY KEY, username VARCHAR(64) UNIQUE NOT NULL,
        email VARCHAR(128) UNIQUE NOT NULL, password_hash VARCHAR(256) NOT NULL,
        account_type VARCHAR(16) DEFAULT 'normal', trial_expires_at TIMESTAMPTZ,
        is_active BOOLEAN DEFAULT TRUE, created_at TIMESTAMPTZ DEFAULT now())""",
    """CREATE TABLE groups (
        id VARCHAR(36) PRIMARY KEY, name VARCHAR(32) UNIQUE NOT NULL,
        description VARCHAR(128) DEFAULT '', sort_order INTEGER DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT now())""",
    """CREATE TABLE prompts (
        id VARCHAR(36) PRIMARY KEY, category VARCHAR(64) NOT NULL, title VARCHAR(128) NOT NULL,
        content TEXT NOT NULL, sort_order INTEGER DEFAULT 0, is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT now())""",
    """CREATE TABLE notices (
        id VARCHAR(36) PRIMARY KEY, content TEXT NOT NULL, is_active BOOLEAN DEFAULT TRUE,
        updated_at TIMESTAMPTZ DEFAULT now())""",
    """CREATE TABLE token_inventory (
        id VARCHAR(36) PRIMARY KEY, token_value VARCHAR(512) NOT NULL,
        "group" VARCHAR(32) NOT NULL, is_trial BOOLEAN DEFAULT FALSE,
        is_assigned BOOLEAN DEFAULT FALSE, assigned_to VARCHAR(36), assigned_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT now(), CONSTRAINT uq_token_value_group UNIQUE (token_value, "group"))""",
    """CREATE TABLE ai_models (
        id VARCHAR(36) PRIMARY KEY, name VARCHAR(64) NOT NULL, display_name VARCHAR(128) NOT NULL,
        provider VARCHAR(32) DEFAULT 'OpenAI', billing_type VARCHAR(16) NOT NULL,
        model_type VARCHAR(16) NOT NULL, "group" VARCHAR(32) NOT NULL,
        is_enabled BOOLEAN DEFAULT TRUE, trial_allowed BOOLEAN DEFAULT FALSE,
        price_input VARCHAR(32), price_output VARCHAR(32), price_cached VARCHAR(32),
        price_per_call VARCHAR(32), sort_order INTEGER DEFAULT 0,
        context_window INTEGER DEFAULT 32768, supports_tools BOOLEAN DEFAULT FALSE,
        supports_vision BOOLEAN DEFAULT FALSE, CONSTRAINT uq_model_group UNIQUE (name, "group"))""",
    """CREATE TABLE user_tokens (
        id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL REFERENCES users(id),
        token_id VARCHAR(36) NOT NULL REFERENCES token_inventory(id),
        "group" VARCHAR(32) NOT NULL, balance_usd NUMERIC(10,6) DEFAULT 0.0,
        is_trial BOOLEAN DEFAULT FALSE, created_at TIMESTAMPTZ DEFAULT now(),
        CONSTRAINT uq_user_group UNIQUE (user_id, "group"))""",
    """CREATE TABLE orders (
        id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL REFERENCES users(id),
        out_trade_no VARCHAR(64) UNIQUE NOT NULL, trade_no VARCHAR(64),
        "group" VARCHAR(128) NOT NULL, amount_usd NUMERIC(10,2) NOT NULL,
        amount_cny NUMERIC(10,2) NOT NULL, exchange_rate NUMERIC(10,4) NOT NULL,
        items_json TEXT, pay_type VARCHAR(16), status VARCHAR(16) DEFAULT 'pending',
        out_refund_no VARCHAR(64), token_id VARCHAR(36), created_at TIMESTAMPTZ DEFAULT now(),
        paid_at TIMESTAMPTZ, refunded_at TIMESTAMPTZ, refund_requested_at TIMESTAMPTZ,
        status_before_refund VARCHAR(16))""",
    # 真实 V3 旧库形态：usage_logs 无 unit_price / request_id（回归守卫：
    # 曾因 fixture 误含 unit_price 掩盖 _ensure_columns 遗漏，导致生产 UndefinedColumnError）
    """CREATE TABLE usage_logs (
        id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL REFERENCES users(id),
        model VARCHAR(64) NOT NULL, usage_type VARCHAR(16) NOT NULL,
        image_count INTEGER DEFAULT 0, input_tokens INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0, cached_tokens INTEGER DEFAULT 0,
        cost_usd NUMERIC(10,6) NOT NULL,
        created_at TIMESTAMPTZ DEFAULT now())""",
]

LEGACY_DATA = [
    "INSERT INTO groups (id, name, description, sort_order) VALUES ('g1','image','图片生成组',1),('g2','agent','Agent 对话组',2)",
    "INSERT INTO prompts (id, category, title, content) VALUES ('p1','电商详情图','旧提示词','内容保留')",
    "INSERT INTO token_inventory (id, token_value, \"group\", is_trial, is_assigned, assigned_to, assigned_at) VALUES "
    "('ti1','sk-trial-001','image',true,true,'U2',now()),('ti2','sk-norm-001','image',false,true,'U4',now()),"
    "('ti3','sk-norm-002','image',false,false,NULL,NULL)",
    "INSERT INTO ai_models (id, name, display_name, provider, billing_type, model_type, \"group\", trial_allowed, price_per_call) VALUES "
    "('am1','gpt-image-2','GPT Image 2','OpenAI','per_call','image','image',true,'0.046'),"
    "('am2','qwen3.5-flash','Qwen','Alibaba','per_token','agent','agent',false,null),"
    "('am3','glm-5','GLM','Zhipu','per_token','agent','agent',false,null)",
    # U1：纯 agent 现金余额 3.00
    "INSERT INTO users (id, username, email, password_hash, account_type) VALUES "
    "('U1','u1','u1@x.com','h','paid'),('U2','u2','u2@x.com','h','trial'),"
    "('U3','u3','u3@x.com','h','trial'),('U4','u4','u4@x.com','h','paid'),"
    "('U5','u5','u5@x.com','h','normal')",
    "INSERT INTO user_tokens (id, user_id, token_id, \"group\", balance_usd, is_trial) VALUES "
    "('ut1','U1','ti1','agent',3.000000,false),"       # 非试用行 → 全额现金
    "('ut2','U2','ti1','image',1.000000,true),"        # 试用行未消费 → 全部试用
    "('ut3','U3','ti1','image',1.420000,true),"        # 试用行含充值 → trial 1.00 + cash 0.42
    "('ut4','U4','ti1','image',0.420000,false),"       # image 非试用
    "('ut5','U4','ti1','agent',3.000000,false)",       # agent 非试用 → U4 = 3.42 现金
    "INSERT INTO orders (id, user_id, out_trade_no, \"group\", amount_usd, amount_cny, exchange_rate, status) VALUES "
    "('o1','U4','CYOLD0000000001','image',0.42,3.05,7.25,'assigned'),"
    "('o2','U4','CYOLDREFUNDING1','image',1.00,7.25,7.25,'refunding'),"
    "('o3','U1','CYOLDREFUNDED001','image',2.00,14.50,7.25,'refunded')",
    "UPDATE orders SET refund_requested_at = now() - interval '5 minutes' WHERE id = 'o2'",
    "UPDATE orders SET out_refund_no = 'RFOLD0000000001', refunded_at = now() WHERE id = 'o3'",
    "INSERT INTO usage_logs (id, user_id, model, usage_type, image_count, cost_usd, created_at) VALUES "
    "('ul1','U4','gpt-image-1','image',2,0.092000,now())",
]


def _recreate_legacy_db():
    conn = psycopg2.connect(host="127.0.0.1", port=5432, user="postgres", password="postgres")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {LEGACY_DB} WITH (FORCE)")
    cur.execute(f"CREATE DATABASE {LEGACY_DB}")
    cur.close()
    conn.close()


async def _run_migration_on_legacy():
    from app.core.database import Base
    import app.models  # noqa: F401 注册全部 ORM 模型
    from app.main import (
        _ensure_columns, _ensure_indexes, _migrate_v4_single_model,
        _migrate_v4_shared_token_refund, seed_defaults,
    )
    from sqlalchemy.ext.asyncio import AsyncSession

    engine = create_async_engine(f"{PG}/{LEGACY_DB}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _ensure_columns(conn)
            await _ensure_indexes(conn)
            await _migrate_v4_single_model(conn)
            await _migrate_v4_shared_token_refund(conn)
        # seed 走独立 session（不走全局 engine，它指向测试主库）
        async with AsyncSession(engine) as session:
            from sqlalchemy import select
            from app.models.content import AIModel
            result = await session.execute(select(AIModel).where(AIModel.name == "gpt-image-2"))
            if not result.scalar_one_or_none():
                session.add(AIModel(
                    name="gpt-image-2", display_name="Image2", provider="OpenAI",
                    billing_type="per_call", is_enabled=True, trial_allowed=True,
                    price_per_call=Decimal("0.046"), currency="USD",
                ))
                await session.commit()
        # 迁移幂等：再次执行应为 no-op
        async with engine.begin() as conn:
            await _migrate_v4_single_model(conn)
            await _migrate_v4_shared_token_refund(conn)
    finally:
        await engine.dispose()


@pytest.fixture(scope="module", autouse=True)
def legacy_db():
    _recreate_legacy_db()
    conn = psycopg2.connect(host="127.0.0.1", port=5432, user="postgres", password="postgres", dbname=LEGACY_DB)
    conn.autocommit = True
    cur = conn.cursor()
    for ddl in LEGACY_DDL:
        cur.execute(ddl)
    for dml in LEGACY_DATA:
        cur.execute(dml)
    cur.close()
    conn.close()
    asyncio.run(_run_migration_on_legacy())
    yield


def q(sql: str, params=None):
    conn = psycopg2.connect(host="127.0.0.1", port=5432, user="postgres", password="postgres", dbname=LEGACY_DB)
    cur = conn.cursor()
    cur.execute(sql, params or ())
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def test_balances_migrated():
    """余额迁移规则：非试用行全额现金；试用行前 $1 计试用、超出计现金。"""
    rows = {r[0]: (r[1], r[2]) for r in q("SELECT id, balance_usd, trial_credit_usd FROM users")}
    assert rows["U1"] == (Decimal("3.000000"), Decimal("0.000000"))
    assert rows["U2"] == (Decimal("0.000000"), Decimal("1.000000"))
    assert rows["U3"] == (Decimal("0.420000"), Decimal("1.000000"))
    assert rows["U4"] == (Decimal("3.420000"), Decimal("0.000000"))
    assert rows["U5"] == (Decimal("0.000000"), Decimal("0.000000"))


def test_migration_ledger_written():
    """迁移入账写 MIGRATION 流水，金额可追溯。"""
    rows = q("SELECT user_id, amount_usd, trial_amount, balance_amount, type, status "
             "FROM billing_transactions WHERE type = 'MIGRATION' ORDER BY user_id")
    by_user = {r[0]: r for r in rows}
    assert by_user["U3"][1] == Decimal("1.420000")
    assert by_user["U3"][2] == Decimal("1.000000")
    assert by_user["U3"][3] == Decimal("0.420000")
    assert all(r[5] == "SUCCESS" for r in rows)


def test_only_image2_model_remains():
    """非 Image2 模型全部清除，且 price_per_call 已转为 NUMERIC。"""
    rows = q("SELECT name, price_per_call FROM ai_models")
    assert rows == [("gpt-image-2", Decimal("0.046000"))]

    col_type = q("SELECT data_type FROM information_schema.columns "
                 "WHERE table_name='ai_models' AND column_name='price_per_call'")[0][0]
    assert col_type == "numeric"


def test_legacy_tables_preserved_not_dropped():
    """历史财务/内容数据保留：user_tokens / prompts / groups / orders 原样。"""
    assert q("SELECT COUNT(*) FROM user_tokens")[0][0] == 5
    assert q("SELECT COUNT(*) FROM prompts")[0][0] == 1
    assert q("SELECT COUNT(*) FROM groups")[0][0] == 2
    assert q("SELECT out_trade_no, amount_usd FROM orders")[0] == ("CYOLD0000000001", Decimal("0.42"))


def test_group_columns_now_nullable():
    """旧 NOT NULL 分组列已放宽，新订单可不写 group。"""
    is_nullable = q("SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name='orders' AND column_name='group'")[0][0]
    assert is_nullable == "YES"
    q_is_nullable = q("SELECT is_nullable FROM information_schema.columns "
                      "WHERE table_name='ai_models' AND column_name='group'")[0][0]
    assert q_is_nullable == "YES"


def test_trade_no_unique_index_created():
    idx = q("SELECT indexname FROM pg_indexes WHERE tablename='orders' AND indexname='uq_orders_trade_no'")
    assert idx == [("uq_orders_trade_no",)]


def test_seed_idempotent_single_model():
    """Test 13：迁移+seed 后（含重复执行）始终只有 gpt-image-2。"""
    rows = q("SELECT name FROM ai_models")
    assert rows == [("gpt-image-2",)]


def test_usage_logs_missing_columns_added():
    """回归守卫：V3 旧库 usage_logs 无 unit_price/request_id，启动迁移必须补齐。

    生产事故：ORM 含 unit_price 但 _ensure_columns 遗漏，旧库升级后
    admin 用户详情 select(UsageLog) 抛 UndefinedColumnError。
    """
    cols = {r[0]: (r[1], r[2]) for r in q(
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
        "WHERE table_name='usage_logs'")}
    assert cols["unit_price"] == ("numeric", "YES")
    assert cols["request_id"] == ("character varying", "YES")


def test_usage_logs_history_unit_price_stays_null():
    """历史行 unit_price 保持 NULL，不伪造价格；数据不丢。"""
    rows = q("SELECT model, image_count, cost_usd, unit_price, request_id FROM usage_logs")
    assert rows == [("gpt-image-1", 2, Decimal("0.092000"), None, None)]


def test_usage_logs_orm_full_select_works():
    """迁移后 ORM 全列查询可用（即 admin 用户详情的真实查询路径）。"""
    import asyncio
    from sqlalchemy import select as sa_select
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.token import UsageLog

    async def run():
        engine = create_async_engine(f"{PG}/{LEGACY_DB}")
        try:
            async with AsyncSession(engine) as session:
                rows = (await session.execute(sa_select(UsageLog))).scalars().all()
                return [(r.model, r.unit_price) for r in rows]
        finally:
            await engine.dispose()

    assert asyncio.run(run()) == [("gpt-image-1", None)]


def test_ensure_columns_idempotent_on_legacy():
    """_ensure_columns 重复执行不失败（幂等）。"""
    import asyncio
    from app.main import _ensure_columns

    async def run():
        engine = create_async_engine(f"{PG}/{LEGACY_DB}")
        try:
            async with engine.begin() as conn:
                await _ensure_columns(conn)
        finally:
            await engine.dispose()

    asyncio.run(run())


# ── V4.1 共享 Token + 退款申请迁移 ────────────────────────────────

def test_legacy_one_to_one_bindings_migrated_to_assignments():
    """旧 1:1 绑定（is_assigned + assigned_to）迁入共享 assignments，且幂等不重复。"""
    rows = q("SELECT token_id, user_id, status FROM runtime_token_assignments ORDER BY token_id, user_id")
    assert ("ti1", "U2", "active") in rows
    assert ("ti2", "U4", "active") in rows
    assert len([r for r in rows if r[0] == "ti1"]) == 1  # 不重复


def test_legacy_refunding_orders_become_refund_requested():
    """旧 refunding 订单（15 分钟自动批准遗留）→ refund_requests(requested) + 订单待审核。"""
    status = q("SELECT status FROM orders WHERE id = 'o2'")[0][0]
    assert status == "refund_requested"
    rows = q("SELECT order_id, user_id, source, status FROM refund_requests")
    assert rows == [("o2", "U4", "user", "requested")]


def test_legacy_refunded_orders_backfill_accumulators():
    """已退款历史订单回填累计退款字段（展示用，幂等）。"""
    row = q("SELECT refunded_cny, refunded_usd FROM orders WHERE id = 'o3'")[0]
    assert row == (Decimal("14.50"), Decimal("2.00"))
    # 未退款订单保持 0
    row1 = q("SELECT refunded_cny, refunded_usd FROM orders WHERE id = 'o1'")[0]
    assert row1 == (Decimal("0.00"), Decimal("0.000000"))
