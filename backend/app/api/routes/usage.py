import json
from typing import Optional, List
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.core.security import get_current_user
from app.core.redis import get_redis
from app.models.content import AIModel
from app.models.user import User, UserToken
from app.models.token import UsageLog

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class ImageUsageReport(BaseModel):
    model: str
    image_count: int = 1


class ChatUsageReport(BaseModel):
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


class AgentUsageReport(BaseModel):
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


class ToolUsageReport(BaseModel):
    tool: str
    quantity: int = 1
    tool_call_id: str


class EstimateItem(BaseModel):
    type: str  # "image", "agent", "postprocess"
    model: str
    image_count: int = 0
    quantity: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


class EstimateRequest(BaseModel):
    items: List[EstimateItem]


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _find_model_and_token(name: str, billing_type: str, user_id: str, db: AsyncSession):
    """Find an AIModel by name+billing_type, then match the user's token for that group."""
    result = await db.execute(
        select(AIModel).where(
            AIModel.name == name,
            AIModel.billing_type == billing_type,
            AIModel.is_enabled == True,
        )
    )
    model_cfg = result.scalar_one_or_none()
    if not model_cfg:
        raise HTTPException(status_code=404, detail=f"模型 {name} ({billing_type}) 不存在或已禁用")

    result = await db.execute(
        select(UserToken).where(
            UserToken.user_id == user_id,
            UserToken.group == model_cfg.group,
        )
    )
    user_token = result.scalar_one_or_none()
    if not user_token:
        raise HTTPException(status_code=403, detail=f"您没有 {model_cfg.group} 分组的使用权限")

    return model_cfg, user_token


def _calc_token_cost(model_cfg, input_tokens: int, output_tokens: int, cached_tokens: int) -> Decimal:
    """Calculate per_token cost in USD."""
    cost = Decimal("0")
    if model_cfg.price_input:
        cost += Decimal(model_cfg.price_input) * input_tokens / 1000
    if model_cfg.price_output:
        cost += Decimal(model_cfg.price_output) * output_tokens / 1000
    if model_cfg.price_cached and cached_tokens > 0:
        cost += Decimal(model_cfg.price_cached) * cached_tokens / 1000
    return cost.quantize(Decimal("0.000001"))


def _calc_call_cost(model_cfg, quantity: int) -> Decimal:
    """Calculate per_call cost in USD."""
    if model_cfg.price_per_call:
        return (Decimal(model_cfg.price_per_call) * quantity).quantize(Decimal("0.000001"))
    return Decimal("0")


# ── Image Usage Report ───────────────────────────────────────────────────────

@router.post("/report/image")
async def report_image_usage(
    req: ImageUsageReport,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    model_cfg, user_token = await _find_model_and_token(req.model, "per_call", user.id, db)

    cost = _calc_call_cost(model_cfg, req.image_count)
    if cost > 0:
        if user_token.balance_usd < cost:
            raise HTTPException(status_code=402, detail="余额不足")
        user_token.balance_usd -= cost

    log = UsageLog(
        user_id=user.id,
        model=req.model,
        usage_type="image",
        image_count=req.image_count,
        cost_usd=str(cost),
    )
    db.add(log)
    await db.commit()

    return {
        "cost_usd": str(cost),
        "balance_usd": str(user_token.balance_usd.quantize(Decimal("0.00"))),
        "group": model_cfg.group,
        "account_type": "trial" if user_token.is_trial else "paid",
    }


# ── Agent Usage Report ───────────────────────────────────────────────────────

@router.post("/report/agent")
async def report_agent_usage(
    req: AgentUsageReport,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    model_cfg, user_token = await _find_model_and_token(req.model, "per_token", user.id, db)

    cost = _calc_token_cost(model_cfg, req.input_tokens, req.output_tokens, req.cached_tokens)
    if cost > 0:
        if user_token.balance_usd < cost:
            raise HTTPException(status_code=402, detail="余额不足")
        user_token.balance_usd -= cost

    log = UsageLog(
        user_id=user.id,
        model=req.model,
        usage_type="agent",
        input_tokens=req.input_tokens,
        output_tokens=req.output_tokens,
        cached_tokens=req.cached_tokens,
        cost_usd=str(cost),
    )
    db.add(log)
    await db.commit()

    return {
        "cost_usd": str(cost),
        "balance_usd": str(user_token.balance_usd.quantize(Decimal("0.00"))),
        "group": model_cfg.group,
        "account_type": "trial" if user_token.is_trial else "paid",
    }


# ── Chat Usage Report (compat → agent) ──────────────────────────────────────

@router.post("/report/chat")
async def report_chat_usage(
    req: ChatUsageReport,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent_req = AgentUsageReport(
        model=req.model,
        input_tokens=req.input_tokens,
        output_tokens=req.output_tokens,
        cached_tokens=req.cached_tokens,
    )
    return await report_agent_usage(agent_req, user, db)


# ── Tool Usage Report ────────────────────────────────────────────────────────

@router.post("/report/tool")
async def report_tool_usage(
    req: ToolUsageReport,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Idempotency check via Redis
    idempotency_key = f"tool_report:{user.id}:{req.tool_call_id}"
    r = get_redis()
    cached = await r.get(idempotency_key)
    if cached:
        return json.loads(cached)

    model_cfg, user_token = await _find_model_and_token(req.tool, "per_call", user.id, db)

    cost = _calc_call_cost(model_cfg, req.quantity)
    if cost > 0:
        if user_token.balance_usd < cost:
            raise HTTPException(status_code=402, detail="余额不足")
        user_token.balance_usd -= cost

    log = UsageLog(
        user_id=user.id,
        model=req.tool,
        usage_type="postprocess",
        image_count=req.quantity,
        cost_usd=str(cost),
    )
    db.add(log)
    await db.commit()

    result = {
        "cost_usd": str(cost),
        "balance_usd": str(user_token.balance_usd.quantize(Decimal("0.00"))),
        "group": model_cfg.group,
        "account_type": "trial" if user_token.is_trial else "paid",
    }

    # Cache result for idempotency (24h TTL)
    await r.setex(idempotency_key, 86400, json.dumps(result))

    return result


# ── Cost Estimate ────────────────────────────────────────────────────────────

@router.post("/estimate")
async def estimate_usage(
    req: EstimateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Load all user tokens indexed by group
    ut_result = await db.execute(
        select(UserToken).where(UserToken.user_id == user.id)
    )
    user_tokens = {ut.group: ut for ut in ut_result.scalars().all()}

    # Accumulate required cost per group
    group_costs: dict = {}  # group -> {"required_usd": Decimal, "balance_usd": Decimal}

    for item in req.items:
        if item.type == "agent":
            result = await db.execute(
                select(AIModel).where(
                    AIModel.name == item.model,
                    AIModel.billing_type == "per_token",
                    AIModel.is_enabled == True,
                )
            )
            model_cfg = result.scalar_one_or_none()
            if not model_cfg:
                continue
            cost = _calc_token_cost(model_cfg, item.input_tokens, item.output_tokens, item.cached_tokens)
        elif item.type in ("image", "postprocess"):
            result = await db.execute(
                select(AIModel).where(
                    AIModel.name == item.model,
                    AIModel.billing_type == "per_call",
                    AIModel.is_enabled == True,
                )
            )
            model_cfg = result.scalar_one_or_none()
            if not model_cfg:
                continue
            qty = max(item.image_count, item.quantity, 1)
            cost = _calc_call_cost(model_cfg, qty)
        else:
            continue

        group = model_cfg.group
        if group not in group_costs:
            ut = user_tokens.get(group)
            group_costs[group] = {
                "required_usd": Decimal("0"),
                "balance_usd": ut.balance_usd if ut else Decimal("0"),
            }
        group_costs[group]["required_usd"] += cost

    # Build response
    total_cost = Decimal("0")
    can_run = True
    groups = []
    fail_messages = []

    for group, data in group_costs.items():
        enough = data["balance_usd"] >= data["required_usd"]
        if not enough:
            can_run = False
            fail_messages.append(f"{group} 余额不足")
        total_cost += data["required_usd"]
        groups.append({
            "group": group,
            "required_usd": str(data["required_usd"].quantize(Decimal("0.000001"))),
            "balance_usd": str(data["balance_usd"].quantize(Decimal("0.00"))),
            "enough": enough,
        })

    if total_cost == 0:
        can_run = True

    return {
        "can_run": can_run,
        "total_cost_usd": str(total_cost.quantize(Decimal("0.000001"))),
        "groups": groups,
        "message": "；".join(fail_messages) if fail_messages else ("免费" if total_cost == 0 else ""),
    }


# ── Usage Records ────────────────────────────────────────────────────────────

@router.get("/records")
async def get_usage_records(
    model: Optional[str] = None,
    usage_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(UsageLog).where(UsageLog.user_id == user.id)

    if model:
        query = query.where(UsageLog.model == model)

    if usage_type:
        # Compat: "chat" matches both "chat" and "agent" records
        if usage_type == "chat":
            query = query.where(UsageLog.usage_type.in_(["chat", "agent"]))
        else:
            query = query.where(UsageLog.usage_type == usage_type)

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Paginate
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
                "input_tokens": log.input_tokens,
                "output_tokens": log.output_tokens,
                "cached_tokens": log.cached_tokens,
                "cost_usd": log.cost_usd,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    }
