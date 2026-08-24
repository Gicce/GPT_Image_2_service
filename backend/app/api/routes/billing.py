"""CY Credits 用户侧端点：报价（quote）+ 钱包/流水查询。

- POST /api/billing/quote：生成任务报价（10 分钟冻结）；所有付费生成入口
  在真正提交前必须先取报价，禁止客户端自行 数量×单价 计算
- GET /api/billing/wallet：三类点数余额 + 兑换率
- GET /api/billing/ledger：账户流水（充值/消费/释放/退款/试用/赠送，统一中文标签）
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.billing import BillingTransaction
from app.models.user import User
from app.services import config_service
from app.services import pricing as pricing_service

router = APIRouter()


class QuoteRequest(BaseModel):
    feature: str = Field(default="image", max_length=32)
    image_count: int = Field(gt=0, le=100)
    model: Optional[str] = Field(default=None, max_length=64)


@router.post("/quote")
async def create_quote(
    req: QuoteRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    try:
        quote = await pricing_service.create_quote(db, user.id, req.feature, req.image_count)
    except pricing_service.NoPriceError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "IMAGE2_DISABLED", "message": "生成服务未开放，请稍后再试"},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    credits_per_cny = await config_service.get_credits_per_cny(db)
    total = user.paid_credits + user.trial_credits + user.gift_credits
    quote["balance_snapshot"] = {
        "paid_credits": user.paid_credits,
        "trial_credits": user.trial_credits,
        "gift_credits": user.gift_credits,
        "total_credits": total,
        "credits_per_cny": credits_per_cny,
        "sufficient": total >= quote["estimated_credits"],
        "remaining_after": total - quote["estimated_credits"],
    }
    return quote


@router.get("/wallet")
async def get_wallet(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    credits_per_cny = await config_service.get_credits_per_cny(db)
    return {
        "paid_credits": user.paid_credits,
        "trial_credits": user.trial_credits,
        "gift_credits": user.gift_credits,
        "total_credits": user.paid_credits + user.trial_credits + user.gift_credits,
        "credits_per_cny": credits_per_cny,
    }


LEDGER_TYPE_LABELS = {
    "IMAGE2_CHARGE": "图片生成",
    "IMAGE2_REFUND": "生成退款",
    "RECHARGE": "充值",
    "RECHARGE_REFUND": "充值退款",
    "ADMIN_ADJUSTMENT": "管理员调整",
    "MIGRATION": "余额迁移",
}


@router.get("/ledger")
async def get_ledger(
    type: Optional[str] = Query(default=None, max_length=32),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(BillingTransaction).where(BillingTransaction.user_id == user.id)
    if type:
        query = query.where(BillingTransaction.type == type)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()

    rows = await db.execute(
        query.order_by(BillingTransaction.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    txns = rows.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "records": [
            {
                "id": t.id,
                "type": t.type,
                "type_label": LEDGER_TYPE_LABELS.get(t.type, t.type),
                "status": t.status,
                # 有向金额：正=入账（充值/退款/释放），负=消费；单位 CY 点
                "amount_credits": (
                    -t.amount_credits if t.type == "IMAGE2_CHARGE" and t.status in ("RESERVED", "SUCCESS")
                    else t.amount_credits
                ),
                "trial_credits_part": t.trial_credits_part,
                "gift_credits_part": t.gift_credits_part,
                "paid_credits_part": t.paid_credits_part,
                "unit_credits": t.unit_credits,
                "image_count": t.image_count,
                "request_id": t.request_id,
                "related_order_id": t.related_order_id,
                "failure_reason": t.failure_reason,
                "remark": t.remark,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in txns
        ],
    }
