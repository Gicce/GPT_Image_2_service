import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.email import send_verification_code
from app.core.redis import get_redis
from app.core.security import (
    _validate_bcrypt_password,
    create_access_token,
    create_admin_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.models.token import TokenInventory
from app.models.user import User, UserToken
from app.services.account import serialize_user

logger = logging.getLogger(__name__)
router = APIRouter()
TRIAL_BALANCE_USD = 1.0
TRIAL_DURATION_DAYS = 2


class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
    account_type: str = "trial"


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


def _normalize_account_type(account_type: str) -> str:
    normalized = (account_type or "normal").strip().lower()
    if normalized not in {"trial", "normal", "paid"}:
        raise HTTPException(status_code=400, detail="account_type must be trial, normal or paid")
    return normalized


async def _ensure_unique_user(username: str, email: str, db: AsyncSession) -> None:
    existing = await db.execute(select(User).where(or_(User.username == username, User.email == email)))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username or email already exists")


async def _user_info(user: User, db: AsyncSession) -> dict:
    return await serialize_user(user, db)


async def _assign_trial_token(user: User, db: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    trial_token = (
        await db.execute(
            select(TokenInventory)
            .where(
                TokenInventory.is_trial == True,
                TokenInventory.group == "image",
                TokenInventory.is_assigned == False,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if not trial_token:
        raise HTTPException(status_code=400, detail="No trial stock available")

    trial_token.is_assigned = True
    trial_token.assigned_to = user.id
    trial_token.assigned_at = now
    user.account_type = "trial"
    user.api_token_id = trial_token.id
    user.trial_expires_at = now + timedelta(days=TRIAL_DURATION_DAYS)

    existing = (
        await db.execute(select(UserToken).where(UserToken.user_id == user.id, UserToken.group == "image"))
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            UserToken(
                user_id=user.id,
                token_id=trial_token.id,
                group="image",
                balance_usd=TRIAL_BALANCE_USD,
                is_trial=True,
            )
        )
    else:
        existing.token_id = trial_token.id
        existing.balance_usd = TRIAL_BALANCE_USD
        existing.is_trial = True


async def _create_user(username: str, email: str, password: str, account_type: str, db: AsyncSession) -> User:
    _validate_bcrypt_password(password)
    normalized_email = email.strip().lower()
    await _ensure_unique_user(username, normalized_email, db)

    user = User(
        id=str(uuid.uuid4()),
        username=username.strip(),
        email=normalized_email,
        password_hash=hash_password(password),
        account_type="paid" if account_type == "paid" else "normal",
        balance_usd=0.0,
    )
    db.add(user)
    await db.flush()

    if account_type == "trial":
        await _assign_trial_token(user, db)

    await db.flush()
    return user


@router.post("/register")
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    account_type = _normalize_account_type(req.account_type)
    user = await _create_user(req.username, req.email, req.password, account_type, db)
    await db.commit()
    await db.refresh(user)
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "user": await _user_info(user, db),
    }


@router.post("/register/send-code")
async def register_send_code(req: RegisterSendCodeRequest, db: AsyncSession = Depends(get_db)):
    account_type = _normalize_account_type(req.account_type)
    _validate_bcrypt_password(req.password)
    email = req.email.strip().lower()
    await _ensure_unique_user(req.username.strip(), email, db)

    redis = get_redis()
    rate_key = f"reg:rate:{email}"
    lockout_key = f"reg:lockout:{email}"
    if await redis.exists(rate_key):
        raise HTTPException(status_code=429, detail="Please wait 60 seconds before requesting another code")
    if await redis.exists(lockout_key):
        raise HTTPException(status_code=429, detail="Too many verification attempts, try again later")

    code = "".join(secrets.choice("0123456789") for _ in range(6))
    await redis.setex(rate_key, 60, "1")
    await redis.setex(
        f"reg:code:{email}",
        300,
        json.dumps(
            {
                "code": code,
                "username": req.username.strip(),
                "email": email,
                "password": req.password,
                "account_type": account_type,
            }
        ),
    )
    await redis.setex(f"reg:attempts:{email}", 300, "0")

    try:
        await send_verification_code(email, code, purpose="register")
    except Exception as exc:
        logger.exception("Failed to send registration code to %s", email)
        raise HTTPException(status_code=500, detail=f"Failed to send email: {exc}")

    return {"message": "Verification code sent"}


@router.post("/register/verify")
async def register_verify(req: RegisterVerifyRequest, db: AsyncSession = Depends(get_db)):
    email = req.email.strip().lower()
    redis = get_redis()
    code_key = f"reg:code:{email}"
    attempts_key = f"reg:attempts:{email}"
    lockout_key = f"reg:lockout:{email}"

    if await redis.exists(lockout_key):
        raise HTTPException(status_code=429, detail="Too many verification attempts, try again later")

    stored = await redis.get(code_key)
    if not stored:
        raise HTTPException(status_code=400, detail="Verification code is invalid or expired")
    payload = json.loads(stored)

    if payload.get("code") != req.code:
        attempts = int(await redis.get(attempts_key) or "0") + 1
        await redis.setex(attempts_key, 300, str(attempts))
        if attempts >= 5:
            await redis.setex(lockout_key, 900, "1")
            await redis.delete(code_key, attempts_key)
            raise HTTPException(status_code=429, detail="Too many verification attempts, try again later")
        raise HTTPException(status_code=400, detail="Verification code is invalid or expired")

    account_type = _normalize_account_type(payload.get("account_type", req.account_type))
    if payload.get("username") != req.username.strip() or payload.get("email") != email:
        raise HTTPException(status_code=400, detail="Verification payload mismatch")
    if payload.get("password") != req.password:
        raise HTTPException(status_code=400, detail="Password mismatch for verification")

    user = await _create_user(req.username, email, req.password, account_type, db)
    await redis.delete(code_key, attempts_key, f"reg:rate:{email}", lockout_key)

    await db.commit()
    await db.refresh(user)
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "user": await _user_info(user, db),
    }


@router.post("/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    identity = req.username.strip()
    user = (
        await db.execute(select(User).where(or_(User.username == identity, User.email == identity.lower())))
    ).scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "user": await _user_info(user, db),
    }


@router.post("/admin/login")
async def admin_login(req: AdminLoginRequest):
    if req.username != settings.ADMIN_USERNAME or req.password != settings.ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    return {"access_token": create_admin_token(), "token_type": "bearer"}


@router.post("/forgot-password/send-code")
async def forgot_password_send_code(req: ForgotPasswordSendRequest, db: AsyncSession = Depends(get_db)):
    email = req.email.strip().lower()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    redis = get_redis()
    rate_key = f"pwd:rate:{email}"
    if await redis.exists(rate_key):
        raise HTTPException(status_code=429, detail="Please wait 60 seconds before requesting another code")

    code = "".join(secrets.choice("0123456789") for _ in range(6))
    await redis.setex(rate_key, 60, "1")
    await redis.setex(f"pwd:code:{email}", 300, code)
    await redis.setex(f"pwd:attempts:{email}", 300, "0")

    try:
        await send_verification_code(email, code, purpose="reset")
    except Exception as exc:
        logger.exception("Failed to send password reset code to %s", email)
        raise HTTPException(status_code=500, detail=f"Failed to send email: {exc}")

    return {"message": "Verification code sent"}


@router.post("/forgot-password/reset")
async def forgot_password_reset(req: ForgotPasswordResetRequest, db: AsyncSession = Depends(get_db)):
    email = req.email.strip().lower()
    redis = get_redis()
    code_key = f"pwd:code:{email}"
    attempts_key = f"pwd:attempts:{email}"
    lockout_key = f"pwd:lockout:{email}"

    if await redis.exists(lockout_key):
        raise HTTPException(status_code=429, detail="Too many verification attempts, try again later")

    stored_code = await redis.get(code_key)
    if not stored_code:
        raise HTTPException(status_code=400, detail="Verification code is invalid or expired")
    if stored_code != req.code:
        attempts = int(await redis.get(attempts_key) or "0") + 1
        await redis.setex(attempts_key, 300, str(attempts))
        if attempts >= 5:
            await redis.setex(lockout_key, 900, "1")
            await redis.delete(code_key, attempts_key)
            raise HTTPException(status_code=429, detail="Too many verification attempts, try again later")
        raise HTTPException(status_code=400, detail="Verification code is invalid or expired")

    _validate_bcrypt_password(req.new_password)
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = hash_password(req.new_password)
    await redis.delete(code_key, attempts_key, f"pwd:rate:{email}", lockout_key)
    await db.commit()
    return {"message": "Password updated"}


@router.post("/upgrade-trial")
async def upgrade_trial(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user.account_type == "paid":
        raise HTTPException(status_code=400, detail="Paid accounts do not need a trial upgrade")

    existing = (
        await db.execute(select(UserToken).where(UserToken.user_id == user.id, UserToken.group == "image"))
    ).scalar_one_or_none()
    if existing and user.account_type == "trial":
        return {"user": await _user_info(user, db)}

    await _assign_trial_token(user, db)
    await db.commit()
    await db.refresh(user)
    return {"user": await _user_info(user, db)}


@router.get("/me")
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _user_info(user, db)
