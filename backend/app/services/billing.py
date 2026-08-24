"""Image2 单模型计费核心（账务唯一真相源，CY Credits 点数制）。

设计要点：
- 业务真相通篇以 CY 点数（INT）记账：paid_credits / trial_credits / gift_credits。
  USD 列（balance_usd / trial_credit_usd / *_usd）降级为兼容镜像：每次点数变动后
  按 legacy_usd_to_credits 回写，供 V4.0.x 旧客户端与旧统计展示，不作为真相。
- 两阶段计费：authorize（额度预占，调用上游之前）→ settle（成功结算 / 失败退款）。
  authorize 可携带 quote_id 冻结报价单价（pricing_rules 快照），管理员事后改价
  不影响已报价任务。
- 并发安全：对 users 行 SELECT ... FOR UPDATE，同用户计费操作串行化，杜绝超扣/丢失更新。
- 幂等：billing_transactions.request_id 唯一约束 + 状态 CAS，一次请求最多扣一次款、最多退一次款。
- 消费优先级：trial → gift → paid，集中在本模块 consume_credits()，页面/路由层禁止自行决定。
- 结算成功时写 cost_margin_ledger 经营账快照（收入只计 paid 部分，trial/gift 记营销价值）。
"""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.billing import BillingTransaction, CostMarginLedger, PricingRule
from app.models.content import AIModel
from app.models.token import UsageLog
from app.models.user import User
from app.services import config_service
from app.services import pricing as pricing_service
from app.services import runtime_token as rt

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
    """paid + gift + trial 点数不足以支付本次调用。"""

    def __init__(self, required: int, available: int):
        self.required = required
        self.available = available
        super().__init__("点数不足，请充值后继续使用")


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
    """兼容展示价（USD 镜像）；计费真实价格走 pricing.resolve_unit_credits。"""
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


def consume_credits(user: User, total: int, *, allow_trial: bool = True) -> tuple[int, int, int]:
    """消费拆分（trial → gift → paid）。只做拆分计算，不落库；调用方保证余额充足。"""
    remaining = total
    trial_part = min(user.trial_credits, remaining) if allow_trial else 0
    remaining -= trial_part
    gift_part = min(user.gift_credits, remaining)
    remaining -= gift_part
    paid_part = min(user.paid_credits, remaining)
    remaining -= paid_part
    if remaining > 0:
        raise QuotaExhaustedError(total, user.trial_credits + user.gift_credits + user.paid_credits)
    return trial_part, gift_part, paid_part


def _source(trial_part: int, gift_part: int, paid_part: int) -> str:
    parts = [p for p in (trial_part, gift_part, paid_part) if p > 0]
    if len(parts) >= 2:
        return "MIXED"
    if trial_part > 0:
        return "TRIAL"
    if gift_part > 0:
        return "GIFT"
    if paid_part > 0:
        return "PAID"
    return "NONE"


def _category(source: str) -> str:
    return {"TRIAL": "trial", "GIFT": "gift", "PAID": "paid", "MIXED": "mixed", "NONE": "none"}.get(source, "paid")


def sync_legacy_mirrors(user: User, legacy_rate: int) -> None:
    """点数 → USD 兼容镜像回写（唯一写入口，杜绝漂移）。"""
    rate = Decimal(max(1, legacy_rate))
    user.balance_usd = q6(Decimal(int(user.paid_credits)) / rate)
    user.trial_credit_usd = q6(Decimal(int(user.trial_credits)) / rate)


def _txn_dict(txn: BillingTransaction, user: User | None = None) -> dict:
    out = {
        "id": txn.id,
        "request_id": txn.request_id,
        "type": txn.type,
        "status": txn.status,
        "model": txn.model,
        "image_count": txn.image_count,
        # CY Credits（V4.2 起业务真相）
        "unit_credits": txn.unit_credits,
        "amount_credits": txn.amount_credits,
        "trial_credits_part": txn.trial_credits_part,
        "gift_credits_part": txn.gift_credits_part,
        "paid_credits_part": txn.paid_credits_part,
        "quote_id": txn.quote_id,
        "pricing_rule_id": txn.pricing_rule_id,
        "pricing_rule_version": txn.pricing_rule_version,
        # USD 兼容镜像（旧客户端展示）
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
        out["paid_credits"] = user.paid_credits
        out["trial_credits"] = user.trial_credits
        out["gift_credits"] = user.gift_credits
        out["total_credits"] = user.paid_credits + user.trial_credits + user.gift_credits
    return out


async def _resolve_price(
    db: AsyncSession, user_id: str, image_count: int, quote_id: str | None, feature: str
) -> tuple[int, str | None, int | None, str | None]:
    """解析冻结单价。返回 (unit_credits, rule_id, rule_version, quote_id_used)。

    优先级：quote_id 命中且校验通过 → 报价冻结价；否则当前生效价。
    """
    frozen = await pricing_service.validate_quote(db, quote_id, user_id, image_count)
    if frozen is not None:
        return (
            int(frozen["unit_credits"]),
            frozen.get("pricing_rule_id"),
            frozen.get("pricing_rule_version"),
            frozen.get("quote_id"),
        )
    unit, rule = await pricing_service.resolve_unit_credits(db, feature)
    return unit, rule.id if rule else None, rule.version if rule else None, None


async def authorize_image2(
    db: AsyncSession,
    user_id: str,
    request_id: str,
    image_count: int,
    *,
    quote_id: str | None = None,
    feature: str = "image",
) -> tuple[BillingTransaction, User]:
    """额度预占：在调用上游之前原子扣除 trial/gift/paid 点数并写入 RESERVED 流水。

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

    try:
        unit_credits, rule_id, rule_version, quote_used = await _resolve_price(
            db, user_id, image_count, quote_id, feature
        )
    except pricing_service.NoPriceError as exc:
        raise ModelDisabledError("Image2 价格未配置") from exc

    cost = unit_credits * image_count
    legacy_rate = await config_service.get_legacy_usd_to_credits(db)
    rate = Decimal(legacy_rate)

    trial_part, gift_part, paid_part = consume_credits(
        user, cost, allow_trial=bool(cfg.trial_allowed)
    )

    user.trial_credits -= trial_part
    user.gift_credits -= gift_part
    user.paid_credits -= paid_part
    sync_legacy_mirrors(user, legacy_rate)

    txn = BillingTransaction(
        user_id=user_id,
        type=CHARGE,
        status="RESERVED",
        request_id=request_id,
        model=IMAGE2_MODEL_ID,
        image_count=image_count,
        unit_credits=unit_credits,
        amount_credits=cost,
        trial_credits_part=trial_part,
        gift_credits_part=gift_part,
        paid_credits_part=paid_part,
        quote_id=quote_used,
        pricing_rule_id=rule_id,
        pricing_rule_version=rule_version,
        unit_price_usd=q6(Decimal(unit_credits) / rate),
        amount_usd=q6(Decimal(cost) / rate),
        trial_amount=q6(Decimal(trial_part) / rate),
        balance_amount=q6(Decimal(paid_part) / rate),
        billing_source=_source(trial_part, gift_part, paid_part),
        balance_before=q6(Decimal(int(user.paid_credits + paid_part)) / rate),
        balance_after=user.balance_usd,
        trial_before=q6(Decimal(int(user.trial_credits + trial_part)) / rate),
        trial_after=user.trial_credit_usd,
    )
    db.add(txn)
    await db.flush()

    logger.info(
        "authorize request=%s user=%s count=%d cost=%dcr (trial=%d gift=%d paid=%d unit=%d rule=%s)",
        request_id, user_id, image_count, cost, trial_part, gift_part, paid_part,
        unit_credits, rule_id,
    )
    return txn, user


async def _write_margin_ledger(
    db: AsyncSession,
    txn: BillingTransaction,
    user: User,
    *,
    reserved_credits: int,
    charged_credits: int,
    released_credits: int,
    successful_units: int,
    failed_units: int,
) -> None:
    """结算成功时冻结经营账快照。不 commit。"""
    credits_per_cny = await config_service.get_credits_per_cny(db)
    credit_value = Decimal(1) / Decimal(credits_per_cny)

    rule = None
    if txn.pricing_rule_id:
        rule = await db.get(PricingRule, txn.pricing_rule_id)
    nominal = d(rule.nominal_unit_cost_rmb) if rule is not None else Decimal("0")
    safety = d(rule.safety_buffer) if rule is not None else await config_service.get_config_decimal(db, "cost_safety_buffer")
    provider_route = rule.provider_route if rule is not None else "unpriced"

    token = await rt.get_user_active_token(db, user.id)
    token_id = token.id if token is not None else None

    paid_value = (Decimal(int(txn.paid_credits_part)) * credit_value).quantize(SIX_PLACES)
    promo_value = (Decimal(int(txn.trial_credits_part + txn.gift_credits_part)) * credit_value).quantize(SIX_PLACES)
    actual_cost = (nominal * Decimal(successful_units)).quantize(SIX_PLACES)
    effective_unit = (nominal * (Decimal("1") + d(safety))).quantize(SIX_PLACES)
    effective_cost = (effective_unit * Decimal(successful_units)).quantize(SIX_PLACES)
    profit = (paid_value - actual_cost).quantize(SIX_PLACES)
    margin = (profit / paid_value).quantize(Decimal("0.0001")) if paid_value > 0 else None

    db.add(CostMarginLedger(
        billing_transaction_id=txn.id,
        request_id=txn.request_id,
        user_id=user.id,
        pricing_rule_id=txn.pricing_rule_id,
        pricing_rule_version=txn.pricing_rule_version,
        unit_credits=txn.unit_credits or 0,
        reserved_credits=reserved_credits,
        charged_credits=charged_credits,
        released_credits=released_credits,
        category=_category(txn.billing_source),
        credit_value_rmb=credit_value.quantize(SIX_PLACES),
        revenue_rmb=paid_value,
        promotional_value_rmb=promo_value,
        provider="packyapi",
        provider_route=provider_route,
        token_inventory_id=token_id,
        nominal_unit_cost_rmb=nominal.quantize(SIX_PLACES),
        safety_buffer=d(safety),
        effective_unit_cost_rmb=effective_unit,
        actual_cost_rmb=actual_cost,
        effective_cost_rmb=effective_cost,
        gross_profit_rmb=profit,
        gross_margin=margin,
        successful_units=successful_units,
        failed_units=failed_units,
        settled_at=datetime.now(timezone.utc),
    ))
    await db.flush()


async def settle_image2(
    db: AsyncSession,
    user_id: str,
    request_id: str,
    success: bool,
    final_image_count: int | None = None,
    failure_reason: str | None = None,
) -> tuple[BillingTransaction, User]:
    """结算预占：成功→按实际数量计费入账（多退少不补）+ 经营账快照；失败→全额退款。

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

    legacy_rate = await config_service.get_legacy_usd_to_credits(db)
    reserved_trial = int(txn.trial_credits_part)
    reserved_gift = int(txn.gift_credits_part)
    reserved_paid = int(txn.paid_credits_part)
    reserved_count = int(txn.image_count)
    # 兼容旧数据：V4.2 之前创建的预占无点数快照，按 USD 镜像反推
    if txn.unit_credits is None or txn.amount_credits == 0:
        unit_price = d(txn.unit_price_usd) if txn.unit_price_usd is not None else Decimal("0")
        txn.unit_credits = int((unit_price * Decimal(legacy_rate)).to_integral_value(rounding="ROUND_HALF_UP"))
        txn.amount_credits = int((d(txn.amount_usd) * Decimal(legacy_rate)).to_integral_value(rounding="ROUND_HALF_UP"))
        txn.trial_credits_part = int((d(txn.trial_amount) * Decimal(legacy_rate)).to_integral_value())
        txn.balance_amount = txn.balance_amount or Decimal("0")
        txn.paid_credits_part = int((d(txn.balance_amount) * Decimal(legacy_rate)).to_integral_value())
        txn.gift_credits_part = max(0, txn.amount_credits - txn.trial_credits_part - txn.paid_credits_part)
        reserved_trial, reserved_gift, reserved_paid = (
            txn.trial_credits_part, txn.gift_credits_part, txn.paid_credits_part
        )
    unit_credits = int(txn.unit_credits)

    if success:
        count = final_image_count if final_image_count is not None else reserved_count
        if count < 0:
            raise ValueError("final_image_count 不能为负")
        if count > reserved_count:
            raise ValueError("final_image_count 超过授权数量")
        final_cost = unit_credits * count

        # 按试用→赠送→正式优先顺序重算实际消耗
        consumed_trial = min(reserved_trial, final_cost)
        rem = final_cost - consumed_trial
        consumed_gift = min(reserved_gift, rem)
        rem -= consumed_gift
        consumed_paid = min(reserved_paid, rem)

        user.trial_credits += reserved_trial - consumed_trial
        user.gift_credits += reserved_gift - consumed_gift
        user.paid_credits += reserved_paid - consumed_paid
        sync_legacy_mirrors(user, legacy_rate)

        released = txn.amount_credits - final_cost
        txn.status = "SUCCESS"
        txn.image_count = count
        txn.amount_credits = final_cost
        txn.trial_credits_part = consumed_trial
        txn.gift_credits_part = consumed_gift
        txn.paid_credits_part = consumed_paid
        txn.billing_source = _source(consumed_trial, consumed_gift, consumed_paid)
        rate = Decimal(legacy_rate)
        txn.unit_price_usd = q6(Decimal(unit_credits) / rate)
        txn.amount_usd = q6(Decimal(final_cost) / rate)
        txn.trial_amount = q6(Decimal(consumed_trial) / rate)
        txn.balance_amount = q6(Decimal(consumed_paid) / rate)
        txn.balance_after = user.balance_usd
        txn.trial_after = user.trial_credit_usd

        usage = UsageLog(
            user_id=user_id,
            model=IMAGE2_MODEL_ID,
            usage_type="image",
            image_count=count,
            unit_price=q6(Decimal(unit_credits) / rate),
            cost_usd=q6(Decimal(final_cost) / rate),
            unit_credits=unit_credits,
            cost_credits=final_cost,
            request_id=request_id,
        )
        db.add(usage)
        await db.flush()
        txn.related_usage_id = usage.id

        await _write_margin_ledger(
            db, txn, user,
            reserved_credits=reserved_count * unit_credits,
            charged_credits=final_cost,
            released_credits=released,
            successful_units=count,
            failed_units=reserved_count - count,
        )
    else:
        user.trial_credits += reserved_trial
        user.gift_credits += reserved_gift
        user.paid_credits += reserved_paid
        sync_legacy_mirrors(user, legacy_rate)

        txn.status = "FAILED"
        txn.failure_reason = (failure_reason or "upstream failure")[:255]
        txn.balance_after = user.balance_usd
        txn.trial_after = user.trial_credit_usd

    await db.flush()
    logger.info(
        "settle request=%s user=%s success=%s status=%s amount=%dcr",
        request_id, user_id, success, txn.status, txn.amount_credits,
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
    legacy_rate = await config_service.get_legacy_usd_to_credits(db)
    rate = Decimal(legacy_rate)

    trial_back = int(txn.trial_credits_part)
    gift_back = int(txn.gift_credits_part)
    paid_back = int(txn.paid_credits_part)
    user.trial_credits += trial_back
    user.gift_credits += gift_back
    user.paid_credits += paid_back
    sync_legacy_mirrors(user, legacy_rate)

    txn.status = "REFUNDED"
    txn.balance_after = user.balance_usd
    txn.trial_after = user.trial_credit_usd
    txn.remark = reason

    refund_txn = BillingTransaction(
        user_id=txn.user_id,
        type=IMAGE2_REFUND,
        status="SUCCESS",
        request_id=None,
        model=txn.model,
        image_count=txn.image_count,
        unit_credits=txn.unit_credits,
        amount_credits=txn.amount_credits,
        trial_credits_part=trial_back,
        gift_credits_part=gift_back,
        paid_credits_part=paid_back,
        pricing_rule_id=txn.pricing_rule_id,
        pricing_rule_version=txn.pricing_rule_version,
        unit_price_usd=txn.unit_price_usd,
        amount_usd=txn.amount_usd,
        trial_amount=txn.trial_amount,
        balance_amount=txn.balance_amount,
        billing_source=txn.billing_source,
        balance_after=user.balance_usd,
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
    legacy_rate = await config_service.get_legacy_usd_to_credits(db)
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
            user.trial_credits += int(txn.trial_credits_part)
            user.gift_credits += int(txn.gift_credits_part)
            user.paid_credits += int(txn.paid_credits_part)
            sync_legacy_mirrors(user, legacy_rate)
            txn.status = "RELEASED"
            txn.remark = "auto released (reservation timeout)"
            txn.balance_after = user.balance_usd
            txn.trial_after = user.trial_credit_usd
            released += 1
        except Exception:
            logger.exception("release stale reservation %s failed", txn.request_id)
    if released:
        await db.commit()
        logger.info("released %d stale reservations", released)
    return released


async def credit_paid_credits(
    db: AsyncSession,
    user_id: str,
    credits: int,
    txn_type: str,
    *,
    related_order_id: str | None = None,
    remark: str | None = None,
) -> tuple[User, BillingTransaction]:
    """充值入账正式点数（带流水）。不 commit。"""
    if credits <= 0:
        raise ValueError("credits 必须 > 0")
    user = await _lock_user(db, user_id)
    legacy_rate = await config_service.get_legacy_usd_to_credits(db)
    user.paid_credits += int(credits)
    sync_legacy_mirrors(user, legacy_rate)
    rate = Decimal(legacy_rate)
    txn = BillingTransaction(
        user_id=user_id,
        type=txn_type,
        status="SUCCESS",
        amount_credits=int(credits),
        paid_credits_part=int(credits),
        amount_usd=q6(Decimal(int(credits)) / rate),
        balance_amount=q6(Decimal(int(credits)) / rate),
        billing_source="PAID",
        balance_after=user.balance_usd,
        related_order_id=related_order_id,
        remark=remark,
    )
    db.add(txn)
    await db.flush()
    return user, txn


# 兼容旧名（历史调用方）
credit_balance = credit_paid_credits


async def debit_paid_credits_for_refund(
    db: AsyncSession,
    user_id: str,
    credits: int,
    *,
    related_order_id: str | None = None,
    remark: str | None = None,
) -> tuple[User, BillingTransaction, int]:
    """充值退款冲正：从正式点数扣除（点数不足时扣到 0 为止），带流水。不 commit。

    返回 (user, 流水, 实际扣除点数)。
    """
    user = await _lock_user(db, user_id)
    legacy_rate = await config_service.get_legacy_usd_to_credits(db)
    actual = min(int(user.paid_credits), int(credits))
    user.paid_credits -= actual
    sync_legacy_mirrors(user, legacy_rate)
    rate = Decimal(legacy_rate)
    txn = BillingTransaction(
        user_id=user_id,
        type=RECHARGE_REFUND,
        status="SUCCESS",
        amount_credits=actual,
        paid_credits_part=actual,
        amount_usd=q6(Decimal(actual) / rate),
        balance_amount=q6(Decimal(actual) / rate),
        billing_source="PAID",
        balance_after=user.balance_usd,
        related_order_id=related_order_id,
        remark=remark,
    )
    db.add(txn)
    await db.flush()
    return user, txn, actual


# 兼容旧名
debit_balance_for_refund = debit_paid_credits_for_refund


async def grant_trial_credits(db: AsyncSession, user: User, credits: int) -> None:
    """发放试用点数（注册/补领/试用申请）。不 commit。"""
    if credits <= 0:
        return
    legacy_rate = await config_service.get_legacy_usd_to_credits(db)
    user.trial_credits += int(credits)
    sync_legacy_mirrors(user, legacy_rate)
    rate = Decimal(legacy_rate)
    db.add(BillingTransaction(
        user_id=user.id,
        type=ADMIN_ADJUSTMENT,
        status="SUCCESS",
        amount_credits=int(credits),
        trial_credits_part=int(credits),
        amount_usd=q6(Decimal(int(credits)) / rate),
        trial_amount=q6(Decimal(int(credits)) / rate),
        billing_source="TRIAL",
        trial_after=user.trial_credit_usd,
        remark="trial credits grant",
    ))
    await db.flush()


# 兼容旧名
grant_trial_credit = grant_trial_credits


async def grant_gift_credits(
    db: AsyncSession, user: User, credits: int, *, remark: str = "gift credits grant"
) -> None:
    """发放赠送点数（活动/运营）。不 commit。"""
    if credits <= 0:
        return
    legacy_rate = await config_service.get_legacy_usd_to_credits(db)
    user.gift_credits += int(credits)
    sync_legacy_mirrors(user, legacy_rate)
    db.add(BillingTransaction(
        user_id=user.id,
        type=ADMIN_ADJUSTMENT,
        status="SUCCESS",
        amount_credits=int(credits),
        gift_credits_part=int(credits),
        billing_source="GIFT",
        balance_after=user.balance_usd,
        remark=remark,
    ))
    await db.flush()
