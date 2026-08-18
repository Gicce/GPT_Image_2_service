import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.security import get_current_user
from app.core.redis import get_redis
from app.models.user import User

router = APIRouter()

logger = logging.getLogger(__name__)

ONLINE_DEVICE_TTL = 180  # 3 minutes (allows for 60s heartbeat interval + buffer)


@router.post("/heartbeat")
async def client_heartbeat(
    request: Request,
    user: User = Depends(get_current_user),
):
    """Receive heartbeat from client application.

    Stores device info in Redis with TTL for online status tracking.
    Very lightweight - no database writes, only Redis SET with TTL.
    身份以 JWT 解析出的 user 为准（user_id 不可由客户端伪造）；
    IP 由服务端从请求来源记录，不信任客户端上报。
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

    redis = get_redis()
    if redis:
        key = f"online_device:{user.id}:{device_id}"
        data = {
            "user_id": user.id,
            "device_id": device_id,
            "device_name": device_name,
            "app_version": app_version,
            "platform": platform,
            "last_seen": datetime.now(timezone.utc).isoformat(),
            "ip": client_ip,
            "server_url": server_url,
        }
        try:
            await redis.set(key, json.dumps(data), ex=ONLINE_DEVICE_TTL)
        except Exception:
            logger.exception("heartbeat redis set failed (user=%s)", user.id)

    return {"status": "ok", "ttl": ONLINE_DEVICE_TTL}
