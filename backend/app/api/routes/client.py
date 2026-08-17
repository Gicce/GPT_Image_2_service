from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import json
import traceback

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.redis import get_redis
from app.models.user import User

router = APIRouter()

ONLINE_DEVICE_TTL = 180  # 3 minutes (allows for 60s heartbeat interval + buffer)


@router.post("/heartbeat")
async def client_heartbeat(
    request: Request,
    user: User = Depends(get_current_user),
):
    """Receive heartbeat from client application.
    Stores device info in Redis with TTL for online status tracking.
    Very lightweight - no database writes, only Redis SET with TTL."""

    print("[heartbeat] ===== RECEIVED =====")
    print(f"[heartbeat] user_id: {user.id}")
    print(f"[heartbeat] email: {user.email}")

    try:
        body = await request.json()
    except json.JSONDecodeError:
        print("[heartbeat] ERROR: Invalid JSON body")
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    device_id = body.get("device_id", "")
    device_name = body.get("device_name", "")
    app_version = body.get("app_version", "")
    platform = body.get("platform", "")
    server_url = body.get("server_url", "")

    print(f"[heartbeat] device_id: {device_id}")
    print(f"[heartbeat] device_name: {device_name}")
    print(f"[heartbeat] app_version: {app_version}")
    print(f"[heartbeat] platform: {platform}")

    if not device_id:
        print("[heartbeat] ERROR: device_id is required")
        raise HTTPException(status_code=400, detail="device_id is required")

    # Try to get client IP (optional)
    client_ip = request.headers.get("X-Forwarded-For", "")
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else ""

    # Store in Redis with TTL
    redis = get_redis()
    print(f"[heartbeat] redis client: {redis is not None}")

    if redis:
        key = f"online_device:{user.id}:{device_id}"
        data = {
            "user_id": user.id,
            "device_id": device_id,
            "device_name": device_name,
            "app_version": app_version,
            "platform": platform,
            "last_seen": datetime.utcnow().isoformat(),
            "ip": client_ip,
            "server_url": server_url,
        }
        try:
            await redis.set(key, json.dumps(data), ex=ONLINE_DEVICE_TTL)
            print(f"[heartbeat] redis key: {key}")
            print(f"[heartbeat] ttl: {ONLINE_DEVICE_TTL}")
            print(f"[heartbeat] value: {json.dumps(data)[:200]}")
        except Exception as e:
            print(f"[heartbeat] ERROR: Redis set failed: {e}")
            traceback.print_exc()
    else:
        print("[heartbeat] WARNING: Redis unavailable")

    print("[heartbeat] ===== SUCCESS =====")
    return {"status": "ok", "ttl": ONLINE_DEVICE_TTL}