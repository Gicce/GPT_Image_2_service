import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from aiosmtplib import SMTP, SMTPException

from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_verification_code(to_email: str, code: str, purpose: str = "reset") -> None:
    # 开发模式：不真实发邮件，直接打印验证码
    if settings.APP_ENV == "development" and not settings.SMTP_HOST:
        logger.info("[DEV MODE] 验证码发送给 %s: %s (用途: %s)", to_email, code, purpose)
        logger.info("[DEV MODE] ===== 验证码: %s =====", code)
        return

    # 检查 SMTP 配置
    if not settings.SMTP_HOST or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.error("SMTP 配置缺失: SMTP_HOST=%s, SMTP_USER=%s, SMTP_PASSWORD=%s",
                     settings.SMTP_HOST or "(空)", settings.SMTP_USER or "(空)",
                     "(未设置)" if not settings.SMTP_PASSWORD else "(已设置)")
        raise ValueError("SMTP 配置不完整，请检查 .env 文件中的 SMTP_HOST、SMTP_USER、SMTP_PASSWORD")

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

    try:
        logger.info("正在连接 SMTP 服务器: %s:%d (SSL=%s)",
                    settings.SMTP_HOST, settings.SMTP_PORT, settings.SMTP_USE_SSL)

        if settings.SMTP_USE_SSL:
            smtp = SMTP(hostname=settings.SMTP_HOST, port=settings.SMTP_PORT, use_tls=True)
        else:
            smtp = SMTP(hostname=settings.SMTP_HOST, port=settings.SMTP_PORT, start_tls=True)

        await smtp.connect()
        logger.info("SMTP 连接成功，正在登录...")

        await smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        logger.info("SMTP 登录成功，正在发送邮件...")

        await smtp.send_message(msg)
        logger.info("邮件发送成功: %s", to_email)

        await smtp.quit()
        logger.info("验证码已发送到 %s", to_email)

    except SMTPException as e:
        logger.error("SMTP 错误: %s - %s", type(e).__name__, str(e))
        raise
    except Exception as e:
        logger.error("邮件发送异常: %s - %s", type(e).__name__, str(e))
        raise
