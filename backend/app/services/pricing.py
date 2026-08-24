"""Pricing Engine：CY Credits 唯一定价来源 + 报价冻结 + 毛利计算。

- 售价来源：pricing_rules 当前生效规则；规则表缺失时回退
  ai_models.price_per_call × legacy_usd_to_credits（兼容窗口，保证可用性）
- 报价（quote）：生成后存 Redis（TTL 10 分钟），authorize 凭 quote_id 取回
  服务端冻结单价——客户端传来的任何金额字段一律不参与计价
- 毛利数学（Price Guard 同一套公式）：
    revenue_rmb          = unit_credits / credits_per_cny
    effective_unit_cost  = nominal_unit_cost_rmb × (1 + safety_buffer)
    gross_profit         = revenue_rmb - effective_unit_cost
    gross_margin         = gross_profit / revenue_rmb
    min_unit_credits     = ceil_step(effective_unit_cost / (1 - target_margin) × credits_per_cny)
"""

import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.models.billing import PricingRule
from app.models.content import AIModel
from app.services import config_service

QUOTE_TTL_SECONDS = 600
FEATURE_IMAGE = "image"
KNOWN_FEATURES = {FEATURE_IMAGE}


class NoPriceError(Exception):
    """无可用定价（规则表与 ai_models 均缺失）。"""


def ceil_to_step(value: float, step: int) -> int:
    if step <= 1:
        return math.ceil(value)
    return int(math.ceil(value / step) * step)


async def get_active_rule(db: AsyncSession, feature: str = FEATURE_IMAGE) -> PricingRule | None:
    result = await db.execute(
        select(PricingRule).where(
            PricingRule.feature == feature,
            PricingRule.enabled.is_(True),
        ).order_by(PricingRule.model)
    )
    return result.scalars().first()


async def resolve_unit_credits(db: AsyncSession, feature: str = FEATURE_IMAGE) -> tuple[int, PricingRule | None]:
    """解析当前单张点数价。返回 (unit_credits, rule|null)。

    rule 为 None 表示走 ai_models 兼容回退（无规则时期）。
    """
    rule = await get_active_rule(db, feature)
    if rule is not None and rule.unit_credits > 0:
        return int(rule.unit_credits), rule

    legacy_rate = await config_service.get_legacy_usd_to_credits(db)
    result = await db.execute(select(AIModel).where(AIModel.name == "gpt-image-2"))
    cfg = result.scalar_one_or_none()
    if cfg is not None and cfg.price_per_call is not None:
        unit = int((Decimal(str(cfg.price_per_call)) * Decimal(legacy_rate)).to_integral_value(rounding="ROUND_HALF_UP"))
        if unit > 0:
            return unit, None
    raise NoPriceError("无可用定价规则")


def margin_math(
    unit_credits: int,
    nominal_unit_cost_rmb: Decimal | float,
    target_margin: Decimal | float,
    safety_buffer: Decimal | float,
    credits_per_cny: int,
    rounding_step: int = 10,
) -> dict:
    """单张毛利测算（Price Guard 与后台编辑预览共用）。金额单位人民币元。"""
    nominal = Decimal(str(nominal_unit_cost_rmb))
    target = Decimal(str(target_margin))
    buffer = Decimal(str(safety_buffer))
    cpc = Decimal(max(1, int(credits_per_cny)))

    revenue = (Decimal(unit_credits) / cpc).quantize(Decimal("0.000001"))
    effective_unit_cost = (nominal * (Decimal("1") + buffer)).quantize(Decimal("0.000001"))
    profit = (revenue - effective_unit_cost).quantize(Decimal("0.000001"))
    margin = (profit / revenue).quantize(Decimal("0.0001")) if revenue > 0 else None

    min_unit_credits = 0
    if target < Decimal("1"):
        raw_min = effective_unit_cost / (Decimal("1") - target) * cpc
        min_unit_credits = ceil_to_step(float(raw_min), rounding_step)

    return {
        "unit_credits": unit_credits,
        "revenue_rmb": str(revenue),
        "nominal_unit_cost_rmb": str(nominal.quantize(Decimal("0.000001"))),
        "effective_unit_cost_rmb": str(effective_unit_cost),
        "gross_profit_rmb": str(profit),
        "gross_margin": str(margin) if margin is not None else None,
        "target_margin": str(target),
        "safety_buffer": str(buffer),
        "min_unit_credits": min_unit_credits,
        "below_target": margin is None or margin < target,
    }


async def create_quote(
    db: AsyncSession,
    user_id: str,
    feature: str,
    image_count: int,
) -> dict:
    """生成报价（写 Redis，TTL 10 分钟）。返回可直接下发给客户端的报价体。"""
    if feature not in KNOWN_FEATURES:
        feature = FEATURE_IMAGE
    if image_count < 1:
        raise ValueError("image_count 必须 >= 1")

    unit_credits, rule = await resolve_unit_credits(db, feature)
    estimated = unit_credits * image_count

    quote_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=QUOTE_TTL_SECONDS)
    payload = {
        "quote_id": quote_id,
        "user_id": user_id,
        "feature": feature,
        "image_count": image_count,
        "unit_credits": unit_credits,
        "pricing_rule_id": rule.id if rule else None,
        "pricing_rule_version": rule.version if rule else None,
        "created_at": now.isoformat(),
    }
    redis = get_redis()
    if redis is not None:
        try:
            await redis.set(f"billing_quote:{quote_id}", json.dumps(payload), ex=QUOTE_TTL_SECONDS)
        except Exception:  # noqa: BLE001 - Redis 不可用时报价降级为无冻结
            quote_id = ""

    return {
        "quote_id": quote_id or None,
        "feature": feature,
        "model": rule.model if rule else "gpt-image-2",
        "unit_credits": unit_credits,
        "quantity": image_count,
        "estimated_credits": estimated,
        "pricing_rule_id": rule.id if rule else None,
        "pricing_rule_version": rule.version if rule else None,
        "expires_at": expires_at.isoformat(),
        "frozen": bool(quote_id),
    }


async def validate_quote(
    db: AsyncSession,
    quote_id: str | None,
    user_id: str,
    image_count: int,
) -> dict | None:
    """authorize 前校验报价：存在、未过期、归属当前用户、数量一致。

    返回冻结载荷；quote_id 为空 / Redis 丢失 / 过期 / 不匹配 → None（按当前价计）。
    """
    if not quote_id:
        return None
    redis = get_redis()
    if redis is None:
        return None
    try:
        raw = await redis.get(f"billing_quote:{quote_id}")
    except Exception:  # noqa: BLE001
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if payload.get("user_id") != user_id:
        return None
    if int(payload.get("image_count", -1)) != image_count:
        return None
    return payload
