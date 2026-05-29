import json
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.core.security import get_current_user
from app.models.content import AIModel
from app.models.token import UsageLog
from app.models.user import User, UserToken
from app.services.account import infer_group_from_model, normalize_model_type

router = APIRouter()


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
    request_id: str | None = None


class ToolUsageReport(BaseModel):
    tool: str
    quantity: int = 1
    tool_call_id: str


class EstimateItem(BaseModel):
    type: str
    model: Optional[str] = None
    tool: Optional[str] = None
    quantity: int = 0
    image_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


class EstimateRequest(BaseModel):
    items: list[EstimateItem]


def _decimal(value) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value))


async def _find_model(name: str, usage_type: str, db: AsyncSession) -> AIModel | None:
    models = (
        await db.execute(
            select(AIModel)
            .where(AIModel.name == name, AIModel.is_enabled == True)
            .order_by(AIModel.sort_order, AIModel.name)
        )
    ).scalars().all()
    if not models:
        return None
    if usage_type == "postprocess":
        for model in models:
            if normalize_model_type(model.model_type) == "postprocess":
                return model
    if usage_type == "image":
        for model in models:
            if normalize_model_type(model.model_type) == "image":
                return model
    if usage_type in {"agent", "chat"}:
        for model in models:
            if normalize_model_type(model.model_type) == "agent":
                return model
    return models[0]


async def _resolve_balance_bucket(user: User, group: str, db: AsyncSession) -> tuple[UserToken | None, str]:
    row = await db.execute(select(UserToken).where(UserToken.user_id == user.id, UserToken.group == group))
    user_token = row.scalar_one_or_none()
    if user_token:
        return user_token, "group"
    return None, "legacy"


def _token_balance_value(user: User, user_token: UserToken | None, bucket_type: str) -> Decimal:
    if bucket_type == "group" and user_token is not None:
        return _decimal(user_token.balance_usd)
    return _decimal(user.balance_usd)


def _apply_cost(user: User, user_token: UserToken | None, bucket_type: str, cost: Decimal) -> Decimal:
    if bucket_type == "group" and user_token is not None:
        next_balance = _decimal(user_token.balance_usd) - cost
        user_token.balance_usd = next_balance
        return next_balance
    next_balance = _decimal(user.balance_usd) - cost
    user.balance_usd = next_balance
    return next_balance


def _per_call_cost(model: AIModel, quantity: int) -> Decimal:
    price = _decimal(model.price_per_call or model.price_per_image)
    return (price * Decimal(max(quantity, 0))).quantize(Decimal("0.000001"))


def _per_token_cost(model: AIModel, input_tokens: int, output_tokens: int, cached_tokens: int) -> Decimal:
    cost = Decimal("0")
    cost += _decimal(model.price_input or model.price_input_per_m) * Decimal(input_tokens) / Decimal(1000)
    cost += _decimal(model.price_output or model.price_output_per_m) * Decimal(output_tokens) / Decimal(1000)
    cost += _decimal(model.price_cached or model.price_cached_per_m) * Decimal(cached_tokens) / Decimal(1000)
    return cost.quantize(Decimal("0.000001"))


async def _charge(
    user: User,
    model: AIModel,
    db: AsyncSession,
    usage_type: str,
    *,
    quantity: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_tokens: int = 0,
) -> tuple[Decimal, Decimal, str]:
    group = infer_group_from_model(model)
    user_token, bucket_type = await _resolve_balance_bucket(user, group, db)
    balance = _token_balance_value(user, user_token, bucket_type)
    if usage_type in {"image", "postprocess"}:
        cost = _per_call_cost(model, quantity)
    else:
        cost = _per_token_cost(model, input_tokens, output_tokens, cached_tokens)
    if cost > balance:
        raise HTTPException(status_code=402, detail="Insufficient balance")
    next_balance = _apply_cost(user, user_token, bucket_type, cost)
    return cost, next_balance, group


@router.post("/report/image")
async def report_image_usage(req: ImageUsageReport, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    model = await _find_model(req.model, "image", db)
    if model is None:
        raise HTTPException(status_code=404, detail=f"Model {req.model} not found")
    quantity = max(req.image_count, 1)
    cost, balance, group = await _charge(user, model, db, "image", quantity=quantity)
    db.add(UsageLog(user_id=user.id, model=req.model, usage_type="image", image_count=quantity, cost_usd=cost))
    await db.commit()
    return {"cost_usd": float(cost), "balance_usd": float(balance), "group": group, "account_type": user.account_type}


@router.post("/report/agent")
async def report_agent_usage(req: AgentUsageReport, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    model = await _find_model(req.model, "agent", db)
    if model is None:
        raise HTTPException(status_code=404, detail=f"Model {req.model} not found")
    cost, balance, group = await _charge(
        user,
        model,
        db,
        "agent",
        input_tokens=req.input_tokens,
        output_tokens=req.output_tokens,
        cached_tokens=req.cached_tokens,
    )
    db.add(
        UsageLog(
            user_id=user.id,
            model=req.model,
            usage_type="agent",
            input_tokens=req.input_tokens,
            output_tokens=req.output_tokens,
            cached_tokens=req.cached_tokens,
            cost_usd=cost,
        )
    )
    await db.commit()
    return {"cost_usd": float(cost), "balance_usd": float(balance), "group": group, "account_type": user.account_type}


@router.post("/report/chat")
async def report_chat_usage(req: ChatUsageReport, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await report_agent_usage(
        AgentUsageReport(
            model=req.model,
            input_tokens=req.input_tokens,
            output_tokens=req.output_tokens,
            cached_tokens=req.cached_tokens,
        ),
        user,
        db,
    )


@router.post("/report/tool")
async def report_tool_usage(req: ToolUsageReport, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    redis = get_redis()
    cache_key = f"tool_report:{user.id}:{req.tool_call_id}"
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    model = await _find_model(req.tool, "postprocess", db)
    if model is None:
        raise HTTPException(status_code=404, detail=f"Tool {req.tool} not found")
    quantity = max(req.quantity, 1)
    cost, balance, group = await _charge(user, model, db, "postprocess", quantity=quantity)
    db.add(UsageLog(user_id=user.id, model=req.tool, usage_type="postprocess", image_count=quantity, cost_usd=cost))
    await db.commit()
    result = {"cost_usd": float(cost), "balance_usd": float(balance), "group": group, "account_type": user.account_type}
    await redis.setex(cache_key, 86400, json.dumps(result))
    return result


@router.post("/estimate")
async def estimate_usage(req: EstimateRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    group_costs: dict[str, dict[str, Decimal]] = {}
    has_group_tokens = bool((await db.execute(select(UserToken.id).where(UserToken.user_id == user.id).limit(1))).scalar_one_or_none())

    for item in req.items:
        target_name = item.model or item.tool
        if not target_name:
            continue
        model = await _find_model(target_name, item.type, db)
        if model is None:
            continue
        group = infer_group_from_model(model)
        user_token = (
            await db.execute(select(UserToken).where(UserToken.user_id == user.id, UserToken.group == group))
        ).scalar_one_or_none()
        balance = _decimal(user_token.balance_usd) if user_token is not None else (_decimal(user.balance_usd) if not has_group_tokens else Decimal("0"))

        if item.type in {"image", "postprocess"}:
            qty = max(item.quantity, item.image_count, 1)
            cost = _per_call_cost(model, qty)
        else:
            cost = _per_token_cost(model, item.input_tokens, item.output_tokens, item.cached_tokens)

        group_costs.setdefault(group, {"required_usd": Decimal("0"), "balance_usd": balance})
        group_costs[group]["required_usd"] += cost

    total_cost = Decimal("0")
    groups = []
    can_run = True
    fail_messages = []
    for group, data in group_costs.items():
        enough = data["balance_usd"] >= data["required_usd"]
        if not enough:
            can_run = False
            fail_messages.append(f"{group} balance is insufficient")
        total_cost += data["required_usd"]
        groups.append(
            {
                "group": group,
                "required_usd": float(data["required_usd"].quantize(Decimal("0.000001"))),
                "balance_usd": float(data["balance_usd"].quantize(Decimal("0.00"))),
                "enough": enough,
            }
        )

    return {
        "can_run": can_run,
        "total_cost_usd": float(total_cost.quantize(Decimal("0.000001"))),
        "groups": groups,
        "message": "; ".join(fail_messages) if fail_messages else ("free" if total_cost == 0 else ""),
    }


@router.get("/records")
async def get_usage_records(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    logs = (
        await db.execute(
            select(UsageLog).where(UsageLog.user_id == user.id).order_by(UsageLog.created_at.desc()).limit(200)
        )
    ).scalars().all()
    result = []
    for log in logs:
        usage_type = "agent" if log.usage_type == "chat" else log.usage_type
        if usage_type in {"image", "postprocess"}:
            quantity = int(log.image_count or 0)
        else:
            quantity = int((log.input_tokens or 0) + (log.output_tokens or 0) + (log.cached_tokens or 0))
        result.append(
            {
                "model": log.model,
                "type": usage_type,
                "quantity": quantity,
                "cost_usd": float(log.cost_usd),
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
        )
    return result
