"""Runtime Token 分配核心（TokenInventory ↔ User 绑定关系）。

设计要点：
- 一个用户同一时刻至多绑定一枚 Token（is_assigned=True 且 assigned_to=user.id）。
- 更换在单个数据库事务内完成：行锁旧 Token + 行锁目标 Token（skip_locked 防并发争抢），
  旧 Token 解绑、新 Token 绑定、写 token_assignment_logs，由调用方 commit。
- 任何失败（无可用 Token / 目标已被抢占）都会整体回滚，旧绑定保持不变。
- token_value 明文只留在服务端；对外仅经 mask_token 脱敏。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.token import TokenInventory, TokenAssignmentLog


class NoAvailableTokenError(Exception):
    """Token 池中没有可用的（未分配且未禁用）Token。"""


class TokenNotAssignableError(Exception):
    """指定的 Token 不存在 / 已分配给他人 / 已禁用。"""


def mask_token(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return value[:2] + "****"
    return value[:6] + "****" + value[-4:]


def token_public_dict(t: TokenInventory, user=None) -> dict:
    out = {
        "token_id": t.id,
        "masked_token": mask_token(t.token_value),
        "is_trial": t.is_trial,
        "is_disabled": t.is_disabled,
        "assigned_at": t.assigned_at.isoformat() if t.assigned_at else None,
    }
    if user is not None:
        out["assigned_user"] = {
            "id": user.id,
            "username": user.username,
            "email": user.email,
        }
    return out


def _log(db: AsyncSession, token_id: str, user_id: str | None, action: str, source: str) -> None:
    db.add(TokenAssignmentLog(
        id=str(uuid.uuid4()),
        token_id=token_id,
        user_id=user_id,
        action=action,
        source=source,
    ))


async def get_assigned_token(db: AsyncSession, user_id: str) -> TokenInventory | None:
    result = await db.execute(
        select(TokenInventory)
        .where(TokenInventory.assigned_to == user_id, TokenInventory.is_assigned == True)
        .order_by(TokenInventory.assigned_at.desc().nullslast())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def assign_runtime_token(
    db: AsyncSession,
    user_id: str,
    *,
    token_id: str | None = None,
    source: str,
) -> tuple[TokenInventory, TokenInventory | None]:
    """为用户绑定一枚可用 Token（可自动挑选或指定 token_id）。

    事务内完成：旧 Token 解绑（如有）→ 新 Token 绑定 → 写分配历史。
    返回 (新 Token, 被解绑的旧 Token | None)。不 commit，由调用方提交。
    """
    now = datetime.now(timezone.utc)

    # 1) 行锁用户当前 Token（如有），保证更换过程不被并发破坏
    current = await get_assigned_token(db, user_id)
    if current is not None:
        locked = await db.execute(
            select(TokenInventory)
            .where(TokenInventory.id == current.id)
            .with_for_update()
        )
        current = locked.scalar_one()
        if not current.is_assigned or current.assigned_to != user_id:
            current = None

    # 2) 行锁目标 Token
    if token_id is not None:
        target_res = await db.execute(
            select(TokenInventory)
            .where(TokenInventory.id == token_id)
            .with_for_update()
        )
        target = target_res.scalar_one_or_none()
        if target is None:
            raise TokenNotAssignableError("Token 不存在")
        if target.is_disabled:
            raise TokenNotAssignableError("Token 已禁用，无法分配")
        if target.is_assigned and target.assigned_to != user_id:
            raise TokenNotAssignableError("Token 已分配给其他用户")
        if current is not None and target.id == current.id:
            return target, None  # 幂等：重复分配当前 Token
    else:
        target_res = await db.execute(
            select(TokenInventory)
            .where(
                TokenInventory.is_assigned == False,
                TokenInventory.is_disabled == False,
                TokenInventory.is_trial == False,
            )
            .order_by(TokenInventory.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        target = target_res.scalar_one_or_none()
        if target is None:
            raise NoAvailableTokenError()

    # 3) 解绑旧 Token + 写历史
    released = None
    if current is not None and current.id != target.id:
        current.is_assigned = False
        current.assigned_to = None
        current.assigned_at = None
        _log(db, current.id, user_id, "release", source)
        released = current

    # 4) 绑定新 Token + 写历史
    if not target.is_assigned or target.assigned_to != user_id:
        target.is_assigned = True
        target.assigned_to = user_id
        target.assigned_at = now
        _log(db, target.id, user_id, "assign", source)

    return target, released
