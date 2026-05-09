from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, EmailStr
import uuid

from app.core.database import get_db
from app.core.security import hash_password, verify_password, create_access_token, create_admin_token
from app.core.config import settings
from app.models.user import User
from app.models.token import TokenInventory

router = APIRouter()


class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
    account_type: str = "trial"  # "trial" | "paid"


class LoginRequest(BaseModel):
    username: str
    password: str


class AdminLoginRequest(BaseModel):
    username: str
    password: str


@router.post("/register")
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Check username/email uniqueness
    existing = await db.execute(
        select(User).where((User.username == req.username) | (User.email == req.email))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名或邮箱已存在")

    if req.account_type not in ("trial", "paid"):
        raise HTTPException(status_code=400, detail="无效的账户类型")

    now = datetime.now(timezone.utc)
    trial_token = None

    if req.account_type == "trial":
        t = await db.execute(
            select(TokenInventory).where(
                TokenInventory.is_trial == True,
                TokenInventory.is_assigned == False,
            ).limit(1)
        )
        trial_token = t.scalar_one_or_none()
        if not trial_token:
            raise HTTPException(status_code=400, detail="试用名额已满，请直接购买套餐")

    user = User(
        id=str(uuid.uuid4()),
        username=req.username,
        email=req.email,
        password_hash=hash_password(req.password),
        account_type=req.account_type,
        balance_usd=1.0 if req.account_type == "trial" else 0.0,
        api_token_id=trial_token.id if trial_token else None,
        trial_expires_at=now + timedelta(days=2) if req.account_type == "trial" else None,
    )
    db.add(user)

    if trial_token:
        trial_token.is_assigned = True
        trial_token.assigned_to = user.id
        trial_token.assigned_at = now

    await db.flush()
    token = create_access_token(user.id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _user_info(user, trial_token),
    }


@router.post("/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    token_record = None
    if user.api_token_id:
        r = await db.execute(select(TokenInventory).where(TokenInventory.id == user.api_token_id))
        token_record = r.scalar_one_or_none()

    access_token = create_access_token(user.id)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": _user_info(user, token_record),
    }


@router.post("/admin/login")
async def admin_login(req: AdminLoginRequest):
    if req.username != settings.ADMIN_USERNAME or req.password != settings.ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="管理员账号或密码错误")
    return {"access_token": create_admin_token(), "token_type": "bearer"}


def _user_info(user: User, token_record=None):
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
        "balance_usd": float(user.balance_usd),
        "api_token": token_record.token_value if token_record else None,
        "trial_expires_at": user.trial_expires_at.isoformat() if user.trial_expires_at else None,
        "trial_expired": trial_expired,
    }
