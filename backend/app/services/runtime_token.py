"""Runtime Token 共享池核心（1 Token → N Users）。

设计要点：
- 绑定真相在 runtime_token_assignments（多对多）；旧 token_inventory.is_assigned/assigned_to
  为 1:1 时代遗留，迁移后不再读写。
- 一个用户同一时刻至多一个 active 绑定（uq_assignment_one_active_per_user 部分唯一索引）；
  一个 Token 可被任意多用户共享绑定。
- Token 有效性 = 未禁用 AND (未过期) AND (额度未耗尽)；额度 = 该 Token 当前关联用户
  的累计 Image2 消费（usage_logs 聚合），quota NULL 表示无限。
- 默认 Token（is_default）每类型至多一个，切换在事务内先清旧再设新；
  默认只影响"新绑定"（新用户注册/新支付），已绑定用户不迁移。
- token_value 明文只留在服务端；对外仅经 mask_token 脱敏。
- 所有函数不 commit，由调用方提交。
"""

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.token import TokenInventory, TokenAssignmentLog, RuntimeTokenAssignment, UsageLog

logger = logging.getLogger(__name__)


class NoAvailableTokenError(Exception):
    """没有可用的（有效且未禁用）Token。"""


class TokenNotAssignableError(Exception):
    """指定的 Token 不存在 / 已失效，无法绑定。"""


def mask_token(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return value[:2] + "****"
    return value[:6] + "****" + value[-4:]


def _now():
    return datetime.now(timezone.utc)


async def get_token_used_usd(db: AsyncSession, token_id: str) -> Decimal:
    """Token 已用额度 = 当前 active 关联用户的累计 Image2 消费（USD）。

    局限（设计说明）：usage_logs 不记录 token 维度，按"当前在绑用户"聚合，
    用户解绑后其历史消耗不再计入该 Token。作为额度管控的近似值。
    """
    result = await db.execute(
        select(func.coalesce(func.sum(UsageLog.cost_usd), 0)).where(
            UsageLog.user_id.in_(
                select(RuntimeTokenAssignment.user_id).where(
                    RuntimeTokenAssignment.token_id == token_id,
                    RuntimeTokenAssignment.status == "active",
                )
            )
        )
    )
    return Decimal(str(result.scalar()))


async def token_effective_status(
    db: AsyncSession, t: TokenInventory, *, used_usd: Decimal | None = None
) -> str:
    """派生状态：disabled / expired / exhausted / active。"""
    if t.is_disabled:
        return "disabled"
    if t.expires_at is not None and t.expires_at <= datetime.now(timezone.utc):
        return "expired"
    if t.quota_usd is not None:
        used = used_usd if used_usd is not None else await get_token_used_usd(db, t.id)
        if Decimal(str(t.quota_usd)) > 0 and used >= Decimal(str(t.quota_usd)):
            return "exhausted"
    return "active"


async def is_token_assignable(db: AsyncSession, t: TokenInventory) -> bool:
    return await token_effective_status(db, t) == "active"


def _log(db: AsyncSession, token_id: str, user_id: str | None, action: str, source: str) -> None:
    db.add(TokenAssignmentLog(
        id=str(uuid.uuid4()),
        token_id=token_id,
        user_id=user_id,
        action=action,
        source=source,
    ))


async def get_user_active_assignment(db: AsyncSession, user_id: str) -> RuntimeTokenAssignment | None:
    result = await db.execute(
        select(RuntimeTokenAssignment).where(
            RuntimeTokenAssignment.user_id == user_id,
            RuntimeTokenAssignment.status == "active",
        )
    )
    return result.scalar_one_or_none()


async def get_user_active_token(db: AsyncSession, user_id: str) -> TokenInventory | None:
    """用户当前生效的 Token（含已禁用/过期的也返回，由调用方决定是否回落 Master）。"""
    assignment = await get_user_active_assignment(db, user_id)
    if assignment is None:
        return None
    return await db.get(TokenInventory, assignment.token_id)


async def get_assigned_token(db: AsyncSession, user_id: str) -> TokenInventory | None:
    """兼容入口：旧名保留（admin 用户详情等仍在用）。"""
    return await get_user_active_token(db, user_id)


async def resolve_default_token(db: AsyncSession, *, is_trial: bool) -> TokenInventory | None:
    """解析该类型的默认 Token（须仍有效：未禁用/未过期/额度未尽）。"""
    result = await db.execute(
        select(TokenInventory).where(
            TokenInventory.is_trial == is_trial,
            TokenInventory.is_default == True,
        ).limit(1)
    )
    token = result.scalar_one_or_none()
    if token is None:
        return None
    if not await is_token_assignable(db, token):
        return None
    return token


async def bind_token_to_user(
    db: AsyncSession,
    user_id: str,
    token: TokenInventory,
    *,
    source: str,
) -> tuple[TokenInventory, TokenInventory | None]:
    """将用户绑定到 Token（共享）：释放用户其它 active 绑定 → upsert 本绑定。

    幂等：用户已 active 绑定同一 Token 时直接返回 (token, None)。
    不 commit，由调用方提交。
    """
    if not await is_token_assignable(db, token):
        raise TokenNotAssignableError("Token 已失效（禁用/过期/额度耗尽），无法绑定")

    now = _now()
    released = None
    current = await get_user_active_assignment(db, user_id)
    if current is not None:
        current_token = await db.get(TokenInventory, current.token_id)
        if current.token_id == token.id:
            return token, None  # 幂等
        current.status = "released"
        current.released_at = now
        _log(db, current.token_id, user_id, "release", source)
        released = current_token

    existing = await db.execute(
        select(RuntimeTokenAssignment).where(
            RuntimeTokenAssignment.token_id == token.id,
            RuntimeTokenAssignment.user_id == user_id,
        )
    )
    assignment = existing.scalar_one_or_none()
    if assignment is None:
        db.add(RuntimeTokenAssignment(
            id=str(uuid.uuid4()),
            token_id=token.id,
            user_id=user_id,
            status="active",
            source=source,
            assigned_at=now,
        ))
    else:
        assignment.status = "active"
        assignment.source = source
        assignment.assigned_at = now
        assignment.released_at = None
    _log(db, token.id, user_id, "assign", source)
    return token, released


async def release_user_token(db: AsyncSession, user_id: str, *, source: str) -> TokenInventory | None:
    """解除用户当前 active 绑定。返回被释放的 Token（无绑定返回 None）。不 commit。"""
    assignment = await get_user_active_assignment(db, user_id)
    if assignment is None:
        return None
    assignment.status = "released"
    assignment.released_at = _now()
    _log(db, assignment.token_id, user_id, "release", source)
    return await db.get(TokenInventory, assignment.token_id)


async def ensure_paid_assignment(db: AsyncSession, user_id: str) -> TokenInventory | None:
    """支付成功后自动绑定：已有 active 正式绑定则不动；否则绑默认正式 Token。

    默认 Token 后续切换不影响已绑定用户（只作用于新绑定时刻）。
    无可用默认正式 Token 时记 warning 并跳过（余额照常入账，运行时回落 Master Token）。
    不 commit。
    """
    current = await get_user_active_assignment(db, user_id)
    if current is not None:
        token = await db.get(TokenInventory, current.token_id)
        if token is not None and not token.is_trial and not token.is_disabled:
            return token  # 已有正式绑定，保持不变（不随默认切换迁移）

    default_paid = await resolve_default_token(db, is_trial=False)
    if default_paid is None:
        logger.warning(
            "no effective default paid token; skip auto assignment for user %s", user_id
        )
        return None
    token, _released = await bind_token_to_user(db, user_id, default_paid, source="auto_paid")
    logger.info("auto bound default paid token %s to user %s", default_paid.id, user_id)
    return token


async def assign_runtime_token(
    db: AsyncSession,
    user_id: str,
    *,
    token_id: str | None = None,
    source: str,
) -> tuple[TokenInventory, TokenInventory | None]:
    """管理员为用户分配/更换 Token（共享模式）。

    token_id 省略时自动挑选默认正式 Token（无默认则最旧可用正式 Token）。
    """
    if token_id is not None:
        token = await db.get(TokenInventory, token_id)
        if token is None:
            raise TokenNotAssignableError("Token 不存在")
        return await bind_token_to_user(db, user_id, token, source=source)

    target = await resolve_default_token(db, is_trial=False)
    if target is None:
        result = await db.execute(
            select(TokenInventory)
            .where(
                TokenInventory.is_trial == False,
                TokenInventory.is_disabled == False,
                TokenInventory.expires_at.is_(None) | (TokenInventory.expires_at > datetime.now(timezone.utc)),
            )
            .order_by(TokenInventory.created_at)
            .limit(1)
        )
        target = result.scalar_one_or_none()
    if target is None:
        raise NoAvailableTokenError()
    return await bind_token_to_user(db, user_id, target, source=source)


def token_public_dict(t: TokenInventory, assigned_at: datetime | None = None) -> dict:
    return {
        "token_id": t.id,
        "name": t.name,
        "masked_token": mask_token(t.token_value),
        "is_trial": t.is_trial,
        "is_disabled": t.is_disabled,
        "assigned_at": assigned_at.isoformat() if assigned_at else None,
    }
