"""
Email service for sending tenant invite emails via SMTP.
"""
import html
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


def _escape(s: str) -> str:
    return html.escape(s, quote=True)


class EmailService:
    """Send transactional emails (e.g. tenant invites) via SMTP."""

    @staticmethod
    def is_configured() -> bool:
        return bool(settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD)

    @staticmethod
    def send_tenant_invite(
        to_email: str,
        tenant_name: str,
        setup_url: str,
        username: Optional[str] = None,
    ) -> bool:
        """
        Send tenant setup invite email with link and optional username.

        Returns True if sent successfully, False otherwise.
        """
        if not EmailService.is_configured():
            logger.warning(
                "SMTP not configured (SMTP_HOST, SMTP_USER, SMTP_PASSWORD); "
                "skipping tenant invite email"
            )
            return False

        safe_name = _escape(tenant_name)
        safe_url = _escape(setup_url)
        safe_username = _escape(username) if username else ""

        username_block = ""
        if username:
            username_block = f"""
            <p><strong>Your username:</strong> <code style="background:#f0f0f0;padding:4px 8px;border-radius:4px;">{safe_username}</code></p>
            <p>Use this username to log in after you set your password.</p>
            """

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family:sans-serif;line-height:1.5;color:#333;">
            <h2>You're invited to set up {safe_name} on PharmaSight</h2>
            <p>Click the link below to complete your account setup:</p>
            <p><a href="{setup_url}" style="background:#2563eb;color:white;padding:10px 20px;text-decoration:none;border-radius:6px;display:inline-block;">Complete setup</a></p>
            <p style="word-break:break-all;font-size:12px;color:#666;">Or copy this link: {safe_url}</p>
            {username_block}
            <p style="color:#666;font-size:14px;">This link expires in 7 days. If you didn't expect this email, you can ignore it.</p>
        </body>
        </html>
        """

        plain = f"""You're invited to set up {tenant_name} on PharmaSight.\n\nComplete your setup: {setup_url}\n"""
        if username:
            plain += f"\nYour username: {username}\nUse this to log in after setting your password.\n"
        plain += "\nThis link expires in 7 days.\n"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Complete your PharmaSight setup – {tenant_name}"
        msg["From"] = settings.EMAIL_FROM
        msg["To"] = to_email
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(settings.EMAIL_FROM, [to_email], msg.as_string())
            logger.info(f"Tenant invite email sent to {to_email}")
            return True
        except Exception as e:
            logger.exception(f"Failed to send tenant invite email to {to_email}: {e}")
            return False

    @staticmethod
    def send_password_reset(to_email: str, reset_url: str, expire_minutes: int = 60) -> bool:
        """
        Send password reset email with link. Returns True if sent successfully.
        """
        if not EmailService.is_configured():
            logger.warning("SMTP not configured; skipping password reset email")
            return False
        safe_url = _escape(reset_url)
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family:sans-serif;line-height:1.5;color:#333;">
            <h2>Reset your PharmaSight password</h2>
            <p>Click the link below to set a new password:</p>
            <p><a href="{safe_url}" style="background:#2563eb;color:white;padding:10px 20px;text-decoration:none;border-radius:6px;display:inline-block;">Reset password</a></p>
            <p style="word-break:break-all;font-size:12px;color:#666;">Or copy: {safe_url}</p>
            <p style="color:#666;font-size:14px;">This link expires in {expire_minutes} minutes. If you didn't request this, ignore this email.</p>
        </body>
        </html>
        """
        plain = f"Reset your PharmaSight password: {reset_url}\n\nThis link expires in {expire_minutes} minutes.\n"
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Reset your PharmaSight password"
        msg["From"] = settings.EMAIL_FROM
        msg["To"] = to_email
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html_body, "html"))
        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(settings.EMAIL_FROM, [to_email], msg.as_string())
            logger.info(f"Password reset email sent to {to_email}")
            return True
        except Exception as e:
            logger.exception(f"Failed to send password reset email to {to_email}: {e}")
            return False
