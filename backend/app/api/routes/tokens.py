from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services import runtime_token as rt

router = APIRouter()


@router.get("/trial-stock")
async def get_trial_stock(db: AsyncSession = Depends(get_db)):
    """公开端点：试用通道可用性（共享池模式下 = 存在有效的默认试用 Token）。

    保留 remaining/available 字段形状以兼容旧客户端：
    available=true 时 remaining=1，否则 remaining=0。
    """
    trial_token = await rt.resolve_default_token(db, is_trial=True)
    available = trial_token is not None
    return {"remaining": 1 if available else 0, "available": available}
