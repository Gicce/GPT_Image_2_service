"""v1.0.0 账户治理专项：密码重置 / 归档恢复 / 彻底删除 / 邮箱释放 / 版本接口。

隔离边界：全部在 cyimage_v4_test 测试库 + Redis db15 上运行，支付链路不触达真实微信。
"""

import json
import uuid

import httpx
import pytest
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password, create_access_token
from app.main import app
from app.services.order_assignment import assign_paid_order, PurgedAccountError
from tests.conftest import make_admin_headers, make_user


ADMIN = make_admin_headers()
ADMIN_PASSWORD = "admin-test-password"  # conftest clean_tables 写入的测试管理员密码


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


async def _set_password(user_id: str, password: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "UPDATE users SET password_hash = :h WHERE id = :id"
        ), {"h": hash_password(password), "id": user_id})
        await db.commit()


async def _use_registrable_email(user) -> str:
    """make_user 生成 @test.local（保留 TLD，EmailStr 拒绝）；换合法域名以验证邮箱释放。"""
    email = user.email.replace("@test.local", "@example.com")
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "UPDATE users SET email = :e WHERE id = :id"
        ), {"e": email, "id": user.id})
        await db.commit()
    return email


async def _audit_details(action: str) -> list[dict]:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT detail FROM admin_audit_logs WHERE action = :a"
        ), {"a": action})).scalars().all()
    return [json.loads(r) for r in rows]


async def _login(client, username: str, password: str):
    return await client.post("/api/auth/login", json={"username": username, "password": password})


# ── 管理员重置客户密码 ───────────────────────────────────────────

async def test_reset_password_generated_flow_revokes_old_sessions(client):
    user = await make_user("reset-target")
    await _set_password(user.id, "old-password-123")
    old_login = await _login(client, user.username, "old-password-123")
    assert old_login.status_code == 200
    old_token = old_login.json()["access_token"]
    me_headers = {"Authorization": f"Bearer {old_token}"}
    assert (await client.get("/api/auth/me", headers=me_headers)).status_code == 200

    response = await client.post(
        f"/api/admin/users/{user.id}/reset-password",
        json={"admin_password": ADMIN_PASSWORD, "reason": "客户忘记密码，电话核实"},
        headers=ADMIN,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["generated"] is True
    temp_password = body["new_password"]
    assert 10 <= len(temp_password) <= 14 and not set(temp_password) & set("0O1lI")

    # 旧会话立即失效；旧密码不能登录；新临时密码可登录且会话可用
    assert (await client.get("/api/auth/me", headers=me_headers)).status_code == 401
    assert (await _login(client, user.username, "old-password-123")).status_code == 401
    new_login = await _login(client, user.username, temp_password)
    assert new_login.status_code == 200
    assert (await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {new_login.json()['access_token']}"},
    )).status_code == 200

    # 审计有记录，且不含任何密码材料
    audits = await _audit_details("user_password_reset")
    assert any(a["user_id"] == user.id and a["generated"] is True for a in audits)
    assert not any(temp_password in json.dumps(a) for a in audits)

    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT password_changed_at, token_version FROM users WHERE id = :id"
        ), {"id": user.id})).one()
        assert row.password_changed_at is not None
        assert row.token_version == 1


async def test_reset_password_manual_and_guards(client):
    user = await make_user("reset-manual")

    ok = await client.post(
        f"/api/admin/users/{user.id}/reset-password",
        json={"admin_password": ADMIN_PASSWORD, "new_password": "manual-pw-123456", "reason": "管理员手动设置"},
        headers=ADMIN,
    )
    assert ok.status_code == 200 and ok.json()["generated"] is False
    assert (await _login(client, user.username, "manual-pw-123456")).status_code == 200

    wrong_pw = await client.post(
        f"/api/admin/users/{user.id}/reset-password",
        json={"admin_password": "not-the-admin-password", "reason": "x"},
        headers=ADMIN,
    )
    assert wrong_pw.status_code == 401

    too_short = await client.post(
        f"/api/admin/users/{user.id}/reset-password",
        json={"admin_password": ADMIN_PASSWORD, "new_password": "short", "reason": "x"},
        headers=ADMIN,
    )
    assert too_short.status_code == 400

    no_auth = await client.post(
        f"/api/admin/users/{user.id}/reset-password",
        json={"admin_password": ADMIN_PASSWORD, "reason": "x"},
    )
    assert no_auth.status_code == 401

    # 归档账户不能重置密码
    await client.post(f"/api/admin/users/{user.id}/archive", json={"reason": "测试归档"}, headers=ADMIN)
    archived = await client.post(
        f"/api/admin/users/{user.id}/reset-password",
        json={"admin_password": ADMIN_PASSWORD, "reason": "x"},
        headers=ADMIN,
    )
    assert archived.status_code == 409
    assert archived.json()["detail"]["code"] == "USER_ARCHIVED"


# ── 归档 / 恢复 ──────────────────────────────────────────────────

async def test_archive_revokes_sessions_and_restore_requires_relogin(client):
    user = await make_user("arch-restore")
    await _set_password(user.id, "keep-password-1")
    login = await _login(client, user.username, "keep-password-1")
    token = {"Authorization": f"Bearer {login.json()['access_token']}"}

    archived = await client.post(
        f"/api/admin/users/{user.id}/archive", json={"reason": "违规测试"}, headers=ADMIN,
    )
    assert archived.status_code == 200
    # 归档即禁用：存量会话立即失效
    assert (await client.get("/api/auth/me", headers=token)).status_code in (401, 403)
    assert (await _login(client, user.username, "keep-password-1")).status_code == 403

    restored = await client.post(
        f"/api/admin/users/{user.id}/restore", json={"reason": "申诉通过"}, headers=ADMIN,
    )
    assert restored.status_code == 200

    # 恢复不复活旧会话：归档前的 token 仍然失效
    assert (await client.get("/api/auth/me", headers=token)).status_code == 401
    # 原密码重新登录可用
    relogin = await _login(client, user.username, "keep-password-1")
    assert relogin.status_code == 200
    assert any(a["user_id"] == user.id for a in await _audit_details("user_restored"))

    not_archived = await client.post(
        f"/api/admin/users/{user.id}/restore", json={"reason": "重复恢复"}, headers=ADMIN,
    )
    assert not_archived.status_code == 400


async def test_archived_user_cannot_adjust_balance_or_assign_token(client):
    user = await make_user("arch-guard")
    await client.post(f"/api/admin/users/{user.id}/archive", json={"reason": "x"}, headers=ADMIN)

    balance = await client.put(
        f"/api/admin/users/{user.id}/balance", json={"paid_credits": 100}, headers=ADMIN,
    )
    assert balance.status_code == 409
    assign = await client.post(
        f"/api/admin/users/{user.id}/runtime-token/assign", json={}, headers=ADMIN,
    )
    assert assign.status_code == 409


# ── 彻底删除：干净账户（物理删除 + 邮箱释放 + 试用一次性） ────────

async def test_hard_delete_clean_account_releases_email_and_keeps_claim(client):
    user = await make_user("purge-clean")
    email = await _use_registrable_email(user)
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO trial_claims (id, normalized_email, user_id_at_claim, claimed_at, grant_credits, status, campaign_version) "
            "VALUES (:id, :email, :uid, now(), 500, 'granted', 1)"
        ), {"id": str(uuid.uuid4()), "email": email, "uid": user.id})
        await db.commit()

    resp = await client.post(
        f"/api/admin/users/{user.id}/hard-delete",
        json={"admin_password": ADMIN_PASSWORD, "confirm_identity": user.username, "reason": "测试删除空账户"},
        headers=ADMIN,
    )
    assert resp.status_code == 200
    assert resp.json()["mode"] == "purge"

    async with AsyncSessionLocal() as db:
        assert (await db.execute(text(
            "SELECT count(*) FROM users WHERE id = :id"), {"id": user.id}
        )).scalar() == 0
        # 试用领取依据独立保留：同邮箱重注册不能重复领试用
        assert (await db.execute(text(
            "SELECT count(*) FROM trial_claims WHERE user_id_at_claim = :id"), {"id": user.id}
        )).scalar() == 1

    # 幂等：重复调用直接成功且无副作用
    replay = await client.post(
        f"/api/admin/users/{user.id}/hard-delete",
        json={"admin_password": ADMIN_PASSWORD, "confirm_identity": user.username, "reason": "重复调用"},
        headers=ADMIN,
    )
    assert replay.status_code == 200
    assert replay.json()["already_purged"] is True

    # 原邮箱重注册：正常成功，产生全新用户 ID；试用领取资格已被 trial_claims
    # 独立保留（上断言），重注册账号不继承旧资产（防重复领取的既有回归见 test_trial_claims）
    re_reg = await client.post("/api/auth/register", json={
        "username": "purge-clean-reborn", "email": email, "password": "new-user-pw-123", "account_type": "normal",
    })
    assert re_reg.status_code == 200
    new_id = re_reg.json()["user"]["id"]
    assert new_id != user.id
    assert re_reg.json()["user"]["total_credits"] == 0  # 不继承旧账户资产
    # 同一邮箱占用检查对新账号生效（身份隔离：新号改邮箱前，原邮箱再次注册被拒）
    dup = await client.post("/api/auth/register", json={
        "username": "purge-clean-reborn2", "email": email, "password": "another-pw-12345", "account_type": "normal",
    })
    assert dup.status_code == 400


# ── 彻底删除：有业务历史与非零余额（脱敏主体 + 余额核销 + 追溯） ──

async def _attach_business_history(user_id: str, *, paid_credits: int = 300, gift_credits: int = 50) -> str:
    """直接 SQL 构造历史数据（订单/流水/用量），模拟有业务历史的账户。"""
    order_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO orders (id, user_id, out_trade_no, amount_usd, amount_cny, exchange_rate, "
            "refunded_cny, refunded_usd, status, created_at) "
            "VALUES (:id, :uid, :tno, 5.00, 35.00, 7.0, 0, 0, 'assigned', now())"
        ), {"id": order_id, "uid": user_id, "tno": f"CYHARD{uuid.uuid4().hex[:8].upper()}"})
        await db.execute(text(
            "INSERT INTO billing_transactions (id, user_id, type, status, amount_usd, trial_amount, "
            "balance_amount, billing_source, image_count, amount_credits, created_at, updated_at) "
            "VALUES (:id, :uid, 'RECHARGE', 'SUCCESS', 5, 0, 5, 'PAID', 0, 500, now(), now())"
        ), {"id": str(uuid.uuid4()), "uid": user_id})
        await db.execute(text(
            "INSERT INTO usage_logs (id, user_id, model, usage_type, image_count, input_tokens, "
            "output_tokens, cached_tokens, cost_usd, cost_credits, created_at) "
            "VALUES (:id, :uid, 'gpt-image-2', 'image', 1, 0, 0, 0, 0.1, 80, now())"
        ), {"id": str(uuid.uuid4()), "uid": user_id})
        await db.execute(text(
            "UPDATE users SET paid_credits = :paid, gift_credits = :gift WHERE id = :uid"
        ), {"paid": paid_credits, "gift": gift_credits, "uid": user_id})
        await db.commit()
    return order_id


async def test_hard_delete_with_history_disposes_balance_and_keeps_ledger(client):
    user = await make_user("purge-history")
    registrable_email = await _use_registrable_email(user)
    order_id = await _attach_business_history(user.id, paid_credits=300, gift_credits=50)
    await client.post(f"/api/admin/users/{user.id}/archive", json={"reason": "先归档"}, headers=ADMIN)

    resp = await client.post(
        f"/api/admin/users/{user.id}/hard-delete",
        json={"admin_password": ADMIN_PASSWORD, "confirm_identity": registrable_email, "reason": "客户注销申请，余额不退"},
        headers=ADMIN,
    )
    assert resp.status_code == 200
    assert resp.json()["mode"] == "anonymize"

    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT username, email, is_active, purged_at, purged_by, purge_reason, "
            "paid_credits, gift_credits, trial_credits, token_version FROM users WHERE id = :id"
        ), {"id": user.id})).one()
        # 登录身份消灭：用户名/邮箱改写、禁用、密码不可用（哈希已重写）
        assert row.username.startswith("purged-") and row.username != user.username
        assert row.email.endswith("@purged.invalid") and row.email != user.email
        assert row.is_active is False
        assert row.purged_at is not None and row.purged_by == "admin"
        assert row.purge_reason == "客户注销申请，余额不退"
        # 余额核销清零
        assert (row.paid_credits, row.gift_credits, row.trial_credits) == (0, 0, 0)
        assert row.token_version >= 1

        # 核销留痕：每个非零桶一条 ADMIN_ADJUSTMENT，金额等于原值，不构成收入
        dispose_rows = (await db.execute(text(
            "SELECT amount_credits, remark FROM billing_transactions "
            "WHERE user_id = :uid AND type = 'ADMIN_ADJUSTMENT' AND remark LIKE '账户彻底删除余额核销%'"
        ), {"uid": user.id})).all()
        assert sorted(r.amount_credits for r in dispose_rows) == [50, 300]

        # 账务留存：订单/流水/用量仍可按用户追溯（FK 未破坏）
        assert (await db.execute(text("SELECT count(*) FROM orders WHERE id = :id"), {"id": order_id})).scalar() == 1
        assert (await db.execute(text(
            "SELECT count(*) FROM billing_transactions WHERE user_id = :uid AND type = 'RECHARGE'"
        ), {"uid": user.id})).scalar() == 1
        assert (await db.execute(text(
            "SELECT count(*) FROM usage_logs WHERE user_id = :uid"
        ), {"uid": user.id})).scalar() == 1

    # 原邮箱可注册新账户，新账户零资产、零历史
    re_reg = await client.post("/api/auth/register", json={
        "username": "purge-history-reborn", "email": registrable_email, "password": "reborn-pw-12345", "account_type": "normal",
    })
    assert re_reg.status_code == 200
    assert re_reg.json()["user"]["total_credits"] == 0

    # 审计包含原用户名/邮箱快照与核销明细，不含管理员密码
    audits = await _audit_details("user_hard_deleted")
    mine = [a for a in audits if a["user_id"] == user.id]
    assert mine and mine[0]["original_username"] == user.username
    assert mine[0]["original_email"] == registrable_email
    assert mine[0]["balance_disposed"] == {"paid": 300, "gift": 50}
    assert ADMIN_PASSWORD not in json.dumps(mine)

    # 已删除账户：不可恢复、不可编辑、不可重置密码
    assert (await client.post(f"/api/admin/users/{user.id}/restore", json={"reason": "x"}, headers=ADMIN)).status_code == 409
    assert (await client.put(f"/api/admin/users/{user.id}", json={"username": "hack"}, headers=ADMIN)).status_code == 409
    assert (await client.post(
        f"/api/admin/users/{user.id}/reset-password",
        json={"admin_password": ADMIN_PASSWORD, "reason": "x"}, headers=ADMIN,
    )).status_code == 409


async def test_hard_delete_guards(client):
    user = await make_user("purge-guards")
    await _attach_business_history(user.id)

    # 普通管理员 403
    normal_admin_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO admin_users (id, username, display_name, password_hash, role, is_active, "
            "must_change_password, created_at, updated_at) "
            "VALUES (:id, 'op-hard', 'Op', :pw, 'admin', true, false, now(), now())"
        ), {"id": normal_admin_id, "pw": hash_password("operator-pw-123")})
        await db.commit()
    normal_headers = make_admin_headers(role="admin", admin_id=normal_admin_id, username="op-hard")
    forbidden = await client.post(
        f"/api/admin/users/{user.id}/hard-delete",
        json={"admin_password": "operator-pw-123", "confirm_identity": user.username, "reason": "x"},
        headers=normal_headers,
    )
    assert forbidden.status_code == 403

    # 管理员密码错误 / 确认信息不匹配
    assert (await client.post(
        f"/api/admin/users/{user.id}/hard-delete",
        json={"admin_password": "wrong", "confirm_identity": user.username, "reason": "x"},
        headers=ADMIN,
    )).status_code == 401
    assert (await client.post(
        f"/api/admin/users/{user.id}/hard-delete",
        json={"admin_password": ADMIN_PASSWORD, "confirm_identity": "someone-else", "reason": "x"},
        headers=ADMIN,
    )).status_code == 400

    # 进行中业务硬阻断：RESERVED 预占
    await client.post(f"/api/admin/users/{user.id}/archive", json={"reason": "x"}, headers=ADMIN)
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO billing_transactions (id, user_id, type, status, amount_usd, trial_amount, "
            "balance_amount, billing_source, image_count, amount_credits, created_at, updated_at) "
            "VALUES (:id, :uid, 'IMAGE2_CHARGE', 'RESERVED', 0, 0, 0, 'NONE', 0, 80, now(), now())"
        ), {"id": str(uuid.uuid4()), "uid": user.id})
        await db.commit()
    blocked = await client.post(
        f"/api/admin/users/{user.id}/hard-delete",
        json={"admin_password": ADMIN_PASSWORD, "confirm_identity": user.username, "reason": "x"},
        headers=ADMIN,
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "USER_HARD_DELETE_BLOCKED"
    assert blocked.json()["detail"]["blockers"]["reserved_billing"] == 1

    # 阻断解除后：进行中退款同样阻断
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM billing_transactions WHERE user_id = :uid AND status = 'RESERVED'"), {"uid": user.id})
        order_row = (await db.execute(text("SELECT id FROM orders WHERE user_id = :uid LIMIT 1"), {"uid": user.id})).one()
        await db.execute(text(
            "INSERT INTO refund_requests (id, order_id, user_id, source, requested_amount_fen, "
            "requested_amount_cny, requested_amount_usd, status, requested_at, created_at, updated_at) "
            "VALUES (:id, :oid, :uid, 'user', 3500, 35, 5, 'requested', now(), now(), now())"
        ), {"id": str(uuid.uuid4()), "oid": order_row.id, "uid": user.id})
        # 顺手验证未完成订单阻断：再放一张 PENDING 单
        await db.execute(text(
            "INSERT INTO orders (id, user_id, out_trade_no, amount_usd, amount_cny, exchange_rate, "
            "refunded_cny, refunded_usd, status, created_at) "
            "VALUES (:id, :uid, :tno, 1, 7, 7, 0, 0, 'pending', now())"
        ), {"id": str(uuid.uuid4()), "uid": user.id, "tno": f"CYPEND{uuid.uuid4().hex[:8].upper()}"})
        await db.commit()
    blocked2 = await client.post(
        f"/api/admin/users/{user.id}/hard-delete",
        json={"admin_password": ADMIN_PASSWORD, "confirm_identity": user.username, "reason": "x"},
        headers=ADMIN,
    )
    detail = blocked2.json()["detail"]
    assert blocked2.status_code == 409
    assert detail["blockers"]["open_refunds"] == 1
    assert detail["blockers"]["incomplete_orders"] == 1
    # 账户未被动过
    async with AsyncSessionLocal() as db:
        assert (await db.execute(text(
            "SELECT purged_at IS NULL FROM users WHERE id = :id"), {"id": user.id}
        )).scalar() is True


# ── 迟到 / 重复支付回调：purged 账户拒绝入账 ─────────────────────

async def test_late_payment_callback_refuses_credit_for_purged_account(client):
    """迟到/重复支付回调防护（服务层纵深防御）。

    正常时序下 PAID/PENDING 订单会被 hard-delete 的进行中业务检查阻断；本测试
    构造的是并发窗口终态（预检通过后回调并发把订单置 PAID）与未来新调用点：
    purged 账户 + PAID 未入账订单同时存在时，assign_paid_order 必须拒绝入账。
    """
    user = await make_user("purge-latepay")
    await _set_password(user.id, "whatever-123")

    # 无进行中业务的干净账户路径：直接 SQL 挂一笔历史订单使其走脱敏主体（FK 保留）
    order_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO orders (id, user_id, out_trade_no, amount_usd, amount_cny, exchange_rate, "
            "refunded_cny, refunded_usd, status, created_at) "
            "VALUES (:id, :uid, :tno, 5, 35, 7, 0, 0, 'refunded', now())"
        ), {"id": order_id, "uid": user.id, "tno": f"CYLATE{uuid.uuid4().hex[:8].upper()}"})
        await db.commit()

    resp = await client.post(
        f"/api/admin/users/{user.id}/hard-delete",
        json={"admin_password": ADMIN_PASSWORD, "confirm_identity": user.username, "reason": "客户注销"},
        headers=ADMIN,
    )
    assert resp.status_code == 200

    # 模拟迟到回调已把订单标为 paid（未入账）后触发 assign
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "UPDATE orders SET status = 'paid', paid_at = now(), credits_granted = 500 WHERE id = :id"
        ), {"id": order_id})
        await db.commit()

    # 迟到回调（PAID 订单补入账）：服务层拒绝入账（notify 需微信验签，
    # 隔离环境以服务层等价覆盖同一防护点），账户点数不变、订单不被标记 assigned
    from app.models.token import Order
    async with AsyncSessionLocal() as db:
        order = await db.get(Order, order_id)
        with pytest.raises(PurgedAccountError):
            await assign_paid_order(db, order, auto=True)
        await db.rollback()
        row = (await db.execute(text(
            "SELECT paid_credits FROM users WHERE id = :id"), {"id": user.id}
        )).one()
        assert row.paid_credits == 0
        assert (await db.execute(text(
            "SELECT status FROM orders WHERE id = :id"), {"id": order_id}
        )).scalar() == "paid"

        # 拒绝入账事件必须进管理员审计流（notify/query 的 PurgedAccountError
        # handler 均调用 _record_purged_payment_rejected；隔离环境直接驱动该
        # helper 断言落库内容——订单号/金额/点数/账户齐全，后台可检索）
        from app.api.routes.payment import _record_purged_payment_rejected
        await db.refresh(order)  # rollback 使实例过期，先刷新避免属性惰性 IO
        await _record_purged_payment_rejected(db, order, exc=PurgedAccountError("账户已彻底删除，拒绝入账"))
        await db.commit()
        audits = await _audit_details("purged_payment_rejected")
        match = [a for a in audits if a["order_id"] == order_id]
        assert match, "拒绝入账事件未写入 admin_audit_logs"
        entry = match[-1]
        assert entry["user_id"] == user.id
        assert entry["amount_cny"] == 35.0
        assert entry["credits_granted"] == 500
        assert "彻底删除" in entry["message"]


# ── 列表口径 / 统计 / 旧 token 兼容 ──────────────────────────────

async def test_archive_scopes_and_stats_exclude_purged(client):
    live = await make_user("scope-live")
    purged = await make_user("scope-purged")
    await _attach_business_history(purged.id)
    await client.post(
        f"/api/admin/users/{purged.id}/hard-delete",
        json={"admin_password": ADMIN_PASSWORD, "confirm_identity": purged.username, "reason": "x"},
        headers=ADMIN,
    )

    current_ids = {row["id"] for row in (await client.get("/api/admin/users", headers=ADMIN)).json()}
    assert live.id in current_ids and purged.id not in current_ids

    purged_rows = (await client.get("/api/admin/users?archive_scope=purged", headers=ADMIN)).json()
    assert [row["id"] for row in purged_rows] == [purged.id]
    assert purged_rows[0]["purged_at"] is not None
    assert purged_rows[0]["purged_by"] == "admin"

    stats = (await client.get("/api/admin/stats", headers=ADMIN)).json()
    assert stats["users_total"] == len(current_ids)  # purged 不计入客户总数

    # 详情包含密码修改时间字段（历史无记录 = null，不编造）
    detail = (await client.get(f"/api/admin/users/{live.id}", headers=ADMIN)).json()
    assert "password_changed_at" in detail
    assert "purged_at" in detail


async def test_legacy_token_without_tv_stays_valid_until_revoked(client):
    """兼容窗口：v1.0.0 之前签发的 token（无 tv 字段）在未发生撤销事件前继续有效。"""
    user = await make_user("legacy-token")
    legacy_token = create_access_token(user.id)  # 不传 token_version，模拟旧版本签发
    headers = {"Authorization": f"Bearer {legacy_token}"}
    assert (await client.get("/api/auth/me", headers=headers)).status_code == 200

    # 发生任意撤销事件（自助改密）后失效
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "UPDATE users SET token_version = 1 WHERE id = :id"), {"id": user.id}
        )
        await db.commit()
    assert (await client.get("/api/auth/me", headers=headers)).status_code == 401


# ── 自助改密撤销会话 + 版本接口 ──────────────────────────────────

async def test_forgot_password_revokes_sessions(client):
    """自助找回密码成功后，旧 Bearer token 立即失效（经 Redis 验证码链路）。"""
    from app.core.redis import get_redis
    user = await make_user("forgot-revoke")
    email = await _use_registrable_email(user)
    await _set_password(user.id, "old-forgot-1")
    login = await _login(client, user.username, "old-forgot-1")
    token = {"Authorization": f"Bearer {login.json()['access_token']}"}

    redis = get_redis()
    await redis.setex(f"pwd:code:{email}", 300, "123456")
    reset = await client.post("/api/auth/forgot-password/reset", json={
        "email": email, "code": "123456", "new_password": "new-forgot-1",
    })
    assert reset.status_code == 200
    assert (await client.get("/api/auth/me", headers=token)).status_code == 401
    assert (await _login(client, user.username, "new-forgot-1")).status_code == 200


async def test_version_endpoints(client):
    health = (await client.get("/api/health")).json()
    assert health["version"] == "1.0.0"

    unauth = await client.get("/api/admin/version")
    assert unauth.status_code == 401

    version = (await client.get("/api/admin/version", headers=ADMIN)).json()
    assert version["version"] == "1.0.0"
    assert version["environment"] == "development"
    assert version["version_status"] == "pending_release"
    assert version["build_commit"] is None  # 测试环境未注入，如实为空
    entries = {e["version"]: e for e in version["version_log"]}
    assert "1.0.0" in entries and entries["1.0.0"]["features"]
    assert set(entries["1.0.0"]) >= {"version", "date", "status", "features", "fixes", "notes"}
    # 日志为纯文本数组，不含可执行内容
    blob = json.dumps(version["version_log"])
    assert "<script" not in blob


# ── 运维入口权限收紧（安全评估修复：SECRET_KEY 提权路径封堵） ────

async def test_config_write_and_restart_require_super_admin(client, tmp_path, monkeypatch):
    """普通管理员不能写 .env / 重启容器（可改 SECRET_KEY = 可伪造 super_admin JWT）。"""
    from datetime import datetime, timezone, timedelta

    normal_admin_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO admin_users (id, username, display_name, password_hash, role, is_active, "
            "must_change_password, created_at, updated_at) "
            "VALUES (:id, 'op-config', 'Op', :pw, 'admin', true, false, now(), now())"
        ), {"id": normal_admin_id, "pw": hash_password("operator-pw-123")})
        await db.commit()
    normal_headers = make_admin_headers(role="admin", admin_id=normal_admin_id, username="op-config")

    # 未登录 / 普通管理员均被拒（不触达 .env 写入与 docker）
    assert (await client.put(
        "/api/admin/config", json={"updates": {"SECRET_KEY": "attacker-known"}},
    )).status_code == 401
    forbidden = await client.put(
        "/api/admin/config",
        json={"updates": {"SECRET_KEY": "attacker-known"}},
        headers=normal_headers,
    )
    assert forbidden.status_code == 403
    assert (await client.post("/api/admin/config/restart", headers=normal_headers)).status_code == 403
    assert (await client.post("/api/admin/config/restart")).status_code == 401

    # 读取保持所有管理员可用（敏感值脱敏）
    readable = await client.get("/api/admin/config", headers=normal_headers)
    assert readable.status_code == 200
    env_blob = json.dumps(readable.json())
    assert "attacker-known" not in env_blob

    # 超级管理员可写入非敏感项（ENV_FILE_PATH 指向临时文件，隔离本机 .env）
    env_file = tmp_path / "env.test"
    env_file.write_text("SERVER_BASE_URL=https://old.example\n", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE_PATH", str(env_file))
    ok = await client.put(
        "/api/admin/config",
        json={"updates": {"SERVER_BASE_URL": "https://new.example"}},
        headers=ADMIN,
    )
    assert ok.status_code == 200
    assert "SERVER_BASE_URL=https://new.example" in env_file.read_text(encoding="utf-8")

    # 防提权验证：攻击者用自造密钥签发的 super_admin token 无法通过验签
    from jose import jwt as _jwt
    from app.core.config import settings as _settings
    forged = _jwt.encode(
        {"sub": "attacker", "admin_id": str(uuid.uuid4()), "role": "super_admin",
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        "attacker-known-secret", algorithm=_settings.ALGORITHM,
    )
    forged_resp = await client.post(
        "/api/admin/config/restart",
        headers={"Authorization": f"Bearer {forged}"},
    )
    assert forged_resp.status_code == 401
