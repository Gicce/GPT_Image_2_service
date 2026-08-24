"""旧美元余额 → CY 点数一次性迁移（v4.2_credits）。

三步走（生产强制执行顺序）：
1. preview_credits_migration：只读测算，输出 转换用户数 / 旧总余额 / 转换后总点数 /
   异常用户数（负余额等）
2. 人工核对报告
3. apply_credits_migration：逐户换算（round(balance_usd × legacy_usd_to_credits)），
   写 MIGRATION 流水，回写 USD 镜像，登记 schema_migrations 版本标记

安全保证：
- 幂等：schema_migrations 版本标记存在则跳过
- 可回滚：迁移不删除任何旧列/旧数据；回滚 = 用流水 MIGRATION 记录反向冲正
- 非生产环境在启动 lifespan 自动 apply；生产环境必须由 super_admin 经管理接口触发
"""

import logging
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import BillingTransaction
from app.models.user import User
from app.services import billing
from app.services import config_service

logger = logging.getLogger(__name__)

MIGRATION_VERSION_CREDITS = "v4.2_credits_billing"


async def credits_migration_applied(db: AsyncSession) -> bool:
    result = await db.execute(
        text("SELECT 1 FROM schema_migrations WHERE version = :v"),
        {"v": MIGRATION_VERSION_CREDITS},
    )
    return result.scalar() is not None


def _convert(amount: Decimal | None, rate: int) -> int:
    if amount is None:
        return 0
    return int((billing.d(amount) * Decimal(rate)).to_integral_value(rounding=ROUND_HALF_UP))


async def preview_credits_migration(db: AsyncSession) -> dict:
    """只读预演：不修改任何数据。"""
    rate = await config_service.get_legacy_usd_to_credits(db)
    result = await db.execute(select(User))
    users = result.scalars().all()

    total_balance_usd = Decimal("0")
    total_trial_usd = Decimal("0")
    total_paid_credits = 0
    total_trial_credits = 0
    anomalies: list[dict] = []
    samples: list[dict] = []

    for u in users:
        bal = billing.d(u.balance_usd)
        tr = billing.d(u.trial_credit_usd)
        if bal < 0 or tr < 0:
            anomalies.append({"user_id": u.id, "email": u.email, "balance_usd": str(bal), "trial_usd": str(tr)})
            continue
        paid_cr = _convert(bal, rate)
        trial_cr = _convert(tr, rate)
        total_balance_usd += bal
        total_trial_usd += tr
        total_paid_credits += paid_cr
        total_trial_credits += trial_cr
        if len(samples) < 10:
            samples.append({
                "user_id": u.id,
                "email": u.email,
                "balance_usd": str(bal),
                "trial_usd": str(tr),
                "paid_credits": paid_cr,
                "trial_credits": trial_cr,
            })

    return {
        "applied": await credits_migration_applied(db),
        "legacy_usd_to_credits": rate,
        "user_count": len(users),
        "converted_count": len(users) - len(anomalies),
        "total_balance_usd": str(total_balance_usd.quantize(Decimal("0.000001"))),
        "total_trial_usd": str(total_trial_usd.quantize(Decimal("0.000001"))),
        "total_paid_credits": total_paid_credits,
        "total_trial_credits": total_trial_credits,
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
        "samples": samples,
    }


async def apply_credits_migration(conn_or_db, db: AsyncSession | None = None) -> dict:
    """正式执行迁移（幂等）。返回与 preview 相同结构的执行报告。

    必须在无并发写余额的窗口执行（部署流程保证：发布后立即触发）。
    """
    if await credits_migration_applied(conn_or_db):
        report = await preview_credits_migration(conn_or_db)
        report["executed"] = False
        report["message"] = "迁移已执行过（幂等跳过）"
        return report

    report = await preview_credits_migration(conn_or_db)
    rate = report["legacy_usd_to_credits"]

    result = await conn_or_db.execute(select(User))
    users = result.scalars().all()
    migrated = 0
    for u in users:
        bal = billing.d(u.balance_usd)
        tr = billing.d(u.trial_credit_usd)
        if bal < 0 or tr < 0:
            logger.warning("credits migration skip anomaly user=%s balance=%s", u.id, bal)
            continue
        paid_cr = _convert(bal, rate)
        trial_cr = _convert(tr, rate)
        if paid_cr == 0 and trial_cr == 0 and u.paid_credits == 0 and u.trial_credits == 0:
            continue
        u.paid_credits = paid_cr
        u.trial_credits = trial_cr
        billing.sync_legacy_mirrors(u, rate)
        conn_or_db.add(BillingTransaction(
            user_id=u.id,
            type=billing.MIGRATION,
            status="SUCCESS",
            amount_credits=paid_cr + trial_cr,
            paid_credits_part=paid_cr,
            trial_credits_part=trial_cr,
            amount_usd=billing.q6(bal),
            trial_amount=billing.q6(tr),
            balance_amount=billing.q6(bal),
            billing_source="PAID" if paid_cr > 0 else "NONE",
            balance_after=u.balance_usd,
            trial_after=u.trial_credit_usd,
            remark=f"legacy usd -> credits migration (rate {rate})",
        ))
        migrated += 1
    await conn_or_db.flush()

    await conn_or_db.execute(
        text("INSERT INTO schema_migrations (version) VALUES (:v) ON CONFLICT DO NOTHING"),
        {"v": MIGRATION_VERSION_CREDITS},
    )
    await conn_or_db.flush()

    logger.info(
        "credits migration executed: users=%d paid_cr=%d trial_cr=%d",
        migrated, report["total_paid_credits"], report["total_trial_credits"],
    )
    report["executed"] = True
    report["migrated_count"] = migrated
    return report
