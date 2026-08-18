"""退款申请完整闭环测试（申请 → 审核 → 微信退款 → 冲正，全链路 Decimal 幂等）。"""

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select, text

from app.main import app
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.core.config import settings
from app.models.token import Order, OrderStatus, RefundRequest
from app.services import refund as refund_service
from tests.conftest import make_admin_headers, make_user

ADMIN_HEADERS = make_admin_headers()


def wx_refund_response(status: str, refund_id: str = None) -> tuple[int, str]:
    body = {"status": status, "refund_id": refund_id or f"wx-{uuid.uuid4().hex[:12]}"}
    return 200, json.dumps(body)


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def make_paid_order(username: str, amount_usd="1.00", amount_cny="6.75", credited=True):
    """创建已支付（并默认已入账）订单。返回 (user, order_dict)。"""
    user = await make_user(username, "0", "0")
    async with AsyncSessionLocal() as db:
        order = Order(
            id=str(uuid.uuid4()),
            user_id=user.id,
            out_trade_no=f"CYTEST{uuid.uuid4().hex[:12].upper()}",
            amount_usd=Decimal(amount_usd),
            amount_cny=Decimal(amount_cny),
            exchange_rate=Decimal("6.75"),
            pay_type="wxpay",
            status="paid",
            paid_at=datetime.now(timezone.utc),
        )
        db.add(order)
        await db.flush()
        if credited:
            from app.services.order_assignment import assign_paid_order
            await assign_paid_order(db, order)
        await db.commit()
        return user, {"id": order.id, "out_trade_no": order.out_trade_no}


async def user_headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


# ── Test 1：用户申请退款（持久化 + 后台立即可见） ──────────────────

async def test_user_refund_request_persisted_and_visible_in_admin(client):
    user, order = await make_paid_order("rf_apply")

    headers = await user_headers(user)
    r = await client.post(f"/api/pay/refund_order/{order['out_trade_no']}",
                          json={"reason": "不需要了"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["message"] == "退款申请已提交，等待审核"

    async with AsyncSessionLocal() as db:
        fresh = (await db.execute(select(Order).where(Order.id == order['id']))).scalar_one()
        assert fresh.status == OrderStatus.REFUND_REQUESTED
        req = (await db.execute(select(RefundRequest).where(RefundRequest.order_id == order['id']))).scalar_one()
        assert req.status == "requested"
        assert req.reason == "不需要了"
        assert req.requested_amount_fen == 675

    # 后台订单列表无需查库即可看到退款申请
    r = await client.get("/api/admin/orders", params={"status": "refund_requested"}, headers=ADMIN_HEADERS)
    assert r.status_code == 200
    target = [o for o in r.json() if o["id"] == order["id"]]
    assert len(target) == 1
    assert target[0]["refund_request"]["status"] == "requested"


# ── Test 10：重复申请被拒 ─────────────────────────────────────────

async def test_duplicate_refund_request_rejected(client):
    user, order = await make_paid_order("rf_dup")
    headers = await user_headers(user)

    r1 = await client.post(f"/api/pay/refund_order/{order['out_trade_no']}", headers=headers)
    assert r1.status_code == 200
    r2 = await client.post(f"/api/pay/refund_order/{order['out_trade_no']}", headers=headers)
    assert r2.status_code == 400
    assert "已有退款申请" in r2.json()["detail"]


# ── Test 3：管理员拒绝 ────────────────────────────────────────────

async def test_admin_reject_returns_order_and_saves_note(client):
    user, order = await make_paid_order("rf_reject")
    await client.post(f"/api/pay/refund_order/{order['out_trade_no']}",
                      json={"reason": "xx"}, headers=await user_headers(user))

    r = await client.post(f"/api/admin/orders/{order['id']}/refund/reject",
                          json={"review_note": "已使用额度，不符合退款条件"}, headers=ADMIN_HEADERS)
    assert r.status_code == 200

    async with AsyncSessionLocal() as db:
        fresh = (await db.execute(select(Order).where(Order.id == order['id']))).scalar_one()
        assert fresh.status == OrderStatus.ASSIGNED  # 回到入账状态
        req = (await db.execute(select(RefundRequest).where(RefundRequest.order_id == order['id']))).scalar_one()
        assert req.status == "rejected"
        assert req.review_note == "已使用额度，不符合退款条件"

    # 客户端订单接口能看到拒绝结果
    r = await client.get("/api/pay/orders", headers=await user_headers(user))
    target = next(o for o in r.json() if o["out_trade_no"] == order["out_trade_no"])
    assert target["refund_request"]["status"] == "rejected"
    assert target["refund_request"]["review_note"] == "已使用额度，不符合退款条件"


# 拒绝必须填原因
async def test_admin_reject_requires_note(client):
    user, order = await make_paid_order("rf_reject2")
    await client.post(f"/api/pay/refund_order/{order['out_trade_no']}", headers=await user_headers(user))
    r = await client.post(f"/api/admin/orders/{order['id']}/refund/reject",
                          json={"review_note": ""}, headers=ADMIN_HEADERS)
    assert r.status_code == 400


# ── Test 2 + 49：批准 → PROCESSING（不立即 REFUNDED） ──────────────

async def test_admin_approve_goes_processing_not_refunded(client, monkeypatch):
    user, order = await make_paid_order("rf_appr")
    await client.post(f"/api/pay/refund_order/{order['out_trade_no']}", headers=await user_headers(user))

    from app.core import wechatpay
    calls = []

    async def fake_wx(path, method="GET", data=None):
        calls.append((path, method, data))
        return wx_refund_response("PROCESSING")

    monkeypatch.setattr(settings, "APP_ENV", "production", raising=False)
    monkeypatch.setattr(wechatpay, "wechatpay_request", fake_wx)
    monkeypatch.setattr(refund_service.wechatpay, "wechatpay_request", fake_wx)

    r = await client.post(f"/api/admin/orders/{order['id']}/refund/approve", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "processing"
    assert body["order_status"] == OrderStatus.REFUNDING

    # 微信请求使用订单快照金额（refund=675, total=675, CNY）
    path, method, data = calls[0]
    assert path == "/v3/refund/domestic/refunds"
    assert data["amount"] == {"refund": 675, "total": 675, "currency": "CNY"}

    # 资金尚未冲正（等微信确认）
    async with AsyncSessionLocal() as db:
        from app.models.user import User
        u = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
        assert Decimal(str(u.balance_usd)) == Decimal("1.00")


# ── Test 4 + 6：微信 SUCCESS → 一次事务完成全部冲正 ────────────────

async def test_wechat_success_settles_everything_in_one_tx(client, monkeypatch):
    user, order = await make_paid_order("rf_succ")
    await client.post(f"/api/pay/refund_order/{order['out_trade_no']}", headers=await user_headers(user))

    from app.core import wechatpay

    async def fake_wx(path, method="GET", data=None):
        return wx_refund_response("SUCCESS")

    monkeypatch.setattr(settings, "APP_ENV", "production", raising=False)
    monkeypatch.setattr(wechatpay, "wechatpay_request", fake_wx)

    r = await client.post(f"/api/admin/orders/{order['id']}/refund/approve", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json()["status"] == "success"

    async with AsyncSessionLocal() as db:
        from app.models.user import User
        from app.models.billing import BillingTransaction
        fresh = (await db.execute(select(Order).where(Order.id == order['id']))).scalar_one()
        assert fresh.status == OrderStatus.REFUNDED
        assert Decimal(str(fresh.refunded_cny)) == Decimal("6.75")
        assert Decimal(str(fresh.refunded_usd)) == Decimal("1.00")

        u = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
        assert Decimal(str(u.balance_usd)) == Decimal("0.00")  # 冲正到 0，不为负

        txn = (await db.execute(
            select(BillingTransaction).where(
                BillingTransaction.related_order_id == order['id'],
                BillingTransaction.type == "RECHARGE_REFUND",
            )
        )).scalar_one()
        assert Decimal(str(txn.amount_usd)) == Decimal("1.00")

        req = (await db.execute(select(RefundRequest).where(RefundRequest.order_id == order['id']))).scalar_one()
        assert req.status == "success"
        assert req.out_refund_no and req.out_refund_no.startswith("RF")


# ── Test 5：重复 SUCCESS 幂等 ──────────────────────────────────────

async def test_repeated_success_settles_once(client, monkeypatch):
    user, order = await make_paid_order("rf_idem")
    await client.post(f"/api/pay/refund_order/{order['out_trade_no']}", headers=await user_headers(user))

    async with AsyncSessionLocal() as db:
        req = (await db.execute(select(RefundRequest).where(RefundRequest.order_id == order['id']))).scalar_one()
        req.status = "processing"
        req.out_refund_no = f"RF{uuid.uuid4().hex[:12].upper()}"
        await db.commit()

    # 模拟微信回调 3 次
    for _ in range(3):
        async with AsyncSessionLocal() as db:
            req = (await db.execute(select(RefundRequest).where(RefundRequest.order_id == order['id']))).scalar_one()
            await refund_service.settle_refund_success(db, req, wechat_refund_id="wx-1")
            await db.commit()

    async with AsyncSessionLocal() as db:
        from app.models.user import User
        from app.models.billing import BillingTransaction
        fresh = (await db.execute(select(Order).where(Order.id == order['id']))).scalar_one()
        assert Decimal(str(fresh.refunded_cny)) == Decimal("6.75")  # 只累计一次
        u = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
        assert Decimal(str(u.balance_usd)) == Decimal("0.00")
        txns = (await db.execute(
            select(BillingTransaction).where(BillingTransaction.related_order_id == order['id'])
        )).scalars().all()
        assert len([t for t in txns if t.type == "RECHARGE_REFUND"]) == 1


# ── Test 7 + 8：部分退款精确累计 + 全退差额收口 ────────────────────

async def test_partial_refund_then_full_closeout(client, monkeypatch):
    user, order = await make_paid_order("rf_partial")
    from app.core import wechatpay

    async def fake_wx(path, method="GET", data=None):
        return wx_refund_response("SUCCESS")

    monkeypatch.setattr(settings, "APP_ENV", "production", raising=False)
    monkeypatch.setattr(wechatpay, "wechatpay_request", fake_wx)

    # 第一次部分退款 338 fen
    r = await client.post(f"/api/admin/orders/{order['id']}/refund",
                          json={"refund_amount_cny": "3.38", "reason": "部分退款"}, headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json()["status"] == "success"

    async with AsyncSessionLocal() as db:
        fresh = (await db.execute(select(Order).where(Order.id == order['id']))).scalar_one()
        assert fresh.status == OrderStatus.PARTIALLY_REFUNDED
        assert Decimal(str(fresh.refunded_cny)) == Decimal("3.38")
        # USD 按比例：1.00 × 338/675 = 0.500741
        assert Decimal(str(fresh.refunded_usd)) == Decimal("0.500741")

    # 第二次全额退款 = 剩余 337 fen 收口
    r = await client.post(f"/api/admin/orders/{order['id']}/refund", headers=ADMIN_HEADERS)
    assert r.status_code == 200

    async with AsyncSessionLocal() as db:
        fresh = (await db.execute(select(Order).where(Order.id == order['id']))).scalar_one()
        assert Decimal(str(fresh.refunded_cny)) == Decimal("6.75")  # 精确收口
        assert Decimal(str(fresh.refunded_usd)) == Decimal("1.00")  # 不超过原到账
        assert fresh.status == OrderStatus.REFUNDED


async def test_partial_refund_over_remaining_rejected(client, monkeypatch):
    user, order = await make_paid_order("rf_over")
    from app.core import wechatpay
    monkeypatch.setattr(settings, "APP_ENV", "production", raising=False)

    async def fake_wx(path, method="GET", data=None):
        return wx_refund_response("SUCCESS")

    monkeypatch.setattr(wechatpay, "wechatpay_request", fake_wx)

    r = await client.post(f"/api/admin/orders/{order['id']}/refund",
                          json={"refund_amount_cny": "7.00"}, headers=ADMIN_HEADERS)
    assert r.status_code == 400  # 超过订单金额


# ── Test 9：余额不足禁止负数 ──────────────────────────────────────

async def test_insufficient_balance_never_negative(client, monkeypatch):
    user, order = await make_paid_order("rf_neg", credited=True)
    # 用户已消费 $0.80，余额只剩 $0.20
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "UPDATE users SET balance_usd = 0.20 WHERE id = :uid"
        ), {"uid": user.id})
        await db.commit()

    await client.post(f"/api/pay/refund_order/{order['out_trade_no']}", headers=await user_headers(user))
    from app.core import wechatpay
    monkeypatch.setattr(settings, "APP_ENV", "production", raising=False)

    async def fake_wx(path, method="GET", data=None):
        return wx_refund_response("SUCCESS")

    monkeypatch.setattr(wechatpay, "wechatpay_request", fake_wx)

    r = await client.post(f"/api/admin/orders/{order['id']}/refund/approve", headers=ADMIN_HEADERS)
    assert r.status_code == 200

    async with AsyncSessionLocal() as db:
        from app.models.user import User
        from app.models.billing import BillingTransaction
        u = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
        assert Decimal(str(u.balance_usd)) == Decimal("0.00")  # 扣到 0 为止，不为负
        # 流水如实记录实际扣除 0.20（差额在审核界面提示人工处理）
        txn = (await db.execute(
            select(BillingTransaction).where(
                BillingTransaction.related_order_id == order['id'],
                BillingTransaction.type == "RECHARGE_REFUND",
            )
        )).scalar_one()
        assert Decimal(str(txn.amount_usd)) == Decimal("0.20")


# ── 微信失败 → FAILED，订单回退 ───────────────────────────────────

async def test_wechat_rejection_marks_failed(client, monkeypatch):
    user, order = await make_paid_order("rf_fail")
    await client.post(f"/api/pay/refund_order/{order['out_trade_no']}", headers=await user_headers(user))
    from app.core import wechatpay

    async def fake_wx(path, method="GET", data=None):
        return 403, json.dumps({"code": "NOT_ENOUGH", "message": "余额不足"})

    monkeypatch.setattr(settings, "APP_ENV", "production", raising=False)
    monkeypatch.setattr(wechatpay, "wechatpay_request", fake_wx)

    r = await client.post(f"/api/admin/orders/{order['id']}/refund/approve", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json()["status"] == "failed"

    async with AsyncSessionLocal() as db:
        fresh = (await db.execute(select(Order).where(Order.id == order['id']))).scalar_one()
        assert fresh.status == OrderStatus.ASSIGNED  # 回退可重试
        from app.models.user import User
        u = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
        assert Decimal(str(u.balance_usd)) == Decimal("1.00")  # 资金未动


# ── 处理中：客户端轮询驱动微信查询结算 ────────────────────────────

async def test_client_polling_drives_wechat_query_settlement(client, monkeypatch):
    user, order = await make_paid_order("rf_poll")
    await client.post(f"/api/pay/refund_order/{order['out_trade_no']}", headers=await user_headers(user))
    from app.core import wechatpay

    async def fake_wx(path, method="GET", data=None):
        if method == "POST":
            return wx_refund_response("PROCESSING")
        # GET 查询退款状态
        assert "/v3/refund/domestic/refunds/RF" in path
        return wx_refund_response("SUCCESS")

    monkeypatch.setattr(settings, "APP_ENV", "production", raising=False)
    monkeypatch.setattr(wechatpay, "wechatpay_request", fake_wx)

    await client.post(f"/api/admin/orders/{order['id']}/refund/approve", headers=ADMIN_HEADERS)

    # 客户端退款状态轮询触发查询结算
    r = await client.get(f"/api/pay/refund_status/{order['out_trade_no']}", headers=await user_headers(user))
    assert r.status_code == 200
    assert r.json()["status"] == OrderStatus.REFUNDED
    assert r.json()["refunded_cny"] == 6.75


# ── 退款审核 Modal 数据 ───────────────────────────────────────────

async def test_refund_summary_endpoint(client):
    user, order = await make_paid_order("rf_summary")
    await client.post(f"/api/pay/refund_order/{order['out_trade_no']}",
                      json={"reason": "test"}, headers=await user_headers(user))

    r = await client.get(f"/api/admin/orders/{order['id']}/refund/summary", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["amount_usd"] == 1.0
    assert data["amount_cny"] == 6.75
    assert data["refunded_cny"] == 0.0
    assert data["remaining_refundable_cny"] == 6.75
    assert data["max_usd_reversal"] == 1.0
    assert data["user_balance_usd"] == "1.000000"
    assert data["refund_request"]["status"] == "requested"
    assert data["refund_request"]["reason"] == "test"


# ── 权限：普通用户不能调用管理员退款端点 ──────────────────────────

async def test_refund_endpoints_admin_only(client):
    user, order = await make_paid_order("rf_perm")
    headers = await user_headers(user)
    assert (await client.post(f"/api/admin/orders/{order['id']}/refund/approve", headers=headers)).status_code in (401, 403)
    assert (await client.post(f"/api/admin/orders/{order['id']}/refund", headers=headers)).status_code in (401, 403)


# ── 开发模式模拟：无微信配置时全链路可走通 ────────────────────────

async def test_dev_mode_simulates_refund_success(client):
    user, order = await make_paid_order("rf_dev")
    await client.post(f"/api/pay/refund_order/{order['out_trade_no']}", headers=await user_headers(user))
    r = await client.post(f"/api/admin/orders/{order['id']}/refund/approve", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json()["status"] == "success"

    async with AsyncSessionLocal() as db:
        fresh = (await db.execute(select(Order).where(Order.id == order['id']))).scalar_one()
        assert fresh.status == OrderStatus.REFUNDED


# ── 已退款订单不能再申请 ──────────────────────────────────────────

async def test_refunded_order_cannot_request_again(client):
    user, order = await make_paid_order("rf_again")
    async with AsyncSessionLocal() as db:
        fresh = (await db.execute(select(Order).where(Order.id == order['id']))).scalar_one()
        fresh.status = OrderStatus.REFUNDED
        await db.commit()
    r = await client.post(f"/api/pay/refund_order/{order['out_trade_no']}", headers=await user_headers(user))
    assert r.status_code == 400


# ── Notice SSE 通道 ───────────────────────────────────────────────

async def test_notice_stream_content_type_and_initial_event():
    from app.api.routes import notice as notice_routes

    response = await notice_routes.notice_stream()
    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"

    it = response.body_iterator
    first = await it.__anext__()
    assert "retry: 5000" in first
    second = await it.__anext__()
    assert "event: notice.updated" in second
    await it.aclose()


async def test_admin_notice_update_publishes_broadcast(client):
    r = await client.put("/api/admin/notice", json={"content": "新通知内容", "is_active": True},
                         headers=ADMIN_HEADERS)
    assert r.status_code == 200
    r = await client.get("/api/notice")
    assert r.json()["content"] == "新通知内容"
