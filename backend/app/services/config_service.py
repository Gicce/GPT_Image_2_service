"""system_config K-V 读取服务（业务配置唯一来源，禁止把兑换率散落写死）。

所有读取带代码内默认值：表未建 / 键缺失 / 值非法时回退默认，保证启动即用。
写入一律走 set_config（带 updated_by 留痕），管理后台是唯一写入口。
"""

import logging
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import SystemConfig

logger = logging.getLogger(__name__)

DEFAULTS = {
    "credits_per_cny": "100",          # ¥1 = 100 CY 点
    "legacy_usd_to_credits": "700",    # 旧美元余额→点数迁移率；同时是 USD 兼容镜像回写率
    "trial_feature_enabled": "true",
    "trial_grant_credits": "500",
    "trial_campaign_version": "1",
    "target_margin": "0.70",
    "cost_safety_buffer": "0.10",
    "recharge_min_cny": "1",
    "recharge_max_cny": "5000",
}

INT_KEYS = {
    "credits_per_cny", "legacy_usd_to_credits", "trial_grant_credits",
    "trial_campaign_version", "recharge_min_cny", "recharge_max_cny",
}
DECIMAL_KEYS = {"target_margin", "cost_safety_buffer"}
BOOL_KEYS = {"trial_feature_enabled"}

CONFIG_DESCRIPTIONS = {
    "credits_per_cny": "人民币→CY 点数兑换率（¥1 = N 点）",
    "legacy_usd_to_credits": "旧美元余额→点数迁移兑换率（$1 = N 点）",
    "trial_feature_enabled": "新用户试用通道总开关",
    "trial_grant_credits": "试用赠送 CY 点数",
    "trial_campaign_version": "试用活动版本号",
    "target_margin": "目标毛利率（Price Guard 底线）",
    "cost_safety_buffer": "采购成本安全垫（成本 × (1+N) 参与毛利底线）",
    "recharge_min_cny": "单笔充值下限（人民币）",
    "recharge_max_cny": "单笔充值上限（人民币）",
}


def _coerce(key: str, raw: str):
    default = DEFAULTS[key]
    try:
        if key in INT_KEYS:
            return int(raw)
        if key in DECIMAL_KEYS:
            return Decimal(raw)
        if key in BOOL_KEYS:
            return str(raw).strip().lower() in ("1", "true", "yes", "on")
        return raw
    except (ValueError, InvalidOperation):
        logger.warning("system_config[%s]=%r 非法，回退默认 %s", key, raw, default)
        return _coerce(key, default)


async def get_raw_config(db: AsyncSession, key: str) -> str | None:
    row = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
    cfg = row.scalar_one_or_none()
    return cfg.value if cfg is not None else None


async def get_config(db: AsyncSession, key: str):
    """按键读取并按类型转换；缺失/非法回退代码默认值。"""
    raw = await get_raw_config(db, key)
    return _coerce(key, raw) if raw is not None else _coerce(key, DEFAULTS[key])


async def get_config_int(db: AsyncSession, key: str) -> int:
    value = await get_config(db, key)
    return int(value)


async def get_config_decimal(db: AsyncSession, key: str) -> Decimal:
    value = await get_config(db, key)
    return Decimal(value)


async def get_config_bool(db: AsyncSession, key: str) -> bool:
    value = await get_config(db, key)
    return bool(value)


async def get_credits_per_cny(db: AsyncSession) -> int:
    value = await get_config_int(db, "credits_per_cny")
    return value if value > 0 else 100


async def get_legacy_usd_to_credits(db: AsyncSession) -> int:
    value = await get_config_int(db, "legacy_usd_to_credits")
    return value if value > 0 else 700


async def set_config(
    db: AsyncSession, key: str, value: str, updated_by: str | None = None
) -> SystemConfig:
    """写入配置（upsert）。非法值由调用方（admin API）先校验；不 commit。"""
    if key not in DEFAULTS:
        raise KeyError(f"未知配置键: {key}")
    row = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
    cfg = row.scalar_one_or_none()
    if cfg is None:
        cfg = SystemConfig(
            key=key, value=value, updated_by=updated_by,
            description=CONFIG_DESCRIPTIONS.get(key),
        )
        db.add(cfg)
    else:
        cfg.value = value
        cfg.updated_by = updated_by
    await db.flush()
    return cfg


async def all_configs(db: AsyncSession) -> list[SystemConfig]:
    rows = await db.execute(select(SystemConfig))
    return list(rows.scalars().all())


async def seed_config_defaults(db: AsyncSession) -> int:
    """补齐缺失的配置键（幂等）。返回新增数量。"""
    created = 0
    for key, value in DEFAULTS.items():
        if await get_raw_config(db, key) is None:
            db.add(SystemConfig(
                key=key, value=value,
                description=CONFIG_DESCRIPTIONS.get(key),
                updated_by="system-seed",
            ))
            created += 1
    if created:
        await db.flush()
    return created
