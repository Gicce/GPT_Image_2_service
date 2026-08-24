"""Image2 计费端点：authorize（生成前预占）→ settle（生成后结算/退款）。

额度不足在 authorize 阶段即被拒绝（HTTP 402 + QUOTA_EXHAUSTED），
保证"现金余额 + 试用额度"不足时绝不会调用上游 Image2。
"""

from typing import Optional
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.token import UsageLog
from app.services import billing

router = APIRouter()


class AuthorizeRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=64)
    image_count: int = Field(gt=0, le=100)
    # 报价冻结：携带 /api/billing/quote 返回的 quote_id 时按报价单价计费（参数不符则按当前价）
    quote_id: Optional[str] = Field(default=None, max_length=36)
    feature: str = Field(default="image", max_length=32)


class SettleRequest(BaseModel):
    request_id: str
    success: bool
    image_count: Optional[int] = Field(default=None, ge=0, le=100)
    failure_reason: Optional[str] = Field(default=None, max_length=255)


def _quota_http_error(exc: billing.QuotaExhaustedError) -> HTTPException:
    return HTTPException(
        status_code=402,
        detail={"code": "QUOTA_EXHAUSTED", "message": "点数不足，请充值后继续使用"},
    )


@router.post("/authorize")
async def authorize_usage(
    req: AuthorizeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    try:
        txn, u = await billing.authorize_image2(
            db, user.id, req.request_id, req.image_count,
            quote_id=req.quote_id, feature=req.feature,
        )
    except billing.QuotaExhaustedError as exc:
        raise _quota_http_error(exc) from exc
    except billing.ModelDisabledError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "IMAGE2_DISABLED", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return billing._txn_dict(txn, u)


@router.post("/settle")
async def settle_usage(
    req: SettleRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        txn, u = await billing.settle_image2(
            db, user.id, req.request_id, req.success,
            final_image_count=req.image_count,
            failure_reason=req.failure_reason,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return billing._txn_dict(txn, u)


# ── Usage Stats (summary / trend / models) ───────────────────────────────────
# 所有统计与 /records 明细来自同一张 usage_logs 账单底表，保证余额/趋势/模型/明细一致。

MAX_TREND_DAYS = 366

VALID_METRICS = {"image_count", "request_count", "cost"}


def _parse_date_param(value: str) -> datetime:
    try:
        d = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
    return d


def _resolve_range(start_time: Optional[str], end_time: Optional[str]) -> tuple[datetime, datetime, int]:
    """start/end 均为 YYYY-MM-DD（UTC 日期，闭区间）。缺省时回退到最近 7 天。"""
    if not start_time or not end_time:
        end_dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        start_dt = end_dt - timedelta(days=7)
    else:
        start_dt = _parse_date_param(start_time)
        end_dt = _parse_date_param(end_time) + timedelta(days=1)
    if end_dt <= start_dt:
        raise HTTPException(status_code=400, detail="结束日期必须晚于开始日期")
    days = (end_dt - start_dt).days
    if days > MAX_TREND_DAYS:
        raise HTTPException(status_code=400, detail=f"时间范围一次最多 {MAX_TREND_DAYS} 天")
    return start_dt, end_dt, days


@router.get("/summary")
async def get_usage_summary(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    start_dt, end_dt, _ = _resolve_range(start_time, end_time)

    period_result = await db.execute(
        select(
            func.count(UsageLog.id),
            func.coalesce(func.sum(UsageLog.image_count), 0),
            func.coalesce(func.sum(UsageLog.cost_usd), 0),
        ).where(
            UsageLog.user_id == user.id,
            UsageLog.created_at >= start_dt,
            UsageLog.created_at < end_dt,
        )
    )
    request_count, image_count, period_cost = period_result.one()

    total_result = await db.execute(
        select(func.coalesce(func.sum(UsageLog.cost_usd), 0)).where(UsageLog.user_id == user.id)
    )
    total_spent = total_result.scalar()

    return {
        "period_spent": str(period_cost),
        "total_spent": str(total_spent),
        "request_count": request_count,
        "image_count": image_count,
        "start_time": start_dt.strftime("%Y-%m-%d"),
        "end_time": (end_dt - timedelta(days=1)).strftime("%Y-%m-%d"),
    }


@router.get("/trend")
async def get_usage_trend(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    metric: str = "image_count",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if metric not in VALID_METRICS:
        raise HTTPException(status_code=400, detail=f"metric 仅支持 {'/'.join(sorted(VALID_METRICS))}")
    start_dt, end_dt, days = _resolve_range(start_time, end_time)

    value_expr = {
        "image_count": func.coalesce(func.sum(UsageLog.image_count), 0),
        "request_count": func.count(UsageLog.id),
        "cost": func.coalesce(func.sum(UsageLog.cost_usd), 0),
    }[metric]
    day_expr = func.to_char(UsageLog.created_at, "YYYY-MM-DD").label("day")

    rows = await db.execute(
        select(day_expr, value_expr.label("value")).where(
            UsageLog.user_id == user.id,
            UsageLog.created_at >= start_dt,
            UsageLog.created_at < end_dt,
        ).group_by(day_expr)
    )
    by_day = {row.day: row.value for row in rows}

    # 补零：缺失日期必须显式为 0，不允许图表把 13 号直接连到 15 号
    points = []
    cursor = start_dt
    for _ in range(days):
        key = cursor.strftime("%Y-%m-%d")
        raw = by_day.get(key, 0)
        points.append({"date": key, "value": float(raw) if metric == "cost" else int(raw)})
        cursor += timedelta(days=1)

    return {"metric": metric, "points": points}


@router.get("/models")
async def get_usage_models(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    start_dt, end_dt, _ = _resolve_range(start_time, end_time)

    rows = await db.execute(
        select(
            UsageLog.model,
            UsageLog.usage_type,
            func.count(UsageLog.id).label("request_count"),
            func.coalesce(func.sum(UsageLog.image_count), 0).label("image_count"),
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label("cost_usd"),
        ).where(
            UsageLog.user_id == user.id,
            UsageLog.created_at >= start_dt,
            UsageLog.created_at < end_dt,
        ).group_by(UsageLog.model, UsageLog.usage_type)
        .order_by(func.sum(UsageLog.cost_usd).desc())
    )

    return [
        {
            "model": row.model,
            "usage_type": row.usage_type,
            "request_count": row.request_count,
            "image_count": row.image_count,
            "cost_usd": str(row.cost_usd),
        }
        for row in rows
    ]


@router.get("/records")
async def get_usage_records(
    model: Optional[str] = None,
    usage_type: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(UsageLog).where(UsageLog.user_id == user.id)

    if model:
        query = query.where(UsageLog.model == model)
    if usage_type:
        query = query.where(UsageLog.usage_type == usage_type)
    if start_time or end_time:
        start_dt, end_dt, _ = _resolve_range(start_time, end_time)
        query = query.where(UsageLog.created_at >= start_dt, UsageLog.created_at < end_dt)

    page = max(1, page)
    page_size = max(1, min(100, page_size))

    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    query = query.order_by(UsageLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    logs = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "records": [
            {
                "id": log.id,
                "model": log.model,
                "usage_type": log.usage_type,
                "image_count": log.image_count,
                "unit_price": str(log.unit_price) if log.unit_price is not None else None,
                "cost_usd": log.cost_usd,
                "unit_credits": log.unit_credits,
                "cost_credits": log.cost_credits,
                "request_id": log.request_id,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    }
