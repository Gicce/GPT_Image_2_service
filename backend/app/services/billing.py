"""Image2 单模型计费核心（账务唯一真相源）。

设计要点：
- 全链路 Decimal，数据库 NUMERIC(18,6)，禁止 float 参与余额计算。
- 两阶段计费：authorize（额度预占，调用上游之前）→ settle（成功结算 / 失败退款）。
- 并发安全：对 users 行 SELECT ... FOR UPDATE，同用户计费操作串行化，杜绝超扣/丢失更新。
- 幂等：billing_transactions.request_id 唯一约束 + 状态 CAS，一次请求最多扣一次款、最多退一次款。
- 消费优先级：试用额度优先，现金余额其次，支持组合扣款（MIXED）。
"""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.billing import BillingTransaction
from app.models.content import AIModel
from app.models.token import UsageLog
from app.models.user import User

logger = logging.getLogger(__name__)

IMAGE2_MODEL_ID = "gpt-image-2"
SIX_PLACES = Decimal("0.000001")

CHARGE = "IMAGE2_CHARGE"
IMAGE2_REFUND = "IMAGE2_REFUND"
RECHARGE = "RECHARGE"
RECHARGE_REFUND = "RECHARGE_REFUND"
ADMIN_ADJUSTMENT = "ADMIN_ADJUSTMENT"
MIGRATION = "MIGRATION"


class QuotaExhaustedError(Exception):
    """现金余额 + 试用额度不足以支付本次调用。"""

    def __init__(self, required: Decimal, available: Decimal):
        self.required = required
        self.available = available
        super().__init__("余额不足，请充值后继续使用")


class ModelDisabledError(Exception):
    pass


def q6(value: Decimal) -> Decimal:
    return value.quantize(SIX_PLACES, rounding=ROUND_HALF_UP)


def d(value) -> Decimal:
    """安全转 Decimal（容忍 DB 返回的 Decimal/str/float）。"""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


async def get_image2_config(db: AsyncSession) -> AIModel | None:
    result = await db.execute(select(AIModel).where(AIModel.name == IMAGE2_MODEL_ID))
    return result.scalar_one_or_none()


async def get_image2_price(db: AsyncSession) -> Decimal:
    cfg = await get_image2_config(db)
    if cfg is None or not cfg.is_enabled:
        raise ModelDisabledError("Image2 未启用")
    price = cfg.price_per_call
    if price is None or (price := d(price)) <= 0:
        raise ModelDisabledError("Image2 价格未配置")
    return q6(price)


async def _lock_user(db: AsyncSession, user_id: str) -> User:
    result = await db.execute(select(User).where(User.id == user_id).with_for_update())
    user = result.scalar_one_or_none()
    if user is None:
        raise LookupError(f"user {user_id} not found")
    return user


def _split_charge(trial_available: Decimal, cost: Decimal) -> tuple[Decimal, Decimal]:
    """试用优先扣款：返回 (trial_part, cash_part)。"""
    trial_part = min(trial_available, cost)
    cash_part = cost - trial_part
    return trial_part, cash_part


def _source(trial_part: Decimal, cash_part: Decimal) -> str:
    if trial_part > 0 and cash_part > 0:
        return "MIXED"
    if trial_part > 0:
        return "TRIAL"
    if cash_part > 0:
        return "CASH"
    return "NONE"


def _txn_dict(txn: BillingTransaction, user: User | None = None) -> dict:
    out = {
        "id": txn.id,
        "request_id": txn.request_id,
        "type": txn.type,
        "status": txn.status,
        "model": txn.model,
        "image_count": txn.image_count,
        "unit_price_usd": str(txn.unit_price_usd) if txn.unit_price_usd is not None else None,
        "amount_usd": str(txn.amount_usd),
        "trial_amount": str(txn.trial_amount),
        "balance_amount": str(txn.balance_amount),
        "billing_source": txn.billing_source,
        "failure_reason": txn.failure_reason,
        "created_at": txn.created_at.isoformat() if txn.created_at else None,
    }
    if user is not None:
        out["balance_usd"] = str(q6(d(user.balance_usd)))
        out["trial_credit_usd"] = str(q6(d(user.trial_credit_usd)))
    return out


async def authorize_image2(
    db: AsyncSession,
    user_id: str,
    request_id: str,
    image_count: int,
) -> tuple[BillingTransaction, User]:
    """额度预占：在调用上游之前原子扣除 trial+balance 并写入 RESERVED 流水。

    幂等：同一 request_id 重复调用返回既有流水，不重复扣款。
    本函数不 commit，由调用方提交。
    """
    if image_count < 1:
        raise ValueError("image_count 必须 >= 1")
    if not request_id or len(request_id) > 64:
        raise ValueError("request_id 无效")

    user = await _lock_user(db, user_id)

    # 幂等：已存在同 request_id 的流水直接返回
    existing = await db.execute(
        select(BillingTransaction).where(BillingTransaction.request_id == request_id)
    )
    txn = existing.scalar_one_or_none()
    if txn is not None:
        if txn.user_id != user_id:
            raise PermissionError("request_id 已被其他用户占用")
        return txn, user

    cfg = await get_image2_config(db)
    if cfg is None or not cfg.is_enabled:
        raise ModelDisabledError("Image2 未启用")
    unit_price = d(cfg.price_per_call) if cfg.price_per_call is not None else Decimal("0")
    if unit_price <= 0:
        raise ModelDisabledError("Image2 价格未配置")

    cost = q6(unit_price * image_count)

    trial_available = d(user.trial_credit_usd)
    # trial_allowed 关闭时试用额度冻结，仅可用现金
    if not cfg.trial_allowed:
        trial_available = Decimal("0")
    cash_available = d(user.balance_usd)

    if trial_available + cash_available < cost:
        raise QuotaExhaustedError(cost, trial_available + cash_available)

    trial_part, cash_part = _split_charge(trial_available, cost)
    trial_before = d(user.trial_credit_usd)
    cash_before = d(user.balance_usd)

    user.trial_credit_usd = q6(trial_before - trial_part)
    user.balance_usd = q6(cash_before - cash_part)

    txn = BillingTransaction(
        user_id=user_id,
        type=CHARGE,
        status="RESERVED",
        request_id=request_id,
        model=IMAGE2_MODEL_ID,
        image_count=image_count,
        unit_price_usd=q6(unit_price),
        amount_usd=cost,
        trial_amount=trial_part,
        balance_amount=cash_part,
        billing_source=_source(trial_part, cash_part),
        balance_before=cash_before,
        balance_after=user.balance_usd,
        trial_before=trial_before,
        trial_after=user.trial_credit_usd,
    )
    db.add(txn)
    await db.flush()

    logger.info(
        "authorize request=%s user=%s count=%d cost=%s (trial=%s cash=%s)",
        request_id, user_id, image_count, cost, trial_part, cash_part,
    )
    return txn, user


async def settle_image2(
    db: AsyncSession,
    user_id: str,
    request_id: str,
    success: bool,
    final_image_count: int | None = None,
    failure_reason: str | None = None,
) -> tuple[BillingTransaction, User]:
    """结算预占：成功→按实际数量计费入账；失败→全额退款。

    幂等：重复 settle 返回当前终态，不再变更。
    本函数不 commit，由调用方提交。
    """
    user = await _lock_user(db, user_id)

    result = await db.execute(
        select(BillingTransaction)
        .where(BillingTransaction.request_id == request_id, BillingTransaction.user_id == user_id)
        .with_for_update()
    )
    txn = result.scalar_one_or_none()
    if txn is None or txn.type != CHARGE:
        raise LookupError("计费请求不存在（请先 authorize）")

    if txn.status != "RESERVED":
        # SUCCESS / FAILED / REFUNDED / RELEASED 均为终态，幂等返回
        return txn, user

    reserved_trial = d(txn.trial_amount)
    reserved_cash = d(txn.balance_amount)
    reserved_amount = d(txn.amount_usd)
    unit_price = d(txn.unit_price_usd) if txn.unit_price_usd is not None else Decimal("0")
    trial_before = d(user.trial_credit_usd)
    cash_before = d(user.balance_usd)

    if success:
        count = final_image_count if final_image_count is not None else txn.image_count
        if count < 0:
            raise ValueError("final_image_count 不能为负")
        if count > txn.image_count:
            raise ValueError("final_image_count 超过授权数量")
        final_cost = q6(unit_price * count)

        # 按试用优先顺序重算实际消耗
        consumed_trial = min(reserved_trial, final_cost)
        consumed_cash = final_cost - consumed_trial
        refund_trial = reserved_trial - consumed_trial
        refund_cash = reserved_cash - consumed_cash

        user.trial_credit_usd = q6(trial_before + refund_trial)
        user.balance_usd = q6(cash_before + refund_cash)

        txn.status = "SUCCESS"
        txn.image_count = count
        txn.amount_usd = final_cost
        txn.trial_amount = consumed_trial
        txn.balance_amount = consumed_cash
        txn.billing_source = _source(consumed_trial, consumed_cash)
        txn.balance_before = cash_before
        txn.balance_after = user.balance_usd
        txn.trial_before = trial_before
        txn.trial_after = user.trial_credit_usd

        usage = UsageLog(
            user_id=user_id,
            model=IMAGE2_MODEL_ID,
            usage_type="image",
            image_count=count,
            unit_price=q6(unit_price),
            cost_usd=final_cost,
            request_id=request_id,
        )
        db.add(usage)
        await db.flush()
        txn.related_usage_id = usage.id
    else:
        user.trial_credit_usd = q6(trial_before + reserved_trial)
        user.balance_usd = q6(cash_before + reserved_cash)

        txn.status = "FAILED"
        txn.failure_reason = (failure_reason or "upstream failure")[:255]
        txn.balance_before = cash_before
        txn.balance_after = user.balance_usd
        txn.trial_before = trial_before
        txn.trial_after = user.trial_credit_usd

    await db.flush()
    logger.info(
        "settle request=%s user=%s success=%s status=%s amount=%s",
        request_id, user_id, success, txn.status, txn.amount_usd,
    )
    return txn, user


async def refund_image2_transaction(
    db: AsyncSession,
    txn_id: str,
    reason: str = "admin refund",
) -> tuple[BillingTransaction, User] | None:
    """管理员退款：对 SUCCESS 的 Image2 扣费全额回退（幂等，状态 CAS）。"""
    result = await db.execute(
        select(BillingTransaction).where(BillingTransaction.id == txn_id).with_for_update()
    )
    txn = result.scalar_one_or_none()
    if txn is None:
        return None

    if txn.status != "SUCCESS":
        return txn, None  # 非 SUCCESS 不退款（RESERVED 由 GC/settle 处理）

    user = await _lock_user(db, txn.user_id)
    trial_before = d(user.trial_credit_usd)
    cash_before = d(user.balance_usd)
    user.trial_credit_usd = q6(trial_before + d(txn.trial_amount))
    user.balance_usd = q6(cash_before + d(txn.balance_amount))

    txn.status = "REFUNDED"
    txn.balance_before = cash_before
    txn.balance_after = user.balance_usd
    txn.trial_before = trial_before
    txn.trial_after = user.trial_credit_usd
    txn.remark = reason

    refund_txn = BillingTransaction(
        user_id=txn.user_id,
        type=IMAGE2_REFUND,
        status="SUCCESS",
        request_id=None,
        model=txn.model,
        image_count=txn.image_count,
        unit_price_usd=txn.unit_price_usd,
        amount_usd=txn.amount_usd,
        trial_amount=txn.trial_amount,
        balance_amount=txn.balance_amount,
        billing_source=txn.billing_source,
        balance_before=cash_before,
        balance_after=user.balance_usd,
        trial_before=trial_before,
        trial_after=user.trial_credit_usd,
        related_usage_id=txn.related_usage_id,
        remark=reason,
    )
    db.add(refund_txn)
    await db.flush()
    return txn, user


async def release_stale_reservations(db: AsyncSession, ttl_hours: int | None = None) -> int:
    """释放超时未结算的预占（客户端崩溃/断网兜底），全额退回。返回释放数量。"""
    ttl = timedelta(hours=ttl_hours or settings.RESERVATION_TTL_HOURS)
    cutoff = datetime.now(timezone.utc) - ttl

    result = await db.execute(
        select(BillingTransaction).where(
            BillingTransaction.status == "RESERVED",
            BillingTransaction.created_at < cutoff,
        )
    )
    released = 0
    for txn in result.scalars().all():
        try:
            user = await _lock_user(db, txn.user_id)
            lock = await db.execute(
                select(BillingTransaction)
                .where(BillingTransaction.id == txn.id)
                .with_for_update()
            )
            txn = lock.scalar_one()
            if txn.status != "RESERVED":
                continue
            trial_before = d(user.trial_credit_usd)
            cash_before = d(user.balance_usd)
            user.trial_credit_usd = q6(trial_before + d(txn.trial_amount))
            user.balance_usd = q6(cash_before + d(txn.balance_amount))
            txn.status = "RELEASED"
            txn.remark = "auto released (reservation timeout)"
            txn.balance_before = cash_before
            txn.balance_after = user.balance_usd
            txn.trial_before = trial_before
            txn.trial_after = user.trial_credit_usd
            released += 1
        except Exception:
            logger.exception("release stale reservation %s failed", txn.request_id)
    if released:
        await db.commit()
        logger.info("released %d stale reservations", released)
    return released


async def credit_balance(
    db: AsyncSession,
    user_id: str,
    amount: Decimal,
    txn_type: str,
    *,
    related_order_id: str | None = None,
    remark: str | None = None,
) -> tuple[User, BillingTransaction]:
    """给用户现金余额入账（充值/管理员调整/迁移），带流水。不 commit。"""
    user = await _lock_user(db, user_id)
    before = d(user.balance_usd)
    user.balance_usd = q6(before + d(amount))
    txn = BillingTransaction(
        user_id=user_id,
        type=txn_type,
        status="SUCCESS",
        amount_usd=q6(d(amount)),
        trial_amount=Decimal("0"),
        balance_amount=q6(d(amount)),
        billing_source="CASH",
        balance_before=before,
        balance_after=user.balance_usd,
        related_order_id=related_order_id,
        remark=remark,
    )
    db.add(txn)
    await db.flush()
    return user, txn


async def debit_balance_for_refund(
    db: AsyncSession,
    user_id: str,
    amount: Decimal,
    *,
    related_order_id: str | None = None,
    remark: str | None = None,
) -> tuple[User, BillingTransaction, Decimal]:
    """充值退款冲正：从现金余额扣除（余额不足时扣到 0 为止），带流水。不 commit。

    返回 (user, 流水, 实际扣除金额)。
    """
    user = await _lock_user(db, user_id)
    before = d(user.balance_usd)
    actual = min(before, d(amount))
    user.balance_usd = q6(before - actual)
    txn = BillingTransaction(
        user_id=user_id,
        type=RECHARGE_REFUND,
        status="SUCCESS",
        amount_usd=q6(actual),
        trial_amount=Decimal("0"),
        balance_amount=q6(actual),
        billing_source="CASH",
        balance_before=before,
        balance_after=user.balance_usd,
        related_order_id=related_order_id,
        remark=remark,
    )
    db.add(txn)
    await db.flush()
    return user, txn, actual


async def grant_trial_credit(db: AsyncSession, user: User, amount: Decimal) -> None:
    """发放试用额度（注册/补领）。不 commit。"""
    before = d(user.trial_credit_usd)
    user.trial_credit_usd = q6(before + d(amount))
    db.add(BillingTransaction(
        user_id=user.id,
        type=ADMIN_ADJUSTMENT,
        status="SUCCESS",
        amount_usd=q6(d(amount)),
        trial_amount=q6(d(amount)),
        balance_amount=Decimal("0"),
        billing_source="TRIAL",
        trial_before=before,
        trial_after=user.trial_credit_usd,
        remark="trial credit grant",
    ))
    await db.flush()
