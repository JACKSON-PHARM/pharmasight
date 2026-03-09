"""
Stock Validation Service — Centralized batch and expiry validation for stock entry.

Pure validation logic only in validate_stock_entry (no DB). Config loaded once per request.
Used by GRN, Supplier Invoice, Manual Adjust, Excel Import, Stock Take, and Batch Corrections.
"""
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Mode constants: OFF = no enforcement (log only), WARN = reject expired / allow short with warning, STRICT = reject expired & short unless override
STOCK_VALIDATION_MODE_OFF = "OFF"
STOCK_VALIDATION_MODE_WARN = "WARN"
STOCK_VALIDATION_MODE_STRICT = "STRICT"
STOCK_VALIDATION_SETTING_KEY = "stock_validation_mode"
STOCK_VALIDATION_MIN_EXPIRY_DAYS_KEY = "stock_validation_min_expiry_days"
DEFAULT_MIN_EXPIRY_DAYS = 90

# Company-level switches to require/skip tracking fields (independent).
# Defaults are True to preserve existing behavior (batch+expiry required for tracked items).
REQUIRE_BATCH_TRACKING_KEY = "require_batch_tracking"
REQUIRE_EXPIRY_TRACKING_KEY = "require_expiry_tracking"


def _parse_bool_setting(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    v = str(value).strip().lower()
    if v in ("1", "true", "t", "yes", "y", "on"):
        return True
    if v in ("0", "false", "f", "no", "n", "off"):
        return False
    return default


class StockValidationResult(BaseModel):
    """Result of stock entry validation."""

    valid: bool = Field(..., description="Whether the entry passes validation")
    expired: bool = Field(False, description="Whether the product is expired")
    short_expiry: bool = Field(False, description="Whether expiry is within min_expiry_days threshold")
    days_remaining: Optional[int] = Field(None, description="Days until expiry (negative if expired)")
    message: Optional[str] = Field(None, description="Human-readable message for UI/logging")


class StockValidationError(Exception):
    """Raised when expired products are submitted (hard reject)."""

    def __init__(self, message: str, result: Optional[StockValidationResult] = None):
        super().__init__(message)
        self.result = result


@dataclass(frozen=True)
class StockValidationConfig:
    """Config for stock validation (load once per request)."""

    mode: str  # OFF | WARN | STRICT
    min_expiry_days: int
    require_batch_tracking: bool
    require_expiry_tracking: bool


def get_stock_validation_config(db: "Session", company_id) -> StockValidationConfig:
    """
    Load stock validation config for a company (one query). Use once per request.
    No DB lookup per line item.
    """
    from app.models.settings import CompanySetting

    mode = STOCK_VALIDATION_MODE_STRICT
    min_expiry_days = DEFAULT_MIN_EXPIRY_DAYS
    require_batch_tracking = True
    require_expiry_tracking = True

    rows = (
        db.query(CompanySetting.setting_key, CompanySetting.setting_value)
        .filter(
            CompanySetting.company_id == company_id,
            CompanySetting.setting_key.in_(
                [
                    STOCK_VALIDATION_SETTING_KEY,
                    STOCK_VALIDATION_MIN_EXPIRY_DAYS_KEY,
                    REQUIRE_BATCH_TRACKING_KEY,
                    REQUIRE_EXPIRY_TRACKING_KEY,
                ]
            ),
        )
        .all()
    )
    for key, value in rows:
        if not value:
            continue
        if key == STOCK_VALIDATION_SETTING_KEY:
            v = str(value).strip().upper()
            if v in (STOCK_VALIDATION_MODE_OFF, STOCK_VALIDATION_MODE_WARN, STOCK_VALIDATION_MODE_STRICT):
                mode = v
        elif key == STOCK_VALIDATION_MIN_EXPIRY_DAYS_KEY:
            try:
                min_expiry_days = max(0, int(value))
            except (ValueError, TypeError):
                pass
        elif key == REQUIRE_BATCH_TRACKING_KEY:
            require_batch_tracking = _parse_bool_setting(value, True)
        elif key == REQUIRE_EXPIRY_TRACKING_KEY:
            require_expiry_tracking = _parse_bool_setting(value, True)

    return StockValidationConfig(
        mode=mode,
        min_expiry_days=min_expiry_days,
        require_batch_tracking=require_batch_tracking,
        require_expiry_tracking=require_expiry_tracking,
    )


def validate_stock_entry_with_config(
    config: StockValidationConfig,
    batch_number: Optional[str],
    expiry_date: Optional[date],
    track_expiry: bool,
    override: bool,
    require_batch: Optional[bool] = None,
    require_expiry: Optional[bool] = None,
    reference_date: Optional[date] = None,
) -> StockValidationResult:
    """
    Run validate_stock_entry with config. OFF = log only and return valid.
    WARN = treat short_expiry as override=True (allow, but result.short_expiry set).
    STRICT = use request override.
    """
    if config.mode == STOCK_VALIDATION_MODE_OFF:
        if track_expiry and (batch_number or expiry_date):
            # Optional: log for audit
            logger.info(
                "stock_validation OFF: batch=%s expiry=%s (not enforced)",
                batch_number,
                expiry_date,
            )
        return validate_stock_entry(
            batch_number=batch_number,
            expiry_date=expiry_date,
            track_expiry=track_expiry,
            require_batch=require_batch,
            require_expiry=require_expiry,
            min_expiry_days=config.min_expiry_days,
            override=True,  # OFF: do not reject
            reference_date=reference_date,
        )

    use_override = override
    if config.mode == STOCK_VALIDATION_MODE_WARN:
        use_override = True  # Allow short_expiry; caller can check result.short_expiry for warning
    return validate_stock_entry(
        batch_number=batch_number,
        expiry_date=expiry_date,
        track_expiry=track_expiry,
        require_batch=require_batch,
        require_expiry=require_expiry,
        min_expiry_days=config.min_expiry_days,
        override=use_override,
        reference_date=reference_date,
    )


def validate_stock_entry(
    *,
    batch_number: Optional[str],
    expiry_date: Optional[date],
    track_expiry: bool,
    require_batch: Optional[bool] = None,
    require_expiry: Optional[bool] = None,
    min_expiry_days: int,
    override: bool,
    reference_date: Optional[date] = None,
) -> StockValidationResult:
    """
    Validate a stock entry's batch and expiry (pure function, no DB access).

    Rules:
    - If track_expiry is False → always valid.
    - If track_expiry is True:
      - If require_batch is True → batch_number required
      - If require_expiry is True → expiry_date required
      - If require_expiry is True:
        - If expiry_date < today → raise StockValidationError (hard reject).
        - If expiry_date <= today + min_expiry_days:
          - mark short_expiry=True
          - if override=False → return invalid (do NOT raise)
        - Else → valid.

    Args:
        batch_number: Batch/lot number (required when require_batch=True)
        expiry_date: Expiry date (required when require_expiry=True)
        track_expiry: Whether this entry should consider tracking validation at all.
        require_batch: Whether batch_number is required (defaults to track_expiry behavior).
        require_expiry: Whether expiry_date is required and validated (defaults to track_expiry behavior).
        min_expiry_days: Minimum days until expiry (short-expiry threshold)
        override: Whether short-expiry override is enabled
        reference_date: Date to use as "today" (for testability; default: date.today())

    Returns:
        StockValidationResult with validation status.

    Raises:
        StockValidationError: When expired products are submitted (expiry_date < today).
    """
    today = reference_date if reference_date is not None else date.today()

    if not track_expiry:
        return StockValidationResult(
            valid=True,
            expired=False,
            short_expiry=False,
            days_remaining=None,
            message=None,
        )

    # Backwards compatibility: if called with track_expiry only, require both.
    req_batch = track_expiry if require_batch is None else bool(require_batch)
    req_exp = track_expiry if require_expiry is None else bool(require_expiry)

    # Required fields (independent)
    if req_batch and not (batch_number and str(batch_number).strip()):
        return StockValidationResult(
            valid=False,
            expired=False,
            short_expiry=False,
            days_remaining=None,
            message="Batch number is required for tracked items.",
        )

    if req_exp and not expiry_date:
        return StockValidationResult(
            valid=False,
            expired=False,
            short_expiry=False,
            days_remaining=None,
            message="Expiry date is required for tracked items.",
        )

    if not req_exp:
        return StockValidationResult(
            valid=True,
            expired=False,
            short_expiry=False,
            days_remaining=None,
            message=None,
        )

    # Hard reject: expired
    days_remaining = (expiry_date - today).days
    if days_remaining < 0:
        result = StockValidationResult(
            valid=False,
            expired=True,
            short_expiry=False,
            days_remaining=days_remaining,
            message=f"Expired product cannot be accepted. Expiry date {expiry_date} is in the past.",
        )
        raise StockValidationError(result.message, result=result)

    # Short expiry: within threshold
    threshold_date = today + timedelta(days=min_expiry_days)
    if expiry_date <= threshold_date:
        short_expiry = True
        if not override:
            return StockValidationResult(
                valid=False,
                expired=False,
                short_expiry=True,
                days_remaining=days_remaining,
                message=f"Product expires in {days_remaining} days (minimum {min_expiry_days} required). Override required to accept.",
            )

    # Valid (either not short-expiry, or override=True)
    is_short_expiry = expiry_date <= threshold_date
    return StockValidationResult(
        valid=True,
        expired=False,
        short_expiry=is_short_expiry,
        days_remaining=days_remaining,
        message=None,
    )
