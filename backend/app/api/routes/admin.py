from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from datetime import datetime, timezone
from typing import Optional
import uuid

from app.core.database import get_db
from app.core.security import get_admin_user
from app.core.redis import get_redis
from app.core.config import settings
from app.core.security import hash_password
from app.models.user import User, UserToken
from app.models.token import TokenInventory, Order, UsageLog, OrderStatus
from app.models.content import Notice, Prompt, AIModel

router = APIRouter()


import re

# ── Token Inventory ──────────────────────────────────────────────

class TokenBatchInput(BaseModel):
    tokens: list[str]
    group: str
    is_trial: bool = False


@router.post("/tokens/batch")
async def add_tokens(req: TokenBatchInput, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    if not req.group:
        raise HTTPException(status_code=400, detail="必须指定分组")
    added = 0
    for t in req.tokens:
        t = t.strip()
        if not t:
            continue
        match = re.search(r'(sk-\S+)', t)
        token_value = match.group(1) if match else t
        existing = await db.execute(select(TokenInventory).where(TokenInventory.token_value == token_value))
        if existing.scalar_one_or_none():
            continue
        db.add(TokenInventory(
            id=str(uuid.uuid4()),
            token_value=token_value,
            group=req.group,
            is_trial=req.is_trial,
        ))
        added += 1
    return {"added": added}


@router.get("/tokens/stock")
async def get_stock(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    from app.models.content import Group
    groups_result = await db.execute(select(Group).order_by(Group.sort_order))
    groups = groups_result.scalars().all()
    result = {}
    for g in groups:
        count = await db.execute(
            select(func.count()).select_from(TokenInventory).where(
                TokenInventory.group == g.name,
                TokenInventory.is_assigned == False,
            )
        )
        trial_count = await db.execute(
            select(func.count()).select_from(TokenInventory).where(
                TokenInventory.group == g.name,
                TokenInventory.is_trial == True,
                TokenInventory.is_assigned == False,
            )
        )
        result[g.name] = {"available": count.scalar(), "trial": trial_count.scalar()}
    return result


@router.get("/tokens/available")
async def list_available_tokens(group: str = None, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    query = select(TokenInventory).where(TokenInventory.is_assigned == False)
    if group:
        query = query.where(TokenInventory.group == group)
    result = await db.execute(query.limit(100))
    tokens = result.scalars().all()
    return [{"id": t.id, "token_value": t.token_value,
             "group": t.group, "is_trial": t.is_trial} for t in tokens]


# ── Groups ───────────────────────────────────────────────────────

class GroupCreate(BaseModel):
    name: str
    description: str = ""
    sort_order: int = 0

class GroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None


@router.get("/groups")
async def get_groups(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    from app.models.content import Group
    result = await db.execute(select(Group).order_by(Group.sort_order))
    groups = result.scalars().all()
    return [{"id": g.id, "name": g.name, "description": g.description, "sort_order": g.sort_order} for g in groups]


@router.post("/groups")
async def create_group(req: GroupCreate, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    from app.models.content import Group
    existing = await db.execute(select(Group).where(Group.name == req.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="分组名称已存在")
    if not req.sort_order:
        max_order = await db.execute(select(func.coalesce(func.max(Group.sort_order), 0)))
        req.sort_order = max_order.scalar() + 1
    g = Group(id=str(uuid.uuid4()), name=req.name, description=req.description, sort_order=req.sort_order)
    db.add(g)
    await db.flush()
    return {"id": g.id, "name": g.name, "description": g.description, "sort_order": g.sort_order}


@router.put("/groups/{group_id}")
async def update_group(group_id: str, req: GroupUpdate, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    from app.models.content import Group
    result = await db.execute(select(Group).where(Group.id == group_id))
    g = result.scalar_one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="分组不存在")
    for k, v in req.model_dump(exclude_none=True).items():
        setattr(g, k, v)
    await db.flush()
    return {"id": g.id, "name": g.name, "description": g.description, "sort_order": g.sort_order}


@router.delete("/groups/{group_id}")
async def delete_group(group_id: str, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    from app.models.content import Group
    result = await db.execute(select(Group).where(Group.id == group_id))
    g = result.scalar_one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="分组不存在")
    model_count = await db.execute(select(func.count()).select_from(AIModel).where(AIModel.group == g.name))
    token_count = await db.execute(select(func.count()).select_from(TokenInventory).where(TokenInventory.group == g.name))
    if model_count.scalar() > 0 or token_count.scalar() > 0:
        raise HTTPException(status_code=400, detail="该分组下有模型或Token在使用，无法删除")
    await db.delete(g)
    await db.flush()
    return {"ok": True}


# ── Notice ───────────────────────────────────────────────────────

class NoticeUpdate(BaseModel):
    content: str
    is_active: bool = True


@router.put("/notice")
async def update_notice(req: NoticeUpdate, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Notice).limit(1))
    notice = result.scalar_one_or_none()
    if notice:
        notice.content = req.content
        notice.is_active = req.is_active
        notice.updated_at = datetime.now(timezone.utc)
    else:
        db.add(Notice(id=str(uuid.uuid4()), content=req.content, is_active=req.is_active))
    # Invalidate Redis cache
    redis = get_redis()
    await redis.delete("notice_content")
    return {"ok": True}


@router.get("/notice")
async def get_notice_admin(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Notice).limit(1))
    notice = result.scalar_one_or_none()
    return {"content": notice.content if notice else "", "is_active": notice.is_active if notice else True}


# ── Prompts ──────────────────────────────────────────────────────

class PromptCreate(BaseModel):
    category: str
    title: str
    content: str
    sort_order: int = 0


class PromptUpdate(BaseModel):
    category: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


@router.get("/prompts")
async def list_prompts(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Prompt).order_by(Prompt.category, Prompt.sort_order))
    prompts = result.scalars().all()
    return [{"id": p.id, "category": p.category, "title": p.title, "content": p.content,
             "sort_order": p.sort_order, "is_active": p.is_active} for p in prompts]


@router.post("/prompts")
async def create_prompt(req: PromptCreate, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    if not req.sort_order:
        max_order = await db.execute(select(func.coalesce(func.max(Prompt.sort_order), 0)))
        req.sort_order = max_order.scalar() + 1
    p = Prompt(id=str(uuid.uuid4()), **req.model_dump())
    db.add(p)
    await db.flush()
    return {"id": p.id}


@router.put("/prompts/{prompt_id}")
async def update_prompt(prompt_id: str, req: PromptUpdate, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Prompt).where(Prompt.id == prompt_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="提示词不存在")
    for k, v in req.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    return {"ok": True}


@router.delete("/prompts/{prompt_id}")
async def delete_prompt(prompt_id: str, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Prompt).where(Prompt.id == prompt_id))
    p = result.scalar_one_or_none()
    if p:
        await db.delete(p)
    return {"ok": True}


# ── AI Models ────────────────────────────────────────────────────

class ModelCreate(BaseModel):
    name: str
    display_name: str
    provider: str = "OpenAI"
    billing_type: str
    model_type: str
    group: str
    is_enabled: bool = True
    trial_allowed: bool = False
    price_input: Optional[str] = None
    price_output: Optional[str] = None
    price_cached: Optional[str] = None
    price_per_call: Optional[str] = None
    sort_order: int = 0


class ModelUpdate(BaseModel):
    display_name: Optional[str] = None
    provider: Optional[str] = None
    billing_type: Optional[str] = None
    is_enabled: Optional[bool] = None
    trial_allowed: Optional[bool] = None
    group: Optional[str] = None
    price_input: Optional[str] = None
    price_output: Optional[str] = None
    price_cached: Optional[str] = None
    price_per_call: Optional[str] = None
    sort_order: Optional[int] = None


@router.get("/models")
async def list_models(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AIModel).order_by(AIModel.sort_order))
    return [{"id": m.id, "name": m.name, "display_name": m.display_name,
             "provider": m.provider, "billing_type": m.billing_type,
             "model_type": m.model_type, "group": m.group,
             "is_enabled": m.is_enabled, "trial_allowed": m.trial_allowed,
             "price_input": m.price_input, "price_output": m.price_output,
             "price_cached": m.price_cached, "price_per_call": m.price_per_call,
             "sort_order": m.sort_order}
            for m in result.scalars().all()]


@router.post("/models")
async def create_model(req: ModelCreate, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    if not req.sort_order:
        max_order = await db.execute(select(func.coalesce(func.max(AIModel.sort_order), 0)))
        req.sort_order = max_order.scalar() + 1
    m = AIModel(id=str(uuid.uuid4()), **req.model_dump())
    db.add(m)
    await db.flush()
    return {"id": m.id}


@router.put("/models/{model_id}")
async def update_model(model_id: str, req: ModelUpdate, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AIModel).where(AIModel.id == model_id))
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="模型不存在")
    for k, v in req.model_dump(exclude_none=True).items():
        setattr(m, k, v)
    return {"ok": True}


@router.delete("/models/{model_id}")
async def delete_model(model_id: str, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AIModel).where(AIModel.id == model_id))
    m = result.scalar_one_or_none()
    if m:
        await db.delete(m)
    return {"ok": True}


# ── Users ────────────────────────────────────────────────────────

class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    account_type: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/users")
async def list_users(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    from app.models.user import UserToken
    result = await db.execute(select(User).order_by(User.created_at.desc()).limit(200))
    users = result.scalars().all()
    out = []
    for u in users:
        ut_result = await db.execute(select(UserToken).where(UserToken.user_id == u.id))
        tokens = ut_result.scalars().all()
        out.append({
            "id": u.id, "username": u.username, "email": u.email,
            "account_type": u.account_type,
            "is_active": u.is_active,
            "trial_expires_at": u.trial_expires_at.isoformat() if u.trial_expires_at else None,
            "created_at": u.created_at.isoformat(),
            "tokens": [{"group": t.group, "balance_usd": float(t.balance_usd), "is_trial": t.is_trial} for t in tokens],
        })
    return out


@router.get("/users/{user_id}")
async def get_user(user_id: str, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    from app.models.user import UserToken
    result = await db.execute(select(User).where(User.id == user_id))
    u = result.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")

    ut_result = await db.execute(select(UserToken).where(UserToken.user_id == user_id))
    user_tokens = ut_result.scalars().all()
    tokens = []
    for ut in user_tokens:
        tok_result = await db.execute(select(TokenInventory).where(TokenInventory.id == ut.token_id))
        tok = tok_result.scalar_one_or_none()
        tokens.append({
            "group": ut.group,
            "balance_usd": float(ut.balance_usd),
            "api_token": tok.token_value if tok else None,
            "is_trial": ut.is_trial,
        })

    usage_result = await db.execute(
        select(UsageLog).where(UsageLog.user_id == user_id).order_by(UsageLog.created_at.desc()).limit(20)
    )
    usage_logs = usage_result.scalars().all()

    return {
        "id": u.id, "username": u.username, "email": u.email,
        "account_type": u.account_type,
        "is_active": u.is_active,
        "trial_expires_at": u.trial_expires_at.isoformat() if u.trial_expires_at else None,
        "created_at": u.created_at.isoformat(),
        "tokens": tokens,
        "usage_logs": [{"model": log.model, "usage_type": log.usage_type,
                        "cost_usd": float(log.cost_usd), "created_at": log.created_at.isoformat()}
                       for log in usage_logs],
    }


@router.put("/users/{user_id}")
async def update_user(user_id: str, req: UserUpdate, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    u = result.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    for k, v in req.model_dump(exclude_none=True).items():
        setattr(u, k, v)
    return {"ok": True}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    u = result.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    await db.delete(u)
    return {"ok": True}


# ── Orders ───────────────────────────────────────────────────────

@router.get("/orders")
async def list_orders(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Order).order_by(Order.created_at.desc()).limit(200))
    orders = result.scalars().all()
    user_ids = list({o.user_id for o in orders})
    uname_map = {}
    if user_ids:
        ures = await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))
        uname_map = {row.id: row.username for row in ures}
    token_ids = [o.token_id for o in orders if o.token_id]
    token_map = {}
    if token_ids:
        tres = await db.execute(select(TokenInventory.id, TokenInventory.token_value).where(TokenInventory.id.in_(token_ids)))
        token_map = {row.id: row.token_value for row in tres}
    return [{"id": o.id, "user_id": o.user_id, "username": uname_map.get(o.user_id, ""),
             "out_trade_no": o.out_trade_no, "group": o.group,
             "amount_usd": float(o.amount_usd), "amount_cny": float(o.amount_cny),
             "exchange_rate": float(o.exchange_rate) if o.exchange_rate else None,
             "pay_type": o.pay_type, "status": o.status,
             "out_refund_no": o.out_refund_no,
             "token_value": token_map.get(o.token_id, "")[:12] if o.token_id else None,
             "created_at": o.created_at.isoformat(),
             "paid_at": o.paid_at.isoformat() if o.paid_at else None} for o in orders]


class AssignTokenRequest(BaseModel):
    tokens: dict[str, str]  # { "sora": "sk-xxx", "codex": "sk-yyy" }; value 可为空表示充值不换 Token


@router.post("/orders/{order_id}/assign")
async def assign_order_token(order_id: str, req: AssignTokenRequest, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    import json as _json

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != "paid":
        raise HTTPException(status_code=400, detail="订单未支付，无法操作")
    if order.token_id:
        raise HTTPException(status_code=400, detail="订单已处理")

    now = datetime.now(timezone.utc)

    # Parse items_json for merged orders, or fall back to single-group order
    items = []
    if order.items_json:
        items = _json.loads(order.items_json)
    else:
        items = [{"group": order.group, "amount_usd": float(order.amount_usd)}]

    first_token_id = None
    for item in items:
        group = item["group"]
        token_val = req.tokens.get(group, "").strip()

        ut_result = await db.execute(
            select(UserToken).where(UserToken.user_id == order.user_id, UserToken.group == group)
        )
        ut = ut_result.scalar_one_or_none()

        if ut:
            # 充值：增加余额，有新 Token 则更新
            ut.balance_usd = float(ut.balance_usd) + item["amount_usd"]
            if token_val:
                tok_result = await db.execute(select(TokenInventory).where(TokenInventory.id == ut.token_id))
                old_tok = tok_result.scalar_one_or_none()
                if old_tok:
                    old_tok.token_value = token_val
            if first_token_id is None:
                first_token_id = ut.token_id
        else:
            # 分配：必须提供 Token
            if not token_val:
                raise HTTPException(status_code=400, detail=f"分组 {group} 需提供 Token（新分配）")
            token = TokenInventory(
                id=str(uuid.uuid4()),
                token_value=token_val,
                group=group,
                is_trial=False,
                is_assigned=True,
                assigned_to=order.user_id,
                assigned_at=now,
            )
            db.add(token)
            await db.flush()

            if first_token_id is None:
                first_token_id = token.id

            ut = UserToken(
                id=str(uuid.uuid4()),
                user_id=order.user_id,
                token_id=token.id,
                group=group,
                balance_usd=item["amount_usd"],
            )
            db.add(ut)

    if first_token_id:
        order.token_id = first_token_id
    order.status = OrderStatus.ASSIGNED

    user_result = await db.execute(select(User).where(User.id == order.user_id))
    u = user_result.scalar_one_or_none()
    if u:
        u.account_type = "paid"

    return {"ok": True}


@router.post("/orders/{order_id}/close")
async def close_order(order_id: str, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status == OrderStatus.ASSIGNED:
        raise HTTPException(status_code=400, detail="已分配订单请使用退款功能")
    if order.status not in (OrderStatus.PENDING, OrderStatus.PAID):
        raise HTTPException(status_code=400, detail="只能关闭待支付或已支付订单")
    if order.status == OrderStatus.PENDING:
        try:
            from app.core.wechatpay import wechatpay_request
            path = f"/v3/pay/transactions/out-trade-no/{order.out_trade_no}/close"
            code, wx_result = await wechatpay_request(path, method="POST", data={"mchid": settings.WECHAT_MCHID})
            if code not in (200, 204):
                raise HTTPException(status_code=502, detail=f"微信关闭订单失败: {wx_result}")
        except ImportError:
            pass
    order.status = OrderStatus.CLOSED
    return {"ok": True}


class OrderUpdate(BaseModel):
    status: Optional[str] = None
    amount_usd: Optional[float] = None
    group: Optional[str] = None


@router.put("/orders/{order_id}")
async def update_order(order_id: str, req: OrderUpdate, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    for k, v in req.model_dump(exclude_none=True).items():
        setattr(order, k, v)
    return {"ok": True}


@router.delete("/orders/{order_id}")
async def delete_order(order_id: str, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status in (OrderStatus.PAID, OrderStatus.ASSIGNED):
        raise HTTPException(status_code=400, detail="已支付/已分配订单不可删除，请先退款")
    await db.delete(order)
    return {"ok": True}


class OrderItem(BaseModel):
    group: str
    amount_usd: float

class AdminCreateOrderRequest(BaseModel):
    items: list[OrderItem]
    user_id: Optional[str] = None


@router.post("/orders/create")
async def admin_create_order(req: AdminCreateOrderRequest, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    if not req.items:
        raise HTTPException(status_code=400, detail="至少选择一个分组")

    for item in req.items:
        if item.amount_usd < settings.PAYMENT_MIN_PER_ITEM_USD:
            raise HTTPException(status_code=400, detail=f"分组 {item.group} 金额不能小于 ${settings.PAYMENT_MIN_PER_ITEM_USD}")

    total_usd = sum(item.amount_usd for item in req.items)
    if total_usd < settings.PAYMENT_MIN_TOTAL_USD or total_usd > settings.PAYMENT_MAX_TOTAL_USD:
        raise HTTPException(status_code=400, detail=f"总金额需在 ${settings.PAYMENT_MIN_TOTAL_USD} ~ ${settings.PAYMENT_MAX_TOTAL_USD} 之间")

    import httpx
    import json
    from app.core.wechatpay import get_wxpay

    user_id = req.user_id
    if not user_id:
        result = await db.execute(select(User).limit(1))
        u = result.scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=400, detail="系统中没有用户，请先创建用户")
        user_id = u.id

    redis = get_redis()
    cached = await redis.get("exchange_rate_usd_cny")
    if cached:
        rate = float(cached)
    else:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(settings.EXCHANGE_RATE_API)
                data = resp.json()
                rate = float(data["rates"]["CNY"])
                await redis.setex("exchange_rate_usd_cny", 3600, str(rate))
        except Exception:
            rate = 7.25

    amount_cny = round(total_usd * rate, 2)
    out_trade_no = f"CY{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"
    groups = ",".join(item.group for item in req.items)
    items_json = json.dumps([{"group": item.group, "amount_usd": item.amount_usd} for item in req.items])

    order = Order(
        user_id=user_id,
        out_trade_no=out_trade_no,
        group=groups,
        amount_usd=total_usd,
        amount_cny=amount_cny,
        exchange_rate=rate,
        items_json=items_json,
        pay_type="wxpay",
        status="pending",
    )
    db.add(order)
    await db.flush()

    wxpay = get_wxpay()
    from datetime import timedelta
    time_expire = (datetime.now(timezone(timedelta(hours=8))) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    code, result = await wxpay.pay(
        description=f"CyImagePro充值-{groups}",
        out_trade_no=out_trade_no,
        amount={"total": int(round(amount_cny * 100)), "currency": "CNY"},
        time_expire=time_expire,
    )

    if code != 200:
        raise HTTPException(status_code=502, detail=f"微信支付下单失败: {result}")

    return {
        "out_trade_no": out_trade_no,
        "code_url": result.get("code_url"),
        "amount_usd": total_usd,
        "amount_cny": amount_cny,
        "exchange_rate": rate,
        "group": groups,
        "items": [{"group": item.group, "amount_usd": item.amount_usd} for item in req.items],
        "status": "pending",
    }


@router.get("/orders/query_pay/{out_trade_no}")
async def admin_query_pay(out_trade_no: str, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Order).where(Order.out_trade_no == out_trade_no))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != "pending":
        return {"status": order.status, "out_trade_no": order.out_trade_no}

    from app.core.wechatpay import get_wxpay
    wxpay = get_wxpay()
    code, wx_result = await wxpay.query(out_trade_no=order.out_trade_no)
    if code == 200 and wx_result.get("trade_state") == "SUCCESS":
        order.status = "paid"
        order.paid_at = datetime.now(timezone.utc)
        order.trade_no = wx_result.get("transaction_id")
        return {"status": "paid", "out_trade_no": order.out_trade_no}

    return {"status": order.status, "out_trade_no": order.out_trade_no}


# ── User Token Management ────────────────────────────────────────

class UserTokenInput(BaseModel):
    group: str
    token_value: str
    balance_usd: float


@router.post("/users/{user_id}/tokens")
async def add_or_update_user_token(user_id: str, req: UserTokenInput, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    user_result = await db.execute(select(User).where(User.id == user_id))
    if not user_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="用户不存在")

    ut_result = await db.execute(
        select(UserToken).where(UserToken.user_id == user_id, UserToken.group == req.group)
    )
    ut = ut_result.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if ut:
        tok_result = await db.execute(select(TokenInventory).where(TokenInventory.id == ut.token_id))
        tok = tok_result.scalar_one_or_none()
        if tok:
            tok.token_value = req.token_value.strip()
        ut.balance_usd = req.balance_usd
    else:
        # Check if TokenInventory already exists for this token_value + group
        existing_tok = await db.execute(
            select(TokenInventory).where(
                TokenInventory.token_value == req.token_value.strip(),
                TokenInventory.group == req.group,
            )
        )
        tok = existing_tok.scalar_one_or_none()
        if not tok:
            tok = TokenInventory(
                id=str(uuid.uuid4()),
                token_value=req.token_value.strip(),
                group=req.group,
                is_trial=False,
                is_assigned=True,
                assigned_to=user_id,
                assigned_at=now,
            )
            db.add(tok)
            await db.flush()
        ut = UserToken(
            id=str(uuid.uuid4()),
            user_id=user_id,
            token_id=tok.id,
            group=req.group,
            balance_usd=req.balance_usd,
        )
        db.add(ut)

    return {"ok": True}


class BalanceUpdate(BaseModel):
    balance_usd: float


@router.put("/users/{user_id}/tokens/{group}/balance")
async def update_user_token_balance(user_id: str, group: str, req: BalanceUpdate, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    ut_result = await db.execute(
        select(UserToken).where(UserToken.user_id == user_id, UserToken.group == group)
    )
    ut = ut_result.scalar_one_or_none()
    if not ut:
        raise HTTPException(status_code=404, detail="该用户没有此分组的 Token")
    ut.balance_usd = req.balance_usd
    return {"ok": True}


@router.delete("/users/{user_id}/tokens/{group}")
async def delete_user_token(user_id: str, group: str, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    ut_result = await db.execute(
        select(UserToken).where(UserToken.user_id == user_id, UserToken.group == group)
    )
    ut = ut_result.scalar_one_or_none()
    if not ut:
        raise HTTPException(status_code=404, detail="该用户没有此分组的 Token")
    await db.delete(ut)
    return {"ok": True}


# ── Admin password change ─────────────────────────────────────────

class PasswordChange(BaseModel):
    new_password: str


@router.put("/password")
async def change_admin_password(req: PasswordChange, _=Depends(get_admin_user)):
    # Update in-memory settings (persists until restart; for permanent change use .env)
    settings.ADMIN_PASSWORD = req.new_password
    return {"ok": True, "note": "重启后失效，如需永久修改请更新 .env 文件中的 ADMIN_PASSWORD"}


# ── System Config (.env) ─────────────────────────────────────────

import os

SENSITIVE_KEYS = {"SECRET_KEY", "ADMIN_PASSWORD", "POSTGRES_PASSWORD", "WECHAT_APIV3_KEY", "SMTP_PASSWORD"}
MASK = "********"

CONFIG_CATEGORIES = [
    {
        "label": "数据库",
        "icon": "database",
        "keys": ["POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"],
        "descriptions": {"POSTGRES_DB": "数据库名", "POSTGRES_USER": "数据库用户", "POSTGRES_PASSWORD": "数据库密码"},
    },
    {
        "label": "认证与安全",
        "icon": "security",
        "keys": ["SECRET_KEY", "ADMIN_USERNAME", "ADMIN_PASSWORD"],
        "descriptions": {"SECRET_KEY": "JWT 密钥", "ADMIN_USERNAME": "管理员用户名", "ADMIN_PASSWORD": "管理员密码"},
    },
    {
        "label": "微信支付",
        "icon": "wechat",
        "keys": ["WECHAT_MCHID", "WECHAT_APPID", "WECHAT_APIV3_KEY", "WECHAT_CERT_SERIAL_NO",
                 "WECHAT_PRIVATE_KEY_PATH", "WECHAT_PUBLIC_KEY_PATH", "WECHAT_PUBLIC_KEY_ID",
                 "WECHAT_NOTIFY_URL"],
        "descriptions": {"WECHAT_MCHID": "商户号", "WECHAT_APPID": "应用 ID", "WECHAT_APIV3_KEY": "APIv3 密钥",
                         "WECHAT_CERT_SERIAL_NO": "证书序列号", "WECHAT_PRIVATE_KEY_PATH": "私钥路径",
                         "WECHAT_PUBLIC_KEY_PATH": "公钥路径", "WECHAT_PUBLIC_KEY_ID": "公钥 ID",
                         "WECHAT_NOTIFY_URL": "支付回调 URL"},
    },
    {
        "label": "邮件服务 (SMTP)",
        "icon": "smtp",
        "keys": ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM_NAME", "SMTP_USE_SSL"],
        "descriptions": {"SMTP_HOST": "SMTP 服务器", "SMTP_PORT": "端口", "SMTP_USER": "发件邮箱",
                         "SMTP_PASSWORD": "授权码/密码", "SMTP_FROM_NAME": "发件人名称", "SMTP_USE_SSL": "使用 SSL"},
    },
    {
        "label": "支付限额",
        "icon": "payment",
        "keys": ["PAYMENT_MIN_TOTAL_USD", "PAYMENT_MAX_TOTAL_USD", "PAYMENT_MIN_PER_ITEM_USD"],
        "descriptions": {"PAYMENT_MIN_TOTAL_USD": "最低总金额 ($)", "PAYMENT_MAX_TOTAL_USD": "最高总金额 ($)",
                         "PAYMENT_MIN_PER_ITEM_USD": "单项最低金额 ($)"},
    },
    {
        "label": "服务器",
        "icon": "server",
        "keys": ["SERVER_BASE_URL", "EXCHANGE_RATE_API"],
        "descriptions": {"SERVER_BASE_URL": "服务器地址", "EXCHANGE_RATE_API": "汇率 API"},
    },
]


def _infer_field_type(key: str) -> str:
    if key in SENSITIVE_KEYS:
        return "password"
    if key.endswith("_USE_SSL"):
        return "boolean"
    if key.endswith("_PORT") or key.endswith("_MIN") or key.endswith("_MAX") or key.endswith("_EXPIRE") or key.endswith("_MINUTES") or "_MIN_" in key or "_MAX_" in key:
        return "number"
    return "text"


def _parse_env_file(path: str) -> list[dict]:
    lines = []
    if not os.path.exists(path):
        return lines
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            stripped = line.strip()
            if not stripped:
                lines.append({"type": "blank"})
            elif stripped.startswith("#"):
                lines.append({"type": "comment", "raw": line})
            elif "=" in stripped:
                key, _, value = stripped.partition("=")
                lines.append({"type": "kv", "key": key.strip(), "value": value, "raw": line})
            else:
                lines.append({"type": "comment", "raw": line})
    return lines


def _write_env_file(path: str, parsed: list[dict], updates: dict[str, str]) -> list[str]:
    updated_keys = []
    existing_keys = set()
    for entry in parsed:
        if entry["type"] == "kv":
            existing_keys.add(entry["key"])
            if entry["key"] in updates and updates[entry["key"]] != MASK:
                old_val = entry["value"]
                entry["value"] = updates[entry["key"]]
                entry["raw"] = f"{entry['key']}={entry['value']}"
                if old_val != entry["value"]:
                    updated_keys.append(entry["key"])
    for key in updates:
        if key not in existing_keys and updates[key] != MASK:
            parsed.append({"type": "kv", "key": key, "value": updates[key], "raw": f"{key}={updates[key]}"})
            updated_keys.append(key)
    with open(path, "w", encoding="utf-8") as f:
        for entry in parsed:
            if entry["type"] == "blank":
                f.write("\n")
            else:
                f.write(entry["raw"] + "\n")
    return updated_keys


@router.get("/config")
async def get_config(_=Depends(get_admin_user)):
    env_path = os.environ.get("ENV_FILE_PATH", "/app/.env")
    if not os.path.exists(env_path):
        env_path = ".env"
    parsed = _parse_env_file(env_path)
    env_dict = {e["key"]: e["value"] for e in parsed if e["type"] == "kv"}

    categories = []
    for cat in CONFIG_CATEGORIES:
        items = []
        for key in cat["keys"]:
            raw_val = env_dict.get(key, "")
            is_sensitive = key in SENSITIVE_KEYS
            value = MASK if is_sensitive and raw_val else raw_val
            items.append({
                "key": key,
                "value": value,
                "is_sensitive": is_sensitive,
                "field_type": _infer_field_type(key),
                "description": cat["descriptions"].get(key, key),
            })
        categories.append({"label": cat["label"], "icon": cat["icon"], "items": items})

    return {"categories": categories}


class ConfigUpdateRequest(BaseModel):
    updates: dict[str, str]


@router.put("/config")
async def update_config(req: ConfigUpdateRequest, _=Depends(get_admin_user)):
    env_path = os.environ.get("ENV_FILE_PATH", "/app/.env")
    if not os.path.exists(env_path):
        env_path = ".env"

    all_known_keys = set()
    for cat in CONFIG_CATEGORIES:
        all_known_keys.update(cat["keys"])

    for key in req.updates:
        if key not in all_known_keys:
            raise HTTPException(status_code=400, detail=f"未知配置项: {key}")

    parsed = _parse_env_file(env_path)
    updated_keys = _write_env_file(env_path, parsed, req.updates)

    if updated_keys:
        from app.core.config import Settings
        # Clear env vars so Settings reads from the updated .env file
        for key in updated_keys:
            os.environ.pop(key, None)
        new_settings = Settings()
        for field in new_settings.model_fields:
            setattr(settings, field, getattr(new_settings, field))

    return {"ok": True, "updated_keys": updated_keys}


@router.post("/config/restart")
async def restart_backend(_=Depends(get_admin_user)):
    try:
        import docker
        client = docker.from_env()
        containers = client.containers.list(filters={"label": "com.docker.compose.service=backend"})
        if not containers:
            containers = client.containers.list(all=True, filters={"name": "backend"})
        if not containers:
            raise HTTPException(status_code=404, detail="未找到 backend 容器")
        containers[0].restart(timeout=10)
        return {"ok": True}
    except ImportError:
        raise HTTPException(status_code=500, detail="docker SDK 未安装")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"重启失败: {exc}")
