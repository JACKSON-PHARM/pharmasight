from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from uuid import UUID


@dataclass(frozen=True)
class PostingLineSpec:
    account_id: UUID
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    description: Optional[str] = None


@dataclass(frozen=True)
class PostingResult:
    created: bool
    journal_entry_id: Optional[UUID]
    message: str
    skipped_duplicate: bool = False
