import logging
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
import os
import asyncio

from app.core.database import engine, Base, AsyncSessionLocal, AsyncSession
from app.core.redis import init_redis, recover_processing_refunds
from app.api.routes import auth, users, tokens, payment, notice, models, admin, usage, client, admin_accounts, admin_skills, skill_submissions, skills as skills_route, billing as billing_route, trial as trial_route
from app.models.content import AIModel
from app.models.billing import PricingRule
from app.services import billing
from app.services import config_service
from app.services import credits_migration
from app.services import skill_catalog
from app.core.security import hash_password
from app.core.config import settings

logger = logging.getLogger(__name__)

IMAGE2_MODEL_ID = "gpt-image-2"

# 服务版本唯一来源：/health、/api/health 与 FastAPI 元数据均引用此常量
APP_VERSION = "4.2.3"

# V4：系统仅提供 Image2 一个收费模型，seed 只保证它存在，不再创建任何其他默认模型。
IMAGE2_SEED = {
    "name": IMAGE2_MODEL_ID,
    "display_name": "Image2",
    "provider": "OpenAI",
    "billing_type": "per_call",
    "is_enabled": True,
    "trial_allowed": True,
    "price_per_call": Decimal("0.046"),
    "currency": "USD",
}

MIGRATION_VERSION = "v4_single_model"
MIGRATION_VERSION_SHARED_TOKEN_REFUND = "v4_shared_token_refund"
MIGRATION_VERSION_ADMIN_ACCOUNTS = "v402_admin_accounts"
MIGRATION_VERSION_SKILL_SUBMISSIONS = "v423_skill_submissions"


async def seed_defaults():
    async with AsyncSession(engine) as session:
        result = await session.execute(select(AIModel).where(AIModel.name == IMAGE2_MODEL_ID))
        if not result.scalar_one_or_none():
            session.add(AIModel(**IMAGE2_SEED))

        # V4.2 业务配置默认值（幂等，仅补缺失键）
        await config_service.seed_config_defaults(session)
        await skill_catalog.seed_skill_catalog(session)

        # V4.2 定价规则种子：仅当无任何生效规则时创建。
        # 单价 80 点 = ¥0.80（示例成本 ¥0.20 + 10% 安全垫，70% 目标毛利 → 最低 80 点）。
        # 管理员可在后台按真实采购成本调整；所有改动经 Price Guard。
        rule = await session.execute(
            select(PricingRule).where(PricingRule.enabled.is_(True)).limit(1)
        )
        if rule.scalar_one_or_none() is None:
            existing_any = await session.execute(select(PricingRule).limit(1))
            if existing_any.scalar_one_or_none() is None:
                session.add(PricingRule(
                    feature="image",
                    model=IMAGE2_MODEL_ID,
                    unit_credits=80,
                    nominal_unit_cost_rmb=Decimal("0.20"),
                    target_margin=Decimal("0.70"),
                    safety_buffer=Decimal("0.10"),
                    rounding_step=10,
                    created_by="system-seed",
                ))
                logger.info("seeded default pricing rule: 80 credits/image")

        await session.commit()


async def _column_exists(conn, table: str, column: str) -> bool:
    result = await conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :table AND column_name = :column"
    ), {"table": table, "column": column})
    return bool(result.scalar())


async def _ensure_columns(conn):
    """Add new columns to existing tables if they don't exist (PostgreSQL)."""
    new_columns = [
        ("users", "balance_usd", "NUMERIC(18,6) NOT NULL DEFAULT 0"),
        ("users", "trial_credit_usd", "NUMERIC(18,6) NOT NULL DEFAULT 0"),
        ("ai_models", "currency", "VARCHAR(8) NOT NULL DEFAULT 'USD'"),
        ("token_inventory", "is_disabled", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("usage_logs", "request_id", "VARCHAR(64)"),
        # V4 结算单价快照：历史记录无法可靠还原单价，保持 NULL（API 对 NULL 已兼容）
        ("usage_logs", "unit_price", "NUMERIC(10,6)"),
        # V4.1 共享 Token 池
        ("token_inventory", "name", "VARCHAR(128)"),
        ("token_inventory", "is_default", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("token_inventory", "quota_usd", "NUMERIC(18,6)"),
        ("token_inventory", "expires_at", "TIMESTAMPTZ"),
        # V4.1 退款累计（部分退款多次累计，快照语义）
        ("orders", "refunded_cny", "NUMERIC(10,2) NOT NULL DEFAULT 0"),
        ("orders", "refunded_usd", "NUMERIC(18,6) NOT NULL DEFAULT 0"),
        # V4.0.2 管理员体系
        ("admin_users", "must_change_password", "BOOLEAN NOT NULL DEFAULT FALSE"),
        # V4.2 CY Credits
        ("users", "paid_credits", "INTEGER NOT NULL DEFAULT 0"),
        ("users", "trial_credits", "INTEGER NOT NULL DEFAULT 0"),
        ("users", "gift_credits", "INTEGER NOT NULL DEFAULT 0"),
        ("users", "archived_at", "TIMESTAMPTZ"),
        ("users", "archived_by", "VARCHAR(64)"),
        ("billing_transactions", "unit_credits", "INTEGER"),
        ("billing_transactions", "amount_credits", "INTEGER NOT NULL DEFAULT 0"),
        ("billing_transactions", "trial_credits_part", "INTEGER NOT NULL DEFAULT 0"),
        ("billing_transactions", "gift_credits_part", "INTEGER NOT NULL DEFAULT 0"),
        ("billing_transactions", "paid_credits_part", "INTEGER NOT NULL DEFAULT 0"),
        ("billing_transactions", "quote_id", "VARCHAR(36)"),
        ("billing_transactions", "pricing_rule_id", "VARCHAR(36)"),
        ("billing_transactions", "pricing_rule_version", "INTEGER"),
        ("orders", "credits_granted", "INTEGER"),
        ("usage_logs", "unit_credits", "INTEGER"),
        ("usage_logs", "cost_credits", "INTEGER NOT NULL DEFAULT 0"),
        # V4.2.3 社区 Skill 发布元数据
        ("skill_packages", "source", "VARCHAR(16) NOT NULL DEFAULT 'official'"),
        ("skill_packages", "author_display_name", "VARCHAR(96)"),
        ("skill_packages", "preview_sample_id", "VARCHAR(36)"),
        ("skill_packages", "source_submission_id", "VARCHAR(36)"),
    ]
    for table, column, col_type in new_columns:
        if not await _column_exists(conn, table, column):
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))


async def _ensure_indexes(conn):
    index_ddls = [
        "CREATE INDEX IF NOT EXISTS ix_usage_logs_user_created ON usage_logs (user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_usage_logs_user_model ON usage_logs (user_id, model)",
        "CREATE INDEX IF NOT EXISTS ix_usage_logs_user_type ON usage_logs (user_id, usage_type)",
        "CREATE INDEX IF NOT EXISTS ix_usage_logs_user_model_created ON usage_logs (user_id, model, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_usage_logs_request_id ON usage_logs (request_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_usage_logs_request_id ON usage_logs (request_id) WHERE request_id IS NOT NULL",
    ]
    for ddl in index_ddls:
        await conn.execute(text(ddl))

    # 微信 transaction_id 唯一兜底（历史数据存在重复时不创建，避免迁移失败）
    dup = await conn.execute(text(
        "SELECT COUNT(*) FROM (SELECT trade_no FROM orders "
        "WHERE trade_no IS NOT NULL GROUP BY trade_no HAVING COUNT(*) > 1) t"
    ))
    if not dup.scalar():
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_trade_no ON orders (trade_no) "
            "WHERE trade_no IS NOT NULL"
        ))

    # token_inventory 唯一兜底（旧库 UNIQUE(token_value, group) 收敛后单列约束可能缺失；
    # 历史数据存在同 token 多行重复时不创建，避免迁移失败）
    tdup = await conn.execute(text(
        "SELECT COUNT(*) FROM (SELECT token_value FROM token_inventory "
        "GROUP BY token_value HAVING COUNT(*) > 1) t"
    ))
    if not tdup.scalar():
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_token_value ON token_inventory (token_value)"
        ))


async def _drop_not_null(conn, table: str, column: str):
    await conn.execute(text(f'ALTER TABLE {table} ALTER COLUMN "{column}" DROP NOT NULL'))


async def _migrate_v4_single_model(conn):
    """V4 一次性数据迁移：统一余额、单模型收敛。

    - user_tokens 分组余额 → users.balance_usd / trial_credit_usd
      迁移规则（保守，不高估现金）：非试用行全额计现金；试用行前 $1 视为赠送试用额度，
      超出部分视为现金（agent/postprocess 历史余额均为真实付费，计现金）。
    - ai_models 删除全部非 gpt-image-2 模型；price_per_call 由 VARCHAR 迁移为 NUMERIC(18,6)。
    - 旧 NOT NULL 分组列放宽为可空（代码不再写入）。
    - 旧表 prompts / groups / user_tokens 保留数据，不再被代码引用。
    """
    await conn.execute(text(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version VARCHAR(64) PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    ))
    applied = await conn.execute(text(
        "SELECT 1 FROM schema_migrations WHERE version = :v"
    ), {"v": MIGRATION_VERSION})
    if applied.scalar():
        return

    logger.info("running migration %s ...", MIGRATION_VERSION)

    # 1) 放宽历史 NOT NULL 分组列
    for table, column in [
        ("ai_models", "group"), ("token_inventory", "group"), ("orders", "group"),
        ("ai_models", "model_type"),
    ]:
        if await _column_exists(conn, table, column):
            try:
                await _drop_not_null(conn, table, column)
            except Exception:
                logger.warning("drop not null failed: %s.%s", table, column)

    # 2) ai_models.price_per_call VARCHAR → NUMERIC(18,6)（先清掉非 Image2 模型再转）
    if await _column_exists(conn, "ai_models", "price_per_call"):
        col_type = await conn.execute(text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'ai_models' AND column_name = 'price_per_call'"
        ))
        if (col_type.scalar() or "") in ("character varying", "text"):
            await conn.execute(text(
                "DELETE FROM ai_models WHERE name <> :name"
            ), {"name": IMAGE2_MODEL_ID})
            await conn.execute(text(
                "ALTER TABLE ai_models ALTER COLUMN price_per_call TYPE NUMERIC(18,6) "
                "USING NULLIF(TRIM(price_per_call), '')::numeric"
            ))
        else:
            await conn.execute(text(
                "DELETE FROM ai_models WHERE name <> :name"
            ), {"name": IMAGE2_MODEL_ID})

    # 3) 分组余额 → 统一余额
    if await _column_exists(conn, "user_tokens", "balance_usd"):
        await conn.execute(text("""
            UPDATE users u SET
                balance_usd = COALESCE(agg.cash, 0),
                trial_credit_usd = COALESCE(agg.trial, 0)
            FROM (
                SELECT ut.user_id,
                       SUM(CASE WHEN ut.is_trial = false THEN ut.balance_usd
                                ELSE GREATEST(ut.balance_usd - 1.0, 0) END) AS cash,
                       SUM(CASE WHEN ut.is_trial = true THEN LEAST(ut.balance_usd, 1.0)
                                ELSE 0 END) AS trial
                FROM user_tokens ut
                GROUP BY ut.user_id
            ) agg
            WHERE u.id = agg.user_id
              AND (u.balance_usd = 0 AND u.trial_credit_usd = 0)
        """))
        # 迁移入账流水（金额 > 0 的用户），保证账务可追溯
        await conn.execute(text("""
            INSERT INTO billing_transactions
                (id, user_id, type, status, image_count, amount_usd, trial_amount,
                 balance_amount, billing_source, balance_before, balance_after,
                 trial_before, trial_after, remark, created_at, updated_at)
            SELECT gen_random_uuid()::text, u.id, 'MIGRATION', 'SUCCESS', 0,
                   COALESCE(agg.cash, 0) + COALESCE(agg.trial, 0),
                   COALESCE(agg.trial, 0), COALESCE(agg.cash, 0),
                   CASE WHEN COALESCE(agg.trial,0) > 0 AND COALESCE(agg.cash,0) > 0 THEN 'MIXED'
                        WHEN COALESCE(agg.trial,0) > 0 THEN 'TRIAL'
                        WHEN COALESCE(agg.cash,0) > 0 THEN 'CASH'
                        ELSE 'NONE' END,
                   0, u.balance_usd, 0, u.trial_credit_usd,
                   'v4 unified balance migration (user_tokens -> users)', now(), now()
            FROM users u
            JOIN (
                SELECT ut.user_id,
                       SUM(CASE WHEN ut.is_trial = false THEN ut.balance_usd
                                ELSE GREATEST(ut.balance_usd - 1.0, 0) END) AS cash,
                       SUM(CASE WHEN ut.is_trial = true THEN LEAST(ut.balance_usd, 1.0)
                                ELSE 0 END) AS trial
                FROM user_tokens ut
                GROUP BY ut.user_id
            ) agg ON agg.user_id = u.id
            WHERE COALESCE(agg.cash, 0) + COALESCE(agg.trial, 0) > 0
        """))

    await conn.execute(text(
        "INSERT INTO schema_migrations (version) VALUES (:v) ON CONFLICT DO NOTHING"
    ), {"v": MIGRATION_VERSION})
    logger.info("migration %s done", MIGRATION_VERSION)


async def start_reservation_gc_loop():
    """周期释放超时未结算的 Image2 预占（客户端崩溃兜底）。"""
    while True:
        try:
            async with AsyncSessionLocal() as session:
                await billing.release_stale_reservations(session)
        except Exception:
            logger.exception("reservation gc loop failed")
        await asyncio.sleep(600)


async def _migrate_v4_shared_token_refund(conn):
    """V4.1 一次性数据迁移：共享 Token 池 + 退款申请体系。

    - token_inventory 新列（name/is_default/quota_usd/expires_at）由 _ensure_columns 补齐
    - 旧 1:1 绑定（is_assigned/assigned_to）→ runtime_token_assignments
    - 旧 status='refunding' 订单 → refund_requests(requested) + 订单状态 refund_requested
      （旧 15 分钟自动批准机制已移除，改为人工审核）
    - 已退款历史订单回填累计退款字段（refunded_cny/refunded_usd，展示用）
    """
    applied = await conn.execute(text(
        "SELECT 1 FROM schema_migrations WHERE version = :v"
    ), {"v": MIGRATION_VERSION_SHARED_TOKEN_REFUND})
    if applied.scalar():
        return

    logger.info("running migration %s ...", MIGRATION_VERSION_SHARED_TOKEN_REFUND)

    # 0) 订单状态列加宽：新状态 partially_refunded(18) / refund_requested(17) 超出旧 VARCHAR(16)
    await conn.execute(text("ALTER TABLE orders ALTER COLUMN status TYPE VARCHAR(24)"))
    await conn.execute(text("ALTER TABLE orders ALTER COLUMN status_before_refund TYPE VARCHAR(24)"))

    # 1) 旧 1:1 绑定迁入共享 assignments（幂等：ON CONFLICT DO NOTHING）
    await conn.execute(text("""
        INSERT INTO runtime_token_assignments (id, token_id, user_id, status, source, assigned_at)
        SELECT gen_random_uuid()::text, t.id, t.assigned_to, 'active', 'legacy_migration',
               COALESCE(t.assigned_at, now())
        FROM token_inventory t
        WHERE t.is_assigned = true AND t.assigned_to IS NOT NULL
        ON CONFLICT DO NOTHING
    """))

    # 2) 旧 refunding（15 分钟自动批准机制的遗留）→ 退款申请待审核
    await conn.execute(text("""
        INSERT INTO refund_requests (
            id, order_id, user_id, source,
            requested_amount_fen, requested_amount_cny, requested_amount_usd,
            reason, status, requested_at, created_at, updated_at
        )
        SELECT gen_random_uuid()::text, o.id, o.user_id, 'user',
               ROUND(o.amount_cny * 100)::int,
               o.amount_cny,
               o.amount_usd - COALESCE(o.refunded_usd, 0),
               'legacy refunding order migrated', 'requested',
               COALESCE(o.refund_requested_at, now()), now(), now()
        FROM orders o
        WHERE o.status = 'refunding'
        ON CONFLICT DO NOTHING
    """))
    await conn.execute(text(
        "UPDATE orders SET status = 'refund_requested' WHERE status = 'refunding'"
    ))

    # 3) 已退款历史订单回填累计退款字段（幂等：只补 NULL/0）
    await conn.execute(text("""
        UPDATE orders SET refunded_cny = amount_cny, refunded_usd = amount_usd
        WHERE status = 'refunded' AND out_refund_no IS NOT NULL
          AND COALESCE(refunded_cny, 0) = 0
    """))

    await conn.execute(text(
        "INSERT INTO schema_migrations (version) VALUES (:v) ON CONFLICT DO NOTHING"
    ), {"v": MIGRATION_VERSION_SHARED_TOKEN_REFUND})
    logger.info("migration %s done", MIGRATION_VERSION_SHARED_TOKEN_REFUND)


async def _migrate_admin_accounts(conn):
    """V4.0.2 一次性迁移：管理员账户数据库化。

    admin_users 表由 create_all 建立；首次迁移若表为空，用现有 env 管理员
    （ADMIN_USERNAME / ADMIN_PASSWORD）初始化为 super_admin（bcrypt 哈希），
    保证生产环境现有管理员迁移后无需任何操作即可继续登录。
    迁移后 env 管理员凭据仅作为首次引导来源，登录一律以数据库为准。
    """
    applied = await conn.execute(text(
        "SELECT 1 FROM schema_migrations WHERE version = :v"
    ), {"v": MIGRATION_VERSION_ADMIN_ACCOUNTS})
    if applied.scalar():
        return

    logger.info("running migration %s ...", MIGRATION_VERSION_ADMIN_ACCOUNTS)

    count = await conn.execute(text("SELECT COUNT(*) FROM admin_users"))
    if not count.scalar():
        username = settings.ADMIN_USERNAME.strip().lower() or "admin"
        await conn.execute(text(
            "INSERT INTO admin_users (id, username, display_name, password_hash, role, "
            "is_active, must_change_password, created_at, updated_at, password_changed_at) "
            "VALUES (:id, :username, :display_name, :password_hash, 'super_admin', true, false, now(), now(), now())"
        ), {
            "id": str(uuid.uuid4()),
            "username": username,
            "display_name": "超级管理员",
            "password_hash": hash_password(settings.ADMIN_PASSWORD),
        })
        logger.info("bootstrap super_admin '%s' created from env credentials", username)

    await conn.execute(text(
        "INSERT INTO schema_migrations (version) VALUES (:v) ON CONFLICT DO NOTHING"
    ), {"v": MIGRATION_VERSION_ADMIN_ACCOUNTS})
    logger.info("migration %s done", MIGRATION_VERSION_ADMIN_ACCOUNTS)


async def _migrate_skill_submissions(conn):
    """V4.2.3 一次性迁移：社区 Skill 投稿三表显式建表 + 索引。

    生产部署不依赖 ORM create_all 的隐式建表（老容器滚动升级时新表必须由
    本迁移显式补齐）；schema_migrations 记录版本，幂等可重放。
    """
    applied = await conn.execute(text(
        "SELECT 1 FROM schema_migrations WHERE version = :v"
    ), {"v": MIGRATION_VERSION_SKILL_SUBMISSIONS})
    if applied.scalar():
        return

    logger.info("running migration %s ...", MIGRATION_VERSION_SKILL_SUBMISSIONS)
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS skill_submissions (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id),
            local_skill_id VARCHAR(96) NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1,
            version VARCHAR(32) NOT NULL DEFAULT '1.0.0',
            name VARCHAR(128) NOT NULL,
            domain VARCHAR(64) NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            payload JSON NOT NULL DEFAULT '{}'::json,
            source_facts JSON NOT NULL DEFAULT '[]'::json,
            authoring_meta JSON NOT NULL DEFAULT '{}'::json,
            author_display_name VARCHAR(96) NOT NULL DEFAULT '社区创作者',
            status VARCHAR(24) NOT NULL DEFAULT 'submitted',
            review_message TEXT,
            public_skill_id VARCHAR(96),
            reviewed_by VARCHAR(64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            reviewed_at TIMESTAMPTZ
        )
    """))
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS skill_submission_samples (
            id VARCHAR(36) PRIMARY KEY,
            submission_id VARCHAR(36) NOT NULL REFERENCES skill_submissions(id) ON DELETE CASCADE,
            file_path TEXT NOT NULL,
            file_name VARCHAR(255) NOT NULL,
            content_type VARCHAR(64) NOT NULL,
            sha256 VARCHAR(64) NOT NULL,
            task_id VARCHAR(64),
            generation_meta JSON NOT NULL DEFAULT '{}'::json,
            public_cover BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS skill_submission_events (
            id VARCHAR(36) PRIMARY KEY,
            submission_id VARCHAR(36) NOT NULL REFERENCES skill_submissions(id) ON DELETE CASCADE,
            actor VARCHAR(96) NOT NULL,
            actor_type VARCHAR(16) NOT NULL,
            action VARCHAR(32) NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    for ddl in (
        "CREATE INDEX IF NOT EXISTS ix_skill_submissions_user_id ON skill_submissions (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_skill_submissions_status ON skill_submissions (status)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_submission_revision "
        "ON skill_submissions (user_id, local_skill_id, revision)",
        "CREATE INDEX IF NOT EXISTS ix_skill_submission_samples_submission_id "
        "ON skill_submission_samples (submission_id)",
        "CREATE INDEX IF NOT EXISTS ix_skill_submission_events_submission_id "
        "ON skill_submission_events (submission_id)",
    ):
        await conn.execute(text(ddl))

    await conn.execute(text(
        "INSERT INTO schema_migrations (version) VALUES (:v) ON CONFLICT DO NOTHING"
    ), {"v": MIGRATION_VERSION_SKILL_SUBMISSIONS})
    logger.info("migration %s done", MIGRATION_VERSION_SKILL_SUBMISSIONS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_redis()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_columns(conn)
        await _ensure_indexes(conn)
        await _migrate_v4_single_model(conn)
        await _migrate_v4_shared_token_refund(conn)
        await _migrate_admin_accounts(conn)
        await _migrate_skill_submissions(conn)

    # V4.2.3 投稿样例目录：启动即确保存在（容器内挂载持久卷后首启可写）
    try:
        Path(settings.SKILL_SAMPLE_DIR).mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning("cannot create SKILL_SAMPLE_DIR %s", settings.SKILL_SAMPLE_DIR)

    await seed_defaults()

    # V4.2 旧美元余额 → CY 点数迁移：
    # - 非生产（测试/开发）：启动即自动执行（幂等）
    # - 生产：只输出 preview 报告，必须由 super_admin 经
    #   POST /api/admin/billing/credits-migration 确认后执行
    async with AsyncSessionLocal() as session:
        if not await credits_migration.credits_migration_applied(session):
            report = await credits_migration.preview_credits_migration(session)
            if settings.APP_ENV == "production":
                logger.warning(
                    "credits migration PENDING (production): users=%d balance_usd=%s -> credits=%d "
                    "(run POST /api/admin/billing/credits-migration {\"action\":\"apply\"} to apply)",
                    report["user_count"], report["total_balance_usd"],
                    report["total_paid_credits"] + report["total_trial_credits"],
                )
            else:
                await credits_migration.apply_credits_migration(session)
                await session.commit()
                logger.info(
                    "credits migration auto-applied (non-production): users=%d credits=%d",
                    report["user_count"],
                    report["total_paid_credits"] + report["total_trial_credits"],
                )

    # 启动即清理一次超时预占，再进入周期任务
    asyncio.create_task(start_reservation_gc_loop())

    # 恢复微信退款处理中的申请（主动查询状态并结算；旧 15 分钟自动批准机制已移除）
    await recover_processing_refunds()

    yield


# 生产环境关闭交互式 API 文档，避免暴露完整接口结构
_is_production = settings.APP_ENV == "production"

app = FastAPI(
    title="CyImagePro Service", version=APP_VERSION, lifespan=lifespan,
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # 详细堆栈只进服务端日志，不向客户端外泄 SQL/驱动/路径等内部信息
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误，请稍后重试"},
    )

# CORS：认证全部走 Authorization Bearer（无 Cookie），因此不启用 credentials。
# 生产可通过 CORS_ORIGINS 配置显式白名单（逗号分隔）；未配置时放开以兼容
# Tauri 客户端的多变 origin（tauri://localhost、http://tauri.localhost 等）。
_cors_origins = [o.strip() for o in (settings.CORS_ORIGINS or "").split(",") if o.strip()] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(tokens.router, prefix="/api/tokens", tags=["tokens"])
app.include_router(payment.router, prefix="/api/pay", tags=["payment"])
app.include_router(notice.router, prefix="/api/notice", tags=["notice"])
app.include_router(models.router, prefix="/api/models", tags=["models"])
app.include_router(usage.router, prefix="/api/usage", tags=["usage"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(admin_accounts.router, prefix="/api/admin", tags=["admin-accounts"])
app.include_router(client.router, prefix="/api/client", tags=["client"])
app.include_router(billing_route.router, prefix="/api/billing", tags=["billing"])
app.include_router(trial_route.router, prefix="/api/trial", tags=["trial"])
app.include_router(skills_route.router, prefix="/api/skills", tags=["skills"])
app.include_router(skill_submissions.router, prefix="/api/skills", tags=["skill-submissions"])
app.include_router(admin_skills.router, prefix="/api/admin", tags=["admin-skills"])


@app.get("/api")
@app.get("/api/")
async def api_index():
    return {
        "status": "ok",
        "base_url": "/api",
        "routes": [
            "/api/auth",
            "/api/users",
            "/api/tokens",
            "/api/pay",
            "/api/notice",
            "/api/models",
            "/api/usage",
        ],
    }

# Serve frontend admin panel
if os.path.exists("/app/static"):
    app.mount("/admin", StaticFiles(directory="/app/static", html=True), name="admin")


@app.get("/health")
async def health():
    return {"ok": True, "service": "cyimagepro-server", "version": APP_VERSION}


@app.get("/api/health")
async def api_health():
    return {"ok": True, "service": "cyimagepro-server", "version": APP_VERSION}
