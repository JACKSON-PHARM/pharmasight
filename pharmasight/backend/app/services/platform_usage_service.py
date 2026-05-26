"""Privacy-safe platform usage telemetry for SaaS operator dashboards."""
from __future__ import annotations

import html
import logging
import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.services.email_service import EmailService, _envelope_sender
from app.utils.auth_internal import CLAIM_COMPANY_ID, CLAIM_SUB, CLAIM_TYPE, TYPE_ACCESS, decode_internal_token

logger = logging.getLogger(__name__)


SIGNUP_EVENT = "client_signup"
LOGIN_EVENT = "user_login"
USER_CREATED_EVENT = "company_user_created"


def _alert_recipients() -> list[str]:
    raw = (os.getenv("PLATFORM_ALERT_EMAILS") or os.getenv("PLATFORM_NOTIFICATION_EMAILS") or "").strip()
    if not raw:
        raw = (settings.SMTP_USER or "").strip()
    return [x.strip() for x in raw.replace(";", ",").split(",") if x.strip()]


def _safe(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _client_ip(request: Any) -> Optional[str]:
    if not request:
        return None
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded[:80]
    client = getattr(request, "client", None)
    return (getattr(client, "host", None) or None)


def _user_agent(request: Any) -> Optional[str]:
    if not request:
        return None
    value = request.headers.get("user-agent")
    return value[:500] if value else None


def notify_platform_event(
    *,
    event_type: str,
    company_name: Optional[str] = None,
    actor_name: Optional[str] = None,
    actor_email: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> bool:
    """Send a concise operator email. Fails closed to logs; app flows must continue."""
    recipients = _alert_recipients()
    if not recipients or not EmailService.is_configured():
        return False

    labels = {
        SIGNUP_EVENT: "New client signup",
        LOGIN_EVENT: "Client login",
        USER_CREATED_EVENT: "New company user",
    }
    title = labels.get(event_type, event_type.replace("_", " ").title())
    meta = metadata or {}
    rows = [
        ("Company", company_name or meta.get("company_name") or "-"),
        ("User", actor_name or "-"),
        ("Email", actor_email or "-"),
        ("Time", datetime.now(timezone.utc).isoformat()),
    ]
    if meta.get("username"):
        rows.append(("Username", meta.get("username")))
    if meta.get("source"):
        rows.append(("Source", meta.get("source")))

    row_html = "".join(f"<tr><td><strong>{_safe(k)}</strong></td><td>{_safe(v)}</td></tr>" for k, v in rows)
    html_body = f"""
    <!DOCTYPE html>
    <html><body style="font-family:sans-serif;line-height:1.5;color:#333;">
      <h2>{_safe(title)}</h2>
      <table cellpadding="6" cellspacing="0" style="border-collapse:collapse;">{row_html}</table>
      <p style="color:#666;font-size:13px;">This is platform telemetry only. It does not include client inventory, sales, patient, or customer records.</p>
    </body></html>
    """
    plain = "\n".join([title, *[f"{k}: {v}" for k, v in rows]])

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{settings.APP_NAME}: {title}"
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(_envelope_sender(), recipients, msg.as_string())
        return True
    except Exception as exc:
        logger.warning("Platform notification email failed: %s", exc)
        return False


def record_platform_event(
    db: Session,
    *,
    event_type: str,
    company_id: Optional[Any] = None,
    user_id: Optional[Any] = None,
    actor_email: Optional[str] = None,
    actor_name: Optional[str] = None,
    company_name: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    request: Any = None,
    send_email: bool = False,
) -> None:
    """Insert one platform event. Caller owns transaction; failures are non-fatal."""
    try:
        db.execute(
            text(
                """
                INSERT INTO platform_usage_events (
                    company_id, user_id, event_type, actor_email, actor_name, company_name,
                    metadata, request_ip, user_agent
                )
                VALUES (
                    CAST(:company_id AS UUID), CAST(:user_id AS UUID), :event_type, :actor_email,
                    :actor_name, :company_name, CAST(:metadata AS JSONB), :request_ip, :user_agent
                )
                """
            ),
            {
                "company_id": str(company_id) if company_id else None,
                "user_id": str(user_id) if user_id else None,
                "event_type": event_type,
                "actor_email": (actor_email or None),
                "actor_name": (actor_name or None),
                "company_name": (company_name or None),
                "metadata": __import__("json").dumps(metadata or {}),
                "request_ip": _client_ip(request),
                "user_agent": _user_agent(request),
            },
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("Platform usage event skipped: %s", exc)
        return
    if send_email:
        notify_platform_event(
            event_type=event_type,
            company_name=company_name,
            actor_name=actor_name,
            actor_email=actor_email,
            metadata=metadata,
        )


def endpoint_group_for_path(path: str) -> str:
    parts = [p for p in (path or "").split("/") if p]
    if len(parts) >= 3 and parts[0] == "api":
        return f"/api/{parts[1]}/{parts[2]}"
    if len(parts) >= 2 and parts[0] == "api":
        return f"/api/{parts[1]}"
    return "/" + "/".join(parts[:2])


def record_request_counter(
    *,
    company_id: Any,
    path: str,
    method: str,
    status_code: int,
    duration_ms: int,
) -> None:
    """Upsert an aggregated hourly API request counter."""
    if not company_id:
        return
    try:
        with SessionLocal() as db:
            db.execute(
                text(
                    """
                    INSERT INTO platform_usage_counters (
                        hour_start, company_id, endpoint_group, method, status_family,
                        request_count, total_duration_ms, last_seen_at
                    )
                    VALUES (
                        date_trunc('hour', NOW()), CAST(:company_id AS UUID), :endpoint_group,
                        :method, :status_family, 1, :duration_ms, NOW()
                    )
                    ON CONFLICT (hour_start, company_id, endpoint_group, method, status_family)
                    DO UPDATE SET
                        request_count = platform_usage_counters.request_count + 1,
                        total_duration_ms = platform_usage_counters.total_duration_ms + EXCLUDED.total_duration_ms,
                        last_seen_at = NOW()
                    """
                ),
                {
                    "company_id": str(company_id),
                    "endpoint_group": endpoint_group_for_path(path)[:120],
                    "method": (method or "GET")[:12],
                    "status_family": f"{int(status_code / 100)}xx" if status_code else "0xx",
                    "duration_ms": max(0, int(duration_ms or 0)),
                },
            )
            db.commit()
    except Exception as exc:
        logger.debug("Platform request counter skipped: %s", exc)


def company_id_from_authorization(authorization: str) -> Optional[str]:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_internal_token(token, verify_exp=False)
    if not payload or payload.get(CLAIM_TYPE) != TYPE_ACCESS:
        return None
    company_id = payload.get(CLAIM_COMPANY_ID)
    return str(company_id) if company_id else None


__all__ = [
    "SIGNUP_EVENT",
    "LOGIN_EVENT",
    "USER_CREATED_EVENT",
    "company_id_from_authorization",
    "endpoint_group_for_path",
    "record_platform_event",
    "record_request_counter",
]
