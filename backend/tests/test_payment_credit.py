"""支付入账/退款冲正测试：充值幂等（Test 10 等价）、退款扣回、dev_mark_paid。"""

import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.main import app
from app.core.database import AsyncSessionLocal
from app.core.security import create_admin_token
from app.models.token import Order, OrderStatus
from app.models.billing import BillingTransaction
from app.services import billing
from app.services.order_assignment import assign_paid_order
from tests.conftest import make_user, get_user

ADMIN_HEADERS = {"Authorization": f"Bearer {create_admin_token()}"}


async def make_paid_order(user_id: str, amount_usd: str = "10.00") -> Order:
    async with AsyncSessionLocal() as db:
        order = Order(
            user_id=user_id,
            out_trade_no=f"CY{uuid.uuid4().hex[:16].upper()}",
            amount_usd=Decimal(amount_usd),
            amount_cny=Decimal("72.50"),
            exchange_rate=Decimal("7.25"),
            pay_type="wxpay",
            status=OrderStatus.PAID,
        )
        db.add(order)
        await db.commit()
        return order


async def test_recharge_credit_idempotent():
    """Test 10（服务层等价）：重复入账只加一次余额，RECHARGE 流水仅一条。"""
    user = await make_user("p1", "0", "0")
    order = await make_paid_order(user.id, "10.00")

    async with AsyncSessionLocal() as db:
        o = await db.get(Order, order.id)
        await assign_paid_order(db, o, auto=True)
        await db.commit()

    row = await get_user(user.id)
    assert row.balance_usd == Decimal("10.000000")

    # 模拟微信重复 notify / 重复轮询：再次 assign → 幂等
    async with AsyncSessionLocal() as db:
        o = await db.get(Order, order.id)
        await assign_paid_order(db, o, auto=True)
        await db.commit()

    row = await get_user(user.id)
    assert row.balance_usd == Decimal("10.000000")

    async with AsyncSessionLocal() as db:
        txns = (await db.execute(select(BillingTransaction).where(
            BillingTransaction.user_id == user.id,
            BillingTransaction.type == "RECHARGE",
        ))).scalars().all()
    assert len(txns) == 1

    async with AsyncSessionLocal() as db:
        o = await db.get(Order, order.id)
        assert o.status == OrderStatus.ASSIGNED


async def test_recharge_refund_debit():
    """充值退款冲正：扣回充值金额；余额不足时扣到 0 并如实记录实际扣除。"""
    user = await make_user("p2", "3.00", "0")
    order = await make_paid_order(user.id, "10.00")

    async with AsyncSessionLocal() as db:
        o = await db.get(Order, order.id)
        await assign_paid_order(db, o)
        await db.commit()
    row = await get_user(user.id)
    assert row.balance_usd == Decimal("13.000000")

    # 全额退款冲正
    async with AsyncSessionLocal() as db:
        _, _, actual = await billing.debit_balance_for_refund(
            db, user.id, Decimal("10.00"), related_order_id=order.id,
        )
        await db.commit()
    assert actual == Decimal("10.000000")
    row = await get_user(user.id)
    assert row.balance_usd == Decimal("3.000000")

    # 余额不足时（已消费）：扣到 0 为止
    async with AsyncSessionLocal() as db:
        _, _, actual = await billing.debit_balance_for_refund(
            db, user.id, Decimal("10.00"),
        )
        await db.commit()
    assert actual == Decimal("3.000000")
    row = await get_user(user.id)
    assert row.balance_usd == Decimal("0.000000")
    assert row.trial_credit_usd == Decimal("0.000000")  # 退款不动试用额度


async def test_dev_mark_paid_http_idempotent():
    """Test 10（HTTP 层）：dev_mark_paid 重复调用只入账一次。"""
    user = await make_user("p3", "0", "0")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/pay/create_order", json={"amount_usd": 5.0}, headers={
            "Authorization": f"Bearer {__import__('app.core.security', fromlist=['create_access_token']).create_access_token(user.id)}"
        })
        assert r.status_code == 200
        out_trade_no = r.json()["out_trade_no"]
        assert r.json()["dev_mode"] is True

        for _ in range(3):  # 模拟微信三次重复通知路径
            r = await client.post(f"/api/pay/dev/mark_paid/{out_trade_no}", headers=ADMIN_HEADERS)
            assert r.status_code == 200

    row = await get_user(user.id)
    assert row.balance_usd == Decimal("5.000000")  # 只入账一次

    async with AsyncSessionLocal() as db:
        txns = (await db.execute(select(BillingTransaction).where(
            BillingTransaction.user_id == user.id,
            BillingTransaction.type == "RECHARGE",
        ))).scalars().all()
    assert len(txns) == 1
