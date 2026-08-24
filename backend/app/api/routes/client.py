import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.redis import get_redis
from app.models.device import ClientDevice
from app.models.user import User

router = APIRouter()

logger = logging.getLogger(__name__)

ONLINE_DEVICE_TTL = 180  # 3 minutes (allows for 60s heartbeat interval + buffer)


@router.post("/heartbeat")
async def client_heartbeat(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Receive heartbeat from client application.

    两层存储：
    - Redis TTL key（180s）：online 状态判定（key 存在即在线）
    - client_devices 表（upsert）：设备历史永久保留，离线不删除

    时间一律服务器时钟（last_seen = 处理时刻），绝不信任客户端时间戳；
    身份以 JWT 解析出的 user 为准（user_id 不可由客户端伪造）；
    IP 由服务端从请求来源记录。
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    device_id = str(body.get("device_id", ""))[:128]
    device_name = str(body.get("device_name", ""))[:128]
    app_version = str(body.get("app_version", ""))[:64]
    platform = str(body.get("platform", ""))[:64]
    server_url = str(body.get("server_url", ""))[:256]

    if not device_id:
        raise HTTPException(status_code=400, detail="device_id is required")

    # Client IP from request source (nginx 反代取 X-Forwarded-For 首跳)
    client_ip = request.headers.get("X-Forwarded-For", "")
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else ""
    user_agent = (request.headers.get("User-Agent") or "")[:255]

    now = datetime.now(timezone.utc)

    # 设备历史持久化（幂等 upsert：首次心跳创建，之后仅推进 last_seen；失败不阻断心跳）
    try:
        stmt = pg_insert(ClientDevice).values(
            user_id=user.id,
            device_id=device_id,
            device_name=device_name or None,
            platform=platform or None,
            client_version=app_version or None,
            first_seen_at=now,
            last_seen_at=now,
            last_ip=client_ip or None,
            last_user_agent=user_agent or None,
            heartbeat_count=1,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_device_user_device",
            set_={
                "device_name": stmt.excluded.device_name,
                "platform": stmt.excluded.platform,
                "client_version": stmt.excluded.client_version,
                "last_seen_at": stmt.excluded.last_seen_at,
                "last_ip": stmt.excluded.last_ip,
                "last_user_agent": stmt.excluded.last_user_agent,
                "heartbeat_count": ClientDevice.heartbeat_count + 1,
            },
        )
        await db.execute(stmt)
    except Exception:
        logger.exception("device history upsert failed (non-fatal, user=%s)", user.id)

    redis = get_redis()
    if redis:
        key = f"online_device:{user.id}:{device_id}"
        data = {
            "user_id": user.id,
            "device_id": device_id,
            "device_name": device_name,
            "app_version": app_version,
            "platform": platform,
            "last_seen": now.isoformat(),
            "ip": client_ip,
            "server_url": server_url,
        }
        try:
            await redis.set(key, json.dumps(data), ex=ONLINE_DEVICE_TTL)
        except Exception:
            logger.exception("heartbeat redis set failed (user=%s)", user.id)

    return {"status": "ok", "ttl": ONLINE_DEVICE_TTL}
