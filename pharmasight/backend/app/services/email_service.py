"""
Email service for sending tenant invite emails via SMTP.
"""
import html
import logging
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


def _escape(s: str) -> str:
    return html.escape(s, quote=True)


def _envelope_sender() -> str:
    """Return address to use as SMTP envelope sender. Gmail expects the authenticated user's email."""
    raw = (settings.EMAIL_FROM or "").strip()
    if not raw:
        return (settings.SMTP_USER or "").strip()
    # "Name <user@domain.com>" -> user@domain.com
    m = re.search(r"<([^>]+)>", raw)
    if m:
        return m.group(1).strip().lower()
    if "@" in raw:
        return raw
    return (settings.SMTP_USER or "").strip()


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
        org_login_url: Optional[str] = None,
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

        safe_login = _escape(org_login_url) if org_login_url else ""
        login_block = ""
        if org_login_url:
            login_block = f"""
            <p><strong>After setup, sign in here:</strong> <a href="{safe_login}">{safe_login}</a></p>
            <p style="font-size:14px;color:#666;">Bookmark this link for day-to-day sign-in. It includes your organization code so users land in the correct workspace.</p>
            """

        brand = settings.APP_NAME
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family:sans-serif;line-height:1.5;color:#333;">
            <h2>You're invited to set up {safe_name} on {brand}</h2>
            <p>Click the link below to complete your account setup:</p>
            <p><a href="{safe_url}" style="background:#14b8a6;color:#0f172a;padding:10px 20px;text-decoration:none;border-radius:8px;display:inline-block;font-weight:600;">Complete setup</a></p>
            <p style="word-break:break-all;font-size:12px;color:#666;">Or copy this link: {safe_url}</p>
            {username_block}
            {login_block}
            <p style="color:#666;font-size:14px;">This link expires in 7 days. If you didn't expect this email, you can ignore it.</p>
        </body>
        </html>
        """

        plain = f"""You're invited to set up {tenant_name} on {settings.APP_NAME}.\n\nComplete your setup: {setup_url}\n"""
        if username:
            plain += f"\nYour username: {username}\nUse this to log in after setting your password.\n"
        if org_login_url:
            plain += f"\nSign-in link (after setup): {org_login_url}\n"
        plain += "\nThis link expires in 7 days.\n"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Complete your {settings.APP_NAME} setup – {tenant_name}"
        msg["From"] = settings.EMAIL_FROM
        msg["To"] = to_email
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(_envelope_sender(), [to_email], msg.as_string())
            logger.info(f"Tenant invite email sent to {to_email}")
            return True
        except Exception as e:
            logger.exception(f"Failed to send tenant invite email to {to_email}: {e}")
            return False

    @staticmethod
    def send_password_reset(
        to_email: str,
        reset_url: str,
        expire_minutes: int = 60,
        *,
        username: Optional[str] = None,
        tenant_subdomain: Optional[str] = None,
        sign_in_url: Optional[str] = None,
    ) -> bool:
        """
        Send password reset email with link. Returns True if sent successfully.
        Optionally includes username and a direct sign-in URL so users know what to enter on the login page.
        """
        if not EmailService.is_configured():
            logger.warning(
                "SMTP not configured; skipping password reset email. "
                "SMTP_HOST=%s SMTP_USER=%s SMTP_PASSWORD=%s (values hidden)",
                "set" if settings.SMTP_HOST else "MISSING",
                "set" if settings.SMTP_USER else "MISSING",
                "set" if settings.SMTP_PASSWORD else "MISSING",
            )
            return False
        safe_url = _escape(reset_url)
        safe_user = _escape(username) if username else ""
        safe_tenant = _escape(tenant_subdomain) if tenant_subdomain else ""
        safe_sign_in = _escape(sign_in_url) if sign_in_url else ""

        username_block = ""
        if username:
            username_block = f"""
            <p><strong>Your username:</strong> <code style="background:#f0f0f0;padding:4px 8px;border-radius:4px;">{safe_user}</code></p>
            <p>On the sign-in page, enter this username (not only your email) and your new password after you reset.</p>
            """
        tenant_block = ""
        if tenant_subdomain and sign_in_url:
            tenant_block = f"""
            <p><strong>Your organization link:</strong> <a href="{safe_sign_in}">{safe_sign_in}</a></p>
            <p style="font-size:14px;color:#666;">Bookmark this if your account belongs to <code>{safe_tenant}</code> so the app opens the correct workspace.</p>
            """

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family:sans-serif;line-height:1.5;color:#333;">
            <h2>Reset your {settings.APP_NAME} password</h2>
            <p>Click the link below to set a new password:</p>
            <p><a href="{safe_url}" style="background:#14b8a6;color:#0f172a;padding:10px 20px;text-decoration:none;border-radius:8px;display:inline-block;font-weight:600;">Reset password</a></p>
            <p style="word-break:break-all;font-size:12px;color:#666;">Or copy: {safe_url}</p>
            {username_block}
            {tenant_block}
            <p style="color:#666;font-size:14px;">This link expires in {expire_minutes} minutes. If you didn't request this, ignore this email.</p>
        </body>
        </html>
        """
        plain = f"Reset your {settings.APP_NAME} password: {reset_url}\n\nThis link expires in {expire_minutes} minutes.\n"
        if username:
            plain += f"\nYour username: {username}\nUse this username when signing in (with your new password).\n"
        if tenant_subdomain and sign_in_url:
            plain += f"\nYour organization sign-in link: {sign_in_url}\n"
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Reset your {settings.APP_NAME} password"
        msg["From"] = settings.EMAIL_FROM
        msg["To"] = to_email
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html_body, "html"))
        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(_envelope_sender(), [to_email], msg.as_string())
            logger.info(f"Password reset email sent to {to_email}")
            return True
        except Exception as e:
            err_msg = f"{type(e).__name__}: {e}"
            logger.exception("Failed to send password reset email to %s: %s", to_email, e)
            # Re-raise so caller can log a short message (e.g. for Render logs)
            raise RuntimeError(err_msg) from e
