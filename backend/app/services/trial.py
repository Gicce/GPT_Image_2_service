"""Trial Entitlement V1：新用户试用一次性领取（Claim Ledger 锚定 normalized email）。

规则：
- 每个真实邮箱生命周期只能领取一次（trial_claims.normalized_email 唯一约束），
  删除账号 / 重新注册均不可重复领取
- 领取前提（全部满足才 trial_available=true）：
    trial_feature_enabled 开启
    AND 试用默认 Token 存在且有效（未禁用/未过期/额度未耗尽）
- 首次申请自动通过：发放 trial_grant_credits 点数 + 绑定试用默认 Token
- 并发双击由数据库唯一约束兜底（IntegrityError → ALREADY_CLAIMED）
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trial import TrialClaim
from app.models.user import User
from app.services import billing
from app.services import config_service
from app.services import runtime_token as rt

logger = logging.getLogger(__name__)

TRIAL_VALID_DAYS = 2

REASON_OK = "ok"
REASON_DISABLED = "trial_disabled"                    # 试用通道总开关关闭
REASON_NO_TOKEN = "trial_token_unavailable"           # 无有效试用默认 Token
REASON_ALREADY_CLAIMED = "already_claimed"            # 该邮箱已领取过
REASON_INELIGIBLE_ACCOUNT = "account_ineligible"      # 当前账号状态不允许（已付费等）


def normalize_email(email: str) -> str:
    """规范化：trim + lowercase（与注册链路 users.email 存储规范一致）。"""
    return (email or "").strip().lower()


async def get_claim_by_email(db: AsyncSession, email: str) -> TrialClaim | None:
    normalized = normalize_email(email)
    if not normalized:
        return None
    result = await db.execute(
        select(TrialClaim).where(TrialClaim.normalized_email == normalized)
    )
    return result.scalar_one_or_none()


async def trial_availability(db: AsyncSession) -> dict:
    """试用通道开放判定（不含单账号领取状态）。"""
    enabled = await config_service.get_config_bool(db, "trial_feature_enabled")
    if not enabled:
        return {"available": False, "reason": REASON_DISABLED}

    token = await rt.resolve_default_token(db, is_trial=True)
    if token is None:
        return {"available": False, "reason": REASON_NO_TOKEN}

    return {"available": True, "reason": REASON_OK, "token_id": token.id}


async def trial_status_for_user(db: AsyncSession, user: User) -> dict:
    """客户端展示用：入口是否可见 + 当前账号领取状态。"""
    availability = await trial_availability(db)
    claim = await get_claim_by_email(db, user.email)
    grant = await config_service.get_config_int(db, "trial_grant_credits")
    campaign = await config_service.get_config_int(db, "trial_campaign_version")

    trial_available = availability["available"] and claim is None
    reason = availability["reason"]
    if availability["available"] and claim is not None:
        reason = REASON_ALREADY_CLAIMED

    return {
        "trial_available": trial_available,
        "reason": reason,
        "already_claimed": claim is not None,
        "claimed_at": claim.claimed_at.isoformat() if claim is not None else None,
        "grant_credits": grant,
        "campaign_version": campaign,
    }


class TrialClaimError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


async def record_trial_claim(
    db: AsyncSession, user: User, grant_credits: int, *, source: str
) -> TrialClaim:
    """写入 claim 记录；同邮箱重复（含并发双击）抛 TrialClaimError(ALREADY_CLAIMED)。

    用 SAVEPOINT 包裹：唯一约束冲突只回滚本插入，不破坏调用方事务。不 commit。
    """
    claim = TrialClaim(
        normalized_email=normalize_email(user.email),
        user_id_at_claim=user.id,
        grant_credits=grant_credits,
        campaign_version=await config_service.get_config_int(db, "trial_campaign_version"),
        source=source,
    )
    try:
        async with db.begin_nested():
            db.add(claim)
            await db.flush()
    except IntegrityError as exc:
        raise TrialClaimError(
            REASON_ALREADY_CLAIMED, "该邮箱已领取过新用户试用"
        ) from exc
    return claim


async def claim_trial_for_user(db: AsyncSession, user: User) -> dict:
    """「申请免费试用」主入口：自动通过 + 一次性领取。调用方 commit。"""
    if not user.is_active:
        raise TrialClaimError(REASON_INELIGIBLE_ACCOUNT, "账号已被禁用")
    if user.account_type == "paid":
        raise TrialClaimError(REASON_INELIGIBLE_ACCOUNT, "当前账号为正式账号，无需试用")

    availability = await trial_availability(db)
    if not availability["available"]:
        raise TrialClaimError(
            availability["reason"],
            "试用通道暂未开放，请稍后再试" if availability["reason"] == REASON_NO_TOKEN
            else "试用活动未开启",
        )

    existing = await get_claim_by_email(db, user.email)
    if existing is not None:
        raise TrialClaimError(REASON_ALREADY_CLAIMED, "该邮箱已领取过新用户试用")

    grant = await config_service.get_config_int(db, "trial_grant_credits")
    token = await rt.resolve_default_token(db, is_trial=True)

    claim = await record_trial_claim(db, user, grant, source="account_claim")
    await rt.bind_token_to_user(db, user.id, token, source="register_trial")
    user.account_type = "trial"
    user.trial_expires_at = datetime.now(timezone.utc) + timedelta(days=TRIAL_VALID_DAYS)
    await billing.grant_trial_credits(db, user, grant)

    logger.info("trial claimed user=%s email=%s grant=%dcr", user.id, claim.normalized_email, grant)
    return {
        "granted": True,
        "grant_credits": grant,
        "claim_id": claim.id,
        "campaign_version": claim.campaign_version,
    }
