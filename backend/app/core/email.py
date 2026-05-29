import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from aiosmtplib import SMTP

from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_verification_code(to_email: str, code: str, purpose: str = "reset") -> None:
    if not settings.SMTP_HOST or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        raise RuntimeError("SMTP is not configured")

    if purpose == "register":
        subject = "CyImagePro registration code"
        title = "Registration code"
        desc = "Use the verification code below to complete your registration."
    else:
        subject = "CyImagePro password reset code"
        title = "Password reset code"
        desc = "Use the verification code below to reset your password."

    body_html = f"""
    <div style=\"max-width:480px;margin:0 auto;font-family:sans-serif;background:#1e1e2e;color:#e4e4ef;padding:32px;border-radius:12px;\">
      <h2 style=\"color:#00d4aa;margin-top:0;\">{title}</h2>
      <p>{desc}</p>
      <div style=\"font-size:32px;font-weight:700;letter-spacing:8px;color:#00d4aa;text-align:center;margin:24px 0;\">{code}</div>
      <p style=\"color:#8888a0;font-size:13px;\">The code is valid for 5 minutes. If you did not request this action, ignore this email.</p>
    </div>
    """
    body_text = f"{title}: {code}. The code is valid for 5 minutes. If you did not request this action, ignore this email."

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_USER))
    msg["To"] = to_email
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    smtp = SMTP(
        hostname=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        use_tls=settings.SMTP_USE_SSL,
        start_tls=not settings.SMTP_USE_SSL,
    )
    await smtp.connect()
    await smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
    await smtp.send_message(msg)
    await smtp.quit()
    logger.info("Verification code sent to %s", to_email)
