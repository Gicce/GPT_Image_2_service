from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, EmailStr
import uuid
import secrets
import logging
import json

from app.core.database import get_db
from app.core.security import hash_password, verify_password, create_access_token, create_admin_token, get_current_user, _validate_bcrypt_password
from app.core.config import settings
from app.core.redis import get_redis
from app.core.email import send_verification_code
from app.models.user import User
from app.models.admin_user import AdminUser
from app.models.audit import AdminAuditLog
from app.services import billing
from app.services import runtime_token as rt

logger = logging.getLogger(__name__)

router = APIRouter()


class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
    account_type: str = "normal"


class LoginRequest(BaseModel):
    username: str
    password: str


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class ForgotPasswordSendRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResetRequest(BaseModel):
    email: EmailStr
    code: str
    new_password: str


class RegisterSendCodeRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
    account_type: str = "normal"


class RegisterVerifyRequest(BaseModel):
    email: EmailStr
    code: str
    username: str
    password: str
    account_type: str = "normal"


async def _grant_trial(db: AsyncSession, user: User, days: int) -> bool:
    """发放试用：绑定默认试用 Token（共享池，不消耗库存）+ 发放试用额度（写流水）。不 commit。

    返回 False 表示试用通道未开放（无有效默认试用 Token）。
    """
    trial_token = await rt.resolve_default_token(db, is_trial=True)
    if trial_token is None:
        return False

    now = datetime.now(timezone.utc)
    await rt.bind_token_to_user(db, user.id, trial_token, source="register_trial")
    user.account_type = "trial"
    user.trial_expires_at = now + timedelta(days=days)
    await billing.grant_trial_credit(
        db, user, billing.Decimal(str(settings.TRIAL_CREDIT_USD))
    )
    return True


@router.post("/register/send-code")
async def register_send_code(req: RegisterSendCodeRequest, db: AsyncSession = Depends(get_db)):
    if req.account_type not in ("trial", "normal"):
        raise HTTPException(status_code=400, detail="account_type 必须为 trial 或 normal")

    _validate_bcrypt_password(req.password)

    existing = await db.execute(
        select(User).where((User.username == req.username) | (User.email == req.email))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名或邮箱已存在")

    email = req.email.strip().lower()
    redis = get_redis()

    rate_key = f"reg:rate:{email}"
    if await redis.exists(rate_key):
        raise HTTPException(status_code=429, detail="请求过于频繁，请60秒后重试")

    lockout_key = f"reg:lockout:{email}"
    if await redis.exists(lockout_key):
        raise HTTPException(status_code=429, detail="验证码尝试次数过多，请稍后再试")

    await redis.setex(rate_key, 60, "1")

    code = "".join(secrets.choice("0123456789") for _ in range(6))

    code_key = f"reg:code:{email}"
    attempts_key = f"reg:attempts:{email}"

    # Store code + registration data in Redis
    reg_data = {"username": req.username, "password": req.password, "account_type": req.account_type}
    await redis.setex(code_key, 300, json.dumps({"code": code, "data": reg_data}))
    await redis.setex(attempts_key, 300, "0")

    try:
        await send_verification_code(email, code, purpose="register")
    except Exception:
        logger.exception("Failed to send registration code to %s", email)
        raise HTTPException(status_code=500, detail="邮件发送失败，请稍后重试")

    return {"message": "验证码已发送"}


@router.post("/register/verify")
async def register_verify(req: RegisterVerifyRequest, db: AsyncSession = Depends(get_db)):
    email = req.email.strip().lower()
    redis = get_redis()

    code_key = f"reg:code:{email}"
    attempts_key = f"reg:attempts:{email}"
    lockout_key = f"reg:lockout:{email}"

    if await redis.exists(lockout_key):
        raise HTTPException(status_code=429, detail="验证码尝试次数过多，请稍后再试")

    stored = await redis.get(code_key)
    if not stored:
        raise HTTPException(status_code=400, detail="验证码无效或已过期，请重新发送")

    import json
    stored_data = json.loads(stored)

    if stored_data.get("code") != req.code:
        attempts = int(await redis.get(attempts_key) or "0") + 1
        await redis.setex(attempts_key, 300, str(attempts))

        if attempts >= 5:
            await redis.setex(lockout_key, 900, "1")
            await redis.delete(code_key, attempts_key)
            raise HTTPException(status_code=429, detail="验证码尝试次数过多，请稍后再试")

        raise HTTPException(status_code=400, detail="验证码无效或已过期")

    # Re-check uniqueness (could have changed since send-code)
    existing = await db.execute(
        select(User).where((User.username == req.username) | (User.email == req.email))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名或邮箱已存在")

    _validate_bcrypt_password(req.password)

    now = datetime.now(timezone.utc)
    user = User(
        id=str(uuid.uuid4()),
        username=req.username,
        email=email,
        password_hash=hash_password(req.password),
        account_type="normal",
    )
    db.add(user)
    await db.flush()

    if req.account_type == "trial":
        granted = await _grant_trial(db, user, days=2)
        if not granted:
            raise HTTPException(status_code=400, detail="试用名额已满，请直接购买套餐")

    await db.flush()
    access_token = create_access_token(user.id)
    user_info = await _user_info(user, db)

    await redis.delete(code_key, attempts_key, f"reg:rate:{email}")

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user_info,
    }


@router.post("/register")
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    if req.account_type not in ("trial", "normal"):
        raise HTTPException(status_code=400, detail="account_type 必须为 trial 或 normal")

    existing = await db.execute(
        select(User).where((User.username == req.username) | (User.email == req.email))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名或邮箱已存在")

    now = datetime.now(timezone.utc)
    user = User(
        id=str(uuid.uuid4()),
        username=req.username,
        email=req.email,
        password_hash=hash_password(req.password),
        account_type="normal",
    )
    db.add(user)
    await db.flush()

    if req.account_type == "trial":
        granted = await _grant_trial(db, user, days=2)
        if not granted:
            raise HTTPException(status_code=400, detail="试用名额已满，请直接购买套餐")

    await db.flush()
    access_token = create_access_token(user.id)
    user_info = await _user_info(user, db)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user_info,
    }


@router.post("/login")
async def login(req: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    redis = get_redis()

    # 暴力破解防护：用户名 + IP 双维度（阈值比管理员登录宽松，避免误伤正常用户）
    fail_window_s = 900
    username = req.username.strip().lower()
    client_ip = request.headers.get("X-Forwarded-For", "")
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "unknown"

    if redis:
        if (await redis.exists(f"userlogin:lock:user:{username}")
                or await redis.exists(f"userlogin:lock:ip:{client_ip}")):
            raise HTTPException(status_code=429, detail="尝试次数过多，请稍后再试")

    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        if redis:
            for dimension, threshold in (("user", 10), ("ip", 30)):
                key = f"userlogin:fail:{dimension}:{username if dimension == 'user' else client_ip}"
                count = await redis.incr(key)
                if count == 1:
                    await redis.expire(key, fail_window_s)
                if count >= threshold:
                    await redis.setex(f"userlogin:lock:{dimension}:{username if dimension == 'user' else client_ip}",
                                      fail_window_s, "1")
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    if redis:
        await redis.delete(f"userlogin:fail:user:{username}", f"userlogin:fail:ip:{client_ip}")

    access_token = create_access_token(user.id)
    user_info = await _user_info(user, db)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user_info,
    }


@router.post("/admin/login")
async def admin_login(req: AdminLoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    username = req.username.strip().lower()
    redis = get_redis()

    # 客户端 IP：nginx 反代后取 X-Forwarded-For 首跳
    client_ip = request.headers.get("X-Forwarded-For", "")
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "unknown"
    user_agent = (request.headers.get("User-Agent") or "")[:200]

    async def _audit(admin_username: str, action: str, detail: dict):
        db.add(AdminAuditLog(admin=admin_username[:64], action=action,
                             detail=json.dumps({**detail, "ip": client_ip, "ua": user_agent}, ensure_ascii=False)))

    # 暴力破解防护：IP 与用户名两个维度独立计数（15 分钟窗口）
    fail_window_s = 900
    user_fail_threshold = 5
    ip_fail_threshold = 20
    if redis:
        if (await redis.exists(f"adminlogin:lock:user:{username}")
                or await redis.exists(f"adminlogin:lock:ip:{client_ip}")):
            raise HTTPException(status_code=429, detail="尝试次数过多，请稍后再试")

    result = await db.execute(select(AdminUser).where(AdminUser.username == username))
    admin = result.scalar_one_or_none()

    ok = admin is not None and admin.is_active and verify_password(req.password, admin.password_hash)
    if not ok:
        reason = "unknown_user" if admin is None else ("disabled" if not admin.is_active else "bad_password")
        if redis:
            for dimension, threshold in (("user", user_fail_threshold), ("ip", ip_fail_threshold)):
                key = f"adminlogin:fail:{dimension}:{username if dimension == 'user' else client_ip}"
                count = await redis.incr(key)
                if count == 1:
                    await redis.expire(key, fail_window_s)
                if count >= threshold:
                    await redis.setex(f"adminlogin:lock:{dimension}:{username if dimension == 'user' else client_ip}",
                                      fail_window_s, "1")
        # 对外统一文案，不区分用户名是否存在/是否禁用，避免枚举有效管理员
        await _audit(username, "admin_login_failed", {"reason": reason})
        await db.commit()
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    admin.last_login_at = datetime.now(timezone.utc)
    await _audit(username, "admin_login_success", {"admin_id": admin.id})
    await db.commit()

    if redis:
        await redis.delete(f"adminlogin:fail:user:{username}", f"adminlogin:fail:ip:{client_ip}")

    return {
        "access_token": create_admin_token(admin.id, admin.username, admin.role),
        "token_type": "bearer",
        "admin": {
            "id": admin.id,
            "username": admin.username,
            "display_name": admin.display_name,
            "role": admin.role,
            "must_change_password": admin.must_change_password,
        },
    }


@router.post("/forgot-password/send-code")
async def forgot_password_send_code(req: ForgotPasswordSendRequest, db: AsyncSession = Depends(get_db)):
    email = req.email.strip().lower()
    redis = get_redis()

    rate_key = f"pwd:rate:{email}"
    if await redis.exists(rate_key):
        raise HTTPException(status_code=429, detail="请求过于频繁，请60秒后重试")

    lockout_key = f"pwd:lockout:{email}"
    if await redis.exists(lockout_key):
        raise HTTPException(status_code=429, detail="验证码尝试次数过多，请稍后再试")

    await redis.setex(rate_key, 60, "1")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user:
        code = "".join(secrets.choice("0123456789") for _ in range(6))
        code_key = f"pwd:code:{email}"
        attempts_key = f"pwd:attempts:{email}"

        await redis.setex(code_key, 300, code)
        await redis.setex(attempts_key, 300, "0")

        try:
            await send_verification_code(email, code)
        except Exception:
            logger.exception("Failed to send verification code to %s", email)
            raise HTTPException(status_code=500, detail="邮件发送失败，请稍后重试")

    return {"message": "如果该邮箱已注册，验证码已发送"}


@router.post("/forgot-password/reset")
async def forgot_password_reset(req: ForgotPasswordResetRequest, db: AsyncSession = Depends(get_db)):
    email = req.email.strip().lower()
    redis = get_redis()

    code_key = f"pwd:code:{email}"
    attempts_key = f"pwd:attempts:{email}"
    lockout_key = f"pwd:lockout:{email}"

    if await redis.exists(lockout_key):
        raise HTTPException(status_code=429, detail="验证码尝试次数过多，请稍后再试")

    stored_code = await redis.get(code_key)
    if not stored_code or stored_code != req.code:
        attempts = int(await redis.get(attempts_key) or "0") + 1
        await redis.setex(attempts_key, 300, str(attempts))

        if attempts >= 5:
            await redis.setex(lockout_key, 900, "1")
            await redis.delete(code_key, attempts_key)
            raise HTTPException(status_code=429, detail="验证码尝试次数过多，请稍后再试")

        raise HTTPException(status_code=400, detail="验证码无效或已过期")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="验证码无效或已过期")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    _validate_bcrypt_password(req.new_password)
    user.password_hash = hash_password(req.new_password)
    await db.flush()

    await redis.delete(code_key, attempts_key, f"pwd:rate:{email}")

    return {"message": "密码重置成功"}


@router.post("/upgrade-trial")
async def upgrade_trial(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.account_type != "normal":
        raise HTTPException(status_code=400, detail="仅普通账户可申请试用")

    if billing.d(user.trial_credit_usd) > 0:
        raise HTTPException(status_code=400, detail="已领取过试用额度")

    granted = await _grant_trial(db, user, days=3)
    if not granted:
        raise HTTPException(status_code=400, detail="试用名额已满，请直接购买套餐")

    await db.commit()

    user_info = await _user_info(user, db)
    return {"user": user_info}


@router.get("/me")
async def get_me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _user_info(user, db)


async def _user_info(user: User, db: AsyncSession):
    now = datetime.now(timezone.utc)
    trial_expired = (
        user.account_type == "trial"
        and user.trial_expires_at
        and user.trial_expires_at.replace(tzinfo=timezone.utc) < now
    )

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "account_type": user.account_type,
        "trial_expires_at": user.trial_expires_at.isoformat() if user.trial_expires_at else None,
        "trial_expired": trial_expired,
        "balance_usd": str(billing.q6(billing.d(user.balance_usd))),
        "trial_credit_usd": str(billing.q6(billing.d(user.trial_credit_usd))),
    }
