"""Trial Entitlement 用户侧端点：试用状态查询 + 一次性领取。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.services import trial as trial_service

router = APIRouter()


@router.get("/status")
async def trial_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await trial_service.trial_status_for_user(db, user)


@router.post("/claim")
async def claim_trial(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await trial_service.claim_trial_for_user(db, user)
    except trial_service.TrialClaimError as exc:
        status = 409 if exc.code == trial_service.REASON_ALREADY_CLAIMED else 403
        raise HTTPException(
            status_code=status,
            detail={"code": f"TRIAL_{exc.code.upper()}", "message": exc.message},
        ) from exc
    return result
