import json
import os

import httpx
from wechatpayv3.async_ import AsyncWeChatPay, WeChatPayType
from wechatpayv3.utils import build_authorization, load_private_key, load_public_key, rsa_verify

from app.core.config import settings

_wxpay: AsyncWeChatPay | None = None


def get_wxpay() -> AsyncWeChatPay:
    global _wxpay
    if _wxpay is None:
        with open(settings.WECHAT_PRIVATE_KEY_PATH, encoding="utf-8") as f:
            private_key = f.read()
        public_key = None
        if settings.WECHAT_PUBLIC_KEY_PATH and os.path.exists(settings.WECHAT_PUBLIC_KEY_PATH):
            with open(settings.WECHAT_PUBLIC_KEY_PATH, encoding="utf-8") as f:
                public_key = f.read()
        _wxpay = AsyncWeChatPay(
            wechatpay_type=WeChatPayType.NATIVE,
            mchid=settings.WECHAT_MCHID,
            private_key=private_key,
            cert_serial_no=settings.WECHAT_CERT_SERIAL_NO,
            appid=settings.WECHAT_APPID,
            apiv3_key=settings.WECHAT_APIV3_KEY,
            notify_url=settings.WECHAT_NOTIFY_URL,
            public_key=public_key,
            public_key_id=settings.WECHAT_PUBLIC_KEY_ID or None,
        )
    return _wxpay


async def wechatpay_request(path: str, method: str = "GET", data: dict | None = None) -> tuple[int, str]:
    method = method.upper()
    body = json.dumps(data, separators=(",", ":"), ensure_ascii=False) if data is not None else ""
    with open(settings.WECHAT_PRIVATE_KEY_PATH, encoding="utf-8") as f:
        private_key = load_private_key(f.read())

    headers = {
        "Authorization": build_authorization(
            path=path,
            method=method,
            mchid=settings.WECHAT_MCHID,
            serial_no=settings.WECHAT_CERT_SERIAL_NO,
            private_key=private_key,
            data=body,
        ),
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "CyImagePro/wechatpay",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.request(
            method,
            "https://api.mch.weixin.qq.com" + path,
            content=body.encode("utf-8") if body else None,
            headers=headers,
        )

    content = response.text
    if 200 <= response.status_code < 300 and content and settings.WECHAT_PUBLIC_KEY_PATH:
        serial = response.headers.get("Wechatpay-Serial", "")
        if serial == settings.WECHAT_PUBLIC_KEY_ID and os.path.exists(settings.WECHAT_PUBLIC_KEY_PATH):
            with open(settings.WECHAT_PUBLIC_KEY_PATH, encoding="utf-8") as f:
                public_key = load_public_key(f.read())
            ok = rsa_verify(
                response.headers.get("Wechatpay-Timestamp", ""),
                response.headers.get("Wechatpay-Nonce", ""),
                content,
                response.headers.get("Wechatpay-Signature", ""),
                public_key,
            )
            if not ok:
                raise RuntimeError("WeChat Pay response signature verification failed")

    return response.status_code, content
