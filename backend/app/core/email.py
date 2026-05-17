import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from aiosmtplib import SMTP

from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_verification_code(to_email: str, code: str, purpose: str = "reset") -> None:
    if purpose == "register":
        subject = "CyImagePro 邮箱验证码"
        title = "邮箱验证码"
        desc = "您正在注册 CyImagePro 账户"
    else:
        subject = "CyImagePro 密码重置验证码"
        title = "密码重置验证码"
        desc = "您正在重置 CyImagePro 账户密码"

    body_html = f"""
    <div style="max-width:480px;margin:0 auto;font-family:sans-serif;
                background:#1e1e2e;color:#e4e4ef;padding:32px;border-radius:12px;">
      <h2 style="color:#00d4aa;margin-top:0;">{title}</h2>
      <p>{desc}，验证码为：</p>
      <div style="font-size:32px;font-weight:700;letter-spacing:8px;
                  color:#00d4aa;text-align:center;margin:24px 0;">
        {code}
      </div>
      <p style="color:#8888a0;font-size:13px;">
        验证码 5 分钟内有效。如非本人操作，请忽略此邮件。
      </p>
    </div>
    """
    body_text = f"您的{title}为：{code}，5分钟内有效。如非本人操作，请忽略此邮件。"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_USER))
    msg["To"] = to_email
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    if settings.SMTP_USE_SSL:
        smtp = SMTP(hostname=settings.SMTP_HOST, port=settings.SMTP_PORT, use_tls=True)
    else:
        smtp = SMTP(hostname=settings.SMTP_HOST, port=settings.SMTP_PORT, start_tls=True)

    await smtp.connect()
    await smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
    await smtp.send_message(msg)
    await smtp.quit()
    logger.info("Verification code sent to %s", to_email)
