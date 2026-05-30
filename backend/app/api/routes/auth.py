from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, EmailStr
import uuid
import secrets
import logging

from app.core.database import get_db
from app.core.security import hash_password, verify_password, create_access_token, create_admin_token, get_current_user, _validate_bcrypt_password
from app.core.config import settings
from app.core.redis import get_redis
from app.core.email import send_verification_code
from app.models.user import User, UserToken
from app.models.token import TokenInventory

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
    import json
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
        trial_token = await db.execute(
            select(TokenInventory).where(
                TokenInventory.is_trial == True,
                TokenInventory.group == "image",
                TokenInventory.is_assigned == False,
            ).limit(1)
        )
        trial_token = trial_token.scalar_one_or_none()
        if not trial_token:
            raise HTTPException(status_code=400, detail="试用名额已满，请直接购买套餐")

        trial_token.is_assigned = True
        trial_token.assigned_to = user.id
        trial_token.assigned_at = now

        ut = UserToken(
            id=str(uuid.uuid4()),
            user_id=user.id,
            token_id=trial_token.id,
            group="image",
            balance_usd=1.0,
            is_trial=True,
        )
        db.add(ut)
        user.account_type = "trial"
        user.trial_expires_at = now + timedelta(days=2)

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
        trial_token = await db.execute(
            select(TokenInventory).where(
                TokenInventory.is_trial == True,
                TokenInventory.group == "image",
                TokenInventory.is_assigned == False,
            ).limit(1)
        )
        trial_token = trial_token.scalar_one_or_none()
        if not trial_token:
            raise HTTPException(status_code=400, detail="试用名额已满，请直接购买套餐")

        trial_token.is_assigned = True
        trial_token.assigned_to = user.id
        trial_token.assigned_at = now

        ut = UserToken(
            id=str(uuid.uuid4()),
            user_id=user.id,
            token_id=trial_token.id,
            group="image",
            balance_usd=1.0,
            is_trial=True,
        )
        db.add(ut)
        user.account_type = "trial"
        user.trial_expires_at = now + timedelta(days=2)

    await db.flush()
    access_token = create_access_token(user.id)
    user_info = await _user_info(user, db)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user_info,
    }


@router.post("/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    access_token = create_access_token(user.id)
    user_info = await _user_info(user, db)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user_info,
    }


@router.post("/admin/login")
async def admin_login(req: AdminLoginRequest):
    if req.username != settings.ADMIN_USERNAME or req.password != settings.ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="管理员账号或密码错误")
    return {"access_token": create_admin_token(), "token_type": "bearer"}


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

    existing_ut = await db.execute(
        select(UserToken).where(UserToken.user_id == user.id, UserToken.group == "image")
    )
    if existing_ut.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="已拥有该分组的 Token")

    trial_token = await db.execute(
        select(TokenInventory).where(
            TokenInventory.is_trial == True,
            TokenInventory.group == "image",
            TokenInventory.is_assigned == False,
        ).limit(1)
    )
    trial_token = trial_token.scalar_one_or_none()
    if not trial_token:
        raise HTTPException(status_code=400, detail="试用名额已满，请直接购买套餐")

    now = datetime.now(timezone.utc)
    user.account_type = "trial"
    user.trial_expires_at = now + timedelta(days=3)

    trial_token.is_assigned = True
    trial_token.assigned_to = user.id
    trial_token.assigned_at = now

    ut = UserToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_id=trial_token.id,
        group="image",
        balance_usd=1.0,
        is_trial=True,
    )
    db.add(ut)
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

    ut_result = await db.execute(
        select(UserToken).where(UserToken.user_id == user.id)
    )
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

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "account_type": user.account_type,
        "trial_expires_at": user.trial_expires_at.isoformat() if user.trial_expires_at else None,
        "trial_expired": trial_expired,
        "tokens": tokens,
    }
