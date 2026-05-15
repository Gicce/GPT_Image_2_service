from wechatpayv3.async_ import AsyncWeChatPay, WeChatPayType
from app.core.config import settings

_wxpay: AsyncWeChatPay | None = None


def get_wxpay() -> AsyncWeChatPay:
    global _wxpay
    if _wxpay is None:
        with open(settings.WECHAT_PRIVATE_KEY_PATH) as f:
            private_key = f.read()
        _wxpay = AsyncWeChatPay(
            wechatpay_type=WeChatPayType.NATIVE,
            mchid=settings.WECHAT_MCHID,
            private_key=private_key,
            cert_serial_no=settings.WECHAT_CERT_SERIAL_NO,
            appid=settings.WECHAT_APPID,
            apiv3_key=settings.WECHAT_APIV3_KEY,
            notify_url=settings.WECHAT_NOTIFY_URL,
        )
    return _wxpay
