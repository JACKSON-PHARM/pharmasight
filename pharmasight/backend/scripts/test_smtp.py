"""
Test SMTP configuration (password reset / invite emails).

Run from pharmasight/ or pharmasight/backend/ with .env loaded.
  python -m pharmasight.backend.scripts.test_smtp
  python scripts/test_smtp.py [optional_email_to_send_test_to]
"""
from __future__ import annotations

import sys
from pathlib import Path

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from app.config import settings
from app.services.email_service import EmailService


def main() -> int:
    to_email = (sys.argv[1] if len(sys.argv) > 1 else None) or (getattr(settings, "SMTP_USER", None) or "you@example.com")
    print("SMTP test (password reset / invite emails)")
    print("  SMTP_HOST:", "set" if settings.SMTP_HOST else "MISSING")
    print("  SMTP_USER:", "set" if settings.SMTP_USER else "MISSING")
    print("  SMTP_PASSWORD:", "set" if settings.SMTP_PASSWORD else "MISSING")
    print("  EMAIL_FROM:", getattr(settings, "EMAIL_FROM", "") or "(default)")
    print("  Configured:", EmailService.is_configured())
    if not EmailService.is_configured():
        print("\n=> Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD in .env (or Render env) and try again.")
        return 1
    print(f"\nSending test password-reset email to: {to_email}")
    try:
        ok = EmailService.send_password_reset(
            to_email,
            "https://example.com/#password-reset?token=test-token",
            60,
        )
        if ok:
            print("=> Sent OK. Check inbox (and spam).")
            return 0
        print("=> Send returned False. Check server logs above for SMTP errors.")
        return 1
    except Exception as e:
        print(f"=> Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
