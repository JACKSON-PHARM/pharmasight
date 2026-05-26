"""Resolve a human-readable user label (full name or username)."""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.user import User


def resolve_user_display_name(db: Session, user: Any) -> str:
    """
    Return full_name or username for documents/UI.
    Auth cache hits yield stub users with only id — look up the row when needed.
    """
    name = getattr(user, "full_name", None) or getattr(user, "username", None)
    if name and str(name).strip():
        return str(name).strip()

    uid: Optional[UUID] = getattr(user, "id", None)
    if uid is None:
        return "—"

    row = db.query(User.full_name, User.username).filter(User.id == uid).first()
    if row:
        label = row.full_name or row.username
        if label and str(label).strip():
            return str(label).strip()
    return str(uid)
