import json
import os

import httpx
from wechatpayv3.async_ import AsyncWeChatPay, WeChatPayType
from wechatpayv3.utils import (
    build_authorization,
    load_private_key,
    load_public_key,
    rsa_verify,
)

from app.core.config import settings

_wxpay: AsyncWeChatPay | None = None


def is_configured() -> bool:
    """微信支付凭证是否完整可用（私钥文件存在）。"""
    return bool(
        settings.WECHAT_MCHID
        and settings.WECHAT_APPID
        and settings.WECHAT_APIV3_KEY
        and settings.WECHAT_CERT_SERIAL_NO
        and settings.WECHAT_PRIVATE_KEY_PATH
        and os.path.exists(settings.WECHAT_PRIVATE_KEY_PATH)
    )


def get_wxpay() -> AsyncWeChatPay:
    global _wxpay
    if _wxpay is None:
        with open(settings.WECHAT_PRIVATE_KEY_PATH) as f:
            private_key = f.read()
        public_key = None
        if settings.WECHAT_PUBLIC_KEY_PATH and os.path.exists(settings.WECHAT_PUBLIC_KEY_PATH):
            with open(settings.WECHAT_PUBLIC_KEY_PATH) as f:
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


async def wechatpay_request(
    path: str,
    method: str = "GET",
    data: dict | None = None,
) -> tuple[int, str]:
    """Send a WeChat Pay v3 request with an exact request-body signature."""
    method = method.upper()
    body = (
        json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        if data is not None
        else ""
    )
    private_key = load_private_key(open(settings.WECHAT_PRIVATE_KEY_PATH).read())
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
            public_key = load_public_key(open(settings.WECHAT_PUBLIC_KEY_PATH).read())
            ok = rsa_verify(
                response.headers.get("Wechatpay-Timestamp", ""),
                response.headers.get("Wechatpay-Nonce", ""),
                content,
                response.headers.get("Wechatpay-Signature", ""),
                public_key,
            )
            if not ok:
                raise Exception("WeChat Pay response signature verification failed")

    return response.status_code, content
