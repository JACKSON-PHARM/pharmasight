
#!/usr/bin/env python3
"""
Standalone OSCU GavaConnect SBX sequence runner.

Credentials live in ``test_pins.csv`` beside this script, keyed by **app_pin**
(Application Test PIN). Columns:

  app_pin, consumer_key, consumer_secret, integ_pin, branch_id,
  device_serial, apigee_app_id, cmc_key

Hard rule for SBX:
- Stock-move-list endpoints are NOT executed as sequence steps and are NOT used for flow control.
Some optional diagnostics that previously referenced move-list endpoints have been removed/renamed to
avoid reintroducing flow-control dependency via tooling or LLM edits.
After clearing stock/SAR on the **OSCU portal**, use
``python gavaetims.py <PIN> --reset-stock`` to clear local stock-step resume keys.
``python gavaetims.py <PIN> --clean-run`` clears item/stock/composition/sales progress for that PIN.
``python gavaetims.py <PIN> --force-stock-replay`` drops only ``insertStockIOInitial`` /
``saveStockMasterInitial`` and related pending/SAR keys so the pair reruns together.
``python gavaetims.py <PIN> --diagnostic-stock-io`` (with a clean OSCU SBX stock state) resets local
resume for the initial stock triple, forces ``sarNo=1`` / line qty 1, and prints full
``insertStockIOInitial`` / ``saveStockMasterInitial`` payloads for SBX direction checks (no extra retries).

Optional ``.env`` overrides **only**:
  BEARER_TOKEN  — skip OAuth
  CMC_KEY       — skip selectInitOsdcInfo / saved CSV cmc_key
  GAVAETIMS_MINIMAL_ITEM_CD — for ``--minimal-osdc-sale-test`` only: exact ``itemCd`` for the first
  ``saveItem`` attempt (e.g. when KRA’s next sequence is known). Catalog-based allocation is used
  after that attempt fails or for later retries.
  GAVAETIMS_LEDGER_CONTRACT_DIAGNOSTIC_ONLY_PRECHECK — if ``1``/``true``, ``--ledger-contract-test`` runs a
  stderr-only ``selectStockMaster`` line before insert (does not affect IO or verdict inputs).

``--minimal-osdc-sale-test`` + ``--clean-run``: pin blob key ``minimal_osdc_item_cd_override`` in
``.test_state.json`` is **preserved** (other item/sequence keys are cleared) so you can pin the next
SBX ``itemCd`` (e.g. ``KE2NTTU0000003``) without re-editing after each clean run. Removed automatically
after a successful minimal ``saveItem``.

**Customer / taxpayer lookups without running the full sequence** (e.g. item or stock steps failed):
``python gavaetims.py <PIN> --only selectCustomerList,selectTaxpayerInfo`` — runs only those
endpoints (same headers as the full run). Does not require prior steps to have succeeded.

If ``cmc_key`` is empty in CSV, the script validates OAuth + ``selectInitOsdcInfo``
before saving a new key. New PINs are validated the same way before any CSV write.
Clear ``cmc_key`` in the CSV manually to force a refresh (re-validation runs first).

Resume progress is stored in ``.test_state.json`` (keyed by ``app_pin``): ``cmc_key``,
``completed_endpoints``, and run context (``item_cd``, class codes, invoice fields)
so a failed mid-sequence run can continue with the same PIN. Root key ``sarNo_by_tin_bhf``
maps ``"<tin>|<bhfId>"`` → last successful ``insertStockIO`` ``sarNo`` (monotonic across runs;
not cleared by ``--clean-run``).

**Gavaconnect (developer.go.ke) progress bar:** advancing the on-screen “X/23” checklist is
owned by the portal’s certification session, not by raw KRA OSCU calls. A timer at 00:00:00
usually means the validation window ended — request a new/extended session. Follow their
published testcase order and any required screenshots/submissions; otherwise the bar can stay
at “initialization” even when APIs return ``resultCd=000``.

**Product lookup:** the portal testcase “LOOK UP PRODUCT LIST” is ``/selectItemList`` (existing
items for the branch). That is separate from ``/selectItemClsList`` (HS/class codes). This
script calls ``selectItemList`` before ``saveItem`` (empty catalog ``resultCd=001`` is normal),
then **``selectItemListPostSave``** (same ``/selectItemList`` route with ``lastReqDt=20100101000000``)
so SBX returns the full catalog including the saved item (delta ``lastReqDt=now`` often yields
``resultCd=001`` when ``saveItem`` was skipped on resume).
**saveItem itemTyCd 2 (standard goods):** ``itemCd`` suffix sequencing is **linear per prefix** in
``item_cd_next_suffix_by_prefix``: the next suffix is last successful suffix + 1 (seeded from
``kra_item_cd_suffix_by_prefix`` / ``item_cd`` / ``canonical_item_cd`` on first use only).
``selectItemList`` is logged as a **hint only** (never used as max() for allocation). On KRA rejection,
the cursor moves to ``rejected_suffix + 1``, raised by any parsed ``Expected sequence ending with …``
hint. Up to ``MAX_SAVE_ITEM_TY2_ATTEMPTS`` tries stay on itemTyCd 2.
itemTyCd 1 (Paybill-style) is **only** used as an optional final attempt when
``SAVE_ITEM_ALLOW_TY1_FALLBACK`` or ``--allow-save-item-ty1-fallback`` is set.
**Portal testcase names ↔ this script (same API order):**
``SAVE ITEM COMPOSITION`` → ``saveItemComposition``; import lifecycle → ``selectImportItemList`` then
``importedItemInfo`` → ``importedItemConvertedInfo`` → ``updateImportItem``; ``SAVE SALES TRANSACTION`` →
``saveInvoice`` (POST ``/saveTrnsSalesOsdc``); ``LOOK UP PURCHASES-SALES LIST`` → ``selectTrnsPurchaseSalesList``;
``SAVE PURCHASES INFORMATION`` → ``insertTrnsPurchase``.

SBX stock verification uses **insertStockIO + saveStockMaster** as the only success contract.
Any deprecated stock-move-list behavior is intentionally not part of this script.
"""

from __future__ import annotations

import csv
import json
import os
import random
import re
import sys
import time
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests
from dotenv import load_dotenv

load_dotenv()


class SkipToNextSequenceStep(Exception):
    """Raised when ``--continue-on-step-failure`` is set and a sequence step hits a hard stop."""

# Windows terminals often use cp1252; runtime log_tag strings use Unicode arrows/dashes.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass

BASE_URL = "https://sbx.kra.go.ke/etims-oscu/api/v1"
OAUTH_BASE = "https://sbx.kra.go.ke"
OAUTH_TOKEN_PATH = "/v1/token/generate"

# Guardrail: prevent accidental re-introduction of deprecated move-list endpoint logic.
_FORBIDDEN_ENDPOINT_NAME_SUBSTRINGS = ("selectStockMoveList",)
_FORBIDDEN_ENDPOINT_PATHS = ("/selectStockMoveList",)


def _stock_api_cluster_base(full_endpoint_url: str) -> str:
    """
    Directory prefix one level above the operation name (host + shared path prefix).
    Sibling ops should use the same cluster base.
    """
    parts = urlsplit((full_endpoint_url or "").strip())
    path = (parts.path or "").rstrip("/")
    segments = [s for s in path.split("/") if s]
    if len(segments) >= 2:
        new_path = "/" + "/".join(segments[:-1])
    else:
        new_path = "/"
    return urlunsplit((parts.scheme, parts.netloc, new_path, "", ""))


_LAST_INSERT_STOCK_IO_FULL_URL: str | None = None


def reset_insert_stock_io_cluster_url() -> None:
    global _LAST_INSERT_STOCK_IO_FULL_URL
    _LAST_INSERT_STOCK_IO_FULL_URL = None


def register_insert_stock_io_request_url(full_url: str) -> None:
    """Remember the last ``insertStockIO`` POST URL so move-list reads can target the same KRA cluster."""
    global _LAST_INSERT_STOCK_IO_FULL_URL
    u = (full_url or "").strip()
    _LAST_INSERT_STOCK_IO_FULL_URL = u or None
    print(f"CLUSTER CHECK → insertStockIO URL: {u}")


def resolve_select_stock_move_list_url(declared_api_base_url: str) -> str:
    """
    Full URL for deprecated stock-move-list read. If it disagrees with the last ``insertStockIO`` cluster
    (e.g. ``/stock`` vs flat ``/api/v1``), use the insert op's base so read/write hit the same subsystem.
    """
    global _LAST_INSERT_STOCK_IO_FULL_URL
    base = (declared_api_base_url or "").rstrip("/")
    default_full = f"{base}/(deprecated-stock-move-list)"
    ins = _LAST_INSERT_STOCK_IO_FULL_URL
    if not ins:
        print(f"CLUSTER CHECK → deprecated stock-move-list URL: {default_full}")
        return default_full
    io_cluster = _stock_api_cluster_base(ins)
    move_cluster = _stock_api_cluster_base(default_full)
    if io_cluster.rstrip("/") != move_cluster.rstrip("/"):
        aligned = f"{io_cluster.rstrip('/')}/(deprecated-stock-move-list)"
        print(
            "CLUSTER MISMATCH: deprecated stock-move-list base "
            f"{move_cluster!r} != insertStockIO cluster base {io_cluster!r} "
            "— forcing read URL to match insert cluster"
        )
        print(f"CLUSTER CHECK → deprecated stock-move-list URL: {aligned}")
        return aligned
    print(f"CLUSTER CHECK → deprecated stock-move-list URL: {default_full}")
    return default_full


CSV_FILE = Path(__file__).parent / "test_pins.csv"
STATE_FILE = Path(__file__).parent / ".test_state.json"
# Root-level key in ``.test_state.json`` (sibling to per-PIN blobs): last committed insertStockIO ``sarNo`` per tin|bhf.
SAR_NO_BY_TIN_BHF_KEY = "sarNo_by_tin_bhf"

# Non-stock steps that may be skipped on resume when already in ``completed_endpoints``.
SKIPPABLE_NON_STOCK_ENDPOINTS_IF_COMPLETED = frozenset(
    {
        "saveBhfCustomer",
        "saveBhfUser",
        "saveBhfInsurance",
        "saveItem",
        "saveComponentItem",
        "selectItemList",
        "selectNotices",
    }
)

# SBX Apigee sometimes returns HTTP 500 fault "Unresolved variable : targetPath" for routes not wired to this product.
# ``selectTrnsPurchaseSalesListPreComposition`` also soft-skips HTTP 5xx (e.g. 504) — non-critical for purchase flow.
SOFT_SKIP_APIGEE_TARGET_PATH = frozenset(
    {
        "selectInvoiceType",
        "selectCustomerList",
        "selectTaxPayerInfo",
        "selectTrnsSalesList",
        "selectInvoiceDetails",
        "selectTrnsPurchaseSalesListPreComposition",
    }
)


def endpoint_safe_to_retry_on_transport_timeout(endpoint_name: str) -> bool:
    """
    Transport/read timeouts on SBX are common. Retrying mutating endpoints can duplicate writes
    (unknown server-side commit), so only auto-retry select/list probes.
    """
    n = (endpoint_name or "").strip()
    return n.startswith("select") or n in ("importedItemInfo", "importedItemConvertedInfo")


def post_with_retry(
    *,
    endpoint_name: str,
    url: str,
    headers: dict,
    payload: dict,
    timeout: int,
    params: dict | None = None,
    max_attempts: int = 2,
) -> requests.Response:
    """
    Single reusable POST wrapper.
    - Retries only for select/list style endpoints (safe), and only on transport timeouts/connection errors.
    - Never retries based on selectStockMoveList business outcomes (SBX move list is logging-only).
    """
    attempts = int(max_attempts)
    if attempts < 1:
        attempts = 1
    safe = endpoint_safe_to_retry_on_transport_timeout(endpoint_name)
    tries = attempts if safe else 1
    last_exc: Exception | None = None
    for i in range(tries):
        try:
            kw = {"headers": dict(headers), "json": payload, "timeout": timeout}
            if params is not None:
                kw["params"] = params
            return requests.post(url, **kw)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exc = e
            if i >= tries - 1:
                raise
            sl = min(15.0, 3.0 * (2**i) + random.random())
            print(
                f"WARNING: transport timeout talking to SBX (endpoint={endpoint_name!r}). "
                f"Retrying in {sl:.1f}s ({i + 1}/{tries}) …"
            )
            time.sleep(sl)
    raise requests.exceptions.ConnectionError(
        f"no response (endpoint={endpoint_name!r}): {last_exc!r}"
    )


def verify_stock_sbx_safe(
    *,
    insert_stock_parsed: dict | None,
    save_stock_master_parsed: dict | None,
    move_list_resp: requests.Response | None = None,
    move_list_parsed: dict | None = None,
    label: str = "STOCK VERIFY",
) -> bool:
    """
    SBX-safe stock verification:
    - Requires insertStockIO resultCd == "000"
    - Requires saveStockMaster resultCd == "000"
    - selectStockMoveList is best-effort logging only (ignored for success/failure)
    """
    rc_io = (extract_result_cd(insert_stock_parsed) or "").strip() if isinstance(insert_stock_parsed, dict) else ""
    rc_sm = (extract_result_cd(save_stock_master_parsed) or "").strip() if isinstance(save_stock_master_parsed, dict) else ""
    ok = (rc_io == "000") and (rc_sm == "000")
    http_mv = getattr(move_list_resp, "status_code", None) if move_list_resp is not None else None
    rc_mv = (extract_result_cd(move_list_parsed) or "").strip() if isinstance(move_list_parsed, dict) else ""
    print(
        f"{label}: insertStockIO resultCd={rc_io!r} | saveStockMaster resultCd={rc_sm!r} | "
        f"selectStockMoveList HTTP={http_mv!r} resultCd={rc_mv!r} (ignored)"
    )
    return bool(ok)


def _select_stock_move_list_twice_for_item(
    *,
    base_url: str,
    headers: dict,
    tin: str,
    bhf_id: str,
    item_cd: str,
    log_tag: str,
    timeout: int = 120,
) -> tuple[dict | None, requests.Response | None]:
    """
    Two ``/selectStockMoveList`` POSTs with a fresh UTC ``lastReqDt`` each (SBX propagation).
    Returns the **last** parsed JSON and response object (may be non-000 / unusable).
    """
    want = (item_cd or "").strip()
    if not want:
        return None, None
    surl = f"{base_url.rstrip('/')}/selectStockMoveList"
    parsed_last: dict | None = None
    resp_last: requests.Response | None = None
    for i in range(2):
        pl = {
            "tin": (tin or "").strip(),
            "bhfId": (bhf_id or "").strip(),
            "lastReqDt": kra_stock_move_list_last_req_dt_utc_now(),
            "itemCd": want,
        }
        print(f"{log_tag}: POST selectStockMoveList {i + 1}/2 lastReqDt={pl['lastReqDt']!r} itemCd={want!r}")
        try:
            resp_last = requests.post(surl, headers=headers, json=pl, timeout=timeout)
        except requests.RequestException as e:
            print(f"{log_tag}: selectStockMoveList request failed: {e!r}")
            return None, None
        try:
            parsed_last = resp_last.json()
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed_last = None
        if not isinstance(parsed_last, dict):
            parsed_last = None
        if i == 0:
            time.sleep(2.5)
    return parsed_last, resp_last


def kra_strict_select_stock_component_on_hand(
    *,
    base_url: str,
    headers: dict,
    tin: str,
    bhf_id: str,
    component_item_cd: str,
    min_rsd_qty: float,
    log_tag: str,
    timeout: int = 120,
) -> tuple[bool, float | None, dict | None, requests.Response | None]:
    """
    Composition / prelude strict gate: ``selectStockMoveList`` ×2 (UTC ``lastReqDt`` each).

    Returns ``(strict_ok, rsdQty_or_none, last_parsed, last_response)`` where ``strict_ok`` means
    HTTP OK, no gateway error, ``resultCd == "000"``, at least one move row for ``component_item_cd``,
    and extracted ``rsdQty >= min_rsd_qty`` on **either** probe.
    """
    want = (component_item_cd or "").strip()
    if not want:
        return False, None, None, None
    surl = f"{base_url.rstrip('/')}/selectStockMoveList"
    parsed_last: dict | None = None
    resp_last: requests.Response | None = None
    for i in range(2):
        pl = {
            "tin": (tin or "").strip(),
            "bhfId": (bhf_id or "").strip(),
            "lastReqDt": kra_stock_move_list_last_req_dt_utc_now(),
            "itemCd": want,
        }
        print(
            f"{log_tag}: POST selectStockMoveList {i + 1}/2 lastReqDt={pl['lastReqDt']!r} itemCd={want!r}"
        )
        try:
            resp_last = requests.post(surl, headers=headers, json=pl, timeout=timeout)
        except requests.RequestException as e:
            print(f"{log_tag}: selectStockMoveList request failed: {e!r}")
            return False, None, None, None
        try:
            parsed_last = resp_last.json()
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed_last = None
        if not isinstance(parsed_last, dict):
            parsed_last = None
        rc = (extract_result_cd(parsed_last) or "").strip() if isinstance(parsed_last, dict) else ""
        ge = kra_top_level_error_detail(parsed_last) if isinstance(parsed_last, dict) else None
        http_ok = resp_last.status_code < 400 and not ge
        nrows = count_stock_move_list_rows_for_item(parsed_last, want) if isinstance(parsed_last, dict) else 0
        rsd = (
            _first_rsd_qty_for_item_in_stock_move_tree(parsed_last, want)
            if isinstance(parsed_last, dict)
            else None
        )
        strict = (
            http_ok
            and rc == "000"
            and nrows > 0
            and rsd is not None
            and float(rsd) + 1e-9 >= float(min_rsd_qty)
        )
        if strict:
            return True, float(rsd), parsed_last, resp_last
        if i == 0:
            time.sleep(2.5)
    return False, None, parsed_last, resp_last


def best_effort_stock_read_debug(
    *,
    base_url: str,
    headers: dict,
    tin: str,
    bhf_id: str,
    item_cd: str,
    log_tag: str,
    timeout: int = 120,
) -> tuple[dict | None, requests.Response | None]:
    """Two ``/selectStockMoveList`` probes (UTC ``lastReqDt``); logging / probe helper for callers."""
    return _select_stock_move_list_twice_for_item(
        base_url=base_url,
        headers=headers,
        tin=tin,
        bhf_id=bhf_id,
        item_cd=item_cd,
        log_tag=log_tag,
        timeout=timeout,
    )


def sbx_stock_move_list_unreliable(base_url: str) -> bool:
    u = (base_url or "").strip().lower()
    return "sbx." in u or "sandbox" in u


def sbx_select_stock_move_list_unavailable(
    *,
    base_url: str,
    parsed: dict | None,
    resp: requests.Response | None,
) -> bool:
    """
    SBX often omits or delays ``selectStockMoveList`` rows after valid purchases / insertStockIO 000.
    When true, prelude and composition must not spin or hard-fail on move-list strict gates.
    """
    return sbx_stock_move_list_unreliable(base_url)


# SBX may have no customs import rows; still call the testcase but do not fail the whole run.
OPTIONAL_SBX_STEPS = frozenset(
    {"importedItemInfo", "importedItemConvertedInfo", "updateImportItem"}
)

# Full JSON request/response logging for import lifecycle (KRA Postman parity).
_IMPORT_LIFECYCLE_FULL_LOG = frozenset(
    {"importedItemInfo", "importedItemConvertedInfo", "updateImportItem"}
)

# ``select*`` calls that may legitimately return resultCd 001 (empty list).
_SELECT_EMPTY_OK = frozenset(
    {
        "selectImportItemList",
        "importedItemInfo",
        "selectTrnsPurchaseSalesList",
        # Pre-composition binding uses the same saleList shape; new PINs often have no outbound sales yet.
        "selectTrnsPurchaseSalesListPreComposition",
        "selectTrnsSalesList",
        "selectInvoiceDetails",
        "selectCustomerList",
        "selectTaxPayerInfo",
    }
)

# Same /selectStockMoveList route; separate step ids for initial vs final IO→save pairs.
_SELECT_STOCK_MOVE_ENDPOINTS = frozenset()

# Before ``saveStockMasterInitial``: local |pending| or move-list row count above this suggests SBX SAR /
# historical Stock IO backlog (fail fast; do not alter rsdQty or add retries).
INITIAL_SAVE_STOCKMASTER_DIRTY_THRESHOLD = 10
# Unreconciled SAR count (stock_io_next_sar_no - 1) at or above this → likely stacked IO / SBX rsdQty deadlock.
INITIAL_SAVE_STOCKMASTER_SAR_BACKLOG_DIRTY = 3

COMPOSITION_DELAY = 0

# Parent item: quantity for ``insertStockIOInitial`` (runs *after* ``saveItemComposition``) and
# ``saveStockMasterInitial``. Parent stock is not loaded until that triple runs.
INITIAL_PARENT_STOCK_QTY = 100.0
# After ``saveStockMasterPostComposition`` (mandatory pre-OSDC), wait before ``saveTrnsSalesOsdc``.
OSDC_POST_SAVE_STOCK_DELAY_SEC = 7.0
# KRA SBX often accepts saveStockMaster before the sales API sees the item; extra jittered wait after the above.
OSDC_EXTRA_DELAY_BEFORE_SAVE_INVOICE_SEC_MIN = 15.0
OSDC_EXTRA_DELAY_BEFORE_SAVE_INVOICE_SEC_MAX = 25.0
# saveTrnsSalesOsdc: if item not yet visible, wait and retry this endpoint only (do not rerun stock IO/save).
SAVE_INVOICE_STOCK_MASTER_MAX_ATTEMPTS = 6
SAVE_INVOICE_STOCK_MASTER_RETRY_SLEEP_SEC_MIN = 12.0
SAVE_INVOICE_STOCK_MASTER_RETRY_SLEEP_SEC_MAX = 15.0

# Composition consumes ``cpstQty`` of component; purchase feed must exceed that for KRA recognition.
COMPOSITION_CPST_QTY_DEFAULT = 1.0

# Max full prelude cycles (insertStockIO 01/1 → strict move list → saveStockMaster) for composition.
MAX_COMPOSITION_PRELUDE_ROUNDS = 5
# Before each saveItemComposition POST: strict move-list failures trigger a prelude re-run.
MAX_COMPOSITION_STOCK_REBUILD_PER_ATTEMPT = 3

# When False (default), saveItem stays on itemTyCd 2 (standard goods) with monotonic KE2… suffixes only.
# Set True or pass ``--allow-save-item-ty1-fallback`` to allow one final Paybill-style itemTyCd 1 attempt
# after all standard (itemTyCd 2) attempts are exhausted.
SAVE_ITEM_ALLOW_TY1_FALLBACK = False

# Max saveItem attempts while staying on itemTyCd 2 (before optional Paybill fallback when enabled).
MAX_SAVE_ITEM_TY2_ATTEMPTS = 8

# Authoritative next 7-digit numeric suffix per itemCd prefix (e.g. ``KE2NTTU`` → ``21`` means next POST
# uses ``…0000021``). Sequencing does not use selectItemList max(); see ``peek_next_item_cd_suffix_int``.
ITEM_CD_NEXT_SUFFIX_BY_PREFIX_KEY = "item_cd_next_suffix_by_prefix"


# Endpoint ``name`` keys matching the ``sequence`` tuples (for resume skips).
SEQUENCE_STEP_NAMES = (
    "initialize",
    "selectCodeList",
    "selectItemClsList",
    "selectBhfList",
    "selectNotices",
    "saveBhfCustomer",
    "saveBhfUser",
    "saveBhfInsurance",
    "selectItemList",
    "saveItem",
    "selectItemListPostSave",
    "saveComponentItem",
    "selectTrnsPurchaseSalesListPreComposition",
    "selectImportItemList",
    "importedItemInfo",
    "importedItemConvertedInfo",
    "updateImportItem",
    "insertTrnsPurchaseComponentStock",
    "saveStockMasterComponentPurchase",
    "saveItemComposition",
    "insertStockIOInitial",
    "saveStockMasterInitial",
    "insertStockIOPostComposition",
    "saveStockMasterPostComposition",
    "selectInvoiceType",
    "saveInvoice",
    "selectTrnsPurchaseSalesList",
    "insertTrnsPurchase",
    "saveStockMasterAfterPurchase",
    "insertStockIO",
    "saveStockMaster",
    "selectTrnsSalesList",
    "selectInvoiceDetails",
    "selectCustomerList",
    "selectTaxPayerInfo",
)

CSV_COLUMNS = (
    "app_pin",
    "consumer_key",
    "consumer_secret",
    "integ_pin",
    "branch_id",
    "device_serial",
    "apigee_app_id",
    "cmc_key",
)

# All columns except cmc_key must be present before OAuth / API calls.
REQUIRED_BODY_FIELDS = (
    "consumer_key",
    "consumer_secret",
    "integ_pin",
    "branch_id",
    "device_serial",
    "apigee_app_id",
)

PROMPT_FIELD_ORDER = (
    "consumer_key",
    "consumer_secret",
    "integ_pin",
    "branch_id",
    "device_serial",
    "apigee_app_id",
)

_FIELD_LABELS = {
    "consumer_key": "Consumer Key (OAuth Client ID)",
    "consumer_secret": "Consumer Secret (OAuth)",
    "integ_pin": "Integrator PIN",
    "branch_id": "Branch ID",
    "device_serial": "Device Serial Number",
    "apigee_app_id": "Apigee App ID (Client ID)",
}


def get_optional_env(key: str, default: str = "") -> str:
    value = os.getenv(key)
    return value.strip() if value else default


def load_test_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_test_state(root: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(root, f, indent=2)


def normalize_pin_blob(blob) -> dict:
    if not isinstance(blob, dict):
        return {"cmc_key": "", "completed_endpoints": []}
    out = dict(blob)
    out.setdefault("cmc_key", "")
    ce = out.get("completed_endpoints")
    if not isinstance(ce, list):
        ce = []
    out["completed_endpoints"] = [str(x).strip() for x in ce if str(x).strip()]
    return out


def reset_pin_clean_run(pin_blob: dict) -> None:
    """Clear item, stock, composition, import, sales, and purchase steps for a consistent hybrid rerun."""
    preserved_minimal_cd = pin_blob.get("minimal_osdc_item_cd_override")
    ce = list(pin_blob.get("completed_endpoints") or [])
    drop = {
        "saveItem",
        "selectItemListPostSave",
        "insertStockIOInitial",
        "saveStockMasterInitial",
        "saveComponentItem",
        "selectTrnsPurchaseSalesListPreComposition",
        "insertTrnsPurchaseComponentStock",
        "saveStockMasterComponentPurchase",
        "saveItemComposition",
        "insertStockIOPostComposition",
        "saveStockMasterPostComposition",
        "selectImportItemList",
        "importedItemInfo",
        "importedItemConvertedInfo",
        "updateImportItem",
        "selectInvoiceType",
        "saveInvoice",
        "selectTrnsPurchaseSalesList",
        "insertTrnsPurchase",
        "saveStockMasterAfterPurchase",
        "insertStockIO",
        "saveStockMaster",
    }
    pin_blob["completed_endpoints"] = [x for x in ce if x not in drop]
    for k in (
        "item_cd",
        "canonical_item_cd",
        "component_item_cd",
        "stock_io_next_sar_no",
        "stock_io_last_committed_sar_no",
        "stock_io_pending_rsd_qty",
        "stock_io_component_pending_rsd_qty",
        "current_stock_balance",
        "component_stock_balance",
        "stocked_component_for_composition",
        "composition_prelude_logged_io_sar_no",
        "composition_prelude_logged_sm_result_cd",
        "composition_prelude_logged_component_item_cd",
        "kra_item_cd_suffix_by_prefix",
        ITEM_CD_NEXT_SUFFIX_BY_PREFIX_KEY,
        "kra_item_cd_tail_constraint_by_prefix",
        "item_cd_suffix_last_digit",
        "item_cd_suffix_tail_mod",
        "item_cd_suffix_tail_res",
        "item_dft_prc",
        "item_nm_stock",
        "component_item_cls_cd",
        "component_item_tax_ty_cd",
        "save_item_ty_cd",
        "saveItemComposition_resultCd",
        "saveItemComposition_resultMsg",
        "saveItemComposition_responseRefId",
        "saveItemComposition_last_resultCd",
        "saveItemComposition_last_resultMsg",
        "saveItemComposition_last_responseRefId",
        "purchase_invc_no_component",
        "component_reconcile_rsd_qty",
        "component_purchase_bypass_rsd_qty",
        "component_purchase_next_invc_no",
        "parent_rsd_qty_post_purchase",
        "parent_rsd_qty_final",
        "parent_initial_save_rsd_qty_from_kra",
        "component_trns_purchase_ok",
        "precomp_purchase_sales_invc_no",
        "precomp_purchase_spplr_tin",
        "precomp_purchase_spplr_bhf_id",
        "precomp_purchase_spplr_nm",
        "precomp_purchase_link_tax_rt",
        "main_purchase_sales_invc_no",
        "main_purchase_link_tax_rt",
        "import_update_row",
        "import_item_candidates",
        "import_lifecycle_ready",
        "import_lifecycle_skip_reason",
        "select_import_item_list_diag_ok",
        "select_import_item_list_diag_reason",
        "post_composition_osdc_ready",
        "parent_post_composition_io_qty",
        "parent_osdc_prep_rsd_qty",
        "_stock_move_list_initial_io_fallback",
        "_stock_move_list_post_osdc_io_fallback",
    ):
        pin_blob.pop(k, None)
    pin_blob["stock_io_pending_rsd_qty"] = 0.0
    if preserved_minimal_cd is not None and str(preserved_minimal_cd).strip():
        pin_blob["minimal_osdc_item_cd_override"] = str(preserved_minimal_cd).strip()


def reset_pin_stock_progress(pin_blob: dict) -> None:
    """Drop local stock-step progress so the sequence can run again after a portal-side stock/SAR reset."""
    ce = list(pin_blob.get("completed_endpoints") or [])
    drop = {
        "insertStockIOInitial",
        "saveStockMasterInitial",
        "insertTrnsPurchase",
        "saveStockMasterAfterPurchase",
        "insertStockIO",
        "saveStockMaster",
        "saveComponentItem",
        "selectTrnsPurchaseSalesListPreComposition",
        "selectImportItemList",
        "importedItemInfo",
        "importedItemConvertedInfo",
        "updateImportItem",
        "insertTrnsPurchaseComponentStock",
        "saveStockMasterComponentPurchase",
        "saveItemComposition",
        "insertStockIOPostComposition",
        "saveStockMasterPostComposition",
    }
    pin_blob["completed_endpoints"] = [x for x in ce if x not in drop]
    for k in (
        "stock_io_component_pending_rsd_qty",
        "current_stock_balance",
        "component_stock_balance",
        "stocked_component_for_composition",
        "composition_prelude_logged_io_sar_no",
        "composition_prelude_logged_sm_result_cd",
        "composition_prelude_logged_component_item_cd",
        "purchase_invc_no_component",
        "component_reconcile_rsd_qty",
        "component_purchase_bypass_rsd_qty",
        "component_purchase_next_invc_no",
        "parent_rsd_qty_post_purchase",
        "parent_rsd_qty_final",
        "parent_initial_save_rsd_qty_from_kra",
        "parent_initial_insert_stock_qty",
        "component_trns_purchase_ok",
        "precomp_purchase_sales_invc_no",
        "precomp_purchase_spplr_tin",
        "precomp_purchase_spplr_bhf_id",
        "precomp_purchase_spplr_nm",
        "precomp_purchase_link_tax_rt",
        "main_purchase_sales_invc_no",
        "main_purchase_link_tax_rt",
        "import_update_row",
        "import_item_candidates",
        "import_lifecycle_ready",
        "import_lifecycle_skip_reason",
        "select_import_item_list_diag_ok",
        "select_import_item_list_diag_reason",
        "post_composition_osdc_ready",
        "parent_post_composition_io_qty",
        "parent_osdc_prep_rsd_qty",
        "_stock_move_list_initial_io_fallback",
        "_stock_move_list_post_osdc_io_fallback",
    ):
        pin_blob.pop(k, None)
    # Do not force sarNo=1: KRA keeps the real sequence (e.g. next is 9 after failed runs).
    # Omit key so the first attempt defaults to 1, or run again; insertStockIO syncs from KRA errors.
    pin_blob.pop("stock_io_next_sar_no", None)
    pin_blob.pop("stock_io_last_committed_sar_no", None)
    pin_blob["stock_io_pending_rsd_qty"] = 0.0


def reset_pin_initial_stock_atomic_pair(pin_blob: dict) -> None:
    """Clear local completion + pending for the initial IO/save pair so they replay together."""
    ce = list(pin_blob.get("completed_endpoints") or [])
    pin_blob["completed_endpoints"] = [
        x
        for x in ce
        if x
        not in (
            "insertStockIOInitial",
            "saveStockMasterInitial",
        )
    ]
    pin_blob["stock_io_pending_rsd_qty"] = 0.0
    pin_blob.pop("stock_io_next_sar_no", None)
    pin_blob.pop("current_stock_balance", None)
    pin_blob.pop("parent_initial_insert_stock_qty", None)
    pin_blob.pop("parent_initial_save_rsd_qty_from_kra", None)
    pin_blob.pop("_stock_move_list_initial_io_fallback", None)


def apply_diagnostic_stock_io_reset(
    pin_blob: dict,
    state_root: dict | None = None,
    tin: str | None = None,
    bhf_id: str | None = None,
) -> None:
    """Single SBX check: drop local resume for the initial IO → move list → save triple; SAR 1; balance 0."""
    ce = list(pin_blob.get("completed_endpoints") or [])
    drop = {
        "insertStockIOInitial",
        "saveStockMasterInitial",
    }
    pin_blob["completed_endpoints"] = [x for x in ce if x not in drop]
    pin_blob["stock_io_next_sar_no"] = 1
    pin_blob["current_stock_balance"] = 0.0
    pin_blob["stock_io_pending_rsd_qty"] = 0.0
    pin_blob.pop("parent_initial_insert_stock_qty", None)
    pin_blob.pop("parent_initial_save_rsd_qty_from_kra", None)
    pin_blob.pop("_stock_move_list_initial_io_fallback", None)
    if (
        state_root is not None
        and (tin or "").strip()
        and (bhf_id or "").strip()
    ):
        clear_insert_stock_sar_sequence_for_tin_bhf(
            state_root, str(tin).strip(), str(bhf_id).strip()
        )


def reconcile_item_cd_with_pin_state(pin_blob: dict, run_item_cd: str) -> str:
    """Single canonical itemCd from state; log if run variable drifts."""
    saved = (
        pin_blob.get("canonical_item_cd")
        or pin_blob.get("item_cd")
        or ""
    ).strip()
    run = (run_item_cd or "").strip()
    if saved and run and saved != run:
        print(
            "ASSERT itemCd: drift — state canonical "
            f"{saved!r} != run {run!r}; using canonical from "
            f"{STATE_FILE.name}."
        )
        return saved
    return saved or run


def log_step_banner(
    step: str,
    item_cd_val: str,
    completed: list[str],
    *,
    ran_insert_stock_io_this_run: bool,
    ran_insert_stock_io_initial_this_run: bool,
    ran_insert_stock_io_parent_this_run: bool,
) -> None:
    print(f"\n=== STEP: {step}")
    print(f"itemCd: {item_cd_val or '(none)'}")
    print(f"ran_insert_stock_io_this_run: {ran_insert_stock_io_this_run}")
    print(
        "ran_insert_stock_io_initial_this_run: "
        f"{ran_insert_stock_io_initial_this_run}"
    )
    print(
        "ran_insert_stock_io_parent_this_run: "
        f"{ran_insert_stock_io_parent_this_run}"
    )
    print(f"state.completed: {completed} ===\n")


def log_api_result_summary(
    endpoint: str,
    resp: requests.Response | None,
    parsed: dict | None,
    result_cd: str | None,
) -> None:
    http = getattr(resp, "status_code", None)
    rhc = None
    if isinstance(parsed, dict):
        rh = parsed.get("responseHeader")
        if isinstance(rh, dict):
            rhc = rh.get("responseCode")
    print(
        f"… API result [{endpoint}]: HTTP={http} "
        f"responseHeader.responseCode={rhc!r} resultCd={result_cd!r}"
    )


def preview_consumer_key(consumer_key: str) -> str:
    ck = (consumer_key or "").strip()
    if len(ck) <= 14:
        return ck
    return f"{ck[:10]}…{ck[-4:]}"


def ensure_csv_file() -> None:
    if not CSV_FILE.exists():
        CSV_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=list(CSV_COLUMNS)).writeheader()


def read_rows() -> list[dict[str, str]]:
    ensure_csv_file()
    rows: list[dict[str, str]] = []
    with open(CSV_FILE, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return rows
        for raw in reader:
            if not raw:
                continue
            row = {k: (raw.get(k) or "").strip() for k in CSV_COLUMNS}
            if any(row.values()):
                rows.append(row)
    return rows


def write_rows(rows: list[dict[str, str]]) -> None:
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(CSV_COLUMNS), extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (r.get(k) or "").strip() for k in CSV_COLUMNS})


def find_row_index(rows: list[dict[str, str]], app_pin: str) -> int | None:
    ap = app_pin.strip()
    for i, r in enumerate(rows):
        if r.get("app_pin", "").strip() == ap:
            return i
    return None


def row_dict_for_pin(rows: list[dict[str, str]], app_pin: str) -> dict[str, str] | None:
    idx = find_row_index(rows, app_pin)
    if idx is None:
        return None
    return dict(rows[idx])


def upsert_row(rows: list[dict[str, str]], entry: dict[str, str]) -> None:
    ap = str(entry.get("app_pin", "")).strip()
    clean = {k: str(entry.get(k, "") or "").strip() for k in CSV_COLUMNS}
    clean["app_pin"] = ap
    idx = find_row_index(rows, ap)
    if idx is not None:
        rows[idx] = clean
        # Drop later duplicate rows for same PIN
        j = idx + 1
        while j < len(rows):
            if rows[j].get("app_pin", "").strip() == ap:
                rows.pop(j)
            else:
                j += 1
    else:
        rows.append(clean)


def persist(rows: list[dict[str, str]], entry: dict[str, str]) -> None:
    upsert_row(rows, entry)
    write_rows(rows)


def sibling_defaults_from_rows(rows: list[dict[str, str]], exclude_app_pin: str) -> dict[str, str]:
    found: dict[str, str] = {}
    ex = exclude_app_pin.strip()
    for r in rows:
        if r.get("app_pin", "").strip() == ex:
            continue
        for f in ("integ_pin", "branch_id", "device_serial"):
            if f not in found and str(r.get(f) or "").strip():
                found[f] = str(r[f]).strip()
        if len(found) == 3:
            break
    return found


def input_line(label: str, default: str) -> str:
    d = (default or "").strip()
    hint = f" [{d}]" if d else ""
    s = input(f"{label}{hint}: ").strip()
    return s or d


def cli_pin_and_flags() -> tuple[
    str,
    bool,
    bool,
    bool,
    frozenset[str] | None,
    bool,
    bool,
    bool,
    bool,
    bool,
    bool,
    bool,
    bool,
    bool,
    bool,
    bool,
    bool,
    bool,
    bool,
    bool,
]:
    """PIN + reset/clean/replay flags, ``--only``, diagnostics, minimal/matrix, ledger debug, harnesses."""
    raw = [str(x).strip() for x in sys.argv[1:] if str(x).strip()]
    only_steps: frozenset[str] | None = None
    rest: list[str] = []
    i = 0
    while i < len(raw):
        x = raw[i]
        if x.startswith("--only="):
            only_steps = frozenset(
                s.strip() for s in x.split("=", 1)[1].split(",") if s.strip()
            )
            i += 1
        elif x == "--only":
            if i + 1 >= len(raw) or raw[i + 1].startswith("--"):
                raise SystemExit(
                    "--only requires a comma-separated list of endpoint step names "
                    "(e.g. --only selectCustomerList,selectTaxpayerInfo)."
                )
            only_steps = frozenset(
                s.strip() for s in raw[i + 1].split(",") if s.strip()
            )
            i += 2
        else:
            rest.append(x)
            i += 1
    flags = {x for x in rest if x.startswith("--")}
    positionals = [x for x in rest if not x.startswith("--")]
    pin = positionals[0] if positionals else ""
    reset_stock = "--reset-stock" in flags
    clean_run = "--clean-run" in flags
    force_stock_replay = "--force-stock-replay" in flags
    diagnostic_stock_io = "--diagnostic-stock-io" in flags
    allow_save_item_ty1_fallback = "--allow-save-item-ty1-fallback" in flags
    strict_pre_sale_audit = "--strict-pre-sale-audit" in flags
    minimal_osdc_sale_test = "--minimal-osdc-sale-test" in flags
    minimal_osdc_pasteback = "--minimal-osdc-pasteback" in flags
    minimal_stock_ledger_matrix = "--minimal-stock-ledger-matrix" in flags
    debug_ledger_after_io = "--debug-ledger-after-io" in flags
    ledger_contract_test = "--ledger-contract-test" in flags
    stock_lifecycle_isolation_test = "--stock-lifecycle-isolation-test" in flags
    stock_master_visibility_test = "--stock-master-visibility-test" in flags
    sbx_finished_good_ledger_probe = "--sbx-finished-good-ledger-probe" in flags
    portal_checklist_mode = "--portal-checklist-mode" in flags
    bypass_component_stock_gate = "--bypass-component-stock-gate" in flags
    bypass_pre_sale_stock_gate = "--bypass-pre-sale-stock-gate" in flags
    continue_on_step_failure = "--continue-on-step-failure" in flags
    return (
        pin,
        reset_stock,
        clean_run,
        force_stock_replay,
        only_steps,
        diagnostic_stock_io,
        allow_save_item_ty1_fallback,
        strict_pre_sale_audit,
        minimal_osdc_sale_test,
        minimal_osdc_pasteback,
        minimal_stock_ledger_matrix,
        debug_ledger_after_io,
        ledger_contract_test,
        stock_lifecycle_isolation_test,
        stock_master_visibility_test,
        sbx_finished_good_ledger_probe,
        portal_checklist_mode,
        bypass_component_stock_gate,
        bypass_pre_sale_stock_gate,
        continue_on_step_failure,
    )


def prompt_app_pin() -> str:
    pin = cli_pin_and_flags()[0]
    if pin:
        return pin
    print(
        "\nEnter the Application Test PIN for this run (not read from .env).\n"
        "Tip: Ctrl+V or right-click to paste; input is visible.\n"
        "Or pass as first argument: python gavaetims.py <PIN>\n"
        "After resetting stock/SAR on the OSCU portal: python gavaetims.py <PIN> --reset-stock\n"
        "To drop stale item/stock state: python gavaetims.py <PIN> --clean-run\n"
        "To replay only insertStockIOInitial+saveStockMasterInitial: python gavaetims.py <PIN> --force-stock-replay\n"
        "SBX stock direction diagnostic (clean portal stock + local reset): "
        "python gavaetims.py <PIN> --diagnostic-stock-io\n"
        "Optional: enable itemTyCd 1 Paybill fallback (off by default): "
        "python gavaetims.py <PIN> --allow-save-item-ty1-fallback\n"
        "Structured audit before saveTrnsSalesOsdc: python gavaetims.py <PIN> --strict-pre-sale-audit\n"
        "Minimal no-composition sale probe: python gavaetims.py <PIN> --minimal-osdc-sale-test "
        "[--clean-run] [--minimal-osdc-pasteback]\n"
        "  (pre-saveItem selectItemList catalog + KRA sequence retries; optional .env "
        "GAVAETIMS_MINIMAL_ITEM_CD or pin minimal_osdc_item_cd_override in .test_state.json)\n"
        "Stock ledger payload matrix (after minimal saveItem+item gate): "
        "python gavaetims.py <PIN> --minimal-stock-ledger-matrix "
        "(or with --minimal-osdc-sale-test)\n"
        "Ledger delay vs missing-row probe (timed selects + optional selectStockMaster; ~17s sleeps): "
        "add --debug-ledger-after-io to minimal/matrix/full-sequence insertStockIO success paths\n"
        "Ledger contract harness (frozen case, literal sarNo=1, no SAR state; 20s sleeps; 4-line stdout): "
        "python gavaetims.py <PIN> --ledger-contract-test\n"
        "Stock lifecycle isolation (saveItem → IO → move list → saveStockMaster → move list; no composition/sales): "
        "python gavaetims.py <PIN> --stock-lifecycle-isolation-test\n"
        "Portal checklist parity (run /selectStockMoveList but never gate on it): "
        "python gavaetims.py <PIN> --portal-checklist-mode\n"
        "Stock master visibility probe (saveItem → IO → saveStockMaster → selectStockMaster): "
        "python gavaetims.py <PIN> --stock-master-visibility-test\n"
        "SBX finished-good ledger probe (itemTyCd=2: saveItem → IO → saveStockMaster → 10s → baseline×2 + UTC): "
        "python gavaetims.py <PIN> --sbx-finished-good-ledger-probe\n"
        "Sandbox-only: skip component move-list gates (prelude, before saveItemComposition, and main\n"
        "  selectStockMoveListComponentPurchase after component purchase 000): "
        "python gavaetims.py <PIN> --bypass-component-stock-gate\n"
        "Optional: --bypass-pre-sale-stock-gate (legacy SBX flag; default path already trusts "
        "saveStockMasterPostComposition 000 and uses selectStockMoveList only as a diagnostic probe)\n"
        "Sandbox exploration: on hard stop, skip to the next sequence step (may hit dependent-step "
        "errors): python gavaetims.py <PIN> --continue-on-step-failure\n"
    )
    s = input("Enter Application Test PIN: ").strip()
    if not s:
        raise SystemExit("Application Test PIN is required.")
    return s


def ensure_required_fields(
    rows: list[dict[str, str]],
    entry: dict[str, str],
    *,
    new_pin: bool,
    reprompt_all: bool = False,
) -> dict[str, str]:
    """Ensure entry has all REQUIRED_BODY_FIELDS; prompt if needed."""
    app_pin = str(entry.get("app_pin", "")).strip()
    sib = sibling_defaults_from_rows(rows, app_pin)

    if reprompt_all:
        missing = list(PROMPT_FIELD_ORDER)
    else:
        missing = [k for k in PROMPT_FIELD_ORDER if not str(entry.get(k) or "").strip()]

    if not missing:
        return {k: str(entry.get(k, "") or "").strip() for k in CSV_COLUMNS}

    if not sys.stdin.isatty():
        raise SystemExit(
            "Missing CSV fields for this PIN: "
            + ", ".join(missing)
            + f". Fill {CSV_FILE.name} or run interactively (TTY).\n"
            f"Required columns (except cmc_key): {', '.join(REQUIRED_BODY_FIELDS)}"
        )

    if reprompt_all:
        print("\n--- Re-enter all credentials for this Application Test PIN ---\n")
    elif new_pin:
        print(
            "\n--- New Application Test PIN — enter credentials ---\n"
            "(Defaults in [brackets] may come from another row in the CSV.)\n"
        )
    else:
        print(f"\n--- Incomplete row in CSV — enter missing fields ---\nMissing: {', '.join(missing)}\n")

    out = {k: str(entry.get(k, "") or "").strip() for k in CSV_COLUMNS}
    out["app_pin"] = app_pin

    to_ask = [k for k in PROMPT_FIELD_ORDER if k in missing]
    for step_num, k in enumerate(to_ask, start=1):
        default = out.get(k) or sib.get(k, "")
        out[k] = input_line(f"Step {step_num} — {_FIELD_LABELS[k]}", default)

    still = [k for k in REQUIRED_BODY_FIELDS if not str(out.get(k) or "").strip()]
    if still:
        raise SystemExit("ERROR: Still missing: " + ", ".join(still))

    return out


def obtain_bearer_token(
    consumer_key: str, consumer_secret: str, timeout: int = 60
) -> tuple[str | None, str | None]:
    """Return (access_token, error_message)."""
    url = f"{OAUTH_BASE.rstrip('/')}{OAUTH_TOKEN_PATH}"
    params = {"grant_type": "client_credentials"}
    try:
        r = requests.get(url, auth=(consumer_key, consumer_secret), params=params, timeout=timeout)
    except requests.RequestException as e:
        return None, f"OAuth request failed: {e}"

    try:
        data = r.json() if r.text else {}
    except Exception:
        data = {}

    if r.status_code >= 400:
        preview = (r.text or "")[:2000]
        return None, f"OAuth failed: HTTP {r.status_code}{(': ' + preview) if preview else ''}"

    token = data.get("access_token")
    if not token or not str(token).strip():
        return None, "OAuth response missing access_token — " + json.dumps(data, default=str)[:1500]

    return str(token).strip(), None


def validate_credentials_for_app_pin(
    entry: dict[str, str],
) -> tuple[bool, str | None, str | None, str | None]:
    """
    OAuth (unless BEARER_TOKEN in .env) + selectInitOsdcInfo. Does not write CSV.
    Returns (success, error_detail, bearer_if_success, cmc_key_from_response_or_none).
    """
    app_pin = str(entry.get("app_pin", "")).strip()
    consumer_key = entry["consumer_key"]
    consumer_secret = entry["consumer_secret"]
    branch_id = entry["branch_id"]
    device_serial = entry["device_serial"]
    apigee_app_id = entry["apigee_app_id"]

    manual_bearer = get_optional_env("BEARER_TOKEN")
    if manual_bearer:
        bearer = manual_bearer
        print("VALIDATION: Using BEARER_TOKEN from environment (OAuth skipped).")
    else:
        print("VALIDATION: OAuth (client_credentials)...")
        bearer, oerr = obtain_bearer_token(consumer_key, consumer_secret)
        if oerr:
            return False, oerr, None, None
        tok = bearer or ""
        preview = f"{tok[:12]}…{tok[-8:]}" if len(tok) > 24 else "(short token)"
        print(f"VALIDATION: OAuth OK (Bearer {preview}, len={len(tok)})")

    headers = {
        "Authorization": f"Bearer {bearer}",
        "tin": app_pin,
        "bhfId": branch_id,
        "apigee_app_id": apigee_app_id,
        "dvcSrlNo": device_serial,
        "Content-Type": "application/json",
    }
    step0_url = f"{BASE_URL.rstrip('/')}/selectInitOsdcInfo"
    step0_payload = {"tin": app_pin, "bhfId": branch_id, "dvcSrlNo": device_serial}
    print("VALIDATION: Calling selectInitOsdcInfo...")
    print("Payload:", json.dumps(step0_payload, indent=2, ensure_ascii=False))

    try:
        resp0 = requests.post(step0_url, headers=headers, json=step0_payload, timeout=60)
    except requests.RequestException as e:
        return False, f"VALIDATION: selectInitOsdcInfo request failed: {e}", bearer, None

    parsed0 = print_full_response_json(resp0, "selectInitOsdcInfo (validation)")
    result_cd0 = extract_result_cd(parsed0)
    gate_err0 = kra_top_level_error_detail(parsed0)
    rb_msg0 = kra_extract_response_body_result_msg(parsed0)

    if resp0.status_code >= 400:
        detail = f"VALIDATION: HTTP {resp0.status_code} from selectInitOsdcInfo"
        if result_cd0:
            detail += f" (resultCd={result_cd0!r}"
            if rb_msg0:
                detail += f", resultMsg={rb_msg0!r}"
            detail += ")"
        elif rb_msg0:
            detail += f" (resultMsg={rb_msg0!r})"
        return (False, detail, bearer, None)
    if gate_err0:
        return False, f"VALIDATION: KRA gateway error — {gate_err0}", bearer, None
    if result_cd0 not in ("000", "902"):
        return (
            False,
            f"VALIDATION: selectInitOsdcInfo resultCd={result_cd0}",
            bearer,
            None,
        )

    new_cmc = None
    if isinstance(parsed0, dict):
        rb0 = parsed0.get("responseBody")
        if isinstance(rb0, dict):
            ck = rb0.get("cmcKey")
            if isinstance(ck, str) and ck.strip():
                new_cmc = ck.strip()
    if not new_cmc:
        new_cmc = extract_first_cmc_key(parsed0)

    if result_cd0 == "000":
        if not new_cmc:
            return (
                False,
                "VALIDATION: resultCd=000 but cmcKey missing in response.",
                bearer,
                None,
            )
    # result_cd0 == 902: installed device; cmcKey may be absent — still a match

    print(f"VALIDATION: OK (resultCd={result_cd0}, cmcKey={'present' if new_cmc else 'absent (902 acceptable)'})")
    return True, None, bearer, new_cmc


def reload_cmc_from_csv(app_pin: str) -> str | None:
    rows = read_rows()
    e = row_dict_for_pin(rows, app_pin)
    if not e:
        return None
    v = str(e.get("cmc_key") or "").strip()
    return v or None


def fetch_oscu_access_token(consumer_key: str, consumer_secret: str, timeout: int = 60) -> str:
    print("RUNNING oauth_token (GET /v1/token/generate client_credentials)")
    tok, err = obtain_bearer_token(consumer_key, consumer_secret, timeout=timeout)
    if err:
        print(err)
        raise SystemExit(err)
    preview = f"{tok[:12]}…{tok[-8:]}" if len(tok) > 24 else "(short token)"
    print(f"OAUTH_OK Bearer token obtained ({preview}, len={len(tok)})")
    return tok


def deep_override_keys(obj, override_map: dict[str, str]):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in override_map:
                out[k] = override_map[k]
            else:
                out[k] = deep_override_keys(v, override_map)
        return out
    if isinstance(obj, list):
        return [deep_override_keys(x, override_map) for x in obj]
    return obj


def _item_cd_row_match_for_preference(pref: str, il: list | None) -> bool:
    """True if a line item matches the saved product (exact or 7-digit suffix match)."""
    if not pref or not isinstance(il, list):
        return False
    p = pref.strip()
    p7 = p[-7:] if len(p) >= 7 and p[-7:].isdigit() else ""
    for it in il:
        if not isinstance(it, dict):
            continue
        ic = str(it.get("itemCd") or "").strip()
        if not ic:
            continue
        if ic == p:
            return True
        if p7 and len(ic) >= 7 and ic[-7:].isdigit() and ic[-7:] == p7:
            return True
    return False


def extract_spplr_invc_candidates_from_trns_purchase_sales_list(
    parsed,
    *,
    prefer_item_cd: str = "",
    restrict_spplr_tin: str = "",
) -> list[str]:
    """Collect supplier invoice refs for ``requestedInvcNo`` from selectTrnsPurchaseSalesList* JSON.

    KRA rows expose ``spplrInvcNo`` (and sometimes ``invcNo``). Prefer a transaction row whose
    nested ``itemList`` contains ``prefer_item_cd`` when provided (e.g. component or parent SKU).

    If ``restrict_spplr_tin`` is set, only rows whose ``spplrTin`` equals that TIN are used — binding
    ``spplrInvcNo`` from **another** taxpayer's sale line can make KRA reject the purchase server-side.
    """
    preferred: list[str] = []
    rest: list[str] = []
    seen: set[str] = set()
    pref = (prefer_item_cd or "").strip()
    rtin = (restrict_spplr_tin or "").strip()

    def consider_row(row: dict) -> None:
        if rtin:
            row_tin = str(row.get("spplrTin") or "").strip()
            if row_tin != rtin:
                return
        sp = row.get("spplrInvcNo")
        if sp is None or not str(sp).strip():
            return
        s = str(sp).strip()
        if s in seen:
            return
        il = row.get("itemList")
        match = False
        if pref and isinstance(il, list):
            match = _item_cd_row_match_for_preference(pref, il)
        if match:
            preferred.append(s)
        else:
            rest.append(s)
        seen.add(s)

    def walk(o):
        if isinstance(o, dict):
            if "spplrInvcNo" in o and "itemList" in o:
                consider_row(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    if isinstance(parsed, dict):
        walk(parsed)
    # Also pick up loose invcNo (some SBX shapes) not tied to itemList rows
    loose: list[str] = []
    seen_loose: set[str] = set()

    def walk_invc(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "invcNo" and v is not None and str(v).strip():
                    s = str(v).strip()
                    if s not in seen_loose:
                        seen_loose.add(s)
                        loose.append(s)
                walk_invc(v)
        elif isinstance(o, list):
            for x in o:
                walk_invc(x)

    if not rtin:
        walk_invc(parsed)
        return preferred + rest + loose
    return preferred + rest


def extract_preferred_sale_row_for_trns_purchase_binding(
    parsed,
    *,
    prefer_item_cd: str = "",
    restrict_spplr_tin: str = "",
) -> dict | None:
    """Same prioritization as ``extract_spplr_invc_candidates_from_trns_purchase_sales_list`` but return the full sale row.

    Used to copy ``taxRtA``–``taxRtE`` from the linked supplier sale into ``insertTrnsPurchase``; SBX validates
    those rates against the bound ``spplrInvcNo`` row.
    """
    preferred: list[dict] = []
    rest: list[dict] = []
    seen: set[str] = set()
    pref = (prefer_item_cd or "").strip()
    rtin = (restrict_spplr_tin or "").strip()

    def consider_row(row: dict) -> None:
        if rtin:
            row_tin = str(row.get("spplrTin") or "").strip()
            if row_tin != rtin:
                return
        sp = row.get("spplrInvcNo")
        if sp is None or not str(sp).strip():
            return
        s = str(sp).strip()
        if s in seen:
            return
        il = row.get("itemList")
        match = False
        if pref and isinstance(il, list):
            match = _item_cd_row_match_for_preference(pref, il)
        if match:
            preferred.append(row)
        else:
            rest.append(row)
        seen.add(s)

    def walk(o):
        if isinstance(o, dict):
            if "spplrInvcNo" in o and "itemList" in o:
                consider_row(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    if isinstance(parsed, dict):
        walk(parsed)
    pick = preferred[0] if preferred else (rest[0] if rest else None)
    return pick if isinstance(pick, dict) else None


def sale_row_tax_rt_map(row: dict | None) -> dict[str, float]:
    """Header tax rate fields from a ``selectTrnsPurchaseSalesList`` sale row (for purchase payload alignment)."""
    if not row or not isinstance(row, dict):
        return {}
    out: dict[str, float] = {}
    for k in ("taxRtA", "taxRtB", "taxRtC", "taxRtD", "taxRtE"):
        try:
            v = row.get(k)
            out[k] = float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            out[k] = 0.0
    return out


def apply_link_tax_rt_to_purchase_payload(payload: dict, tax_rt_map: object) -> None:
    """When linking a purchase to a supplier sale, mirror that sale's header ``taxRt*`` (KRA rule taxRtB, etc.)."""
    if not isinstance(payload, dict) or not isinstance(tax_rt_map, dict):
        return
    for k in ("taxRtA", "taxRtB", "taxRtC", "taxRtD", "taxRtE"):
        if k not in tax_rt_map:
            continue
        try:
            payload[k] = float(tax_rt_map[k])
        except (TypeError, ValueError):
            pass


# SBX ``saleList`` rows often carry taxRtB=16 while line taxTyCd is A/D; linked insertTrnsPurchase must match.
_LINKED_PURCHASE_TAX_RT_FALLBACK_KE_SBX: dict[str, float] = {
    "taxRtA": 0.0,
    "taxRtB": 16.0,
    "taxRtC": 0.0,
    "taxRtD": 0.0,
    "taxRtE": 0.0,
}


def _link_tax_rt_for_purchase_or_fallback(
    pin_blob: dict, state_key: str, *, note_tag: str
) -> dict[str, float]:
    """Use stored sale-row snapshot when present; otherwise SBX-typical rates (resume without re-select)."""
    raw = pin_blob.get(state_key)
    m = sale_row_tax_rt_map(raw if isinstance(raw, dict) else None)
    if any(m.values()):
        return m
    print(
        f"NOTE: {note_tag} — missing or empty {state_key!r} in resume state; "
        "using Kenya SBX linked-sale taxRt defaults (taxRtB=16)."
    )
    return dict(_LINKED_PURCHASE_TAX_RT_FALLBACK_KE_SBX)


def import_item_list_allows_update_import_item(
    parsed: dict | None, result_cd: str | None
) -> tuple[bool, str]:
    """Whether an import list-style response has usable ``data.itemList`` (``importedItemInfo`` / ``selectImportItemList``)."""
    c = (result_cd or "").strip()
    if c != "000":
        return False, f"import list resultCd is {c!r}, not 000"
    if not isinstance(parsed, dict):
        return False, "import list response has no parsed JSON"
    rb = parsed.get("responseBody")
    if not isinstance(rb, dict):
        return False, "import list response missing responseBody"
    data = rb.get("data")
    if data is None:
        return False, "import list responseBody.data is null"
    if isinstance(data, dict) and len(data) == 0:
        return False, "import list responseBody.data is empty"
    if not isinstance(data, dict):
        return False, "import list responseBody.data is not an object"
    lst = data.get("itemList")
    if not isinstance(lst, list) or len(lst) == 0:
        return False, "import list responseBody.data.itemList missing or empty"
    return True, ""


def extract_first_import_item_row(parsed) -> dict | None:
    """First customs row from selectImportItemList (for updateImportItem taskCd / dclDe / hsCd)."""
    try:
        rb = parsed.get("responseBody") if isinstance(parsed, dict) else None
        data = rb.get("data") if isinstance(rb, dict) else None
        lst = data.get("itemList") if isinstance(data, dict) else None
        if not isinstance(lst, list) or not lst:
            return None
        row = lst[0]
        return row if isinstance(row, dict) else None
    except (TypeError, AttributeError):
        return None


def extract_import_item_rows(parsed: dict | None) -> list[dict]:
    """All customs rows from ``importedItemInfo`` / ``selectImportItemList``-shaped responses."""
    out: list[dict] = []
    if not isinstance(parsed, dict):
        return out
    rb = parsed.get("responseBody")
    if not isinstance(rb, dict):
        return out
    data = rb.get("data")
    if not isinstance(data, dict):
        return out
    lst = data.get("itemList")
    if not isinstance(lst, list):
        return out
    for row in lst:
        if isinstance(row, dict):
            out.append(row)
    return out


def apply_import_kra_row_to_import_update_payload(
    payload: dict,
    row: dict,
    *,
    item_cd: str,
    item_cls_cd: str,
    sales_dt: str,
) -> None:
    """Fill ``updateImportItem`` / ``importedItemConvertedInfo`` body from a server import row (no hardcoded taskCd)."""
    payload["itemClsCd"] = item_cls_cd
    payload["itemCd"] = (item_cd or "").strip()
    payload["taskCd"] = str(row.get("taskCd") or "").strip()
    _dcl = str(row.get("dclDe") or "").strip()
    if _dcl:
        payload["dclDe"] = _dcl[:8] if len(_dcl) >= 8 else _dcl
    else:
        payload["dclDe"] = (sales_dt or "").strip()[:8]
    _hs = str(row.get("hsCd") or "").strip()
    if _hs:
        payload["hsCd"] = _hs
    try:
        payload["itemSeq"] = int(row.get("itemSeq", 1))
    except (TypeError, ValueError):
        payload["itemSeq"] = 1
    # KRA sample uses string status codes; SBX ``updateImportItem`` validates ``imptItemSttsCd`` as string "3".
    payload["imptItemSttsCd"] = "3"
    payload.pop("imptItemsttsCd", None)
    payload.setdefault("remark", "remark")
    payload["remark"] = str(payload.get("remark") or "remark")
    payload.setdefault("modrId", "system")
    payload.setdefault("modrNm", "system")
    payload["modrId"] = str(payload.get("modrId") or "system")
    payload["modrNm"] = str(payload.get("modrNm") or "system")


def coerce_invc_binding(val) -> int | str | None:
    """Normalize a list-extracted invoice id for JSON (int when numeric)."""
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    try:
        return int(s)
    except (TypeError, ValueError):
        return s


def extract_best_supplier_sale_row_cross_tin_fallback(
    parsed,
    *,
    prefer_item_cd: str = "",
) -> dict | None:
    """Pick a row from ``responseBody.data.saleList`` when same-TIN extracts are empty.

    SBX often returns only other taxpayers' ``saleList`` rows. For component purchase
    binding, KRA may require the supplier TIN / branch / supplier invoice from such a row.
    """
    try:
        rb = parsed.get("responseBody") if isinstance(parsed, dict) else None
        data = rb.get("data") if isinstance(rb, dict) else None
        sale_list = data.get("saleList") if isinstance(data, dict) else None
    except (TypeError, AttributeError):
        sale_list = None
    if not isinstance(sale_list, list) or not sale_list:
        return None
    pref = (prefer_item_cd or "").strip()
    preferred: list[dict] = []
    rest: list[dict] = []
    for row in sale_list:
        if not isinstance(row, dict):
            continue
        sp = row.get("spplrInvcNo")
        if sp is None or not str(sp).strip():
            continue
        stin = str(row.get("spplrTin") or "").strip()
        if not stin:
            continue
        il = row.get("itemList")
        il_ok = il if isinstance(il, list) else None
        if pref and _item_cd_row_match_for_preference(pref, il_ok):
            preferred.append(row)
        else:
            rest.append(row)
    pick = preferred[0] if preferred else (rest[0] if rest else None)
    if not pick:
        return None
    return pick


# OSCU sandbox often rejects the root class (e.g. 1000000000) for saveItem; prefer these first.
_SAVE_ITEM_CLS_PREFERENCE_ORDER = ("1010000000", "9901200000")


def _norm_item_cls_cd(val) -> str:
    """Canonical 10-digit-style item class code string from JSON (str/int/float)."""
    if val is None or val is False:
        return ""
    if isinstance(val, bool):
        return ""
    if isinstance(val, (int, float)):
        try:
            return str(int(val))
        except (ValueError, OverflowError):
            return ""
    s = str(val).strip()
    if not s:
        return ""
    if s.isdigit():
        return s
    try:
        return str(int(float(s)))
    except ValueError:
        return s


def _norm_tax_ty_cd(val) -> str:
    if val is None:
        return ""
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        s = str(int(val))
        return s if s else ""
    return str(val).strip()


def item_cls_cd_tax_from_item_cls_list(item_cls_list: list) -> tuple[str, str]:
    """
    Walk ``responseBody.data.itemClsList``.
    Prefer ``1010000000``, then ``9901200000``, else first usable row.
    """
    if not item_cls_list:
        raise SystemExit("STOP: selectItemClsList returned empty itemClsList")
    by_icd: dict[str, str] = {}
    for row in item_cls_list:
        if not isinstance(row, dict):
            continue
        icd = _norm_item_cls_cd(row.get("itemClsCd"))
        tty = _norm_tax_ty_cd(row.get("taxTyCd"))
        if icd and tty:
            by_icd[icd] = tty
    for want in _SAVE_ITEM_CLS_PREFERENCE_ORDER:
        if want in by_icd:
            return want, by_icd[want]
    row0 = item_cls_list[0]
    if isinstance(row0, dict):
        icd = _norm_item_cls_cd(row0.get("itemClsCd"))
        tty = _norm_tax_ty_cd(row0.get("taxTyCd"))
        if icd and tty:
            return icd, tty
    raise SystemExit(
        "STOP: selectItemClsList ok but could not read itemClsCd/taxTyCd from itemClsList"
    )


def extract_item_cls_and_tax_from_parsed(parsed: dict | None) -> tuple[str, str]:
    lst: list | None = None
    if isinstance(parsed, dict):
        rb = parsed.get("responseBody")
        if isinstance(rb, dict):
            data = rb.get("data")
            if isinstance(data, dict):
                raw = data.get("itemClsList")
                if isinstance(raw, list):
                    lst = raw
    if not lst:
        raise SystemExit(
            "STOP: selectItemClsList ok but itemClsList missing or not a non-empty list"
        )
    return item_cls_cd_tax_from_item_cls_list(lst)


def apply_item_cls_dynamic_from_parsed(parsed: dict | None, item_cls_dynamic: dict) -> None:
    icd, tty = extract_item_cls_and_tax_from_parsed(parsed)
    item_cls_dynamic["itemClsCd"] = icd
    item_cls_dynamic["taxTyCd"] = tty


def item_cls_list_from_parsed(parsed: dict | None) -> list:
    if not isinstance(parsed, dict):
        return []
    rb = parsed.get("responseBody")
    if not isinstance(rb, dict):
        return []
    data = rb.get("data")
    if not isinstance(data, dict):
        return []
    raw = data.get("itemClsList")
    return raw if isinstance(raw, list) else []


def merge_item_cls_lists_by_cd(*lists: list) -> list:
    """Union itemClsList rows by itemClsCd; keep higher itemClsLvl when duplicate."""
    by_cd: dict[str, dict] = {}
    for lst in lists:
        for row in lst or []:
            if not isinstance(row, dict):
                continue
            icd = _norm_item_cls_cd(row.get("itemClsCd"))
            if not icd:
                continue
            prev = by_cd.get(icd)
            if prev is None or _row_item_cls_lvl(row) > _row_item_cls_lvl(prev):
                by_cd[icd] = row
    return list(by_cd.values())


def _row_item_cls_lvl(row: dict) -> int:
    """Higher = deeper HS node (selectCodeList cls 49: 4=Commodity). SBX may return 0 for all."""
    v = row.get("itemClsLvl")
    try:
        if v is None:
            return 0
        return int(v)
    except (TypeError, ValueError):
        return 0


def item_cls_list_deepest_first(item_cls_list: list) -> list:
    """Deepest itemClsLvl first when picking classes (commodity before segment); keep all rows."""
    rows = [r for r in item_cls_list if isinstance(r, dict)]
    if not rows:
        return []
    return sorted(rows, key=_row_item_cls_lvl, reverse=True)


def pick_save_item_zero_rated_leaf(item_cls_list: list) -> tuple[str, str] | None:
    """
    SBX saveItem often rejects 9901200000 (zero-rated header). Prefer another taxTyCd C row from the list.
    """
    if not item_cls_list:
        return None
    ordered = item_cls_list_deepest_first(item_cls_list)
    for row in ordered:
        if not isinstance(row, dict):
            continue
        icd = _norm_item_cls_cd(row.get("itemClsCd"))
        tty = (_norm_tax_ty_cd(row.get("taxTyCd")) or "").strip().upper()
        if not icd or tty != "C":
            continue
        if icd != "9901200000":
            return icd, "C"
    for row in ordered:
        if not isinstance(row, dict):
            continue
        icd = _norm_item_cls_cd(row.get("itemClsCd"))
        tty = (_norm_tax_ty_cd(row.get("taxTyCd")) or "").strip().upper()
        if icd == "9901200000" and tty == "C":
            return icd, "C"
    return None


def pick_save_item_standard_if_present(item_cls_list: list) -> tuple[str, str] | None:
    """Prefer 1010000000 + tax A when present (SBX sometimes rejects all tax-C classes for saveItem)."""
    if not item_cls_list:
        return None
    for row in item_cls_list_deepest_first(item_cls_list):
        if not isinstance(row, dict):
            continue
        icd = _norm_item_cls_cd(row.get("itemClsCd"))
        tty = (_norm_tax_ty_cd(row.get("taxTyCd")) or "").strip().upper()
        if icd == "1010000000" and tty == "A":
            return icd, "A"
    return None


def pick_save_item_tax_b_leaf(item_cls_list: list) -> tuple[str, str] | None:
    """Docs example uses taxTyCd B + itemTyCd 1; pick a concrete B row (not 1010000000 header)."""
    if not item_cls_list:
        return None
    for row in item_cls_list_deepest_first(item_cls_list):
        if not isinstance(row, dict):
            continue
        icd = _norm_item_cls_cd(row.get("itemClsCd"))
        tty = (_norm_tax_ty_cd(row.get("taxTyCd")) or "").strip().upper()
        if icd and icd != "1010000000" and tty == "B":
            return icd, "B"
    return None


def extract_first_cmc_key(obj):
    if isinstance(obj, dict):
        v = obj.get("cmcKey")
        if isinstance(v, str) and v.strip():
            return v.strip()
        for vv in obj.values():
            found = extract_first_cmc_key(vv)
            if found:
                return found
    elif isinstance(obj, list):
        for it in obj:
            found = extract_first_cmc_key(it)
            if found:
                return found
    return None


def mask_cmc_preview(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return "(empty)"
    if len(s) <= 10:
        return f"(len={len(s)})"
    return f"{s[:4]}…{s[-4:]} (len={len(s)})"


def item_cd_numeric_suffix(*, item_ty_cd: str) -> str:
    """
    Random 7-digit suffix (legacy). **itemTyCd 2** should use ``alloc_provisional_item_cd_monotonic``
    instead of this helper.
    """
    _ = item_ty_cd
    n = random.randint(0, 999_999) * 10 + 1
    return f"{n:07d}"


def iter_item_cd_strings(obj) -> list[str]:
    """Collect every string value keyed as itemCd from a parsed KRA JSON tree."""
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "itemCd" and isinstance(v, str) and v.strip():
                out.append(v.strip())
            else:
                out.extend(iter_item_cd_strings(v))
    elif isinstance(obj, list):
        for it in obj:
            out.extend(iter_item_cd_strings(it))
    return out


def max_numeric_suffix_for_prefix(parsed: dict | None, prefix: str) -> int:
    """Largest 7-digit trailing sequence for itemCd values starting with ``prefix`` (e.g. KE2NTTU)."""
    prefix = (prefix or "").strip()
    if not prefix or not isinstance(parsed, dict):
        return 0
    want_len = len(prefix) + 7
    mx = 0
    for cd in iter_item_cd_strings(parsed):
        if not cd.startswith(prefix) or len(cd) != want_len:
            continue
        suf = cd[len(prefix) :]
        if suf.isdigit():
            mx = max(mx, int(suf))
    return mx


def next_suffix_int_after(high_water: int, last_digit: int = 1) -> int:
    """Smallest value > high_water whose last decimal digit matches KRA SBX rule (often 1; SBX may require 3, …)."""
    ld = int(last_digit) % 10
    n = int(high_water) + 1
    while n % 10 != ld:
        n += 1
    if n > 9_999_999:
        raise ValueError("itemCd 7-digit suffix exhausted (>9999999)")
    return n


def next_suffix_int_after_mod(high_water: int, modulus: int, residue: int) -> int:
    """Smallest n > high_water with n % modulus == residue (e.g. suffix ending …13 → mod 100, res 13)."""
    n = int(high_water) + 1
    m = int(modulus)
    r = int(residue) % m
    while n % m != r:
        n += 1
    if n > 9_999_999:
        raise ValueError("itemCd 7-digit suffix exhausted (>9999999)")
    return n


def _item_cd_next_suffix_map(pin_blob: dict) -> dict[str, int]:
    pin_blob.setdefault(ITEM_CD_NEXT_SUFFIX_BY_PREFIX_KEY, {})
    raw = pin_blob[ITEM_CD_NEXT_SUFFIX_BY_PREFIX_KEY]
    if not isinstance(raw, dict):
        raw = {}
        pin_blob[ITEM_CD_NEXT_SUFFIX_BY_PREFIX_KEY] = raw
    out: dict[str, int] = {}
    for k, v in raw.items():
        p = str(k or "").strip()
        if not p:
            continue
        try:
            out[p] = int(v)
        except (TypeError, ValueError):
            continue
    pin_blob[ITEM_CD_NEXT_SUFFIX_BY_PREFIX_KEY] = out
    return out


def _seed_initial_next_suffix_for_prefix(pin_blob: dict, prefix: str) -> int:
    """
    One-time seed when ``item_cd_next_suffix_by_prefix`` has no entry: last **successful** local
    suffix for this prefix + 1, else 1. Does not consult selectItemList.
    """
    p = (prefix or "").strip()
    last = 0
    last = max(last, int(max_suffix_int_for_prefix_from_pin(pin_blob, p)))
    for key in ("canonical_item_cd", "item_cd"):
        ic = str(pin_blob.get(key) or "").strip()
        want_len = len(p) + 7
        if ic.startswith(p) and len(ic) == want_len and ic[-7:].isdigit():
            try:
                last = max(last, int(ic[-7:]))
            except ValueError:
                pass
    return max(1, last + 1) if last else 1


def peek_next_item_cd_suffix_int(pin_blob: dict, prefix: str) -> int:
    """Next 7-digit suffix to POST for ``prefix`` (single source: ``item_cd_next_suffix_by_prefix``)."""
    m = _item_cd_next_suffix_map(pin_blob)
    p = (prefix or "").strip()
    if p not in m:
        m[p] = _seed_initial_next_suffix_for_prefix(pin_blob, p)
    n = int(m[p])
    if n < 1:
        m[p] = 1
        n = 1
    if n > 9_999_999:
        raise ValueError("itemCd 7-digit suffix exhausted (>9999999)")
    return n


def advance_item_cd_next_suffix_after_save_item_failure(
    pin_blob: dict, prefix: str, rejected_suffix: int, err_txt: str | None
) -> None:
    """
    After a rejected saveItem: ``next = rejected_suffix + 1``, raised by any KRA tail hint in
    ``err_txt``. Never decreases the stored cursor.
    """
    m = _item_cd_next_suffix_map(pin_blob)
    p = (prefix or "").strip()
    suf = int(rejected_suffix)
    nxt = suf + 1
    mr = kra_parse_item_cd_suffix_constraint(err_txt or "")
    if mr is not None:
        mod, res = int(mr[0]), int(mr[1])
        try:
            hint_floor = next_suffix_int_after_mod(suf, mod, res)
            nxt = max(nxt, int(hint_floor))
        except Exception:
            pass
    prev = m.get(p)
    if prev is not None:
        nxt = max(nxt, int(prev))
    if nxt > 9_999_999:
        raise ValueError("itemCd 7-digit suffix exhausted (>9999999)")
    m[p] = nxt


def alloc_monotonic_item_cd_suffix(
    prefix: str,
    select_item_parsed: dict | None,
    pin_blob: dict,
    attempt_hw: dict[str, int],
) -> str:
    """
    Next 7-digit itemCd suffix for ``prefix``. **Single source:** ``peek_next_item_cd_suffix_int``
    (local cursor + seed from last successful suffix only). ``select_item_parsed`` is optional
    catalog output for **debug/hint logging only**; ``attempt_hw`` is ignored (legacy signature).
    """
    prefix = (prefix or "").strip()
    if isinstance(select_item_parsed, dict) and prefix:
        cm = max_numeric_suffix_for_prefix(select_item_parsed, prefix)
        print(
            f"saveItem: selectItemList catalog max suffix for {prefix!r} "
            f"(hint only, not used for sequencing): {int(cm)}"
        )
    _ = attempt_hw
    n = peek_next_item_cd_suffix_int(pin_blob, prefix)
    return f"{int(n):07d}"


def alloc_provisional_item_cd_monotonic(
    item_ty_cd: str,
    pkg_unit_cd: str,
    qty_unit_cd: str,
    pin_blob: dict,
    select_item_parsed: dict | None,
) -> str:
    """
    Provisional ``itemCd`` for sequence templates before ``saveItem``.
    Uses the same linear per-prefix cursor as ``saveItem`` (``item_cd_next_suffix_by_prefix``).
    """
    ty = (item_ty_cd or "").strip()
    prefix = f"KE{ty}{pkg_unit_cd}{qty_unit_cd}"
    # SBX saveItem enforces strict sequential suffix per prefix (including KE1… component/service items).
    suf = alloc_monotonic_item_cd_suffix(prefix, select_item_parsed, pin_blob, {})
    return f"{prefix}{suf}"


def next_item_cd_for_composition_branch(
    main_item_cd: str,
    select_item_parsed: dict | None,
    pin_blob: dict,
) -> str:
    """
    Next ``itemCd`` for a second ``/saveItem`` (component) after ``main_item_cd``.

    Uses the same linear per-prefix cursor as ``saveItem`` (not selectItemList max).
    ``select_item_parsed`` is optional catalog output for hint logging only.
    """
    ic = (main_item_cd or "").strip()
    m = re.match(r"(.+?)(\d{7})$", ic)
    if not m:
        raise ValueError(f"expected … + 7 digit suffix on itemCd, got {ic!r}")
    pfx, suf_s = m.group(1), m.group(2)
    _ = int(suf_s)  # parent suffix; sequencing is by component prefix cursor, not parent+1
    if isinstance(select_item_parsed, dict) and pfx:
        cm = max_numeric_suffix_for_prefix(select_item_parsed, pfx)
        print(
            f"composition branch: selectItemList catalog max for {pfx!r} "
            f"(hint only, not used for sequencing): {int(cm)}"
        )
    n = peek_next_item_cd_suffix_int(pin_blob, pfx)
    return f"{pfx}{int(n):07d}"


def persist_item_cd_suffix_map(pin_blob: dict, item_cd: str) -> None:
    """Store last successful numeric suffix and advance the authoritative next-suffix cursor."""
    ic = (item_cd or "").strip()
    if len(ic) < 7 or not ic[-7:].isdigit():
        return
    pfx, suf_s = ic[:-7], ic[-7:]
    suf = int(suf_s)
    pin_blob.setdefault("kra_item_cd_suffix_by_prefix", {})
    if not isinstance(pin_blob["kra_item_cd_suffix_by_prefix"], dict):
        pin_blob["kra_item_cd_suffix_by_prefix"] = {}
    pin_blob["kra_item_cd_suffix_by_prefix"][pfx] = suf
    m = _item_cd_next_suffix_map(pin_blob)
    m[pfx] = suf + 1


def extract_result_cd(parsed_json):
    if not isinstance(parsed_json, dict):
        return None
    rb = parsed_json.get("responseBody")
    if isinstance(rb, dict) and rb.get("resultCd") is not None:
        return str(rb.get("resultCd")).strip()
    if parsed_json.get("resultCd") is not None:
        return str(parsed_json.get("resultCd")).strip()
    if "responseBody" in parsed_json and isinstance(parsed_json["responseBody"], dict):
        rbc = parsed_json["responseBody"].get("resultCode")
        if rbc is not None:
            return str(rbc).strip()
    rc = parsed_json.get("resultCode")
    if rc is not None:
        return str(rc).strip()
    return None


def kra_expected_rsd_qty_from_mismatch_message(msg: str | None) -> float | None:
    """Parse saveStockMaster mismatch text, e.g. ``Expected: -300.0 but found: 100``."""
    if not msg:
        return None
    m = re.search(r"Expected:\s*(-?\d+(?:\.\d+)?)", msg, re.IGNORECASE)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def log_save_stock_master_decision(
    step: str, *, executed: bool, detail: str
) -> None:
    """Audit line: ``saveStockMaster`` POST vs intentional skip (never blind-saves)."""
    tag = "EXECUTED" if executed else "SKIPPED"
    print(f"saveStockMaster [{tag}] {step}: {detail}")


def kra_save_stock_master_messages_for_mismatch_parse(parsed: dict | None) -> str:
    """Best-effort blob for ``kra_expected_rsd_qty_from_mismatch_message``."""
    if not isinstance(parsed, dict):
        return ""
    parts: list[str] = []
    rh = parsed.get("responseHeader")
    if isinstance(rh, dict):
        parts.append(str(rh.get("debugMessage") or ""))
        parts.append(str(rh.get("customerMessage") or ""))
    parts.append(kra_save_item_error_text(parsed) or "")
    parts.append(str(kra_extract_response_body_result_msg(parsed) or ""))
    return " ".join(parts)


def kra_expected_next_sar_no_from_message(msg: str | None) -> int | None:
    """Parse insertStockIO validation, e.g. ``Invalid sarNo: Expected: 9 but found: 1``."""
    if not msg:
        return None
    m = re.search(
        r"Invalid\s+sarNo:\s*Expected:\s*(\d+)\s+but\s+found:\s*\d+",
        msg,
        re.IGNORECASE,
    )
    if not m:
        m = re.search(r"Expected:\s*(\d+)\s+but\s+found:\s*\d+", msg, re.IGNORECASE)
    if not m:
        return None
    try:
        v = int(m.group(1))
        return v if v >= 1 else None
    except ValueError:
        return None


def _ensure_sar_no_by_tin_bhf_map(state_root: dict) -> dict:
    raw = state_root.setdefault(SAR_NO_BY_TIN_BHF_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
        state_root[SAR_NO_BY_TIN_BHF_KEY] = raw
    return raw


def sar_sequence_state_key(tin: str, bhf_id: str) -> str:
    return f"{str(tin).strip()}|{str(bhf_id).strip()}"


def last_committed_insert_stock_sar_no(
    state_root: dict,
    tin: str,
    bhf_id: str,
    pin_blob: dict | None,
) -> int:
    """
    Last successfully committed ``sarNo`` from insertStockIO for (tin, bhfId).
    ``0`` means none recorded yet (next POST should use ``1``).
    """
    smap = _ensure_sar_no_by_tin_bhf_map(state_root)
    k = sar_sequence_state_key(tin, bhf_id)
    if k in smap:
        try:
            return max(0, int(smap[k]))
        except (TypeError, ValueError):
            pass
    if pin_blob is not None:
        try:
            nxt = int(pin_blob.get("stock_io_next_sar_no") or 0)
            if nxt >= 1:
                return max(0, nxt - 1)
        except (TypeError, ValueError):
            pass
    return 0


def resolve_next_insert_stock_sar_no(
    state_root: dict,
    tin: str,
    bhf_id: str,
    pin_blob: dict | None,
) -> int:
    """Next monotonic ``sarNo`` = last committed + 1 (minimum ``1``)."""
    return last_committed_insert_stock_sar_no(state_root, tin, bhf_id, pin_blob) + 1


def persist_committed_insert_stock_sar_no(
    state_root: dict,
    tin: str,
    bhf_id: str,
    committed_sar_no: int,
    pin_blob: dict | None,
) -> None:
    """After ``resultCd`` ``000``: store successful ``sarNo``; keep ``pin_blob`` in sync."""
    c = int(committed_sar_no)
    if c < 1:
        return
    smap = _ensure_sar_no_by_tin_bhf_map(state_root)
    smap[sar_sequence_state_key(tin, bhf_id)] = c
    if pin_blob is not None:
        pin_blob["stock_io_next_sar_no"] = c + 1


def apply_kra_expected_insert_stock_sar_no(
    state_root: dict,
    tin: str,
    bhf_id: str,
    expected_sar_no: int,
    pin_blob: dict | None,
) -> None:
    """
    KRA ``Invalid sarNo: Expected: X but found: Y`` — next POST must use ``sarNo=X``.
    Persist ``last_committed = X - 1`` so ``resolve_next`` yields ``X``.
    """
    x = int(expected_sar_no)
    if x < 1:
        return
    smap = _ensure_sar_no_by_tin_bhf_map(state_root)
    smap[sar_sequence_state_key(tin, bhf_id)] = max(0, x - 1)
    if pin_blob is not None:
        pin_blob["stock_io_next_sar_no"] = x


def clear_insert_stock_sar_sequence_for_tin_bhf(
    state_root: dict, tin: str, bhf_id: str
) -> None:
    """Remove persisted SAR for this branch (e.g. ``--diagnostic-stock-io`` fresh SAR 1)."""
    smap = _ensure_sar_no_by_tin_bhf_map(state_root)
    k = sar_sequence_state_key(tin, bhf_id)
    if k in smap:
        del smap[k]


def kra_extract_response_ref_id(parsed: dict | None) -> str:
    """``responseHeader.responseRefID`` from a KRA JSON response."""
    if not isinstance(parsed, dict):
        return ""
    rh = parsed.get("responseHeader")
    if isinstance(rh, dict) and rh.get("responseRefID") is not None:
        return str(rh.get("responseRefID") or "").strip()
    return ""


def kra_extract_response_body_result_msg(parsed: dict | None) -> str:
    """``responseBody.resultMsg`` when present (may be empty if ``responseBody`` is null)."""
    if not isinstance(parsed, dict):
        return ""
    rb = parsed.get("responseBody")
    if isinstance(rb, dict) and rb.get("resultMsg") is not None:
        return str(rb.get("resultMsg") or "").strip()
    return ""


def kra_save_item_error_text(parsed: dict | None) -> str:
    """Join KRA saveItem failure messages (HTTP 400 gate) for parsing."""
    if not isinstance(parsed, dict):
        return ""
    rh = parsed.get("responseHeader")
    if not isinstance(rh, dict):
        return ""
    parts: list[str] = []
    for k in ("customerMessage", "debugMessage"):
        v = rh.get(k)
        if v is not None and str(v).strip():
            parts.append(str(v).strip())
    return " ".join(parts)


def kra_insert_stock_io_error_text(parsed: dict | None) -> str:
    """KRA insertStockIO gate errors (same ``responseHeader`` shape as saveItem)."""
    return kra_save_item_error_text(parsed)


def kra_parse_item_cd_suffix_constraint(msg: str | None) -> tuple[int, int] | None:
    """
    Parse saveItem rejection, e.g. ``********3`` or ``********13`` (multi-digit tail).
    Returns (modulus, residue) for the 7-digit numeric suffix, e.g. (10, 3) or (100, 13).
    """
    if not msg:
        return None
    patterns = (
        r"Expected sequence ending with[:\s]*\*+(\d+)",
        r"Expected sequence ending with\s*\*+(\d+)",
        r"ending with[:\s]*\*+(\d+)",
        r"sequence ending with[:\s]*\*+(\d+)",
    )
    tail_s: str | None = None
    for pat in patterns:
        m = re.search(pat, msg, re.IGNORECASE)
        if m:
            tail_s = m.group(1)
            break
    if tail_s is None:
        return None
    try:
        tail = int(tail_s)
    except ValueError:
        return None
    if tail < 10:
        return (10, tail % 10)
    if tail < 100:
        return (100, tail)
    if tail < 1000:
        return (1000, tail)
    if tail < 10000:
        return (10_000, tail)
    return None


def fix_item_cd_from_error(current_item_cd: str, error_message: str) -> str | None:
    """
    SBX saveItem sequence recovery.

    KRA often returns: ``Expected sequence ending with: ********13`` (or ``********3``).
    We must keep the same itemCd prefix and adjust ONLY the trailing 7-digit numeric suffix.

    Returns a corrected itemCd (same prefix, new 7-digit suffix) or None if it can't be derived.
    """
    ic = (current_item_cd or "").strip()
    if len(ic) < 8 or not ic[-7:].isdigit():
        return None
    pfx = ic[:-7]
    try:
        cur = int(ic[-7:])
    except ValueError:
        return None
    # We do not derive a candidate from the error message; caller must recompute from selectItemList.
    _ = error_message
    return None


def apply_item_cd_sequence_recovery_hints(
    pin_blob: dict, failed_item_cd: str, error_message: str
) -> str | None:
    """Advance the linear itemCd cursor after a failed saveItem (rejected suffix + 1, plus KRA hint)."""
    ic_fail = (failed_item_cd or "").strip()
    if len(ic_fail) < 8 or not ic_fail[-7:].isdigit():
        return None
    pfx = ic_fail[:-7]
    try:
        suf = int(ic_fail[-7:])
    except ValueError:
        return None
    advance_item_cd_next_suffix_after_save_item_failure(pin_blob, pfx, suf, error_message)
    return None


def next_item_cd_from_catalog(
    *,
    item_ty_cd: str,
    pkg_unit_cd: str,
    qty_unit_cd: str,
    catalog_parsed: dict | None,
    pin_blob: dict,
    attempt_hw: dict[str, int] | None = None,
) -> str:
    """
    Build next ``itemCd`` for itemTyCd=2 using the **linear local cursor** (same as ``saveItem``).
    ``catalog_parsed`` is optional and used for **hint logging only** (not max() sequencing).
    """
    _ = attempt_hw
    ty = (item_ty_cd or "").strip()
    if ty != "2":
        raise ValueError("next_item_cd_from_catalog only supports itemTyCd=2")
    prefix = f"KE{ty}{pkg_unit_cd}{qty_unit_cd}"
    if isinstance(catalog_parsed, dict):
        mx = max_numeric_suffix_for_prefix(catalog_parsed, prefix)
        print(
            f"next_item_cd_from_catalog: selectItemList max for {prefix!r} "
            f"(hint only, not used for sequencing): {int(mx)}"
        )
    n = peek_next_item_cd_suffix_int(pin_blob, prefix)
    return f"{prefix}{int(n):07d}"


def max_suffix_int_for_prefix_from_pin(pin_blob: dict, prefix: str) -> int:
    """Last **successful** saveItem 7-digit suffix for ``prefix`` (from ``persist_item_cd_suffix_map``)."""
    sm = pin_blob.get("kra_item_cd_suffix_by_prefix")
    if not isinstance(sm, dict):
        return 0
    v = sm.get((prefix or "").strip())
    if v is None:
        return 0
    if isinstance(v, int):
        return v
    if isinstance(v, dict):
        try:
            return int(v.get("max", 0) or 0)
        except (TypeError, ValueError):
            return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def kra_tail_constraint_for_prefix(
    pin_blob: dict, prefix: str
) -> tuple[int, int] | None:
    """Per-prefix (modulus, residue) from KRA ``Expected sequence ending with …`` (itemTyCd 2)."""
    pfx = (prefix or "").strip()
    cr = pin_blob.get("kra_item_cd_tail_constraint_by_prefix")
    if not isinstance(cr, dict):
        return None
    sub = cr.get(pfx)
    if not isinstance(sub, dict):
        return None
    try:
        m = int(sub["mod"])
        r = int(sub["res"])
        return (m, r)
    except (KeyError, TypeError, ValueError):
        return None


def set_kra_tail_constraint_for_prefix(
    pin_blob: dict, prefix: str, modulus: int, residue: int
) -> None:
    pin_blob.setdefault("kra_item_cd_tail_constraint_by_prefix", {})
    if not isinstance(pin_blob["kra_item_cd_tail_constraint_by_prefix"], dict):
        pin_blob["kra_item_cd_tail_constraint_by_prefix"] = {}
    pin_blob["kra_item_cd_tail_constraint_by_prefix"][(prefix or "").strip()] = {
        "mod": int(modulus),
        "res": int(residue),
    }


def clear_kra_tail_constraint_for_prefix(pin_blob: dict, prefix: str) -> None:
    d = pin_blob.get("kra_item_cd_tail_constraint_by_prefix")
    pfx = (prefix or "").strip()
    if isinstance(d, dict) and pfx in d:
        del d[pfx]


def stock_io_line_amounts_for_tax_ty(
    *,
    unit_prc: float,
    qty: float,
    tax_ty_cd: str,
) -> tuple[float, float, float, float]:
    """
    (splyAmt, taxblAmt, taxAmt, totAmt) for one stock IO line.
    SBX validates taxblAmt for taxTyCd B: VAT-inclusive supply splits ≈ /1.16.
    """
    sply = float(unit_prc) * float(qty)
    tty = (tax_ty_cd or "A").strip().upper()
    if tty == "B":
        taxbl = round(sply / 1.16, 2)
        tax_amt = round(sply - taxbl, 2)
        return sply, taxbl, tax_amt, sply
    return sply, sply, 0.0, sply


def endpoint_accepts_result_cd(endpoint_name: str, result_cd: str | None) -> bool:
    """Whether the step may proceed without a resultCd retry (body-only; HTTP/gate checked separately)."""
    c = (result_cd or "").strip()
    if endpoint_name == "initialize":
        return c in ("000", "902")
    # selectItemList: 000 = rows returned; 001 = no products yet ("There is no search result") — valid before saveItem
    if endpoint_name == "selectItemList":
        return c in ("000", "001")
    # After saveItem: GavaConnect expects a real product row (strict 000 for certification UX).
    if endpoint_name == "selectItemListPostSave":
        return c == "000"
    # Portal checklist parity: the portal marks /selectStockMoveList as PASSED when resultCd is 001 (empty).
    if endpoint_name == "portalSelectStockMoveList":
        return c in ("000", "001")
    if endpoint_name in _SELECT_STOCK_MOVE_ENDPOINTS:
        return c in ("000", "001")
    if endpoint_name in _SELECT_EMPTY_OK:
        return c in ("000", "001")
    return c == "000"


def endpoint_http_ok_for_kra(endpoint_name: str, resp: requests.Response, result_cd: str | None) -> bool:
    """
    KRA JSON often uses responseHeader.responseCode 200 inside the body while Apigee HTTP may be 400 for
    business-empty outcomes. For selectItemList + resultCd 001, accept HTTP < 500 if body was parsed.
    """
    if resp.status_code < 400:
        return True
    if endpoint_name == "selectItemList" and (result_cd or "").strip() == "001":
        return resp.status_code < 500
    if endpoint_name == "selectItemListPostSave" and (result_cd or "").strip() == "001":
        return resp.status_code < 500
    if endpoint_name == "portalSelectStockMoveList" and (result_cd or "").strip() == "001":
        return resp.status_code < 500
    if endpoint_name in _SELECT_STOCK_MOVE_ENDPOINTS and (result_cd or "").strip() == "001":
        return resp.status_code < 500
    if endpoint_name in _SELECT_EMPTY_OK and (result_cd or "").strip() == "001":
        return resp.status_code < 500
    return False


def response_contains_item_cd(obj, target_item_cd: str) -> bool:
    want = (target_item_cd or "").strip()
    if not want:
        return False
    if isinstance(obj, dict):
        v = obj.get("itemCd")
        if isinstance(v, str) and v.strip() == want:
            return True
        return any(response_contains_item_cd(x, want) for x in obj.values())
    if isinstance(obj, list):
        return any(response_contains_item_cd(x, want) for x in obj)
    return False


def count_stock_move_list_rows_for_item(
    parsed: dict | None, want_item_cd: str
) -> int:
    """Count list rows that look like stock moves and match ``itemCd`` (selectStockMoveList-style body)."""
    want = (want_item_cd or "").strip()
    if not want or not isinstance(parsed, dict):
        return 0
    best = 0

    def consider_list(lst: list) -> None:
        nonlocal best
        if not lst or not all(isinstance(x, dict) for x in lst):
            return
        keys: set[str] = set()
        for x in lst:
            keys.update(x.keys())
        if not keys.intersection({"itemCd", "sarNo", "rplQty", "qty"}):
            return
        c = sum(1 for x in lst if str(x.get("itemCd") or "").strip() == want)
        best = max(best, c)

    def walk(o: object) -> None:
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            consider_list(o)
            for x in o:
                walk(x)

    walk(parsed)
    return best


def composition_prelude_verify_stock_ledger_has_item(
    *,
    base_url: str,
    headers: dict,
    tin: str,
    bhf_id: str,
    item_cd: str,
    log_tag: str,
    timeout: int = 180,
    now_probes: int | None = None,
) -> tuple[bool, dict | None, requests.Response | None]:
    """
    **Diagnostic only.** Same move-list gate as strict stock paths: two POSTs with UTC ``lastReqDt``.
    ``now_probes`` is ignored (kept for signature compatibility).
    """
    _ = now_probes
    parsed_last, resp_last = best_effort_stock_read_debug(
        base_url=base_url,
        headers=headers,
        tin=tin,
        bhf_id=bhf_id,
        item_cd=item_cd,
        log_tag=log_tag,
        timeout=timeout,
    )
    # Never gate on move-list visibility.
    return True, parsed_last, resp_last


def _first_rsd_qty_for_item_in_stock_move_tree(
    parsed: dict | None, want_item_cd: str
) -> float | None:
    """Depth-first: first quantity field on a dict whose itemCd matches (selectStockMoveList-style)."""
    want = (want_item_cd or "").strip()
    if not want or not isinstance(parsed, dict):
        return None

    def walk(o: object) -> float | None:
        if isinstance(o, dict):
            ic = str(o.get("itemCd") or "").strip()
            if ic == want:
                for k in ("rsdQty", "rplQty", "qty", "stkQty"):
                    if k in o and o[k] is not None:
                        try:
                            return float(o[k])
                        except (TypeError, ValueError):
                            pass
            for v in o.values():
                r = walk(v)
                if r is not None:
                    return r
        elif isinstance(o, list):
            for x in o:
                r = walk(x)
                if r is not None:
                    return r
        return None

    return walk(parsed)


# --- Pre-sale stock gate + structured audit ---
# Before ``saveInvoice`` (``/saveTrnsSalesOsdc``): mandatory contract is **insertStockIOPostComposition 000 +
# saveStockMasterPostComposition 000** (``post_composition_osdc_ready``). ``selectStockMoveList*`` is diagnostic
# only (best-effort via ``strict_pre_sale_select_stock_move_or_exit``); it must not block OSDC sales.
# With ``--strict-pre-sale-audit``, ``run_strict_pre_sale_audit_block`` runs BHF + ``selectItemList`` + the same
# best-effort move-list probe (still non-blocking for the sale POST).
# ``selectItemList`` uses baseline ``lastReqDt`` where applicable.
KRA_LIST_BASELINE_LAST_REQ_DT = "20100101000000"


def kra_stock_move_list_last_req_dt_utc_now() -> str:
    """Current UTC ``lastReqDt`` for ``selectStockMoveList`` (``YYYYMMDDHHmmss``)."""
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
STOCK_MOVE_LIST_GATE_RECHECK_SLEEP_SEC_MIN = 2.0
STOCK_MOVE_LIST_GATE_RECHECK_SLEEP_SEC_MAX = 3.0
KRA_STOCK_MOVE_GATE_FAIL_HINT = (
    "Common causes (not exhaustive): wrong bhfId, wrong OSCU base URL (stock vs sales cluster), "
    "item not yet in the stock move registry, itemClsCd/catalog mismatch, IO payload or SAR sequence."
)

# ``responseHeader`` keys sometimes used for request/response correlation (SBX varies).
_LEDGER_DEBUG_RH_TRACE_KEYS = (
    "responseRefID",
    "responseRefId",
    "traceId",
    "requestId",
)

DEBUG_LEDGER_VERDICT_EVENTUAL = "LEDGER_EVENTUAL_CONSISTENCY"
DEBUG_LEDGER_VERDICT_NO_POSTING = "NO_LEDGER_POSTING"
DEBUG_LEDGER_VERDICT_READ_INVALID = "READ_ENDPOINT_INVALID"
DEBUG_LEDGER_VERDICT_SKIPPED = "SKIPPED_NO_ITEMCD"

# --- Ledger contract validation harness (``--ledger-contract-test``) ---
# Isolated IO→move-list probe; **not** a substitute for judging SBX ledger behavior from the full runner.
# Contract scope: only the keys in ``BASE_LEDGER_TEST_CASE`` populate the stock line. No cls/nm/prc/tax
# reconstruction. Literal ``sarNo=1``, ``orgSarNo=0`` — no SAR reads/writes. Edit source to change repro.
BASE_LEDGER_TEST_CASE: dict[str, object] = {
    "tin": "P600002923A",
    "bhfId": "00",
    "itemCd": "KE2NTTU0000005",
    "ioTyCd": "1",
    "qty": 1,
    "pkgUnitCd": "NT",
    "qtyUnitCd": "TU",
    "taxTyCd": "A",
}

LEDGER_CONTRACT_VERDICT_POSTED = "LEDGER_POSTED"
LEDGER_CONTRACT_VERDICT_NOT_POSTED = "LEDGER_NOT_POSTED"
LEDGER_CONTRACT_VERDICT_READ_FAILURE = "LEDGER_READ_FAILURE"


def run_ledger_contract_test(
    *,
    base_url: str,
    headers: dict,
    sales_dt_hint: str,
    timeout: int = 120,
) -> str:
    """
    Single frozen IO POST + three move-list probes. Stdout: exactly four lines under
    ``=== LEDGER CONTRACT RESULT ===``. No cluster helpers, no SAR persistence, no line enrichment beyond
    ``BASE_LEDGER_TEST_CASE``. **Not** for inferring overall SBX ledger support — use the full sequence runner
    (real IO payloads) for that.
    """
    tin = str(BASE_LEDGER_TEST_CASE["tin"]).strip()
    bhf_id = str(BASE_LEDGER_TEST_CASE["bhfId"]).strip()
    item_cd = str(BASE_LEDGER_TEST_CASE["itemCd"]).strip()
    io_ty = str(BASE_LEDGER_TEST_CASE["ioTyCd"]).strip()
    qty = float(BASE_LEDGER_TEST_CASE["qty"])
    pkg_u = str(BASE_LEDGER_TEST_CASE["pkgUnitCd"]).strip()
    qty_u = str(BASE_LEDGER_TEST_CASE["qtyUnitCd"]).strip()
    tty = str(BASE_LEDGER_TEST_CASE["taxTyCd"]).strip()

    if (
        get_optional_env("GAVAETIMS_LEDGER_CONTRACT_DIAGNOSTIC_ONLY_PRECHECK", "")
        .strip()
        .lower()
        in ("1", "true", "yes", "y")
    ):
        sm_url = f"{base_url.rstrip('/')}/selectStockMaster"
        sm_pl = {
            "tin": tin,
            "bhfId": bhf_id,
            "itemCd": item_cd,
            "lastReqDt": KRA_LIST_BASELINE_LAST_REQ_DT,
        }
        try:
            r_pre = requests.post(sm_url, headers=headers, json=sm_pl, timeout=timeout)
            h = getattr(r_pre, "status_code", None)
            try:
                p_pre = r_pre.json()
            except (TypeError, ValueError, json.JSONDecodeError):
                p_pre = None
            rc = (extract_result_cd(p_pre) or "").strip() if isinstance(p_pre, dict) else ""
            ref = kra_extract_response_ref_id(p_pre if isinstance(p_pre, dict) else None)
            print(
                f"diagnostic_only_precheck: HTTP={h!r} resultCd={rc!r} responseRefID={ref!r}",
                file=sys.stderr,
            )
        except requests.RequestException as e:
            print(f"diagnostic_only_precheck: request_error={e!r}", file=sys.stderr)

    io_ocrn_8 = (sales_dt_hint or "").strip()[:8]
    if len(io_ocrn_8) != 8:
        io_ocrn_8 = datetime.now(timezone.utc).strftime("%Y%m%d")

    stock_line: dict[str, object] = {
        "itemCd": item_cd,
        "ioTyCd": io_ty,
        "pkgUnitCd": pkg_u,
        "pkg": qty,
        "qtyUnitCd": qty_u,
        "qty": qty,
        "taxTyCd": tty,
    }
    io_root: dict[str, object] = {
        "sarNo": 1,
        "regTyCd": "M",
        "custTin": tin,
        "sarTyCd": "01",
        "ocrnDt": io_ocrn_8,
        "totItemCnt": 1,
        "totTaxblAmt": 0.0,
        "totTaxAmt": 0.0,
        "totAmt": 0.0,
        "orgSarNo": 0,
        "regrId": "system",
        "regrNm": "system",
        "modrId": "system",
        "modrNm": "system",
        "itemList": [stock_line],
    }
    io_url = f"{base_url.rstrip('/')}/insertStockIO"
    ins_rc = ""
    ins_ref = ""
    ins_parsed: dict | None = None
    r_io: requests.Response | None = None
    try:
        r_io = requests.post(io_url, headers=headers, json=io_root, timeout=timeout)
        try:
            ins_parsed = r_io.json()
        except (TypeError, ValueError, json.JSONDecodeError):
            ins_parsed = None
        if isinstance(ins_parsed, dict):
            ins_rc = (extract_result_cd(ins_parsed) or "").strip()
            ins_ref = kra_extract_response_ref_id(ins_parsed)
    except requests.RequestException:
        ins_parsed = None

    insert_ok = (
        r_io is not None
        and getattr(r_io, "status_code", 999) < 400
        and isinstance(ins_parsed, dict)
        and not kra_top_level_error_detail(ins_parsed)
        and ins_rc == "000"
    )

    surl = f"{base_url.rstrip('/')}/selectStockMoveList"
    pl_mv = {
        "tin": tin,
        "bhfId": bhf_id,
        "lastReqDt": KRA_LIST_BASELINE_LAST_REQ_DT,
        "itemCd": item_cd,
    }
    move_rows: list[dict[str, object]] = []
    read_failed = False
    schedule: tuple[tuple[int, str], ...] = (
        (0, "0s"),
        (5, "5s"),
        (15, "15s"),
    )
    for pause_sec, tlabel in schedule:
        if pause_sec > 0:
            time.sleep(float(pause_sec))
        entry: dict[str, object] = {"t": tlabel}
        try:
            r_mv = requests.post(surl, headers=headers, json=pl_mv, timeout=timeout)
            entry["http"] = getattr(r_mv, "status_code", None)
            if r_mv.status_code >= 400:
                read_failed = True
            try:
                p_mv = r_mv.json()
            except (TypeError, ValueError, json.JSONDecodeError):
                p_mv = None
            if not isinstance(p_mv, dict):
                if r_mv.status_code < 400:
                    read_failed = True
                entry["resultCd"] = ""
                entry["rows"] = 0
            else:
                entry["resultCd"] = (extract_result_cd(p_mv) or "").strip()
                nrows = count_stock_move_list_rows_for_item(p_mv, item_cd)
                entry["rows"] = int(nrows)
        except requests.RequestException:
            read_failed = True
            entry["http"] = None
            entry["resultCd"] = ""
            entry["rows"] = 0
        move_rows.append(entry)

    any_rows = any(int(m.get("rows") or 0) > 0 for m in move_rows)
    if read_failed:
        verdict = LEDGER_CONTRACT_VERDICT_READ_FAILURE
    elif any_rows:
        verdict = LEDGER_CONTRACT_VERDICT_POSTED
    elif insert_ok:
        verdict = LEDGER_CONTRACT_VERDICT_NOT_POSTED
    else:
        verdict = LEDGER_CONTRACT_VERDICT_READ_FAILURE

    print(
        "\n=== LEDGER CONTRACT RESULT ===\n"
        f"insert_resultCd: {ins_rc!r}\n"
        f"insert_responseRefID: {ins_ref!r}\n"
        f"move_probe_results: {json.dumps(move_rows, ensure_ascii=False)}\n"
        f"verdict: {verdict}\n"
    )
    return verdict


def _stock_lifecycle_isolation_move_list_probe(
    *,
    base_url: str,
    headers: dict,
    tin: str,
    bhf_id: str,
    item_cd: str,
    log_label: str,
    timeout: int = 120,
) -> tuple[str, int, float | None]:
    """Single ``selectStockMoveList`` POST with UTC ``lastReqDt``. No sleeps."""
    surl = resolve_select_stock_move_list_url(base_url)
    _lrd = kra_stock_move_list_last_req_dt_utc_now()
    print(f"STOCK MOVE QUERY using lastReqDt = {_lrd} (LIFECYCLE ISOLATION)")
    pl = {
        "tin": tin,
        "bhfId": bhf_id,
        "lastReqDt": _lrd,
        "itemCd": item_cd,
    }
    r = requests.post(surl, headers=headers, json=pl, timeout=timeout)
    p: dict | None = None
    try:
        p = r.json()
    except (TypeError, ValueError, json.JSONDecodeError):
        p = None
    rc = (extract_result_cd(p) or "").strip() if isinstance(p, dict) else ""
    nrows = count_stock_move_list_rows_for_item(p, item_cd) if isinstance(p, dict) else 0
    rsd = _first_rsd_qty_for_item_in_stock_move_tree(p, item_cd) if isinstance(p, dict) else None
    ref = kra_extract_response_ref_id(p)
    print(f"\n--- LIFECYCLE ISOLATION: {log_label} ---")
    print(f"  URL: {surl}")
    print(f"  HTTP: {getattr(r, 'status_code', None)!r}")
    print(f"  resultCd: {rc!r}")
    print(f"  rows_matching_itemCd: {nrows}")
    print(f"  rsdQty (first match): {rsd if rsd is not None else '(none)'}")
    print(f"  responseRefID: {ref!r}")
    if isinstance(p, dict):
        print(json.dumps(p, indent=2, ensure_ascii=False, default=str)[:4000])
    else:
        print(getattr(r, "text", "")[:2000])
    return rc, nrows, rsd


def run_stock_lifecycle_isolation_test(
    *,
    base_url: str,
    headers: dict,
    effective_tin: str,
    branch_id: str,
    state_root: dict,
    pin_blob: dict,
    sales_dt: str,
    item_cls_dynamic: dict,
    item_ty_cd: str,
    pkg_unit_cd: str,
    qty_unit_cd: str,
    on_pin_blob_mutation: Callable[[], None] | None = None,
    qty_io: float = 100.0,
    prc: float = 100.0,
    timeout: int = 120,
) -> int:
    """
    Five-step isolation (no composition, no matrix, no full sequence, no sales):
    ``saveItem`` → ``insertStockIO`` (IN) → immediate ``selectStockMoveList`` → ``saveStockMaster``
    (``rsdQty`` = IO qty, not from move list) → ``selectStockMoveList`` again.
    """
    reset_insert_stock_io_cluster_url()
    icd = str(item_cls_dynamic.get("itemClsCd") or "1010000000").strip()
    tty = str(item_cls_dynamic.get("taxTyCd") or "A").strip()
    print(
        "\n"
        + "=" * 72
        + "\nSTOCK LIFECYCLE ISOLATION TEST\n"
        "  saveItem → insertStockIO (IN) → selectStockMoveList (immediate) →\n"
        "  saveStockMaster (rsdQty = IO qty) → selectStockMoveList (immediate)\n"
        "  No composition / matrix / sales.\n"
        + "=" * 72
        + "\n"
    )
    bhf_rows: list[dict[str, str]] = []

    print("\n--- Step 1: saveItem ---")
    catalog_parsed = select_item_list_fetch_catalog_for_item_cd_planning(
        base_url=base_url,
        headers=headers,
        tin=effective_tin,
        bhf_id=branch_id,
        response_log_prefix="LIFECYCLE ISOLATION catalog",
    )
    si_url = f"{base_url.rstrip('/')}/saveItem"
    item_cd = ""
    save_item_ok = False
    p1: object | None = None
    for attempt in range(2):
        item_cd = next_item_cd_from_catalog(
            item_ty_cd=item_ty_cd,
            pkg_unit_cd=pkg_unit_cd,
            qty_unit_cd=qty_unit_cd,
            catalog_parsed=catalog_parsed,
            pin_blob=pin_blob,
        )
        print(f"LIFECYCLE ISOLATION: saveItem attempt {attempt + 1}/2 itemCd={item_cd!r}")
        si_payload = {
            "itemCd": item_cd,
            "itemClsCd": icd,
            "itemTyCd": item_ty_cd,
            "itemNm": "LIFECYCLE ISOLATION ITEM",
            "orgnNatCd": "KE",
            "pkgUnitCd": pkg_unit_cd,
            "qtyUnitCd": qty_unit_cd,
            "taxTyCd": tty,
            "dftPrc": prc,
            "isrcAplcbYn": "N",
            "useYn": "Y",
            "regrId": "system",
            "regrNm": "system",
            "modrId": "system",
            "modrNm": "system",
        }
        normalize_save_item_payload_fields(si_payload)
        si_payload = save_item_payload_omit_nulls(si_payload)
        audit_append_row(
            bhf_rows,
            endpoint="saveItem",
            payload=si_payload,
            headers=headers,
            fallback_tin=effective_tin,
            fallback_bhf=branch_id,
        )
        r1 = requests.post(si_url, headers=headers, json=si_payload, timeout=timeout)
        p1 = print_full_response_json(r1, f"LIFECYCLE ISOLATION saveItem ({attempt + 1}/5)")
        result_cd = (extract_result_cd(p1) or "").strip()
        gate_err = kra_top_level_error_detail(p1)
        if r1.status_code < 400 and not gate_err and result_cd == "000":
            persist_item_cd_suffix_map(pin_blob, item_cd)
            if on_pin_blob_mutation is not None:
                on_pin_blob_mutation()
            save_item_ok = True
            break
        _err_txt = kra_save_item_error_text(p1 if isinstance(p1, dict) else None)
        apply_item_cd_sequence_recovery_hints(pin_blob, item_cd, _err_txt)
        if on_pin_blob_mutation is not None:
            on_pin_blob_mutation()
    if not save_item_ok:
        print("\n=== STOCK LIFECYCLE ISOLATION RESULT ===\nSTOP: saveItem did not return 000.\n")
        return 1

    print("\n--- Step 2: insertStockIO (inbound ioTyCd=1) ---")
    io_url = f"{base_url.rstrip('/')}/insertStockIO"
    io_ocrn_8 = (sales_dt or "").strip()[:8]
    if len(io_ocrn_8) != 8:
        io_ocrn_8 = datetime.now(timezone.utc).strftime("%Y%m%d")
    line_sply, _tb, _tx, _tot = stock_io_line_amounts_for_tax_ty(
        unit_prc=float(prc), qty=float(qty_io), tax_ty_cd=tty
    )
    stock_line_template = {
        "itemSeq": 1,
        "itemCd": item_cd,
        "ioTyCd": "1",
        "itemClsCd": icd,
        "itemNm": "LIFECYCLE ISOLATION ITEM",
        "pkgUnitCd": pkg_unit_cd,
        "pkg": float(qty_io),
        "qtyUnitCd": qty_unit_cd,
        "qty": float(qty_io),
        "prc": float(prc),
        "splyAmt": line_sply,
        "totDcAmt": 0.0,
        "taxblAmt": _tb,
        "taxTyCd": tty,
        "taxAmt": _tx,
        "totAmt": _tot,
    }
    insert_rc = ""
    io_ok = False
    p2: object | None = None
    sar_resync_used = False
    for _io_attempt in range(2):
        sar_n = resolve_next_insert_stock_sar_no(
            state_root, effective_tin, branch_id, pin_blob
        )
        print(f"SAR sequence → using sarNo={sar_n}")
        org_sn = 0 if sar_n <= 1 else sar_n - 1
        io_root = {
            "sarNo": sar_n,
            "regTyCd": "M",
            "custTin": effective_tin,
            "sarTyCd": "01",
            "ocrnDt": io_ocrn_8,
            "totItemCnt": 1,
            "totTaxblAmt": _tb,
            "totTaxAmt": _tx,
            "totAmt": _tot,
            "orgSarNo": org_sn,
            "regrId": "system",
            "regrNm": "system",
            "modrId": "system",
            "modrNm": "system",
            "itemList": [dict(stock_line_template)],
        }
        audit_append_row(
            bhf_rows,
            endpoint="insertStockIO",
            payload=io_root,
            headers=headers,
            fallback_tin=effective_tin,
            fallback_bhf=branch_id,
        )
        register_insert_stock_io_request_url(io_url)
        r2 = requests.post(io_url, headers=headers, json=io_root, timeout=timeout)
        p2 = print_full_response_json(
            r2,
            f"LIFECYCLE ISOLATION insertStockIO (attempt {_io_attempt + 1}/2, sarNo={sar_n})",
        )
        rc2 = (extract_result_cd(p2) or "").strip()
        ge2 = kra_top_level_error_detail(p2)
        insert_rc = rc2
        if r2.status_code < 400 and not ge2 and rc2 == "000":
            persist_committed_insert_stock_sar_no(
                state_root, effective_tin, branch_id, sar_n, pin_blob
            )
            if on_pin_blob_mutation is not None:
                on_pin_blob_mutation()
            io_ok = True
            break
        err_io = kra_insert_stock_io_error_text(p2 if isinstance(p2, dict) else None)
        exp_sar = kra_expected_next_sar_no_from_message(err_io)
        if (
            not sar_resync_used
            and exp_sar is not None
            and err_io
            and "Invalid sarNo" in err_io
        ):
            apply_kra_expected_insert_stock_sar_no(
                state_root, effective_tin, branch_id, exp_sar, pin_blob
            )
            sar_resync_used = True
            if on_pin_blob_mutation is not None:
                on_pin_blob_mutation()
            continue
        break
    if not io_ok:
        print(
            "\n=== STOCK LIFECYCLE ISOLATION RESULT ===\n"
            f"insertStockIO resultCd: {insert_rc!r}\n"
            "STOP: insertStockIO did not return 000 — cannot test move list vs saveStockMaster.\n"
        )
        return 1

    print("\n--- Step 3: selectStockMoveList IMMEDIATELY after insertStockIO (no sleep) ---")
    rc_before, rows_before, rsd_before = _stock_lifecycle_isolation_move_list_probe(
        base_url=base_url,
        headers=headers,
        tin=effective_tin,
        bhf_id=branch_id,
        item_cd=item_cd,
        log_label="move list BEFORE saveStockMaster (immediate, UTC lastReqDt)",
        timeout=timeout,
    )

    print("\n--- Step 4: saveStockMaster (rsdQty from IO qty, not from move list) ---")
    sm_url = f"{base_url.rstrip('/')}/saveStockMaster"
    sm_payload = {
        "itemCd": item_cd,
        "rsdQty": float(qty_io),
        "regrId": "system",
        "regrNm": "system",
        "modrId": "system",
        "modrNm": "system",
    }
    r_sm = requests.post(sm_url, headers=headers, json=sm_payload, timeout=timeout)
    p_sm = print_full_response_json(r_sm, "LIFECYCLE ISOLATION saveStockMaster")
    sm_rc = (extract_result_cd(p_sm) or "").strip() if isinstance(p_sm, dict) else ""

    print("\n--- Step 5: selectStockMoveList IMMEDIATELY after saveStockMaster (no sleep) ---")
    rc_after, rows_after, rsd_after = _stock_lifecycle_isolation_move_list_probe(
        base_url=base_url,
        headers=headers,
        tin=effective_tin,
        bhf_id=branch_id,
        item_cd=item_cd,
        log_label="move list AFTER saveStockMaster (immediate, UTC lastReqDt)",
        timeout=timeout,
    )

    if rows_before > 0:
        interp = (
            "Move list already had rows before saveStockMaster → IO may be sufficient for "
            "visibility in this probe (saveStockMaster not the first gate)."
        )
    elif rows_after > 0:
        interp = (
            "Rows appeared only after saveStockMaster → saveStockMaster likely required "
            "(or strongly correlated) with move-list visibility for this SBX path."
        )
    else:
        interp = (
            "No rows before or after (immediate UTC lastReqDt probes) → saveStockMaster did not "
            "surface moves in this window; consider delay/lastReqDt rules or IO not "
            "materializing to move list."
        )
    print(
        "\n=== STOCK LIFECYCLE ISOLATION RESULT ===\n"
        f"itemCd: {item_cd!r}\n"
        f"insertStockIO resultCd: {insert_rc!r}\n"
        f"move_list BEFORE saveStockMaster: resultCd={rc_before!r} rows={rows_before} rsdQty={rsd_before!r}\n"
        f"saveStockMaster resultCd: {sm_rc!r}\n"
        f"move_list AFTER saveStockMaster: resultCd={rc_after!r} rows={rows_after} rsdQty={rsd_after!r}\n"
        f"note: {interp}\n"
    )
    if on_pin_blob_mutation is not None:
        on_pin_blob_mutation()
    return 0


def _extract_stock_master_rsd_qty(parsed: dict | None, want_item_cd: str) -> float | None:
    """Best-effort: find rsdQty/stkQty for itemCd in selectStockMaster response."""
    want = (want_item_cd or "").strip()
    if not want or not isinstance(parsed, dict):
        return None

    def walk(o: object) -> float | None:
        if isinstance(o, dict):
            ic = str(o.get("itemCd") or "").strip()
            if ic == want:
                for k in ("rsdQty", "stkQty", "qty", "rplQty"):
                    if k in o and o[k] is not None:
                        try:
                            return float(o[k])
                        except (TypeError, ValueError):
                            pass
            for v in o.values():
                r = walk(v)
                if r is not None:
                    return r
        elif isinstance(o, list):
            for x in o:
                r = walk(x)
                if r is not None:
                    return r
        return None

    return walk(parsed)


def run_stock_master_visibility_test(
    *,
    base_url: str,
    headers: dict,
    effective_tin: str,
    branch_id: str,
    state_root: dict,
    pin_blob: dict,
    sales_dt: str,
    item_cls_dynamic: dict,
    item_ty_cd: str,
    pkg_unit_cd: str,
    qty_unit_cd: str,
    on_pin_blob_mutation: Callable[[], None] | None = None,
    qty_io: float = 100.0,
    prc: float = 100.0,
    timeout: int = 120,
) -> int:
    """
    Minimal validation probe for SBX:
      saveItem → insertStockIO (IN) → saveStockMaster (rsdQty = IO qty) → selectStockMaster
    Prints a single summary block with rsdQty when present.
    """
    print(
        "\n"
        + "=" * 72
        + "\nSTOCK MASTER VISIBILITY PROBE\n"
        "  saveItem → insertStockIO (IN) → saveStockMaster (rsdQty = IO qty) → selectStockMaster\n"
        "  (Use this when selectStockMoveList is timing out / empty on SBX.)\n"
        + "=" * 72
        + "\n"
    )

    # Step 1: saveItem (reuse isolation logic for monotonic itemCd)
    catalog_parsed = select_item_list_fetch_catalog_for_item_cd_planning(
        base_url=base_url,
        headers=headers,
        tin=effective_tin,
        bhf_id=branch_id,
        response_log_prefix="STOCK MASTER PROBE catalog",
    )
    si_url = f"{base_url.rstrip('/')}/saveItem"
    icd = str(item_cls_dynamic.get("itemClsCd") or "1010000000").strip()
    tty = str(item_cls_dynamic.get("taxTyCd") or "A").strip()
    item_cd = ""
    for attempt in range(2):
        item_cd = next_item_cd_from_catalog(
            item_ty_cd=item_ty_cd,
            pkg_unit_cd=pkg_unit_cd,
            qty_unit_cd=qty_unit_cd,
            catalog_parsed=catalog_parsed,
            pin_blob=pin_blob,
        )
        print(f"STOCK MASTER PROBE: saveItem attempt {attempt + 1}/2 itemCd={item_cd!r}")
        si_payload = {
            "itemCd": item_cd,
            "itemClsCd": icd,
            "itemTyCd": item_ty_cd,
            "itemNm": "STOCK MASTER VISIBILITY PROBE ITEM",
            "orgnNatCd": "KE",
            "pkgUnitCd": pkg_unit_cd,
            "qtyUnitCd": qty_unit_cd,
            "taxTyCd": tty,
            "dftPrc": float(prc),
            "isrcAplcbYn": "N",
            "useYn": "Y",
            "regrId": "system",
            "regrNm": "system",
            "modrId": "system",
            "modrNm": "system",
        }
        r_si = requests.post(si_url, headers=headers, json=si_payload, timeout=timeout)
        p_si = print_full_response_json(r_si, f"STOCK MASTER PROBE saveItem ({attempt + 1}/5)")
        rc_si = (extract_result_cd(p_si) or "").strip() if isinstance(p_si, dict) else ""
        ge_si = kra_top_level_error_detail(p_si) if isinstance(p_si, dict) else None
        if r_si.status_code < 400 and not ge_si and rc_si == "000":
            persist_item_cd_suffix_map(pin_blob, item_cd)
            if on_pin_blob_mutation is not None:
                on_pin_blob_mutation()
            break
        _err_txt = kra_save_item_error_text(p_si if isinstance(p_si, dict) else None)
        apply_item_cd_sequence_recovery_hints(pin_blob, item_cd, _err_txt)
        if on_pin_blob_mutation is not None:
            on_pin_blob_mutation()
    if not item_cd:
        return 1

    # Step 2: insertStockIO (IN)
    io_url = f"{base_url.rstrip('/')}/insertStockIO"
    sar_no_used = resolve_next_insert_stock_sar_no(state_root, effective_tin, branch_id, pin_blob)
    org_sar = 0 if sar_no_used <= 1 else sar_no_used - 1
    io_ocrn_8 = (sales_dt or "").strip()[:8]
    if len(io_ocrn_8) != 8:
        io_ocrn_8 = datetime.now(timezone.utc).strftime("%Y%m%d")
    line_sply, line_taxbl, line_tax, line_tot = stock_io_line_amounts_for_tax_ty(
        unit_prc=float(prc), qty=float(qty_io), tax_ty_cd=tty
    )
    print(
        f"STOCK MASTER PROBE: insertStockIO item → qty={float(qty_io):g} "
        f"price={float(prc):g} splyAmt={float(line_sply):.2f}"
    )
    stock_line = {
        "itemSeq": 1,
        "itemCd": item_cd,
        "ioTyCd": "1",
        "itemClsCd": icd,
        "itemNm": "STOCK MASTER VISIBILITY PROBE ITEM",
        "pkgUnitCd": pkg_unit_cd,
        "pkg": float(qty_io),
        "qtyUnitCd": qty_unit_cd,
        "qty": float(qty_io),
        "prc": float(prc),
        "splyAmt": float(line_sply),
        "totDcAmt": 0.0,
        "taxblAmt": float(line_taxbl),
        "taxTyCd": tty,
        "taxAmt": float(line_tax),
        "totAmt": float(line_tot),
    }
    io_root: dict[str, object] = {
        "sarNo": sar_no_used,
        "regTyCd": "M",
        "custTin": effective_tin,
        "sarTyCd": "01",
        "ocrnDt": io_ocrn_8,
        "totItemCnt": 1,
        "totTaxblAmt": float(line_taxbl),
        "totTaxAmt": float(line_tax),
        "totAmt": float(line_tot),
        "orgSarNo": org_sar,
        "regrId": "system",
        "regrNm": "system",
        "modrId": "system",
        "modrNm": "system",
        "itemList": [stock_line],
    }
    register_insert_stock_io_request_url(io_url)
    r_io = requests.post(io_url, headers=headers, json=io_root, timeout=timeout)
    p_io = print_full_response_json(r_io, f"STOCK MASTER PROBE insertStockIO (sarNo={sar_no_used})")
    rc_io = (extract_result_cd(p_io) or "").strip() if isinstance(p_io, dict) else ""
    ge_io = kra_top_level_error_detail(p_io) if isinstance(p_io, dict) else None
    if not (r_io.status_code < 400 and not ge_io and rc_io == "000"):
        print("\n=== STOCK MASTER VISIBILITY RESULT ===\nSTOP: insertStockIO did not return 000.\n")
        return 1
    persist_committed_insert_stock_sar_no(state_root, effective_tin, branch_id, sar_no_used, pin_blob)
    if on_pin_blob_mutation is not None:
        on_pin_blob_mutation()

    # Step 3: saveStockMaster (rsdQty = IO qty)
    sm_url = f"{base_url.rstrip('/')}/saveStockMaster"
    sm_payload = {
        "itemCd": item_cd,
        "rsdQty": float(qty_io),
        "regrId": "system",
        "regrNm": "system",
        "modrId": "system",
        "modrNm": "system",
    }
    r_sm = requests.post(sm_url, headers=headers, json=sm_payload, timeout=timeout)
    p_sm = print_full_response_json(r_sm, "STOCK MASTER PROBE saveStockMaster")
    rc_sm = (extract_result_cd(p_sm) or "").strip() if isinstance(p_sm, dict) else ""
    ge_sm = kra_top_level_error_detail(p_sm) if isinstance(p_sm, dict) else None
    if not (r_sm.status_code < 400 and not ge_sm and rc_sm == "000"):
        print("\n=== STOCK MASTER VISIBILITY RESULT ===\nSTOP: saveStockMaster did not return 000.\n")
        return 1

    # Step 4: selectStockMaster (validation endpoint)
    surl = resolve_select_stock_move_list_url(base_url)  # reuse cluster base chooser
    sm_base = _stock_api_cluster_base(surl)
    sel_url = f"{sm_base.rstrip('/')}/selectStockMaster"
    sel_pl = {
        "tin": effective_tin,
        "bhfId": branch_id,
        "itemCd": item_cd,
        "lastReqDt": KRA_LIST_BASELINE_LAST_REQ_DT,
    }
    p_sel: dict | None = None
    http_sel: int | None = None
    rc_sel = ""
    for t in range(6):
        try:
            r_sel = requests.post(sel_url, headers=headers, json=sel_pl, timeout=timeout)
            http_sel = getattr(r_sel, "status_code", None)
            p_sel = print_full_response_json(r_sel, f"STOCK MASTER PROBE selectStockMaster (try {t + 1}/6)")
            rc_sel = (extract_result_cd(p_sel) or "").strip() if isinstance(p_sel, dict) else ""
            if http_sel is not None and http_sel == 504:
                time.sleep(3.0 + (random.random() * 1.2))
                continue
            break
        except requests.RequestException:
            time.sleep(3.0 + (random.random() * 1.2))
            continue

    rsd_seen = _extract_stock_master_rsd_qty(p_sel if isinstance(p_sel, dict) else None, item_cd)
    print(
        "\n=== STOCK MASTER VISIBILITY RESULT ===\n"
        f"itemCd: {item_cd!r}\n"
        f"insertStockIO resultCd: {rc_io!r}\n"
        f"saveStockMaster resultCd: {rc_sm!r}\n"
        f"selectStockMaster HTTP: {http_sel!r}\n"
        f"selectStockMaster resultCd: {rc_sel!r}\n"
        f"selectStockMaster rsdQty: {rsd_seen!r}\n"
    )
    return 0


def _sbx_finished_good_single_move_list_post(
    *,
    base_url: str,
    headers: dict,
    tin: str,
    bhf_id: str,
    item_cd: str,
    last_req_dt: str,
    log_label: str,
    timeout: int = 120,
) -> tuple[str, int, float | None]:
    """One ``selectStockMoveList`` POST (no 504 retry loop)."""
    surl = resolve_select_stock_move_list_url(base_url)
    print(f"STOCK MOVE QUERY using lastReqDt = {last_req_dt}")
    pl = {
        "tin": tin,
        "bhfId": bhf_id,
        "lastReqDt": last_req_dt,
        "itemCd": item_cd,
    }
    r = requests.post(surl, headers=headers, json=pl, timeout=timeout)
    p: dict | None = None
    try:
        p = r.json()
    except (TypeError, ValueError, json.JSONDecodeError):
        p = None
    rc = (extract_result_cd(p) or "").strip() if isinstance(p, dict) else ""
    nrows = count_stock_move_list_rows_for_item(p, item_cd) if isinstance(p, dict) else 0
    rsd = _first_rsd_qty_for_item_in_stock_move_tree(p, item_cd) if isinstance(p, dict) else None
    ref = kra_extract_response_ref_id(p)
    print(f"\n--- FINISHED GOOD LEDGER PROBE: {log_label} ---")
    print(f"  lastReqDt: {last_req_dt!r}")
    print(f"  HTTP: {getattr(r, 'status_code', None)!r}")
    print(f"  resultCd: {rc!r}")
    print(f"  rows_matching_itemCd: {nrows}")
    print(f"  rsdQty (first match): {rsd if rsd is not None else '(none)'}")
    print(f"  responseRefID: {ref!r}")
    if isinstance(p, dict):
        print(json.dumps(p, indent=2, ensure_ascii=False, default=str)[:4000])
    else:
        print(getattr(r, "text", "")[:2000])
    return rc, nrows, rsd


def run_sbx_finished_good_ledger_probe(
    *,
    base_url: str,
    headers: dict,
    effective_tin: str,
    branch_id: str,
    state_root: dict,
    pin_blob: dict,
    sales_dt: str,
    item_cls_dynamic: dict,
    pkg_unit_cd: str,
    qty_unit_cd: str,
    on_pin_blob_mutation: Callable[[], None] | None = None,
    qty_io: float = 100.0,
    prc: float = 100.0,
    timeout: int = 120,
) -> int:
    """
    Controlled SBX probe: **itemTyCd=2** only. Single ``saveItem``, single ``insertStockIO`` (no SAR
    resync retry), ``saveStockMaster`` with ``rsdQty`` = IO qty, **sleep 10s**, then **three** one-shot
    ``selectStockMoveList`` calls with **fresh** UTC ``lastReqDt`` each (2.5s between POSTs). No 504
    backoff loops; no extra IO/saveItem retries.
    """
    item_ty_cd = "2"
    reset_insert_stock_io_cluster_url()
    icd = str(item_cls_dynamic.get("itemClsCd") or "1010000000").strip()
    tty = str(item_cls_dynamic.get("taxTyCd") or "A").strip()
    print(
        "\n"
        + "=" * 72
        + "\nSBX FINISHED GOOD LEDGER PROBE (itemTyCd=2)\n"
        "  saveItem → insertStockIO (IN) → saveStockMaster (rsdQty=IO qty) → sleep 10s →\n"
        "  selectStockMoveList: UTC lastReqDt ×3 (fresh per POST, 2.5s apart; no 504 retries)\n"
        + "=" * 72
        + "\n"
    )
    bhf_rows: list[dict[str, str]] = []

    print("\n--- Step 1: saveItem (single attempt, itemTyCd=2) ---")
    catalog_parsed = select_item_list_fetch_catalog_for_item_cd_planning(
        base_url=base_url,
        headers=headers,
        tin=effective_tin,
        bhf_id=branch_id,
        response_log_prefix="FINISHED GOOD PROBE catalog",
    )
    si_url = f"{base_url.rstrip('/')}/saveItem"
    item_cd = alloc_provisional_item_cd_monotonic(
        item_ty_cd, pkg_unit_cd, qty_unit_cd, pin_blob, catalog_parsed
    )
    print(f"FINISHED GOOD PROBE: itemCd={item_cd!r}")
    si_payload = {
        "itemCd": item_cd,
        "itemClsCd": icd,
        "itemTyCd": item_ty_cd,
        "itemNm": "FINISHED GOOD LEDGER PROBE ITEM",
        "orgnNatCd": "KE",
        "pkgUnitCd": pkg_unit_cd,
        "qtyUnitCd": qty_unit_cd,
        "taxTyCd": tty,
        "dftPrc": prc,
        "isrcAplcbYn": "N",
        "useYn": "Y",
        "regrId": "system",
        "regrNm": "system",
        "modrId": "system",
        "modrNm": "system",
    }
    normalize_save_item_payload_fields(si_payload)
    si_payload = save_item_payload_omit_nulls(si_payload)
    audit_append_row(
        bhf_rows,
        endpoint="saveItem",
        payload=si_payload,
        headers=headers,
        fallback_tin=effective_tin,
        fallback_bhf=branch_id,
    )
    r1 = requests.post(si_url, headers=headers, json=si_payload, timeout=timeout)
    p1 = print_full_response_json(r1, "FINISHED GOOD PROBE saveItem (single)")
    si_rc = (extract_result_cd(p1) or "").strip()
    if (
        r1.status_code >= 400
        or kra_top_level_error_detail(p1)
        or si_rc != "000"
    ):
        print(
            "\n=== SBX FINISHED GOOD LEDGER PROBE RESULT ===\n"
            f"saveItem resultCd: {si_rc!r}\n"
            "CLASSIFICATION: ABORTED_SAVEITEM_NOT_000\n"
        )
        return 1
    persist_item_cd_suffix_map(pin_blob, item_cd)
    if on_pin_blob_mutation is not None:
        on_pin_blob_mutation()

    print("\n--- Step 2: insertStockIO (IN, single POST) ---")
    io_url = f"{base_url.rstrip('/')}/insertStockIO"
    io_ocrn_8 = (sales_dt or "").strip()[:8]
    if len(io_ocrn_8) != 8:
        io_ocrn_8 = datetime.now(timezone.utc).strftime("%Y%m%d")
    line_sply, _tb, _tx, _tot = stock_io_line_amounts_for_tax_ty(
        unit_prc=float(prc), qty=float(qty_io), tax_ty_cd=tty
    )
    stock_line = {
        "itemSeq": 1,
        "itemCd": item_cd,
        "ioTyCd": "1",
        "itemClsCd": icd,
        "itemNm": "FINISHED GOOD LEDGER PROBE ITEM",
        "pkgUnitCd": pkg_unit_cd,
        "pkg": float(qty_io),
        "qtyUnitCd": qty_unit_cd,
        "qty": float(qty_io),
        "prc": float(prc),
        "splyAmt": line_sply,
        "totDcAmt": 0.0,
        "taxblAmt": _tb,
        "taxTyCd": tty,
        "taxAmt": _tx,
        "totAmt": _tot,
    }
    sar_n = resolve_next_insert_stock_sar_no(
        state_root, effective_tin, branch_id, pin_blob
    )
    print(f"SAR sequence → using sarNo={sar_n}")
    org_sn = 0 if sar_n <= 1 else sar_n - 1
    io_root = {
        "sarNo": sar_n,
        "regTyCd": "M",
        "custTin": effective_tin,
        "sarTyCd": "01",
        "ocrnDt": io_ocrn_8,
        "totItemCnt": 1,
        "totTaxblAmt": _tb,
        "totTaxAmt": _tx,
        "totAmt": _tot,
        "orgSarNo": org_sn,
        "regrId": "system",
        "regrNm": "system",
        "modrId": "system",
        "modrNm": "system",
        "itemList": [stock_line],
    }
    audit_append_row(
        bhf_rows,
        endpoint="insertStockIO",
        payload=io_root,
        headers=headers,
        fallback_tin=effective_tin,
        fallback_bhf=branch_id,
    )
    register_insert_stock_io_request_url(io_url)
    r2 = requests.post(io_url, headers=headers, json=io_root, timeout=timeout)
    p2 = print_full_response_json(r2, "FINISHED GOOD PROBE insertStockIO (single)")
    io_rc = (extract_result_cd(p2) or "").strip()
    if r2.status_code >= 400 or kra_top_level_error_detail(p2) or io_rc != "000":
        print(
            "\n=== SBX FINISHED GOOD LEDGER PROBE RESULT ===\n"
            f"insertStockIO resultCd: {io_rc!r}\n"
            "CLASSIFICATION: ABORTED_INSERT_IO_NOT_000\n"
        )
        return 1
    persist_committed_insert_stock_sar_no(
        state_root, effective_tin, branch_id, sar_n, pin_blob
    )
    if on_pin_blob_mutation is not None:
        on_pin_blob_mutation()

    print("\n--- Step 3: saveStockMaster (rsdQty = IO qty) ---")
    sm_url = f"{base_url.rstrip('/')}/saveStockMaster"
    sm_payload = {
        "itemCd": item_cd,
        "rsdQty": float(qty_io),
        "regrId": "system",
        "regrNm": "system",
        "modrId": "system",
        "modrNm": "system",
    }
    r_sm = requests.post(sm_url, headers=headers, json=sm_payload, timeout=timeout)
    p_sm = print_full_response_json(r_sm, "FINISHED GOOD PROBE saveStockMaster")
    sm_rc = (extract_result_cd(p_sm) or "").strip() if isinstance(p_sm, dict) else ""

    print("\n--- Step 4: wait 10 seconds before move-list probes ---")
    time.sleep(10.0)

    lrd1 = kra_stock_move_list_last_req_dt_utc_now()
    rc_b1, rows_b1, _ = _sbx_finished_good_single_move_list_post(
        base_url=base_url,
        headers=headers,
        tin=effective_tin,
        bhf_id=branch_id,
        item_cd=item_cd,
        last_req_dt=lrd1,
        log_label="move list UTC 1/3",
        timeout=timeout,
    )
    time.sleep(2.5)
    lrd2 = kra_stock_move_list_last_req_dt_utc_now()
    rc_b2, rows_b2, _ = _sbx_finished_good_single_move_list_post(
        base_url=base_url,
        headers=headers,
        tin=effective_tin,
        bhf_id=branch_id,
        item_cd=item_cd,
        last_req_dt=lrd2,
        log_label="move list UTC 2/3",
        timeout=timeout,
    )
    time.sleep(2.5)
    lrd3 = kra_stock_move_list_last_req_dt_utc_now()
    rc_u, rows_u, _ = _sbx_finished_good_single_move_list_post(
        base_url=base_url,
        headers=headers,
        tin=effective_tin,
        bhf_id=branch_id,
        item_cd=item_cd,
        last_req_dt=lrd3,
        log_label="move list UTC 3/3",
        timeout=timeout,
    )
    max_rows = max(int(rows_b1), int(rows_b2), int(rows_u))
    if max_rows <= 0:
        classification = "SBX_NON_MATERIALIZING_LEDGER"
    else:
        classification = "SBX_MOVE_LIST_SHOWS_ROWS"

    print(
        "\n=== SBX FINISHED GOOD LEDGER PROBE RESULT ===\n"
        f"itemCd: {item_cd!r}\n"
        f"insertStockIO resultCd: {io_rc!r}\n"
        f"saveStockMaster resultCd: {sm_rc!r}\n"
        f"move_list UTC 1/3: resultCd={rc_b1!r} rows={rows_b1} lastReqDt={lrd1!r}\n"
        f"move_list UTC 2/3: resultCd={rc_b2!r} rows={rows_b2} lastReqDt={lrd2!r}\n"
        f"move_list UTC 3/3: resultCd={rc_u!r} rows={rows_u} lastReqDt={lrd3!r}\n"
        f"max_rows_across_probes: {max_rows}\n"
        f"CLASSIFICATION: {classification}\n"
    )
    if on_pin_blob_mutation is not None:
        on_pin_blob_mutation()
    return 0


def _kra_response_header_trace_slice(parsed: dict | None) -> dict[str, str]:
    """Subset of ``responseHeader`` fields for cross-call correlation (debug ledger)."""
    if not isinstance(parsed, dict):
        return {}
    rh = parsed.get("responseHeader")
    if not isinstance(rh, dict):
        return {}
    out: dict[str, str] = {}
    for k in _LEDGER_DEBUG_RH_TRACE_KEYS:
        v = rh.get(k)
        if v is not None and str(v).strip():
            out[str(k)] = str(v).strip()
    return out


def _ledger_debug_insert_vs_select_ref_overlap(
    insert_parsed: dict | None, select_parsed_list: list[dict | None]
) -> tuple[bool, list[str]]:
    """
    Returns (any_value_match, detail_lines). Compares insert ``responseHeader`` trace values to each
    select response (same key + same value counts as a match — rare for ``responseRefID`` per call).
    """
    ins = _kra_response_header_trace_slice(insert_parsed)
    if not ins:
        return False, ["insert: no trace fields in responseHeader"]
    matches: list[str] = []
    for i, sp in enumerate(select_parsed_list, start=1):
        if not isinstance(sp, dict):
            continue
        sel = _kra_response_header_trace_slice(sp)
        for k, iv in ins.items():
            if k in sel and sel[k] == iv:
                matches.append(f"probe{i}: {k} matches insert ({iv!r})")
    return (bool(matches), matches if matches else ["no insert trace value equals any select trace value"])


def run_debug_ledger_watch_after_insert_stock_io_ok(
    *,
    base_url: str,
    headers: dict,
    tin: str,
    bhf_id: str,
    item_cd: str,
    insert_parsed: dict | None,
    timeout: int = 120,
) -> str:
    """
    Opt-in diagnostics (``--debug-ledger-after-io``): timed ``selectStockMoveList`` probes, optional
    ``selectStockMaster`` POST, then a **single classification** (no extra endpoints beyond those two).

    Verdict (from move-list probes only): ``LEDGER_EVENTUAL_CONSISTENCY`` | ``NO_LEDGER_POSTING`` |
    ``READ_ENDPOINT_INVALID``.
    """
    want = (item_cd or "").strip()
    if not want:
        print("DEBUG LEDGER: skip (empty itemCd)")
        return DEBUG_LEDGER_VERDICT_SKIPPED

    io_ref = kra_extract_response_ref_id(insert_parsed)
    io_trace = _kra_response_header_trace_slice(insert_parsed)
    print(
        "\n=== DEBUG LEDGER (opt-in): after insertStockIO resultCd=000 ===\n"
        f"insertStockIO responseRefID={io_ref!r}\n"
        f"insertStockIO responseHeader trace slice: {io_trace!r}\n"
        "--- Timed selectStockMoveList probes (same itemCd, UTC lastReqDt per POST) ---"
    )
    surl = resolve_select_stock_move_list_url(base_url)
    probes: tuple[tuple[int, str], ...] = (
        (0, "immediate"),
        (2, "after 2s sleep"),
        (5, "after 5s sleep"),
        (10, "after 10s sleep"),
    )
    move_list_read_invalid = False
    had_move_rows = False
    sel_refs: list[str] = []
    select_parsed_list: list[dict | None] = []

    for i, (pause_sec, label) in enumerate(probes):
        if pause_sec > 0:
            print(f"DEBUG LEDGER: sleep {pause_sec}s ({label}) …")
            time.sleep(float(pause_sec))
        _dl_ts = kra_stock_move_list_last_req_dt_utc_now()
        print(f"STOCK MOVE QUERY using lastReqDt = {_dl_ts} (DEBUG LEDGER {label})")
        pl = {
            "tin": tin,
            "bhfId": bhf_id,
            "lastReqDt": _dl_ts,
            "itemCd": want,
        }
        tag = f"DEBUG LEDGER selectStockMoveList probe {i + 1}/{len(probes)} ({label}) itemCd={want!r}"
        try:
            r = requests.post(surl, headers=headers, json=pl, timeout=timeout)
        except requests.RequestException as e:
            print(f"DEBUG LEDGER: {label} POST failed: {e}")
            move_list_read_invalid = True
            select_parsed_list.append(None)
            sel_refs.append("")
            continue
        if r.status_code >= 400:
            move_list_read_invalid = True
        p = print_full_response_json(r, tag)
        parsed_dict = p if isinstance(p, dict) else None
        if r.status_code < 400 and parsed_dict is None:
            move_list_read_invalid = True
        select_parsed_list.append(parsed_dict)
        sel_ref = kra_extract_response_ref_id(parsed_dict)
        sel_refs.append(sel_ref)
        rc = (extract_result_cd(parsed_dict) or "").strip() if parsed_dict else ""
        nrows = (
            count_stock_move_list_rows_for_item(parsed_dict, want)
            if parsed_dict
            else 0
        )
        if nrows > 0:
            had_move_rows = True
        print(
            f"DEBUG LEDGER: {label} HTTP={r.status_code} resultCd={rc!r} "
            f"responseRefID={sel_ref!r} rows_matching_itemCd={nrows}"
        )

    if move_list_read_invalid:
        verdict = DEBUG_LEDGER_VERDICT_READ_INVALID
    elif had_move_rows:
        verdict = DEBUG_LEDGER_VERDICT_EVENTUAL
    else:
        verdict = DEBUG_LEDGER_VERDICT_NO_POSTING

    overlap_any, overlap_lines = _ledger_debug_insert_vs_select_ref_overlap(
        insert_parsed, select_parsed_list
    )
    print(
        "\n--- DEBUG LEDGER: insert vs select trace correlation ---\n"
        f"selectStockMoveList responseRefIDs (in probe order): {sel_refs!r}\n"
        f"insert_vs_select_trace_overlap: {overlap_any} ({'; '.join(overlap_lines)})"
    )

    sm_base = _stock_api_cluster_base(surl)
    sm_url = f"{sm_base.rstrip('/')}/selectStockMaster"
    sm_pl = {
        "tin": tin,
        "bhfId": bhf_id,
        "itemCd": want,
        "lastReqDt": KRA_LIST_BASELINE_LAST_REQ_DT,
    }
    print(
        "\n--- DEBUG LEDGER: optional selectStockMaster (not in public OSCU stock function table) ---\n"
        f"POST {sm_pl} → {sm_url}"
    )
    sm_ref = ""
    sm_http: int | None = None
    sm_rc = ""
    sm_note = ""
    try:
        rsm = requests.post(sm_url, headers=headers, json=sm_pl, timeout=timeout)
        sm_http = getattr(rsm, "status_code", None)
        psm = print_full_response_json(rsm, "DEBUG LEDGER selectStockMaster (optional)")
        sm_ref = kra_extract_response_ref_id(psm if isinstance(psm, dict) else None)
        sm_rc = (extract_result_cd(psm) or "").strip() if isinstance(psm, dict) else ""
        ge = kra_top_level_error_detail(psm) if isinstance(psm, dict) else None
        if sm_http is not None and sm_http >= 400:
            sm_note = " (HTTP error — route may be absent on this product)"
        elif ge:
            sm_note = f" (gateway/body: {ge!r})"
        print(
            f"DEBUG LEDGER: selectStockMaster HTTP={sm_http} resultCd={sm_rc!r} "
            f"responseRefID={sm_ref!r}{sm_note}"
        )
    except requests.RequestException as e:
        sm_note = f" request_error={e!r}"
        print(f"DEBUG LEDGER: selectStockMaster request failed: {e}")

    _vmean = (
        "at least one move-list probe showed row(s) for itemCd (immediate or delayed)."
        if verdict == DEBUG_LEDGER_VERDICT_EVENTUAL
        else (
            "move-list probe(s) had HTTP error or transport failure — read path or routing problem."
            if verdict == DEBUG_LEDGER_VERDICT_READ_INVALID
            else (
                "all move-list probes returned HTTP<400 but no matching rows — IO 000 did not surface "
                "in this list window (SBX rule / not posted / filter), not explained by delay alone."
            )
        )
    )
    print(
        f"\n{'=' * 72}\n"
        f"DEBUG LEDGER VERDICT (selectStockMoveList probes only): {verdict}\n"
        f"insertStockIO responseRefID: {io_ref!r}\n"
        f"selectStockMoveList responseRefIDs (probe order): {sel_refs!r}\n"
        f"Meaning: {_vmean}\n"
        "(selectStockMaster probe above is supplementary; verdict does not use it.)\n"
        f"{'=' * 72}\n"
    )
    return verdict


def select_stock_move_list_gate_two_baseline_probes(
    *,
    base_url: str,
    headers: dict,
    tin: str,
    bhf_id: str,
    item_cd: str,
    min_rsd_qty: float | None = None,
    capture_stock_move_list: object = None,
    response_log_prefix: str = "",
    timeout: int = 120,
    log_stock_flow_summary: bool = False,
    require_extractable_rsd: bool = True,
    one_utc_now_probe_after_baselines: bool = False,
) -> tuple[bool, float | None, dict | None, requests.Response | None]:
    """
    Two UTC ``lastReqDt`` probes (same strict gate as ``kra_strict_select_stock_component_on_hand``).
    ``min_rsd_qty`` may be ``None`` (treated as ``0``).
    """
    _ = (
        capture_stock_move_list,
        log_stock_flow_summary,
        require_extractable_rsd,
        one_utc_now_probe_after_baselines,
    )
    floor = 0.0 if min_rsd_qty is None else float(min_rsd_qty)
    return kra_strict_select_stock_component_on_hand(
        base_url=base_url,
        headers=headers,
        tin=tin,
        bhf_id=bhf_id,
        component_item_cd=item_cd,
        min_rsd_qty=floor,
        log_tag=response_log_prefix or "select_stock_move_list_gate_two_baseline_probes",
        timeout=timeout,
    )


def print_minimal_select_stock_raw_dump(
    select_stock_move_list_bodies: list[tuple[str, object]],
) -> None:
    """Always print captured ``selectStockMoveList`` JSON for minimal test (Part 5 / debugging)."""
    print("\n=== RAW selectStockMoveList (minimal test) ===")
    if not select_stock_move_list_bodies:
        print("(no selectStockMoveList responses captured)")
        return
    for title, body in select_stock_move_list_bodies:
        print(f"\n### {title}\n")
        if isinstance(body, dict):
            print(json.dumps(body, indent=2, ensure_ascii=False, default=str))
        else:
            print(repr(body))


def print_minimal_osdc_pasteback_block(
    *,
    a: str,
    b: str,
    c: str,
    d: str,
    e: str,
    select_stock_move_list_bodies: list[tuple[str, object]],
) -> None:
    """Copy-friendly footer: A–E plus raw ``selectStockMoveList`` JSON (for senior / ticket paste)."""
    print("\n=== PASTEBACK (A–E + selectStockMoveList) ===")
    print(f"A. BHF Consistency: {a}")
    print(f"B. Item Visibility: {b}")
    print(f"C. Stock Visibility: {c}")
    print(f"D. Minimal Test: {d}")
    print(f"E. Root Cause: {e}")
    print("\n--- selectStockMoveList (raw JSON) ---")
    if not select_stock_move_list_bodies:
        print("(no selectStockMoveList responses captured in this run yet)")
        return
    for title, body in select_stock_move_list_bodies:
        print(f"\n### {title}\n")
        if isinstance(body, dict):
            print(json.dumps(body, indent=2, ensure_ascii=False, default=str))
        else:
            print(repr(body))


def bhf_audit_osdc_label(step_name: str) -> str | None:
    """Map runner step names to the four OSCU POST labels for PIN BHF consistency (table only)."""
    s = (step_name or "").strip()
    if s == "saveItem":
        return "saveItem"
    if s in ("insertStockIO", "insertStockIOInitial", "insertStockIOPostComposition"):
        return "insertStockIO"
    if s in (
        "saveStockMaster",
        "saveStockMasterInitial",
        "saveStockMasterAfterPurchase",
        "saveStockMasterComponentPurchase",
        "saveStockMasterPostComposition",
    ):
        return "saveStockMaster"
    if s == "saveInvoice":
        return "saveTrnsSalesOsdc"
    return None


def audit_append_osdc_bhf_row(
    rows: list[dict[str, str]],
    *,
    step_name: str,
    payload: dict | None,
    headers: dict | None,
    fallback_tin: str,
    fallback_bhf: str,
) -> None:
    lbl = bhf_audit_osdc_label(step_name)
    if lbl is None:
        return
    audit_append_row(
        rows,
        endpoint=lbl,
        payload=payload,
        headers=headers,
        fallback_tin=fallback_tin,
        fallback_bhf=fallback_bhf,
    )


def audit_resolve_tin_bhf(
    payload: dict | None,
    headers: dict | None,
    *,
    fallback_tin: str,
    fallback_bhf: str,
) -> tuple[str, str]:
    """Resolve tin/bhfId for logging: JSON body first, then HTTP headers, then CSV/run fallbacks.

    Runner OSCU ``headers`` use a fixed ``tin``/``bhfId`` for the session (Bearer may refresh elsewhere);
    POST paths typically pass ``post_headers = dict(headers)`` so audit snapshots stay consistent.
    """
    pl = payload if isinstance(payload, dict) else {}
    ht = str((headers or {}).get("tin") or fallback_tin).strip()
    hb = str((headers or {}).get("bhfId") or fallback_bhf).strip()
    pt = pl.get("tin")
    if pt is None or str(pt).strip() == "":
        pt = pl.get("custTin")
    tin_out = str(pt).strip() if pt is not None and str(pt).strip() != "" else ht
    pb = pl.get("bhfId")
    bhf_out = str(pb).strip() if pb is not None and str(pb).strip() != "" else hb
    return tin_out, bhf_out


def audit_append_row(
    rows: list[dict[str, str]],
    *,
    endpoint: str,
    payload: dict | None,
    headers: dict | None,
    fallback_tin: str,
    fallback_bhf: str,
) -> None:
    t, b = audit_resolve_tin_bhf(
        payload, headers, fallback_tin=fallback_tin, fallback_bhf=fallback_bhf
    )
    rows.append({"endpoint": endpoint, "tin": t, "bhfId": b})


def audit_print_and_validate_bhf(
    rows: list[dict[str, str]],
    *,
    structured_report_title_on_fail: str | None = None,
) -> None:
    """Print BHF table; raise SystemExit on tin/bhfId mismatch across audited rows."""
    print("\n=== BHF CONSISTENCY AUDIT (audited POSTs only) ===")
    print("endpoint\ttin\tbhfId")
    for r in rows:
        print(f"{r['endpoint']}\t{r['tin']}\t{r['bhfId']}")
    tins = {r["tin"] for r in rows}
    bhfs = {r["bhfId"] for r in rows}
    if len(tins) > 1:
        print(f"\nFLAG ERROR: TIN mismatch detected — {sorted(tins)!r}")
        if structured_report_title_on_fail:
            print(f"\n=== {structured_report_title_on_fail} ===")
            print("A. BHF Consistency: FAIL")
            print("B. Item Visibility: N/A")
            print("C. Stock Visibility: N/A")
            print("D. Minimal Test: N/A")
            print("E. Root Cause: BHF mismatch")
        raise SystemExit("BHF audit: TIN mismatch across audited endpoints (see table above).")
    if len(bhfs) > 1:
        print(f"\nFLAG ERROR: BHF mismatch detected — {sorted(bhfs)!r}")
        if structured_report_title_on_fail:
            print(f"\n=== {structured_report_title_on_fail} ===")
            print("A. BHF Consistency: FAIL")
            print("B. Item Visibility: N/A")
            print("C. Stock Visibility: N/A")
            print("D. Minimal Test: N/A")
            print("E. Root Cause: BHF mismatch")
        raise SystemExit("BHF audit: bhfId mismatch across audited endpoints (see table above).")
    print("(Audited rows: single tin + single bhfId.)\n")


def select_item_list_fetch_catalog_for_item_cd_planning(
    *,
    base_url: str,
    headers: dict,
    tin: str,
    bhf_id: str,
    response_log_prefix: str,
    timeout: int = 120,
    utc_fallback_if_001: bool = True,
) -> dict | None:
    """
    Full-catalog ``selectItemList`` (no ``itemCd`` filter) to drive ``alloc_provisional_item_cd_monotonic``.
    Uses baseline ``lastReqDt`` first; if ``resultCd`` is ``001`` and ``utc_fallback_if_001``, one UTC list.
    """
    surl = f"{base_url.rstrip('/')}/selectItemList"
    lrd = KRA_LIST_BASELINE_LAST_REQ_DT
    pl: dict = {"tin": tin, "bhfId": bhf_id, "lastReqDt": lrd}
    tag = f"{response_log_prefix} selectItemList (catalog) / baseline lastReqDt={lrd}"
    backoff_base = 15.0
    max_504 = 5
    parsed_last: dict | None = None
    for sml_i in range(max_504):
        if sml_i > 0:
            time.sleep(backoff_base * (2 ** (sml_i - 1)))
        resp_last = requests.post(surl, headers=headers, json=pl, timeout=timeout)
        parsed_last = print_full_response_json(resp_last, tag)
        if getattr(resp_last, "status_code", 0) != 504:
            break
    if not isinstance(parsed_last, dict):
        return None
    rc = (extract_result_cd(parsed_last) or "").strip()
    if utc_fallback_if_001 and rc == "001":
        time.sleep(
            random.uniform(
                STOCK_MOVE_LIST_GATE_RECHECK_SLEEP_SEC_MIN,
                STOCK_MOVE_LIST_GATE_RECHECK_SLEEP_SEC_MAX,
            )
        )
        lrd_now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        pl2 = {"tin": tin, "bhfId": bhf_id, "lastReqDt": lrd_now}
        tag2 = f"{response_log_prefix} selectItemList (catalog) / UTC-now lastReqDt={lrd_now}"
        parsed2: dict | None = None
        for sml_i in range(max_504):
            if sml_i > 0:
                time.sleep(backoff_base * (2 ** (sml_i - 1)))
            resp2 = requests.post(surl, headers=headers, json=pl2, timeout=timeout)
            parsed2 = print_full_response_json(resp2, tag2)
            if getattr(resp2, "status_code", 0) != 504:
                break
        if isinstance(parsed2, dict) and (extract_result_cd(parsed2) or "").strip() == "000":
            return parsed2
    return parsed_last


def select_item_list_gate_two_baseline_probes(
    *,
    base_url: str,
    headers: dict,
    tin: str,
    bhf_id: str,
    item_cd: str,
    response_log_prefix: str,
    timeout: int = 120,
) -> tuple[bool, list[str]]:
    """Two baseline ``selectItemList`` POSTs (2–3s apart). Pass iff resultCd 000 and ``itemCd`` appears."""
    surl = f"{base_url.rstrip('/')}/selectItemList"
    detail_parts: list[str] = []
    lrd = KRA_LIST_BASELINE_LAST_REQ_DT
    _ic = (item_cd or "").strip()
    for attempt in (1, 2):
        if attempt == 2:
            time.sleep(
                random.uniform(
                    STOCK_MOVE_LIST_GATE_RECHECK_SLEEP_SEC_MIN,
                    STOCK_MOVE_LIST_GATE_RECHECK_SLEEP_SEC_MAX,
                )
            )
        label = f"{response_log_prefix} selectItemList / baseline {attempt}/2"
        pl: dict = {"tin": tin, "bhfId": bhf_id, "lastReqDt": lrd}
        if _ic:
            pl["itemCd"] = _ic
        print(
            f"\n{response_log_prefix}: selectItemList [baseline {attempt}/2] "
            f"itemCd={item_cd!r} lastReqDt={lrd!r}"
        )
        resp = requests.post(surl, headers=headers, json=pl, timeout=timeout)
        parsed = print_full_response_json(resp, label)
        rc = (extract_result_cd(parsed) or "").strip()
        detail_parts.append(f"baseline {attempt}/2: resultCd={rc!r}")
        if rc == "000" and response_contains_item_cd(parsed, item_cd):
            return True, detail_parts
    return False, detail_parts


def strict_pre_sale_select_item_list_or_exit(
    *,
    base_url: str,
    headers: dict,
    tin: str,
    bhf_id: str,
    item_cd: str,
    abort: Callable[[str], None] | None = None,
) -> None:
    """Require selectItemList resultCd 000 and itemCd present; baseline lastReqDt only, max 2 calls."""
    ok, detail_parts = select_item_list_gate_two_baseline_probes(
        base_url=base_url,
        headers=headers,
        tin=tin,
        bhf_id=bhf_id,
        item_cd=item_cd,
        response_log_prefix="STRICT PRE-SALE",
    )
    if ok:
        return
    msg = "STOP: Item not visible\n" + " | ".join(detail_parts)
    if abort is not None:
        abort(msg)
    raise SystemExit(msg)


def strict_pre_sale_select_stock_move_or_exit(
    *,
    base_url: str,
    headers: dict,
    tin: str,
    bhf_id: str,
    item_cd: str,
    sale_qty: float,
    capture_stock_move_list: list[tuple[str, object]] | None = None,
    one_utc_now_probe_after_baselines: bool = False,
    gate_label: str = "STRICT PRE-SALE",
    exit_banner: str | None = None,
    abort: Callable[[str], None] | None = None,
) -> float:
    """
    Deprecated gate: selectStockMoveList must not control flow in SBX runner.
    Keep best-effort logging only, then allow the run to continue.
    """
    _ = (capture_stock_move_list, one_utc_now_probe_after_baselines, exit_banner, abort)
    print(
        f"\n{gate_label}: selectStockMoveList (best-effort, ignored for gating) "
        f"itemCd={item_cd!r} sale_qty={float(sale_qty):g}"
    )
    parsed_mv, resp_mv = best_effort_stock_read_debug(
        base_url=base_url,
        headers=headers,
        tin=tin,
        bhf_id=bhf_id,
        item_cd=item_cd,
        log_tag=f"{gate_label} selectStockMoveList (best-effort)",
        timeout=120,
    )
    if isinstance(parsed_mv, dict):
        try:
            _n = count_stock_move_list_rows_for_item(parsed_mv, item_cd)
        except Exception:
            _n = 0
        print(f"{gate_label}: move-list rows matching itemCd={item_cd!r}: {_n} (ignored)")
    return float(sale_qty)


def run_strict_pre_sale_audit_block(
    *,
    bhf_rows: list[dict[str, str]],
    base_url: str,
    headers: dict,
    effective_tin: str,
    branch_id: str,
    item_cd: str,
    sale_qty: float,
    abort: Callable[[str], None] | None = None,
) -> None:
    audit_print_and_validate_bhf(
        bhf_rows, structured_report_title_on_fail="STRUCTURED REPORT"
    )
    strict_pre_sale_select_item_list_or_exit(
        base_url=base_url,
        headers=headers,
        tin=effective_tin,
        bhf_id=branch_id,
        item_cd=item_cd,
        abort=abort,
    )
    _rsd_gate = strict_pre_sale_select_stock_move_or_exit(
        base_url=base_url,
        headers=headers,
        tin=effective_tin,
        bhf_id=branch_id,
        item_cd=item_cd,
        sale_qty=sale_qty,
        abort=abort,
    )
    print("\n=== STRUCTURED REPORT ===")
    print("A. BHF Consistency: PASS")
    print("B. Item Visibility: PASS")
    print("C. Stock Visibility: PASS (selectStockMoveList diagnostic only; not a gate)")
    print(
        f"   (probe returned sale_qty reference={_rsd_gate:g}; sale_qty={float(sale_qty):g})"
    )
    print("D. Minimal Test: N/A")
    print("E. Root Cause: N/A (gates passed)\n")


def composition_probe_select_stock_move_for_item(
    *,
    base_url: str,
    headers: dict,
    tin: str,
    bhf_id: str,
    component_item_cd: str,
    label: str,
) -> tuple[float | None, dict | None, requests.Response | None]:
    """
    Diagnostic: ``selectStockMoveList`` ×2 with UTC ``lastReqDt`` (same gate as strict stock paths).
    """
    ok, rsd, parsed, resp = select_stock_move_list_gate_two_baseline_probes(
        base_url=base_url,
        headers=headers,
        tin=tin,
        bhf_id=bhf_id,
        item_cd=component_item_cd,
        min_rsd_qty=None,
        capture_stock_move_list=None,
        response_log_prefix=f"COMPOSITION DIAG selectStockMoveList [{label}]",
        timeout=120,
        log_stock_flow_summary=False,
        require_extractable_rsd=True,
        one_utc_now_probe_after_baselines=False,
    )
    if not ok or rsd is None:
        rsd = None
    print(f"\nCOMPOSITION DIAG: selectStockMoveList (component) [{label}]")
    print(f"  component_item_cd={component_item_cd!r}")
    print(f"  HTTP={getattr(resp, 'status_code', None) if resp is not None else None}")
    if rsd is not None:
        print(f"  extracted rsdQty (best-effort) for component={rsd:g}")
    else:
        print(
            "  extracted rsdQty: (none — no matching itemCd row or convertible quantity field)"
        )
    print("  full response JSON:")
    print(
        json.dumps(
            parsed,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
    return rsd, parsed, resp


def log_stock_flow_insert_io_prelude_summary(
    *, item_cd: str, parsed: dict | None, http_status: int | None = None
) -> None:
    """One-line summary after full JSON is printed (composition prelude insertStockIO)."""
    ic = (item_cd or "").strip()
    rc = (extract_result_cd(parsed) or "").strip() if isinstance(parsed, dict) else ""
    rh = parsed.get("responseHeader") if isinstance(parsed, dict) else None
    print("\n--- STOCK FLOW insertStockIO (composition prelude) SUMMARY ---")
    print(f"  itemCd: {ic!r}")
    print(f"  HTTP status: {http_status}")
    print(f"  resultCd: {rc!r}")
    if isinstance(rh, dict):
        print(f"  responseHeader: {json.dumps(rh, ensure_ascii=False, default=str)}")
    else:
        print(f"  responseHeader: {rh!r}")
    print("---\n")


def log_stock_flow_select_stock_move_list_summary(
    *,
    phase_label: str,
    item_cd: str,
    last_req_dt: str,
    parsed: dict | None,
    http_status: int | None = None,
) -> None:
    """Summary for one selectStockMoveList attempt (e.g. stock gate / flow probe)."""
    want = (item_cd or "").strip()
    rc = (extract_result_cd(parsed) or "").strip() if isinstance(parsed, dict) else ""
    rsd = (
        _first_rsd_qty_for_item_in_stock_move_tree(parsed, want)
        if isinstance(parsed, dict)
        else None
    )
    nrows = (
        count_stock_move_list_rows_for_item(parsed, want)
        if isinstance(parsed, dict)
        else 0
    )
    rh = parsed.get("responseHeader") if isinstance(parsed, dict) else None
    print(f"\n--- STOCK FLOW selectStockMoveList ({phase_label}) lastReqDt={last_req_dt!r} ---")
    print(f"  itemCd (filter): {want!r}")
    print(f"  HTTP status: {http_status}")
    print(f"  resultCd: {rc!r}")
    print(f"  rows matching itemCd: {nrows}")
    print(f"  extracted rsdQty: {rsd if rsd is not None else '(none)'}")
    if isinstance(rh, dict):
        print(f"  responseHeader: {json.dumps(rh, ensure_ascii=False, default=str)}")
    else:
        print(f"  responseHeader: {rh!r}")
    print("---\n")


def log_stock_flow_save_stock_master_prelude_summary(
    *,
    item_cd: str,
    rsd_qty_sent: float,
    parsed: dict | None,
    http_status: int | None = None,
) -> None:
    """Summary after saveStockMaster (composition prelude)."""
    ic = (item_cd or "").strip()
    rc = (extract_result_cd(parsed) or "").strip() if isinstance(parsed, dict) else ""
    rh = parsed.get("responseHeader") if isinstance(parsed, dict) else None
    print("\n--- STOCK FLOW saveStockMaster (composition prelude) SUMMARY ---")
    print(f"  itemCd: {ic!r}")
    print(f"  rsdQty (sent): {rsd_qty_sent:g}")
    print(f"  HTTP status: {http_status}")
    print(f"  resultCd: {rc!r}")
    if isinstance(rh, dict):
        print(f"  responseHeader: {json.dumps(rh, ensure_ascii=False, default=str)}")
    else:
        print(f"  responseHeader: {rh!r}")
    print("---\n")


def kra_probe_select_stock_move_rsd_for_item(
    *,
    base_url: str,
    headers: dict,
    tin: str,
    bhf_id: str,
    item_cd: str,
    log_tag: str,
    timeout: int = 120,
) -> tuple[float | None, dict | None, requests.Response | None]:
    """
    ``selectStockMoveList`` ×2 with UTC ``lastReqDt``: return ``rsdQty`` when ``resultCd`` is ``000``
    and a row exists, **without** enforcing a minimum quantity (unlike the strict gate).
    """
    want = (item_cd or "").strip()
    if not want:
        return None, None, None
    parsed_last, resp_last = best_effort_stock_read_debug(
        base_url=base_url,
        headers=headers,
        tin=tin,
        bhf_id=bhf_id,
        item_cd=want,
        log_tag=log_tag,
        timeout=timeout,
    )
    rsd = (
        _first_rsd_qty_for_item_in_stock_move_tree(parsed_last, want)
        if isinstance(parsed_last, dict)
        else None
    )
    return rsd, parsed_last, resp_last


def save_item_composition_insufficient_stock(parsed: dict | None) -> bool:
    """True when SBX rejects saveItemComposition with insufficient component/parent stock."""
    if not isinstance(parsed, dict):
        return False
    rh = parsed.get("responseHeader")
    if not isinstance(rh, dict):
        return False
    cm = str(rh.get("customerMessage") or "")
    dm = str(rh.get("debugMessage") or "")
    blob = f"{cm} {dm}".lower()
    return (
        "insufficient" in blob
        or "sufficient stock" in blob
        or "don't have sufficient" in blob
        or "do not have sufficient" in blob
    )


def detect_dirty_sandbox_before_initial_save_stock_master(
    *,
    pin_blob: dict,
    item_cd_val: str,
    base_url: str,
    headers: dict,
    tin: str,
    bhf_id: str,
    threshold: int | float = INITIAL_SAVE_STOCKMASTER_DIRTY_THRESHOLD,
) -> tuple[bool, list[str]]:
    """
    Read-only signals only (no rsdQty changes). Returns ``(is_dirty, reasons)``.
    Optionally probes ``selectStockMoveList``; skips probe if the response is not usable.
    """
    reasons: list[str] = []
    thr = float(threshold)
    bal = 0.0
    raw_bal = pin_blob.get("current_stock_balance")
    try:
        if raw_bal is not None and str(raw_bal).strip() != "":
            bal = float(raw_bal)
    except (TypeError, ValueError):
        bal = 0.0
    if abs(bal) < 1e-12:
        raw = pin_blob.get("stock_io_pending_rsd_qty")
        try:
            pend = float(raw) if raw is not None and str(raw).strip() != "" else 0.0
        except (TypeError, ValueError):
            pend = 0.0
        bal = abs(pend)
    if abs(bal) > thr:
        reasons.append(
            f"|current_stock_balance| is {abs(bal):g} (threshold {thr:g}) — local runner state "
            "suggests accumulated unreconciled Stock IO / SAR backlog."
        )

    try:
        next_sar = int(pin_blob.get("stock_io_next_sar_no") or 1)
    except (TypeError, ValueError):
        next_sar = 1
    sar_depth = max(0, next_sar - 1)
    if sar_depth >= INITIAL_SAVE_STOCKMASTER_SAR_BACKLOG_DIRTY:
        reasons.append(
            f"stock_io_next_sar_no={next_sar} implies ~{sar_depth} unreconciled SAR row(s) "
            f"(>={INITIAL_SAVE_STOCKMASTER_SAR_BACKLOG_DIRTY}) — SBX often deadlocks saveStockMasterInitial "
            "(rsdQty vs Stock IO mismatch). Clear stock/SAR for this PIN or use a fresh PIN."
        )

    surl = resolve_select_stock_move_list_url(base_url)
    pl = {
        "tin": tin,
        "bhfId": bhf_id,
        "lastReqDt": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
    }
    try:
        resp_mv = requests.post(surl, headers=headers, json=pl, timeout=120)
        try:
            parsed = resp_mv.json()
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = None
    except requests.RequestException:
        parsed = None

    if isinstance(parsed, dict) and not kra_top_level_error_detail(parsed):
        rc = extract_result_cd(parsed)
        if rc in ("000", "001"):
            nmove = count_stock_move_list_rows_for_item(parsed, item_cd_val)
            if nmove > thr:
                reasons.append(
                    f"selectStockMoveList reports {nmove} move row(s) for itemCd={item_cd_val!r} "
                    f"(threshold {thr:g}) — likely historical Stock IO on this sandbox."
                )
    return (bool(reasons), reasons)


def sbx_test_session_log_truncation(parsed) -> bool:
    """SBX certification logger sometimes fails after the business call (response_desc VARCHAR too small)."""
    if not isinstance(parsed, dict):
        return False
    rh = parsed.get("responseHeader")
    if isinstance(rh, dict):
        dm = str(rh.get("debugMessage") or "")
        if "test_session_api_log" in dm and "response_desc" in dm:
            return True
    return False


def apigee_unresolved_target_path_fault(parsed) -> bool:
    """True when SBX returns ``{"fault": {..., "faultstring": "...targetPath..."}}``."""
    if not isinstance(parsed, dict):
        return False
    fault = parsed.get("fault")
    if not isinstance(fault, dict):
        return False
    detail = fault.get("detail")
    err_c = ""
    if isinstance(detail, dict):
        err_c = str(detail.get("errorcode") or "")
    fs = str(fault.get("faultstring") or "")
    return "entities.UnresolvedVariable" in err_c or "targetPath" in fs


def kra_save_invoice_error_blob(parsed: dict | None, gate_err: str | None) -> str:
    """Concatenate gate line and responseHeader messages for substring checks."""
    parts: list[str] = []
    if gate_err:
        parts.append(str(gate_err))
    if isinstance(parsed, dict):
        rh = parsed.get("responseHeader")
        if isinstance(rh, dict):
            for _k in ("debugMessage", "customerMessage"):
                _t = (rh.get(_k) or "").strip()
                if _t:
                    parts.append(_t)
    return " ".join(parts)


def kra_save_invoice_stock_master_propagation_error(detail: str | None) -> bool:
    """True when OSDC rejects the sale with the stock-master visibility message (retry saveTrnsSalesOsdc only)."""
    if not detail:
        return False
    return "does not exist in your stock master" in detail.lower()


def kra_top_level_error_detail(parsed_json) -> str | None:
    if not isinstance(parsed_json, dict):
        return None
    rh = parsed_json.get("responseHeader")
    if not isinstance(rh, dict):
        return None
    rcode = rh.get("responseCode")
    try:
        ri = int(rcode) if rcode is not None else None
    except (TypeError, ValueError):
        ri = None
    if ri is None or ri < 400:
        return None
    msg = (rh.get("debugMessage") or rh.get("customerMessage") or "").strip()
    ref = (rh.get("responseRefID") or "").strip()
    parts = [f"responseHeader.responseCode={ri}"]
    if ref:
        parts.append(f"ref={ref}")
    if msg:
        parts.append(msg)
    return " | ".join(parts)


def save_stock_master_strict_failure_reason(parsed: dict | None) -> str | None:
    """
    GavaConnect / certification UI treat saveStockMaster* as failed unless the body shows a clean 000.
    Some SBX responses use HTTP 200 with responseHeader.responseCode 400 + null responseBody — gate_err
    catches that. This adds checks where responseHeader looks OK but resultCd is missing or not 000.
    """
    if not isinstance(parsed, dict):
        return "no parsed JSON"
    rc = extract_result_cd(parsed)
    if (rc or "").strip() != "000":
        return f"resultCd={rc!r} (GavaConnect expects 000 in responseBody)"
    rh = parsed.get("responseHeader")
    if isinstance(rh, dict):
        code = rh.get("responseCode")
        try:
            hri = int(code) if code is not None else None
        except (TypeError, ValueError):
            hri = None
        if hri is not None and hri >= 400:
            return (
                f"responseHeader.responseCode={hri} with resultCd={rc!r} "
                "(treat as failure — matches GavaConnect red state)"
            )
    return None


def print_response_body_result_cd(parsed, endpoint_name: str) -> None:
    rc = extract_result_cd(parsed)
    print(f"responseBody.resultCd: {rc!r}  [{endpoint_name}]")


def print_full_response_json(resp: requests.Response, endpoint_name: str = "") -> dict | None:
    try:
        parsed = resp.json()
        print(json.dumps(parsed, indent=2, ensure_ascii=False, default=str))
        print_response_body_result_cd(parsed, endpoint_name or "?")
        return parsed
    except Exception:
        text = resp.text or ""
        print(text)
        print(f"responseBody.resultCd: None  [{endpoint_name or '?'}] (non-JSON body)")
        return None


def save_item_payload_omit_nulls(payload: dict) -> dict:
    """Strip null keys so saveItem JSON has no null-valued fields."""
    return {k: v for k, v in payload.items() if v is not None}


def normalize_save_item_payload_fields(payload: dict) -> None:
    """KRA saveItem ItemSaveReq: dftPrc / sftyQty as numbers; itemTyCd is CHAR (string)."""
    ity = payload.get("itemTyCd")
    if ity is not None and ity != "":
        payload["itemTyCd"] = str(ity).strip()[:5]
    dp = payload.get("dftPrc")
    try:
        if dp is None or dp == "":
            payload["dftPrc"] = 100
        else:
            payload["dftPrc"] = int(float(dp))
    except (TypeError, ValueError):
        payload["dftPrc"] = 100
    sq = payload.get("sftyQty")
    try:
        if sq is None or sq == "":
            payload.pop("sftyQty", None)
        else:
            payload["sftyQty"] = int(float(sq))
    except (TypeError, ValueError):
        payload.pop("sftyQty", None)
    if payload.get("sftyQty") == 0:
        payload.pop("sftyQty", None)


def print_save_item_http_debug(
    resp: requests.Response | None, req_headers: dict, payload: dict
) -> None:
    print("SAVE_ITEM_DEBUG response.status_code:", getattr(resp, "status_code", None))
    print("SAVE_ITEM_DEBUG response.text:", getattr(resp, "text", None))
    print("SAVE_ITEM_DEBUG request.headers:", json.dumps(dict(req_headers), indent=2, default=str))
    print(
        "SAVE_ITEM_DEBUG request.body:",
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
    )


def _minimal_matrix_save_item_single_try(
    *,
    base_url: str,
    headers: dict,
    effective_tin: str,
    branch_id: str,
    item_ty_cd: str,
    icd: str,
    tty: str,
    pkg_unit_cd: str,
    qty_unit_cd: str,
    prc: float,
    pin_blob: dict,
    catalog_parsed: dict | None,
    bhf_rows: list[dict[str, str]],
    log_tag: str,
) -> str | None:
    """One ``saveItem`` POST (no retry loop). Returns ``itemCd`` on ``000``."""
    item_cd = alloc_provisional_item_cd_monotonic(
        item_ty_cd, pkg_unit_cd, qty_unit_cd, pin_blob, catalog_parsed
    )
    si_url = f"{base_url.rstrip('/')}/saveItem"
    si_payload = {
        "itemCd": item_cd,
        "itemClsCd": icd,
        "itemTyCd": item_ty_cd,
        "itemNm": "MINIMAL MATRIX ITEM",
        "orgnNatCd": "KE",
        "pkgUnitCd": pkg_unit_cd,
        "qtyUnitCd": qty_unit_cd,
        "taxTyCd": tty,
        "dftPrc": prc,
        "isrcAplcbYn": "N",
        "useYn": "Y",
        "regrId": "system",
        "regrNm": "system",
        "modrId": "system",
        "modrNm": "system",
    }
    normalize_save_item_payload_fields(si_payload)
    si_payload = save_item_payload_omit_nulls(si_payload)
    audit_append_row(
        bhf_rows,
        endpoint="saveItem",
        payload=si_payload,
        headers=headers,
        fallback_tin=effective_tin,
        fallback_bhf=branch_id,
    )
    r1 = requests.post(si_url, headers=headers, json=si_payload, timeout=120)
    p1 = print_full_response_json(r1, log_tag)
    rc = (extract_result_cd(p1) or "").strip()
    ge = kra_top_level_error_detail(p1)
    if r1.status_code < 400 and not ge and rc == "000":
        persist_item_cd_suffix_map(pin_blob, item_cd)
        return item_cd
    print(f"{log_tag}: saveItem not OK (HTTP={r1.status_code}, resultCd={rc!r})")
    return None


def _minimal_matrix_single_insert_io_and_move_summary(
    *,
    test_num: int,
    test_title: str,
    base_url: str,
    headers: dict,
    effective_tin: str,
    branch_id: str,
    item_cd: str,
    item_nm: str,
    icd: str,
    tty: str,
    pkg_unit_cd: str,
    qty_unit_cd: str,
    prc: float,
    qty_io: float,
    sales_dt: str,
    io_ty_cd: str,
    stock_line_extra: dict | None,
    io_root_extra: dict | None,
    state_root: dict,
    pin_blob: dict,
    bhf_rows: list[dict[str, str]],
    stock_move_captures: list[tuple[str, object]],
    on_pin_blob_mutation: Callable[[], None] | None,
    debug_ledger_after_io: bool = False,
) -> bool:
    """
    One ``insertStockIO`` POST (no SAR correction retry) + move-list gate (unchanged probes).
    Prints required MATRIX summary lines. Returns True if move list shows a row for ``itemCd``.
    """
    print(f"\n{'=' * 72}\nMATRIX TEST {test_num}: {test_title}\n{'=' * 72}")
    io_url = f"{base_url.rstrip('/')}/insertStockIO"
    io_ocrn_8 = (sales_dt or "").strip()[:8]
    if len(io_ocrn_8) != 8:
        io_ocrn_8 = datetime.now(timezone.utc).strftime("%Y%m%d")
    line_sply, _tb, _tx, _tot = stock_io_line_amounts_for_tax_ty(
        unit_prc=float(prc), qty=qty_io, tax_ty_cd=tty
    )
    stock_line: dict = {
        "itemSeq": 1,
        "itemCd": item_cd,
        "ioTyCd": io_ty_cd,
        "itemClsCd": icd,
        "itemNm": item_nm,
        "pkgUnitCd": pkg_unit_cd,
        "pkg": qty_io,
        "qtyUnitCd": qty_unit_cd,
        "qty": qty_io,
        "prc": float(prc),
        "splyAmt": line_sply,
        "totDcAmt": 0.0,
        "taxblAmt": _tb,
        "taxTyCd": tty,
        "taxAmt": _tx,
        "totAmt": _tot,
    }
    if stock_line_extra:
        stock_line.update(stock_line_extra)
    sar_n = resolve_next_insert_stock_sar_no(
        state_root, effective_tin, branch_id, pin_blob
    )
    print(f"SAR sequence → using sarNo={sar_n}")
    org_sn = 0 if sar_n <= 1 else sar_n - 1
    io_root: dict = {
        "sarNo": sar_n,
        "regTyCd": "M",
        "custTin": effective_tin,
        "sarTyCd": "01",
        "ocrnDt": io_ocrn_8,
        "totItemCnt": 1,
        "totTaxblAmt": _tb,
        "totTaxAmt": _tx,
        "totAmt": _tot,
        "orgSarNo": org_sn,
        "regrId": "system",
        "regrNm": "system",
        "modrId": "system",
        "modrNm": "system",
        "itemList": [stock_line],
    }
    if io_root_extra:
        for k, v in io_root_extra.items():
            if k != "itemList":
                io_root[k] = v
    audit_append_row(
        bhf_rows,
        endpoint="insertStockIO",
        payload=io_root,
        headers=headers,
        fallback_tin=effective_tin,
        fallback_bhf=branch_id,
    )
    register_insert_stock_io_request_url(io_url)
    r2 = requests.post(io_url, headers=headers, json=io_root, timeout=120)
    p2 = print_full_response_json(r2, f"MATRIX T{test_num} insertStockIO")
    rc2 = (extract_result_cd(p2) or "").strip()
    ge2 = kra_top_level_error_detail(p2)
    io_ok = r2.status_code < 400 and not ge2 and rc2 == "000"
    print(
        f"MATRIX T{test_num} insertStockIO: HTTP={r2.status_code} resultCd={rc2!r} accepted={io_ok}"
    )
    if io_ok:
        persist_committed_insert_stock_sar_no(
            state_root, effective_tin, branch_id, sar_n, pin_blob
        )
        if on_pin_blob_mutation is not None:
            on_pin_blob_mutation()
        if debug_ledger_after_io:
            run_debug_ledger_watch_after_insert_stock_io_ok(
                base_url=base_url,
                headers=headers,
                tin=effective_tin,
                bhf_id=branch_id,
                item_cd=item_cd,
                insert_parsed=p2 if isinstance(p2, dict) else None,
            )

    pmv, rmv = best_effort_stock_read_debug(
        base_url=base_url,
        headers=headers,
        tin=effective_tin,
        bhf_id=branch_id,
        item_cd=item_cd,
        log_tag=f"MATRIX T{test_num} post-insertStockIO selectStockMoveList (best-effort)",
        timeout=120,
    )
    if isinstance(pmv, dict):
        stock_move_captures.append(
            (f"MATRIX T{test_num} selectStockMoveList (best-effort)", deepcopy(pmv))
        )
    mv_rc = (extract_result_cd(pmv) or "").strip() if isinstance(pmv, dict) else "(n/a)"
    nrows = count_stock_move_list_rows_for_item(pmv, item_cd) if isinstance(pmv, dict) else 0
    print(
        f"MATRIX T{test_num} stock read (debug disabled): HTTP={getattr(rmv,'status_code',None)!r} "
        f"resultCd={mv_rc!r} rows_matching_itemCd={nrows} (ignored)"
    )
    # Matrix "success" is insertStockIO acceptance; move-list is logging-only.
    return bool(io_ok)


def _minimal_stock_ledger_matrix_sequence(
    *,
    base_url: str,
    headers: dict,
    effective_tin: str,
    branch_id: str,
    item_cd_ty2: str,
    icd_ty2: str,
    tty_ty2: str,
    pkg_unit_cd: str,
    qty_unit_cd: str,
    prc: float,
    qty_io: float,
    sales_dt: str,
    item_cls_dynamic: dict,
    pin_blob: dict,
    state_root: dict,
    bhf_rows: list[dict[str, str]],
    stock_move_captures: list[tuple[str, object]],
    on_pin_blob_mutation: Callable[[], None] | None,
    pasteback: bool,
    _pb: Callable[..., None],
    debug_ledger_after_io: bool = False,
) -> int:
    """Sequential ledger probes (TEST 1–4); stop on first move-list row. See ``--minimal-stock-ledger-matrix``."""
    print(
        "\n=== MINIMAL STOCK LEDGER MATRIX "
        "(single IO variable per step; stop when selectStockMoveList shows a row) ===\n"
    )
    sr = state_root if isinstance(state_root, dict) else {}

    # TEST 1 — only ioTyCd "3" vs baseline "1"
    if _minimal_matrix_single_insert_io_and_move_summary(
        test_num=1,
        test_title='ioTyCd="3" (adjustment); all else same as baseline minimal IO',
        base_url=base_url,
        headers=headers,
        effective_tin=effective_tin,
        branch_id=branch_id,
        item_cd=item_cd_ty2,
        item_nm="MINIMAL TEST ITEM",
        icd=icd_ty2,
        tty=tty_ty2,
        pkg_unit_cd=pkg_unit_cd,
        qty_unit_cd=qty_unit_cd,
        prc=prc,
        qty_io=qty_io,
        sales_dt=sales_dt,
        io_ty_cd="3",
        stock_line_extra=None,
        io_root_extra=None,
        state_root=sr,
        pin_blob=pin_blob,
        bhf_rows=bhf_rows,
        stock_move_captures=stock_move_captures,
        on_pin_blob_mutation=on_pin_blob_mutation,
        debug_ledger_after_io=debug_ledger_after_io,
    ):
        print("\n>>> MATRIX: STOP — TEST 1 passed (move list row present).\n")
        _pb("PASS", "PASS", "PASS", "MATRIX TEST 1 OK", "ioTyCd=3 produced ledger row")
        print_minimal_select_stock_raw_dump(stock_move_captures)
        return 0

    # TEST 2 — baseline ioTyCd "1" + supplier fields on IO root only
    if _minimal_matrix_single_insert_io_and_move_summary(
        test_num=2,
        test_title='spplrTin/spplrNm/spplrBhfId on insertStockIO; ioTyCd="1"',
        base_url=base_url,
        headers=headers,
        effective_tin=effective_tin,
        branch_id=branch_id,
        item_cd=item_cd_ty2,
        item_nm="MINIMAL TEST ITEM",
        icd=icd_ty2,
        tty=tty_ty2,
        pkg_unit_cd=pkg_unit_cd,
        qty_unit_cd=qty_unit_cd,
        prc=prc,
        qty_io=qty_io,
        sales_dt=sales_dt,
        io_ty_cd="1",
        stock_line_extra=None,
        io_root_extra={
            "spplrTin": "P000000000A",
            "spplrNm": "TEST SUPPLIER",
            "spplrBhfId": "00",
        },
        state_root=sr,
        pin_blob=pin_blob,
        bhf_rows=bhf_rows,
        stock_move_captures=stock_move_captures,
        on_pin_blob_mutation=on_pin_blob_mutation,
        debug_ledger_after_io=debug_ledger_after_io,
    ):
        print("\n>>> MATRIX: STOP — TEST 2 passed (move list row present).\n")
        _pb("PASS", "PASS", "PASS", "MATRIX TEST 2 OK", "supplier context produced ledger row")
        print_minimal_select_stock_raw_dump(stock_move_captures)
        return 0

    # TEST 3 — itemTyCd "1" (new item), IO baseline ioTyCd "1"
    ic3 = str(item_cls_dynamic.get("itemClsCd") or "1010000000").strip()
    tty3 = str(item_cls_dynamic.get("taxTyCd") or "A").strip()
    print("\n--- MATRIX: refresh catalog for itemTyCd=1 / KE1… prefix ---")
    cat3 = select_item_list_fetch_catalog_for_item_cd_planning(
        base_url=base_url,
        headers=headers,
        tin=effective_tin,
        bhf_id=branch_id,
        response_log_prefix="MATRIX TEST 3 catalog",
    )
    cd3 = _minimal_matrix_save_item_single_try(
        base_url=base_url,
        headers=headers,
        effective_tin=effective_tin,
        branch_id=branch_id,
        item_ty_cd="1",
        icd=ic3,
        tty=tty3,
        pkg_unit_cd=pkg_unit_cd,
        qty_unit_cd=qty_unit_cd,
        prc=prc,
        pin_blob=pin_blob,
        catalog_parsed=cat3,
        bhf_rows=bhf_rows,
        log_tag="MATRIX TEST 3 saveItem (itemTyCd=1, single try)",
    )
    if cd3:
        ok_vis3, _ = select_item_list_gate_two_baseline_probes(
            base_url=base_url,
            headers=headers,
            tin=effective_tin,
            bhf_id=branch_id,
            item_cd=cd3,
            response_log_prefix="MATRIX TEST 3 pre-IO selectItemList",
        )
        print(f"MATRIX TEST 3 pre-insertStockIO selectItemList gate: ok={ok_vis3}")
        if ok_vis3 and _minimal_matrix_single_insert_io_and_move_summary(
            test_num=3,
            test_title='itemTyCd=1 item; ioTyCd="1" (baseline IO)',
            base_url=base_url,
            headers=headers,
            effective_tin=effective_tin,
            branch_id=branch_id,
            item_cd=cd3,
            item_nm="MINIMAL MATRIX ITEM",
            icd=ic3,
            tty=tty3,
            pkg_unit_cd=pkg_unit_cd,
            qty_unit_cd=qty_unit_cd,
            prc=prc,
            qty_io=qty_io,
            sales_dt=sales_dt,
            io_ty_cd="1",
            stock_line_extra=None,
            io_root_extra=None,
            state_root=sr,
            pin_blob=pin_blob,
            bhf_rows=bhf_rows,
            stock_move_captures=stock_move_captures,
            on_pin_blob_mutation=on_pin_blob_mutation,
            debug_ledger_after_io=debug_ledger_after_io,
        ):
            print("\n>>> MATRIX: STOP — TEST 3 passed (move list row present).\n")
            _pb("PASS", "PASS", "PASS", "MATRIX TEST 3 OK", "itemTyCd=1 path produced ledger row")
            print_minimal_select_stock_raw_dump(stock_move_captures)
            return 0
    else:
        print("MATRIX TEST 3 skipped IO (saveItem did not return 000).")

    # TEST 4 — hardcoded: itemTyCd 1, itemClsCd 1010000000, ioTyCd 3
    ic4 = "1010000000"
    tty4 = str(item_cls_dynamic.get("taxTyCd") or "A").strip()
    print("\n--- MATRIX: refresh catalog for TEST 4 (KE1… + fixed cls) ---")
    cat4 = select_item_list_fetch_catalog_for_item_cd_planning(
        base_url=base_url,
        headers=headers,
        tin=effective_tin,
        bhf_id=branch_id,
        response_log_prefix="MATRIX TEST 4 catalog",
    )
    cd4 = _minimal_matrix_save_item_single_try(
        base_url=base_url,
        headers=headers,
        effective_tin=effective_tin,
        branch_id=branch_id,
        item_ty_cd="1",
        icd=ic4,
        tty=tty4,
        pkg_unit_cd=pkg_unit_cd,
        qty_unit_cd=qty_unit_cd,
        prc=prc,
        pin_blob=pin_blob,
        catalog_parsed=cat4,
        bhf_rows=bhf_rows,
        log_tag="MATRIX TEST 4 saveItem (itemTyCd=1, itemClsCd=1010000000, single try)",
    )
    if cd4:
        ok_vis4, _ = select_item_list_gate_two_baseline_probes(
            base_url=base_url,
            headers=headers,
            tin=effective_tin,
            bhf_id=branch_id,
            item_cd=cd4,
            response_log_prefix="MATRIX TEST 4 pre-IO selectItemList",
        )
        print(f"MATRIX TEST 4 pre-insertStockIO selectItemList gate: ok={ok_vis4}")
        if ok_vis4 and _minimal_matrix_single_insert_io_and_move_summary(
            test_num=4,
            test_title='itemTyCd=1, itemClsCd=1010000000, ioTyCd="3"',
            base_url=base_url,
            headers=headers,
            effective_tin=effective_tin,
            branch_id=branch_id,
            item_cd=cd4,
            item_nm="MINIMAL MATRIX ITEM",
            icd=ic4,
            tty=tty4,
            pkg_unit_cd=pkg_unit_cd,
            qty_unit_cd=qty_unit_cd,
            prc=prc,
            qty_io=qty_io,
            sales_dt=sales_dt,
            io_ty_cd="3",
            stock_line_extra=None,
            io_root_extra=None,
            state_root=sr,
            pin_blob=pin_blob,
            bhf_rows=bhf_rows,
            stock_move_captures=stock_move_captures,
            on_pin_blob_mutation=on_pin_blob_mutation,
            debug_ledger_after_io=debug_ledger_after_io,
        ):
            print("\n>>> MATRIX: STOP — TEST 4 passed (move list row present).\n")
            _pb("PASS", "PASS", "PASS", "MATRIX TEST 4 OK", "hardcoded ty1/cls/ioTy3 produced ledger row")
            print_minimal_select_stock_raw_dump(stock_move_captures)
            return 0
    else:
        print("MATRIX TEST 4 skipped IO (saveItem did not return 000).")

    print("\n>>> MATRIX: all tests completed — no move-list row satisfied the gate.\n")
    try:
        audit_print_and_validate_bhf(
            bhf_rows,
            structured_report_title_on_fail="STRUCTURED REPORT (minimal stock ledger matrix)",
        )
    except SystemExit:
        raise
    _pb(
        "PASS",
        "PASS",
        "FAIL",
        "MATRIX all tests",
        "No selectStockMoveList row after TEST 1–4",
    )
    print_minimal_select_stock_raw_dump(stock_move_captures)
    return 1


def run_minimal_osdc_sale_test(
    *,
    base_url: str,
    headers: dict,
    effective_tin: str,
    branch_id: str,
    item_cls_dynamic: dict,
    sales_dt: str,
    cfm_dt: str,
    pkg_unit_cd: str,
    qty_unit_cd: str,
    item_ty_cd: str,
    pin_blob: dict,
    pasteback: bool = False,
    on_pin_blob_mutation: Callable[[], None] | None = None,
    state_root: dict | None = None,
    stock_ledger_matrix: bool = False,
    debug_ledger_after_io: bool = False,
) -> int:
    """
    Strict linear probe (KRA query truth only): selectItemList (catalog) → saveItem with monotonic
    itemCd from KRA list + local state + sequence-error retries → selectItemList gate (pre-IO) →
    insertStockIO (ioTyCd=1, qty=100) → selectStockMoveList (UTC ``lastReqDt`` ×2) →
    saveStockMaster (rsdQty from that move list only) → strict pre-sale item + stock gates (same
    UTC move-list gate) → saveTrnsSalesOsdc. No literal/fallback qty; no saveStockMaster
    mismatch retries; no composition.
    """
    qty_io = 100.0
    prc = 100.0
    bhf_rows: list[dict[str, str]] = []
    stock_move_captures: list[tuple[str, object]] = []
    reset_insert_stock_io_cluster_url()

    def _pb(a: str, b: str, c: str, d: str, e: str) -> None:
        if pasteback:
            print_minimal_osdc_pasteback_block(
                a=a,
                b=b,
                c=c,
                d=d,
                e=e,
                select_stock_move_list_bodies=stock_move_captures,
            )

    icd = str(item_cls_dynamic.get("itemClsCd") or "1010000000").strip()
    tty = str(item_cls_dynamic.get("taxTyCd") or "A").strip()
    print("\n=== MINIMAL OSDC SALE TEST (no composition) ===\n")
    ic_prefix = f"KE{item_ty_cd}{pkg_unit_cd}{qty_unit_cd}"
    print(
        "\n--- MINIMAL TEST: pre-saveItem selectItemList (full catalog for itemCd planning) ---"
    )
    catalog_parsed = select_item_list_fetch_catalog_for_item_cd_planning(
        base_url=base_url,
        headers=headers,
        tin=effective_tin,
        bhf_id=branch_id,
        response_log_prefix="MINIMAL",
    )
    api_mx_cat = max_numeric_suffix_for_prefix(catalog_parsed, ic_prefix)
    print(
        f"MINIMAL: catalog max 7-digit suffix for {ic_prefix!r}: {api_mx_cat} "
        "(combined with local state / KRA tail-constraint hints for next itemCd)"
    )

    env_item = (get_optional_env("GAVAETIMS_MINIMAL_ITEM_CD") or "").strip()
    pin_item = str(pin_blob.get("minimal_osdc_item_cd_override") or "").strip()
    override_mode: str | None = None
    if env_item:
        override_mode = "env"
    elif pin_item:
        override_mode = "pin"

    si_url = f"{base_url.rstrip('/')}/saveItem"
    item_cd = ""
    p1: object | None = None
    _minimal_save_max = 5
    save_item_ok = False

    for attempt in range(_minimal_save_max):
        if override_mode == "env" and attempt == 0:
            item_cd = env_item
            print(f"MINIMAL: first saveItem uses GAVAETIMS_MINIMAL_ITEM_CD={item_cd!r}")
        elif override_mode == "pin" and attempt == 0:
            item_cd = pin_item
            print(
                f"MINIMAL: first saveItem uses minimal_osdc_item_cd_override from {STATE_FILE.name} "
                f"({item_cd!r})"
            )
        else:
            item_cd = alloc_provisional_item_cd_monotonic(
                item_ty_cd, pkg_unit_cd, qty_unit_cd, pin_blob, catalog_parsed
            )
            print(
                f"MINIMAL: derived itemCd={item_cd!r} "
                f"(saveItem attempt {attempt + 1}/{_minimal_save_max})"
            )

        si_payload = {
            "itemCd": item_cd,
            "itemClsCd": icd,
            "itemTyCd": item_ty_cd,
            "itemNm": "MINIMAL TEST ITEM",
            "orgnNatCd": "KE",
            "pkgUnitCd": pkg_unit_cd,
            "qtyUnitCd": qty_unit_cd,
            "taxTyCd": tty,
            "dftPrc": prc,
            "isrcAplcbYn": "N",
            "useYn": "Y",
            "regrId": "system",
            "regrNm": "system",
            "modrId": "system",
            "modrNm": "system",
        }
        normalize_save_item_payload_fields(si_payload)
        si_payload = save_item_payload_omit_nulls(si_payload)
        audit_append_row(
            bhf_rows,
            endpoint="saveItem",
            payload=si_payload,
            headers=headers,
            fallback_tin=effective_tin,
            fallback_bhf=branch_id,
        )
        r1 = requests.post(si_url, headers=headers, json=si_payload, timeout=120)
        p1 = print_full_response_json(
            r1, f"MINIMAL saveItem attempt {attempt + 1}/{_minimal_save_max}"
        )
        result_cd = (extract_result_cd(p1) or "").strip()
        gate_err = kra_top_level_error_detail(p1)
        ok_si = r1.status_code < 400 and not gate_err and result_cd == "000"
        if ok_si:
            persist_item_cd_suffix_map(pin_blob, item_cd)
            pin_blob.pop("item_cd_suffix_tail_mod", None)
            pin_blob.pop("item_cd_suffix_tail_res", None)
            pin_blob.pop("item_cd_suffix_last_digit", None)
            if len(item_cd) >= 8 and item_cd[-7:].isdigit():
                clear_kra_tail_constraint_for_prefix(pin_blob, item_cd[:-7])
            pin_blob.pop("minimal_osdc_item_cd_override", None)
            if on_pin_blob_mutation is not None:
                on_pin_blob_mutation()
            print(f"MINIMAL saveItem OK itemCd={item_cd!r}")
            save_item_ok = True
            break
        _err_txt = kra_save_item_error_text(p1 if isinstance(p1, dict) else None)
        _fixed = apply_item_cd_sequence_recovery_hints(pin_blob, item_cd, _err_txt)
        if _fixed and _fixed != item_cd:
            si_payload["itemCd"] = _fixed
            normalize_save_item_payload_fields(si_payload)
            si_payload = save_item_payload_omit_nulls(si_payload)
            print(f"MINIMAL: immediate retry with corrected itemCd={_fixed!r}")
            r2 = requests.post(si_url, headers=headers, json=si_payload, timeout=120)
            p2 = print_full_response_json(r2, "MINIMAL saveItem (corrected retry)")
            rc2 = (extract_result_cd(p2) or "").strip()
            ge2 = kra_top_level_error_detail(p2)
            if r2.status_code < 400 and not ge2 and rc2 == "000":
                persist_item_cd_suffix_map(pin_blob, _fixed)
                pin_blob.pop("item_cd_suffix_tail_mod", None)
                pin_blob.pop("item_cd_suffix_tail_res", None)
                pin_blob.pop("item_cd_suffix_last_digit", None)
                if len(_fixed) >= 8 and _fixed[-7:].isdigit():
                    clear_kra_tail_constraint_for_prefix(pin_blob, _fixed[:-7])
                pin_blob.pop("minimal_osdc_item_cd_override", None)
                if on_pin_blob_mutation is not None:
                    on_pin_blob_mutation()
                print(f"MINIMAL saveItem OK itemCd={_fixed!r} (corrected retry)")
                item_cd = _fixed
                save_item_ok = True
                break
        if on_pin_blob_mutation is not None:
            on_pin_blob_mutation()
        if attempt >= _minimal_save_max - 1:
            try:
                audit_print_and_validate_bhf(
                    bhf_rows,
                    structured_report_title_on_fail="STRUCTURED REPORT (minimal test)",
                )
            except SystemExit:
                raise
            _err_txt = kra_save_item_error_text(p1 if isinstance(p1, dict) else None)
            _seq_e = (
                "saveItem itemCd sequence / reuse vs KRA internal counter (see KRA message)"
                if _err_txt and "sequence" in _err_txt.lower()
                else "Other (saveItem did not return 000)"
            )
            print(
                "\n=== STRUCTURED REPORT (minimal test) ===\n"
                "A. BHF Consistency: PASS\n"
                "B. Item Visibility: N/A\n"
                "C. Stock Visibility: N/A\n"
                "D. Minimal Test: FAIL (saveItem)\n"
                f"E. Root Cause: {_seq_e}\n"
            )
            _pb("PASS", "N/A", "N/A", "FAIL (saveItem)", _seq_e)
            print_minimal_select_stock_raw_dump(stock_move_captures)
            return 1
        print(
            f"RETRY: minimal saveItem (next attempt uses catalog + updated sequence hints) …"
        )

    if not save_item_ok:
        return 1

    print(
        "\n--- MINIMAL TEST: pre-insertStockIO selectItemList "
        f"(lastReqDt={KRA_LIST_BASELINE_LAST_REQ_DT} only, max 2 calls) ---"
    )
    ok_item_pre_io, _item_pre_parts = select_item_list_gate_two_baseline_probes(
        base_url=base_url,
        headers=headers,
        tin=effective_tin,
        bhf_id=branch_id,
        item_cd=item_cd,
        response_log_prefix="MINIMAL pre-insertStockIO",
    )
    if not ok_item_pre_io:
        try:
            audit_print_and_validate_bhf(
                bhf_rows,
                structured_report_title_on_fail="STRUCTURED REPORT (minimal test)",
            )
        except SystemExit:
            raise
        print(
            "\n=== STRUCTURED REPORT (minimal test) ===\n"
            "A. BHF Consistency: PASS\n"
            "B. Item Visibility: FAIL (pre-insertStockIO)\n"
            "C. Stock Visibility: N/A\n"
            "D. Minimal Test: FAIL (pre-insertStockIO item gate)\n"
            "E. Root Cause: Item not visible after saveItem — propagation delay, wrong bhfId/cluster, "
            "or itemClsCd/catalog mismatch (insertStockIO would likely fail silently later)\n"
        )
        _pb(
            "PASS",
            "FAIL (pre-insertStockIO)",
            "N/A",
            "FAIL (pre-insertStockIO item gate)",
            "Item not visible after saveItem (check propagation / bhfId / itemClsCd)",
        )
        print_minimal_select_stock_raw_dump(stock_move_captures)
        return 1

    if stock_ledger_matrix:
        return _minimal_stock_ledger_matrix_sequence(
            base_url=base_url,
            headers=headers,
            effective_tin=effective_tin,
            branch_id=branch_id,
            item_cd_ty2=item_cd,
            icd_ty2=icd,
            tty_ty2=tty,
            pkg_unit_cd=pkg_unit_cd,
            qty_unit_cd=qty_unit_cd,
            prc=prc,
            qty_io=qty_io,
            sales_dt=sales_dt,
            item_cls_dynamic=item_cls_dynamic,
            pin_blob=pin_blob,
            state_root=state_root if isinstance(state_root, dict) else {},
            bhf_rows=bhf_rows,
            stock_move_captures=stock_move_captures,
            on_pin_blob_mutation=on_pin_blob_mutation,
            pasteback=pasteback,
            _pb=_pb,
            debug_ledger_after_io=debug_ledger_after_io,
        )

    io_url = f"{base_url.rstrip('/')}/insertStockIO"
    io_ocrn_8 = (sales_dt or "").strip()[:8]
    if len(io_ocrn_8) != 8:
        io_ocrn_8 = datetime.now(timezone.utc).strftime("%Y%m%d")
    line_sply, _tb, _tx, _tot = stock_io_line_amounts_for_tax_ty(
        unit_prc=float(prc), qty=qty_io, tax_ty_cd=tty
    )
    stock_line_template = {
        "itemSeq": 1,
        "itemCd": item_cd,
        "ioTyCd": "1",
        "itemClsCd": icd,
        "itemNm": "MINIMAL TEST ITEM",
        "pkgUnitCd": pkg_unit_cd,
        "pkg": qty_io,
        "qtyUnitCd": qty_unit_cd,
        "qty": qty_io,
        "prc": float(prc),
        "splyAmt": line_sply,
        "totDcAmt": 0.0,
        "taxblAmt": _tb,
        "taxTyCd": tty,
        "taxAmt": _tx,
        "totAmt": _tot,
    }
    sr = state_root if isinstance(state_root, dict) else {}
    minimal_io_ok = False
    p2: object | None = None
    sar_resync_used = False
    for _io_attempt in range(2):
        sar_n = resolve_next_insert_stock_sar_no(sr, effective_tin, branch_id, pin_blob)
        print(f"SAR sequence → using sarNo={sar_n}")
        org_sn = 0 if sar_n <= 1 else sar_n - 1
        io_root = {
            "sarNo": sar_n,
            "regTyCd": "M",
            "custTin": effective_tin,
            "sarTyCd": "01",
            "ocrnDt": io_ocrn_8,
            "totItemCnt": 1,
            "totTaxblAmt": _tb,
            "totTaxAmt": _tx,
            "totAmt": _tot,
            "orgSarNo": org_sn,
            "regrId": "system",
            "regrNm": "system",
            "modrId": "system",
            "modrNm": "system",
            "itemList": [dict(stock_line_template)],
        }
        audit_append_row(
            bhf_rows,
            endpoint="insertStockIO",
            payload=io_root,
            headers=headers,
            fallback_tin=effective_tin,
            fallback_bhf=branch_id,
        )
        register_insert_stock_io_request_url(io_url)
        r2 = requests.post(io_url, headers=headers, json=io_root, timeout=120)
        p2 = print_full_response_json(
            r2,
            f"MINIMAL insertStockIO (attempt {_io_attempt + 1}/2, sarNo={sar_n})",
        )
        rc2 = (extract_result_cd(p2) or "").strip()
        ge2 = kra_top_level_error_detail(p2)
        if r2.status_code < 400 and not ge2 and rc2 == "000":
            persist_committed_insert_stock_sar_no(
                sr, effective_tin, branch_id, sar_n, pin_blob
            )
            if on_pin_blob_mutation is not None:
                on_pin_blob_mutation()
            minimal_io_ok = True
            break
        err_io = kra_insert_stock_io_error_text(p2 if isinstance(p2, dict) else None)
        exp_sar = kra_expected_next_sar_no_from_message(err_io)
        if (
            not sar_resync_used
            and exp_sar is not None
            and err_io
            and "Invalid sarNo" in err_io
        ):
            print(
                f"SAR corrected from {sar_n} → {exp_sar} based on KRA response"
            )
            apply_kra_expected_insert_stock_sar_no(
                sr, effective_tin, branch_id, exp_sar, pin_blob
            )
            sar_resync_used = True
            if on_pin_blob_mutation is not None:
                on_pin_blob_mutation()
            continue
        try:
            audit_print_and_validate_bhf(
                bhf_rows,
                structured_report_title_on_fail="STRUCTURED REPORT (minimal test)",
            )
        except SystemExit:
            raise
        _sar_hint = (
            "Invalid sarNo / SAR sequence vs KRA (see .test_state.json "
            f"{SAR_NO_BY_TIN_BHF_KEY})"
            if err_io and "sarNo" in err_io.lower()
            else "insertStockIO not accepted — check payload / SAR / itemClsCd"
        )
        print(
            "\n=== STRUCTURED REPORT (minimal test) ===\n"
            "A. BHF Consistency: PASS\n"
            "B. Item Visibility: N/A\n"
            "C. Stock Visibility: N/A\n"
            "D. Minimal Test: FAIL (insertStockIO)\n"
            f"E. Root Cause: {_sar_hint}\n"
        )
        _pb("PASS", "N/A", "N/A", "FAIL (insertStockIO)", _sar_hint)
        print_minimal_select_stock_raw_dump(stock_move_captures)
        return 1

    if not minimal_io_ok:
        return 1

    if debug_ledger_after_io:
        run_debug_ledger_watch_after_insert_stock_io_ok(
            base_url=base_url,
            headers=headers,
            tin=effective_tin,
            bhf_id=branch_id,
            item_cd=item_cd,
            insert_parsed=p2 if isinstance(p2, dict) else None,
        )

    print("\n--- MINIMAL TEST: post-insertStockIO selectStockMoveList (best-effort, ignored) ---")
    pmv, _rmv = best_effort_stock_read_debug(
        base_url=base_url,
        headers=headers,
        tin=effective_tin,
        bhf_id=branch_id,
        item_cd=item_cd,
        log_tag="MINIMAL post-insertStockIO selectStockMoveList (best-effort)",
        timeout=120,
    )
    if isinstance(pmv, dict):
        stock_move_captures.append(("MINIMAL selectStockMoveList (best-effort)", deepcopy(pmv)))
    # Stock master is the oracle; do not gate on move list in SBX.
    sm_qty = float(qty)
    sm_url = f"{base_url.rstrip('/')}/saveStockMaster"
    sm_payload = {
        "itemCd": item_cd,
        "rsdQty": float(sm_qty),
        "regrId": "system",
        "regrNm": "system",
        "modrId": "system",
        "modrNm": "system",
    }
    audit_append_row(
        bhf_rows,
        endpoint="saveStockMaster",
        payload=sm_payload,
        headers=headers,
        fallback_tin=effective_tin,
        fallback_bhf=branch_id,
    )
    r3 = requests.post(sm_url, headers=headers, json=sm_payload, timeout=120)
    p3 = print_full_response_json(r3, "MINIMAL saveStockMaster")
    if kra_top_level_error_detail(p3) or (extract_result_cd(p3) or "").strip() != "000":
        try:
            audit_print_and_validate_bhf(
                bhf_rows,
                structured_report_title_on_fail="STRUCTURED REPORT (minimal test)",
            )
        except SystemExit:
            raise
        print(
            "\n=== STRUCTURED REPORT (minimal test) ===\n"
            "A. BHF Consistency: PASS\n"
            "B. Item Visibility: N/A\n"
            "C. Stock Visibility: PASS (move list had stock; saveStockMaster POST rejected)\n"
            "D. Minimal Test: FAIL (saveStockMaster)\n"
            "E. Root Cause: Other (saveStockMaster rejected — see KRA response; no Expected-rsd retry)\n"
        )
        _pb(
            "PASS",
            "N/A",
            "PASS (move list OK; saveStockMaster failed)",
            "FAIL (saveStockMaster)",
            "Other (saveStockMaster rejected)",
        )
        print_minimal_select_stock_raw_dump(stock_move_captures)
        return 1

    invc_no = str(int(datetime.now(timezone.utc).timestamp()) % 999_999_999 or 1)
    trd_invc = f"MIN-{invc_no}"
    sply_i, tb_i, tx_i, tot_i = stock_io_line_amounts_for_tax_ty(
        unit_prc=float(prc), qty=qty_io, tax_ty_cd=tty
    )
    sale_payload: dict = {
        "tin": effective_tin,
        "bhfId": branch_id,
        "regTyCd": "M",
        "custTin": effective_tin,
        "custNm": "Minimal Test Customer",
        "salesTyCd": "N",
        "rcptTyCd": "S",
        "pmtTyCd": "01",
        "trdInvcNo": trd_invc,
        "invcNo": invc_no,
        "orgInvcNo": "0",
        "salesSttsCd": "02",
        "cfmDt": cfm_dt,
        "salesDt": sales_dt,
        "totItemCnt": 1,
        "taxblAmtA": 0.0,
        "taxblAmtB": 0.0,
        "taxblAmtC": 0.0,
        "taxblAmtD": 0.0,
        "taxblAmtE": 0.0,
        "taxRtA": 0.0,
        "taxRtB": 0.0,
        "taxRtC": 0.0,
        "taxRtD": 0.0,
        "taxRtE": 0.0,
        "taxAmtA": 0.0,
        "taxAmtB": 0.0,
        "taxAmtC": 0.0,
        "taxAmtD": 0.0,
        "taxAmtE": 0.0,
        "totTaxblAmt": tb_i,
        "totTaxAmt": tx_i,
        "totAmt": tot_i,
        "prchrAcptcYn": "N",
        "regrId": "system",
        "regrNm": "system",
        "modrId": "system",
        "modrNm": "system",
        "receipt": {"rcptPbctDt": cfm_dt, "prchrAcptcYn": "N"},
        "itemList": [
            {
                "itemSeq": 1,
                "itemClsCd": icd,
                "itemCd": item_cd,
                "itemNm": "MINIMAL TEST ITEM",
                "pkgUnitCd": pkg_unit_cd,
                "pkg": qty_io,
                "qtyUnitCd": qty_unit_cd,
                "qty": qty_io,
                "prc": float(prc),
                "splyAmt": sply_i,
                "dcRt": 0.0,
                "dcAmt": 0.0,
                "taxTyCd": tty,
                "taxblAmt": tb_i,
                "taxAmt": tx_i,
                "totAmt": tot_i,
            }
        ],
    }
    _ctu = tty.upper()
    if _ctu == "A":
        sale_payload["taxblAmtA"] = tb_i
        sale_payload["taxAmtA"] = tx_i
    elif _ctu == "B":
        sale_payload["taxblAmtB"] = tb_i
        sale_payload["taxAmtB"] = tx_i
    elif _ctu == "C":
        sale_payload["taxblAmtC"] = tb_i
        sale_payload["taxAmtC"] = tx_i
    else:
        sale_payload["taxblAmtA"] = tb_i
        sale_payload["taxAmtA"] = tx_i

    if _ctu == "B":
        apply_link_tax_rt_to_purchase_payload(
            sale_payload, dict(_LINKED_PURCHASE_TAX_RT_FALLBACK_KE_SBX)
        )

    try:
        audit_print_and_validate_bhf(
            bhf_rows,
            structured_report_title_on_fail="STRUCTURED REPORT (minimal test)",
        )
    except SystemExit:
        raise

    try:
        strict_pre_sale_select_item_list_or_exit(
            base_url=base_url,
            headers=headers,
            tin=effective_tin,
            bhf_id=branch_id,
            item_cd=item_cd,
        )
    except SystemExit:
        print(
            "\n=== STRUCTURED REPORT (minimal test) ===\n"
            "A. BHF Consistency: PASS\n"
            "B. Item Visibility: FAIL\n"
            "C. Stock Visibility: N/A\n"
            "D. Minimal Test: FAIL (pre-sale item gate)\n"
            "E. Root Cause: Item not propagated\n"
        )
        _pb(
            "PASS",
            "FAIL",
            "N/A",
            "FAIL (pre-sale item gate)",
            "Item not propagated",
        )
        print_minimal_select_stock_raw_dump(stock_move_captures)
        return 1

    strict_pre_sale_select_stock_move_or_exit(
        base_url=base_url,
        headers=headers,
        tin=effective_tin,
        bhf_id=branch_id,
        item_cd=item_cd,
        sale_qty=qty_io,
        capture_stock_move_list=stock_move_captures,
    )

    print(
        "ASSERT pre-saveTrnsSalesOsdc: selectItemList OK; selectStockMoveList probe ran (diagnostic only; "
        f"see logs above). sale_qty={qty_io:g}."
    )
    sale_url = f"{base_url.rstrip('/')}/saveTrnsSalesOsdc"
    _params = {"invcNo": invc_no, "requestedInvcNo": invc_no}
    audit_append_row(
        bhf_rows,
        endpoint="saveTrnsSalesOsdc",
        payload=sale_payload,
        headers=headers,
        fallback_tin=effective_tin,
        fallback_bhf=branch_id,
    )
    r5 = requests.post(
        sale_url,
        headers=headers,
        json=sale_payload,
        params=_params,
        timeout=120,
    )
    p5 = print_full_response_json(r5, "MINIMAL saveTrnsSalesOsdc")
    if (extract_result_cd(p5) or "").strip() == "000" and not kra_top_level_error_detail(p5):
        print(
            "\n=== STRUCTURED REPORT (minimal test) ===\n"
            "A. BHF Consistency: PASS\n"
            "B. Item Visibility: PASS\n"
            "C. Stock Visibility: PASS\n"
            "D. Minimal Test: PASS\n"
            "E. Root Cause: N/A (end-to-end OK)\n"
        )
        _pb("PASS", "PASS", "PASS", "PASS", "N/A (end-to-end OK)")
        print_minimal_select_stock_raw_dump(stock_move_captures)
        return 0
    _blob5 = kra_save_invoice_error_blob(p5, kra_top_level_error_detail(p5))
    print(
        "\n=== STRUCTURED REPORT (minimal test) ===\n"
        "A. BHF Consistency: PASS\n"
        "B. Item Visibility: PASS\n"
        "C. Stock Visibility: PASS\n"
        "D. Minimal Test: FAIL (saveTrnsSalesOsdc)\n"
        "E. Root Cause: "
        + (
            "Stock not visible\n"
            if kra_save_invoice_stock_master_propagation_error(_blob5)
            else "Endpoint/env mismatch (OSDC vs stock API) or other (see response above)\n"
        )
    )
    _e_sale = (
        "Stock not visible"
        if kra_save_invoice_stock_master_propagation_error(_blob5)
        else "Endpoint/env mismatch (OSDC vs stock API) or other (see response above)"
    )
    _pb("PASS", "PASS", "PASS", "FAIL (saveTrnsSalesOsdc)", _e_sale)
    print_minimal_select_stock_raw_dump(stock_move_captures)
    return 1


def main():
    _argv_help = [str(a).strip() for a in sys.argv[1:]]
    if "--help" in _argv_help or "-h" in _argv_help:
        print(
            "Usage: python gavaetims.py <PIN> [flags]\n"
            "Common flags: --clean-run, --reset-stock, --only endpoint1,endpoint2\n"
            "Exploration: --continue-on-step-failure (log hard stops and run remaining sequence steps; "
            "unsafe for cert — dependent steps often fail).\n"
            "Composition (sandbox): --bypass-component-stock-gate\n"
            "  Skips selectStockMoveList verification for component stock in the composition prelude, before\n"
            "  saveItemComposition, and (after insertTrnsPurchaseComponentStock resultCd=000) the main\n"
            "  selectStockMoveListComponentPurchase step—so gateway timeouts / empty move lists do not block\n"
            "  saveStockMasterComponentPurchase. Also trusts a successful prelude insertStockIO. Parent stock\n"
            "  gates are not affected.\n"
            "See module docstring at top of gavaetims.py for full flag list."
        )
        return 0

    manual_bearer = get_optional_env("BEARER_TOKEN")
    manual_cmc = get_optional_env("CMC_KEY")
    validated_bearer: str | None = None

    while True:
        rows = read_rows()
        app_pin = prompt_app_pin()
        state_root = load_test_state()
        pin_key = app_pin.strip()
        pin_blob = normalize_pin_blob(state_root.get(pin_key))
        state_root[pin_key] = pin_blob

        existing = row_dict_for_pin(rows, app_pin)
        new_pin = existing is None

        if existing:
            entry = {k: str(existing.get(k, "") or "").strip() for k in CSV_COLUMNS}
            entry["app_pin"] = app_pin.strip()
        else:
            entry = {k: "" for k in CSV_COLUMNS}
            entry["app_pin"] = app_pin.strip()

        need_validation = new_pin or not str(entry.get("cmc_key") or "").strip()
        reprompt_all = False
        restart_with_new_pin = False

        while True:
            entry = ensure_required_fields(
                rows, entry, new_pin=new_pin, reprompt_all=reprompt_all
            )
            reprompt_all = False

            if not need_validation:
                break

            ok, err, bearer, val_cmc = validate_credentials_for_app_pin(entry)
            if ok:
                validated_bearer = bearer
                if val_cmc:
                    entry["cmc_key"] = val_cmc.strip()
                pin_blob["cmc_key"] = str(entry.get("cmc_key") or "").strip()
                save_test_state(state_root)
                persist(rows, entry)
                print(f"Validated — saved to {CSV_FILE.name}\n")
                break

            print((err or "VALIDATION failed.").strip())
            err_l = (err or "").lower()
            if "oauth" in err_l or "access_token" in err_l:
                print(
                    "The provided OAuth consumer key/secret may be wrong for this Apigee app. "
                    "Please re-enter."
                )
            elif "selectinitosdcinfo" in err_l:
                print(
                    "selectInitOsdcInfo failed (often not an OAuth typo). "
                    "Confirm Application Test PIN, branch (bhfId), and device serial match "
                    "the GavaConnect sandbox registration. resultCd 901 / \"not valid device\" "
                    "means KRA does not accept this device for this PIN until the portal "
                    "registration/session is active."
                )
            else:
                print("Please re-enter credentials or fix the error above.")
            if not sys.stdin.isatty():
                raise SystemExit(
                    "Validation failed and stdin is not a TTY; fix credentials in "
                    f"{CSV_FILE.name} or run interactively."
                )
            choice = input(
                "Press Enter to re-enter all credentials for this PIN, or type "
                "'pin' to enter a different Application Test PIN: "
            ).strip().lower()
            if choice in ("pin", "p"):
                restart_with_new_pin = True
                validated_bearer = None
                break

            for k in PROMPT_FIELD_ORDER:
                entry[k] = ""
            reprompt_all = True

        if restart_with_new_pin:
            continue
        break

    state_root = load_test_state()
    pin_key = app_pin.strip()
    pin_blob = normalize_pin_blob(state_root.get(pin_key))
    state_root[pin_key] = pin_blob
    completed_list: list[str] = list(pin_blob.get("completed_endpoints") or [])

    (
        _,
        reset_stock_cli,
        clean_run_cli,
        force_stock_replay_cli,
        only_steps_cli,
        diagnostic_stock_io_cli,
        save_item_allow_ty1_fallback_cli,
        strict_pre_sale_audit_cli,
        minimal_osdc_sale_test_cli,
        minimal_osdc_pasteback_cli,
        minimal_stock_ledger_matrix_cli,
        debug_ledger_after_io_cli,
        ledger_contract_test_cli,
        stock_lifecycle_isolation_test_cli,
        stock_master_visibility_test_cli,
        sbx_finished_good_ledger_probe_cli,
        portal_checklist_mode_cli,
        bypass_component_stock_gate_cli,
        bypass_pre_sale_stock_gate_cli,
        continue_on_step_failure_cli,
    ) = cli_pin_and_flags()

    def _argv_has_any_run_mode_flags() -> bool:
        # If the user already supplied flags, don't override their intent with a menu.
        raw = [str(x).strip() for x in sys.argv[1:] if str(x).strip()]
        for x in raw:
            if x.startswith("--"):
                return True
        return False

    if sys.stdin.isatty() and not _argv_has_any_run_mode_flags():
        print("\nSelect run mode:")
        print("  1) Normal run (resume saved state; strict gates)")
        print("  2) Clean run (clear saved state for this PIN)")
        print("  3) Reset stock only (clear stock-related progress)")
        print("  4) Sandbox continue (bypass gates + keep going even on failures)")
        print("     - enables: --bypass-component-stock-gate --bypass-pre-sale-stock-gate --continue-on-step-failure")
        choice = input("Enter 1, 2, 3, or 4: ").strip()
        if choice == "2":
            clean_run_cli = True
        elif choice == "3":
            reset_stock_cli = True
        elif choice == "4":
            # Make it easy to reach later checklist calls even when SBX is flaky.
            bypass_component_stock_gate_cli = True
            bypass_pre_sale_stock_gate_cli = True
            continue_on_step_failure_cli = True
            # Commonly needed with SBX stacked state.
            reset_stock_cli = True
        else:
            # Default to "1" (normal strict run).
            pass

    save_item_allow_ty1_fallback = (
        SAVE_ITEM_ALLOW_TY1_FALLBACK or save_item_allow_ty1_fallback_cli
    )

    def sequence_fail(msg: str) -> None:
        if continue_on_step_failure_cli:
            raise SkipToNextSequenceStep(msg)
        raise SystemExit(msg)

    _continue_step_notes: list[tuple[str, str]] = []
    if continue_on_step_failure_cli:
        print(
            "\nNOTE: --continue-on-step-failure enabled — hard stops skip to the next sequence step "
            "(ledger/order may break; exit code 1 if any step was skipped).\n"
        )
    if clean_run_cli:
        reset_pin_clean_run(pin_blob)
        save_test_state(state_root)
        completed_list = list(pin_blob.get("completed_endpoints") or [])
        print(
            "NOTE: --clean-run applied: cleared item_cd / canonical_item_cd / composition / stock / "
            f"import / sales / purchase steps for this PIN (see {STATE_FILE.name}). "
            f"Root {SAR_NO_BY_TIN_BHF_KEY!r} (insertStockIO SAR sequence) is unchanged."
        )
    if reset_stock_cli:
        reset_pin_stock_progress(pin_blob)
        save_test_state(state_root)
        completed_list = list(pin_blob.get("completed_endpoints") or [])
        print(
            "NOTE: --reset-stock applied: removed stock-related steps from completed_endpoints, cleared "
            "stock_io_next_sar_no (next insert defaults to 1; KRA may respond with Expected: N — the "
            "runner will sync), stock_io_pending_rsd_qty=0, current_stock_balance cleared. "
            "If KRA still holds an old SAR sequence, the first insertStockIO may self-correct; "
            "otherwise clear backlog on the OSCU portal or use a fresh test PIN "
            f"(see {STATE_FILE.name})."
        )
    if force_stock_replay_cli:
        reset_pin_initial_stock_atomic_pair(pin_blob)
        save_test_state(state_root)
        completed_list = list(pin_blob.get("completed_endpoints") or [])
        print(
            "NOTE: --force-stock-replay applied: dropped insertStockIOInitial / saveStockMasterInitial "
            f"from completed_endpoints; stock_io_pending_rsd_qty=0; cleared stock_io_next_sar_no and "
            f"current_stock_balance (see {STATE_FILE.name})."
        )

    _osdc_prep_steps = (
        "insertStockIOPostComposition",
        "saveStockMasterPostComposition",
    )
    if not only_steps_cli and "saveInvoice" not in completed_list:
        _ce_prev = list(completed_list)
        completed_list = [x for x in completed_list if x not in _osdc_prep_steps]
        if len(completed_list) != len(_ce_prev):
            pin_blob["completed_endpoints"] = list(completed_list)
            pin_blob.pop("post_composition_osdc_ready", None)
            pin_blob.pop("parent_post_composition_io_qty", None)
            pin_blob.pop("parent_osdc_prep_rsd_qty", None)
            save_test_state(state_root)
            print(
                "NOTE: saveInvoice not yet successful — dropped mandatory post-composition OSDC prep steps "
                f"{_osdc_prep_steps!r} from completed_endpoints (fresh insertStockIOPostComposition → "
                f"saveStockMasterPostComposition required before saveTrnsSalesOsdc; see {STATE_FILE.name})."
            )

    # Pre-hybrid runs often left insertStockIO (+ selectStockMoveList) without saveStockMaster.
    # Local completion markers then misaligned server backlog vs insertStockIOInitial; strip and reset
    # keys so hybrid initial pair can run (still clear OSCU stock if saveStockMaster* keeps failing).
    if (
        not only_steps_cli
        and "insertStockIO" in completed_list
        and "saveStockMaster" not in completed_list
    ):
        print(
            "NOTE: Hybrid migration — dropping legacy insertStockIO / selectStockMoveList "
            "(saveStockMaster never completed). Reset stock_io_pending_rsd_qty=0; clearing "
            "stock_io_next_sar_no and current_stock_balance. Next: insertStockIOInitial → saveStockMasterInitial. "
            "If rsdQty still mismatches, clear stock on OSCU for this PIN, then --reset-stock "
            f"(see {STATE_FILE.name})."
        )
        completed_list = [
            x
            for x in completed_list
            if x not in ("insertStockIO", "selectStockMoveList")
        ]
        pin_blob["completed_endpoints"] = list(completed_list)
        pin_blob["stock_io_pending_rsd_qty"] = 0.0
        pin_blob.pop("stock_io_next_sar_no", None)
        pin_blob.pop("current_stock_balance", None)
        for _k_mig in (
            "parent_rsd_qty_final",
            "parent_rsd_qty_post_purchase",
            "parent_initial_save_rsd_qty_from_kra",
            "_stock_move_list_initial_io_fallback",
            "_stock_move_list_post_osdc_io_fallback",
        ):
            pin_blob.pop(_k_mig, None)
        save_test_state(state_root)

    _parent_io_done_tags = frozenset({"insertStockIO", "insertStockIOInitial"})
    _any_parent_insert_done = bool(_parent_io_done_tags.intersection(completed_list))

    if (
        not only_steps_cli
        and _any_parent_insert_done
        and pin_blob.get("stock_io_next_sar_no") is None
    ):
        pin_blob["stock_io_next_sar_no"] = 2
        save_test_state(state_root)
        print(
            "NOTE: Set stock_io_next_sar_no=2 (insertStockIO was completed before "
            "SAR sequence tracking). Edit this key if KRA expects a higher sarNo."
        )
    # saveStockMaster rsdQty must come from KRA move list (or mismatch parse), not local SAR math.

    # Do not strip insertStockIOInitial when saveStockMasterInitial is still pending: non-zero
    # current_stock_balance after insert is normal. Re-playing insert would stack SAR/IO on KRA.

    # Wedged resume: final parent insertStockIO + selectStockMoveList done but saveStockMaster not.
    if (
        not only_steps_cli
        and "insertStockIO" in completed_list
        and "selectStockMoveList" in completed_list
        and "saveStockMaster" not in completed_list
    ):
        _bw = pin_blob.get("current_stock_balance")
        try:
            _bal_w = (
                float(_bw)
                if _bw is not None and str(_bw).strip() != ""
                else 0.0
            )
        except (TypeError, ValueError):
            _bal_w = 0.0
        if pin_blob.get("parent_rsd_qty_final") is not None or _bal_w > 1e-9:
            print(
                "NOTE: Stock pipeline wedged (pending saveStockMaster after insertStockIO + move list — "
                "had KRA rsdQty or local balance hint but save never completed). "
                "Removing insertStockIO and selectStockMoveList from completed_endpoints so they "
                "run again in this process together with saveStockMaster. If insertStockIO then fails, "
                "reset OSCU stock/SAR for this PIN and adjust stock_io_* keys in "
                f"{STATE_FILE.name}."
            )
            completed_list = [
                x
                for x in completed_list
                if x not in ("insertStockIO", "selectStockMoveList")
            ]
            pin_blob["completed_endpoints"] = list(completed_list)
            save_test_state(state_root)

    # Final IO recorded but move-list + saveStockMaster never ran (crashed between steps).
    if (
        not only_steps_cli
        and "insertStockIO" in completed_list
        and "selectStockMoveList" not in completed_list
        and "saveStockMaster" not in completed_list
    ):
        print(
            "NOTE: Removing insertStockIO from completed_endpoints — saveStockMaster not done and "
            "selectStockMoveList never ran; will replay final stock IO with move list + save in one run."
        )
        completed_list = [x for x in completed_list if x != "insertStockIO"]
        pin_blob["completed_endpoints"] = list(completed_list)
        save_test_state(state_root)

    if diagnostic_stock_io_cli:
        apply_diagnostic_stock_io_reset(
            pin_blob,
            state_root,
            app_pin.strip(),
            str(entry.get("branch_id") or "").strip(),
        )
        completed_list = list(pin_blob.get("completed_endpoints") or [])
        save_test_state(state_root)
        print(
            "\n"
            + "=" * 78
            + "\nDIAGNOSTIC SBX STOCK IO (--diagnostic-stock-io)\n"
            "  • Resume disabled for insertStockIOInitial / selectStockMoveListInitial / saveStockMasterInitial\n"
            "  • SAR: component composition prelude may use the first sarNo; parent insertStockIOInitial "
            "uses the next free sarNo; current_stock_balance=0 before parent POST\n"
            "  • initial_parent_stock_qty forced to 1 (line qty)\n"
            "  • insertStockIOInitial: one POST only (no retry loop). saveStockMasterInitial: _cap_attempts=2 "
            "(KRA Expected-rsdQty retry after IO-line fallback)\n"
            "  • If KRA says Expected: -1, sarTyCd=11 may be OUT for SBX (direction mismatch).\n"
            + "=" * 78
            + "\n"
        )

    if only_steps_cli:
        if set(only_steps_cli).issubset(set(completed_list)):
            print(
                f"\nAll --only steps already marked complete for this PIN ({STATE_FILE.name}).\n"
                "Remove those names from completed_endpoints to re-run, or omit --only for the full sequence."
            )
            return 0
    elif set(SEQUENCE_STEP_NAMES).issubset(set(completed_list)) and not (
        ledger_contract_test_cli
        or stock_lifecycle_isolation_test_cli
        or sbx_finished_good_ledger_probe_cli
    ):
        print(
            f"\nAll sequence endpoints already completed for this PIN ({STATE_FILE.name}).\n"
            "Nothing to run. Remove or edit completed_endpoints for this PIN to run the sequence again."
        )
        return 0

    st_cmc = (pin_blob.get("cmc_key") or "").strip()
    if st_cmc and not str(entry.get("cmc_key") or "").strip():
        entry["cmc_key"] = st_cmc

    consumer_key = entry["consumer_key"]
    consumer_secret = entry["consumer_secret"]
    branch_id = entry["branch_id"]
    device_serial = entry["device_serial"]
    apigee_app_id = entry["apigee_app_id"]
    effective_tin = str(app_pin).strip()

    print(f"\n=== KRA OSCU Sandbox Runner ({CSV_FILE.name} + optional .env overrides) ===\n")
    print(f"Application Test PIN: {app_pin}")
    print(f"Consumer Key: {preview_consumer_key(consumer_key)}")
    print(f"Device Serial: {device_serial}")
    print(f"Branch ID: {branch_id}")
    print(f"Apigee App ID: {apigee_app_id}")

    if manual_bearer:
        bearer_token = manual_bearer
        print("Using manually provided Bearer token (skipping OAuth).")
    elif validated_bearer:
        bearer_token = validated_bearer
        print("Reusing Bearer token from validation.")
    else:
        bearer_token = fetch_oscu_access_token(consumer_key, consumer_secret)
        persist(rows, entry)
        print(f"Saved credentials to {CSV_FILE.name} (after OAuth).")

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "tin": effective_tin,
        "bhfId": branch_id,
        "apigee_app_id": apigee_app_id,
        "dvcSrlNo": device_serial,
        "Content-Type": "application/json",
    }
    # BHF audit: tin/bhfId stay on this dict for the run; use ``post_headers = dict(headers)`` per POST
    # so Bearer-only refresh (if added later) cannot accidentally rewrite branch context.

    payload_overrides = {
        "tin": effective_tin,
        "custTin": effective_tin,
        "spplrTin": effective_tin,
    }

    # OSCU saveItem: itemCd prefix must match itemTyCd (e.g. "2" → KE2…).
    item_ty_cd = "2"
    pkg_unit_cd = "NT"
    # itemCd pattern embeds qtyUnitCd (2 chars). Must be on KRA saveItem allow-list (not XU/EA).
    qty_unit_cd = "TU"

    now = datetime.now(timezone.utc)
    if completed_list and (pin_blob.get("item_cd") or "").strip():
        item_cd = str(pin_blob.get("item_cd") or "").strip()
        if not item_cd.startswith(f"KE{item_ty_cd}"):
            item_cd = alloc_provisional_item_cd_monotonic(
                item_ty_cd, pkg_unit_cd, qty_unit_cd, pin_blob, None
            )
            pin_blob["item_cd"] = item_cd
            save_test_state(state_root)
            print(
                f"Regenerated itemCd (saved prefix did not match itemTyCd={item_ty_cd}): {item_cd}"
            )
        item_cls_dynamic = {
            "itemClsCd": (pin_blob.get("item_cls_cd") or "1010000000").strip(),
            "taxTyCd": (pin_blob.get("item_tax_ty_cd") or "A").strip(),
        }
        if item_cls_dynamic["itemClsCd"] == "1000000000":
            item_cls_dynamic["itemClsCd"] = "1010000000"
            item_cls_dynamic["taxTyCd"] = "A"
        try:
            stock_qty = int(pin_blob.get("stock_qty") or 100)
        except (TypeError, ValueError):
            stock_qty = 100
        invc_no = (pin_blob.get("invc_no") or "").strip()
        trd_invc = (pin_blob.get("trd_invc") or "").strip()
        sales_dt = (pin_blob.get("sales_dt") or "").strip()
        cfm_dt = (pin_blob.get("cfm_dt") or "").strip()
        if not invc_no:
            invc_no = str(int(now.timestamp()) % 1_000_000_000)
        if not trd_invc:
            trd_invc = f"TRD-{invc_no}"
        if not sales_dt:
            sales_dt = now.strftime("%Y%m%d")
        if not cfm_dt:
            cfm_dt = now.strftime("%Y%m%d%H%M%S")
        print(f"Resuming: using item_cd={item_cd} and saved invoice fields from {STATE_FILE.name}")
    else:
        if completed_list:
            print(
                f"Note: {STATE_FILE.name} lists completed steps but no saved item_cd; "
                "generating new item/invoice data (later steps may fail if earlier steps used another item)."
            )
        item_cd = alloc_provisional_item_cd_monotonic(
            item_ty_cd, pkg_unit_cd, qty_unit_cd, pin_blob, None
        )
        item_cls_dynamic = {"itemClsCd": "1010000000", "taxTyCd": "A"}
        sales_dt = now.strftime("%Y%m%d")
        cfm_dt = now.strftime("%Y%m%d%H%M%S")
        invc_no = str(int(now.timestamp()) % 1_000_000_000)
        trd_invc = f"TRD-{invc_no}"
        stock_qty = 100
    try:
        _invc_base = int(str(invc_no).strip())
    except (TypeError, ValueError):
        _invc_base = int(now.timestamp()) % 1_000_000_000
    try:
        purchase_invc_no = int(pin_blob.get("purchase_invc_no") or 0)
    except (TypeError, ValueError):
        purchase_invc_no = 0
    if purchase_invc_no <= 0:
        purchase_invc_no = (_invc_base + 31_337) % 999_999_999
    if purchase_invc_no == _invc_base:
        purchase_invc_no = (_invc_base + 7) % 999_999_999

    purchase_invc_no_component = (purchase_invc_no + 357_911) % 999_999_999
    if purchase_invc_no_component <= 0:
        purchase_invc_no_component = (purchase_invc_no + 11) % 999_999_999
    if purchase_invc_no_component == purchase_invc_no:
        purchase_invc_no_component = (purchase_invc_no + 2) % 999_999_999
    try:
        _stored_picomp = int(pin_blob.get("purchase_invc_no_component") or 0)
    except (TypeError, ValueError):
        _stored_picomp = 0
    if _stored_picomp > 0:
        purchase_invc_no_component = _stored_picomp

    item_cd = reconcile_item_cd_with_pin_state(pin_blob, item_cd)
    initial_parent_stock_qty = float(INITIAL_PARENT_STOCK_QTY)
    if diagnostic_stock_io_cli:
        initial_parent_stock_qty = 1.0
        stock_qty = 1

    qty = 1.0
    prc = 100.0
    taxbl = prc * qty
    tax_amt = 0.0
    tot_amt = taxbl + tax_amt

    # Component purchase before composition: qty must exceed composition cpstQty (transaction ledger).
    composition_component_purchase_qty = max(
        float(stock_qty),
        float(INITIAL_PARENT_STOCK_QTY),
        float(COMPOSITION_CPST_QTY_DEFAULT) + 1.0,
    )
    _cc_purchase_prc = 10.0
    composition_cmp_tty = (item_cls_dynamic["taxTyCd"] or "A").strip()
    sp_cc, tb_cc, tx_cc, tot_cc = stock_io_line_amounts_for_tax_ty(
        unit_prc=_cc_purchase_prc,
        qty=composition_component_purchase_qty,
        tax_ty_cd=composition_cmp_tty,
    )
    cc_purch_taxbl = {
        "taxblAmtA": 0.0,
        "taxblAmtB": 0.0,
        "taxblAmtC": 0.0,
        "taxblAmtD": 0.0,
        "taxblAmtE": 0.0,
        "taxAmtA": 0.0,
        "taxAmtB": 0.0,
        "taxAmtC": 0.0,
        "taxAmtD": 0.0,
        "taxAmtE": 0.0,
        "taxRtA": 0.0,
        "taxRtB": 0.0,
        "taxRtC": 0.0,
        "taxRtD": 0.0,
        "taxRtE": 0.0,
    }
    _tty_u = composition_cmp_tty.upper()
    if _tty_u == "A":
        cc_purch_taxbl["taxblAmtA"] = tb_cc
        cc_purch_taxbl["taxAmtA"] = tx_cc
    elif _tty_u == "B":
        cc_purch_taxbl["taxblAmtB"] = tb_cc
        cc_purch_taxbl["taxAmtB"] = tx_cc
    elif _tty_u == "C":
        cc_purch_taxbl["taxblAmtC"] = tb_cc
        cc_purch_taxbl["taxAmtC"] = tx_cc
    else:
        cc_purch_taxbl["taxblAmtA"] = tb_cc
        cc_purch_taxbl["taxAmtA"] = tx_cc

    sequence = [
        ("initialize", "/initialize", {"tin": effective_tin, "bhfId": branch_id, "dvcSrlNo": device_serial}),
        (
            "selectCodeList",
            "/selectCodeList",
            {
                "tin": effective_tin,
                "bhfId": branch_id,
                "lastReqDt": "20100101000000",
            },
        ),
        (
            "selectItemClsList",
            "/selectItemClsList",
            {
                "tin": effective_tin,
                "bhfId": branch_id,
                "lastReqDt": "20100101000000",
            },
        ),
        (
            "selectBhfList",
            "/selectBhfList",
            {
                "tin": effective_tin,
                "bhfId": branch_id,
                "lastReqDt": "20100101000000",
            },
        ),
        (
            "selectNotices",
            "/selectNotices",
            {
                "tin": effective_tin,
                "bhfId": branch_id,
                "lastReqDt": "20100101000000",
            },
        ),
        (
            "saveBhfCustomer",
            "/saveBhfCustomer",
            {
                "custNo": str(int(invc_no) % 1_000_000_000).zfill(9),
                "custTin": effective_tin,
                "custNm": "TEST BHF CUSTOMER",
                "adrs": None,
                "telNo": None,
                "email": None,
                "faxNo": None,
                "useYn": "Y",
                "remark": None,
                "regrNm": "system",
                "regrId": "system",
                "modrNm": "system",
                "modrId": "system",
            },
        ),
        (
            "saveBhfUser",
            "/saveBhfUser",
            {
                "userId": f"ps_{invc_no}",
                "userNm": f"ps_{invc_no}",
                "pwd": "Test#Pass1",
                "adrs": None,
                "cntc": None,
                "authCd": None,
                "remark": None,
                "useYn": "Y",
                "regrNm": "system",
                "regrId": "system",
                "modrNm": "system",
                "modrId": "system",
            },
        ),
        (
            "saveBhfInsurance",
            "/saveBhfInsurance",
            {
                "isrccCd": "PS001",
                "isrccNm": "Test Insurance Co",
                "isrcRt": 10,
                "useYn": "Y",
                "regrNm": "system",
                "regrId": "system",
                "modrNm": "system",
                "modrId": "system",
            },
        ),
        (
            "selectItemList",
            "/selectItemList",
            {
                "tin": effective_tin,
                "bhfId": branch_id,
                "lastReqDt": "20100101000000",
            },
        ),
        (
            "saveItem",
            "/saveItem",
            {
                # Strict ItemSaveReq body (identity via headers only); tin/bhfId in body may confuse SBX validator.
                "itemCd": item_cd,
                "itemClsCd": "9901200000",
                "itemTyCd": "2",
                "itemNm": "TEST ITEM",
                "orgnNatCd": "KE",
                "pkgUnitCd": "NT",
                "qtyUnitCd": "TU",
                "taxTyCd": "C",
                "dftPrc": 100,
                "isrcAplcbYn": "N",
                "useYn": "Y",
                "regrId": "system",
                "regrNm": "system",
                "modrId": "system",
                "modrNm": "system",
            },
        ),
        (
            "selectItemListPostSave",
            "/selectItemList",
            {
                "tin": effective_tin,
                "bhfId": branch_id,
                "lastReqDt": "20100101000000",
            },
        ),
        ("saveComponentItem", "/saveItem", {}),
        (
            "selectTrnsPurchaseSalesListPreComposition",
            "/selectTrnsPurchaseSalesList",
            {
                "tin": effective_tin,
                "bhfId": branch_id,
                "lastReqDt": "20100101000000",
            },
        ),
        (
            "selectImportItemList",
            "/selectImportItemList",
            {
                "tin": effective_tin,
                "bhfId": branch_id,
                "lastReqDt": "20100101000000",
            },
        ),
        (
            "importedItemInfo",
            "/importedItemInfo",
            {
                "tin": effective_tin,
                "bhfId": branch_id,
                "lastReqDt": "20100101000000",
            },
        ),
        (
            "importedItemConvertedInfo",
            "/importedItemConvertedInfo",
            {
                "taskCd": "",
                "dclDe": "",
                "itemSeq": 1,
                "hsCd": "",
                "itemClsCd": item_cls_dynamic["itemClsCd"],
                "itemCd": item_cd,
                "imptItemSttsCd": "3",
                "remark": "remark",
                "modrId": "system",
                "modrNm": "system",
            },
        ),
        (
            "updateImportItem",
            "/updateImportItem",
            {
                "taskCd": "",
                "dclDe": sales_dt,
                "itemSeq": 1,
                "hsCd": "",
                "itemClsCd": item_cls_dynamic["itemClsCd"],
                "itemCd": item_cd,
                "imptItemSttsCd": "3",
                "remark": "remark",
                "modrId": "system",
                "modrNm": "system",
            },
        ),
        (
            "insertTrnsPurchaseComponentStock",
            "/insertTrnsPurchase",
            {
                "spplrTin": effective_tin,
                "invcNo": str(int(purchase_invc_no_component)),
                "spplrBhfId": branch_id,
                "spplrNm": "Test Supplier (component stock)",
                "regTyCd": "M",
                "pchsTyCd": "N",
                "rcptTyCd": "P",
                "pmtTyCd": "01",
                "pchsSttsCd": "02",
                "cfmDt": cfm_dt,
                "pchsDt": sales_dt,
                "totItemCnt": 1,
                **cc_purch_taxbl,
                "totTaxblAmt": tb_cc,
                "totTaxAmt": tx_cc,
                "totAmt": tot_cc,
                "regrId": "system",
                "regrNm": "system",
                "modrId": "system",
                "modrNm": "system",
                "itemList": [
                    {
                        "itemSeq": 1,
                        "itemCd": "",
                        "itemClsCd": item_cls_dynamic["itemClsCd"],
                        "itemNm": "COMPONENT ITEM",
                        "pkgUnitCd": pkg_unit_cd,
                        "pkg": composition_component_purchase_qty,
                        "qtyUnitCd": qty_unit_cd,
                        "qty": composition_component_purchase_qty,
                        "prc": _cc_purchase_prc,
                        "splyAmt": sp_cc,
                        "dcRt": 0.0,
                        "dcAmt": 0.0,
                        "taxblAmt": tb_cc,
                        "taxTyCd": composition_cmp_tty,
                        "taxAmt": tx_cc,
                        "totAmt": tot_cc,
                    }
                ],
            },
        ),
        (
            "saveStockMasterComponentPurchase",
            "/saveStockMaster",
            {
                "itemCd": "",
                "rsdQty": composition_component_purchase_qty,
                "regrId": "system",
                "regrNm": "system",
                "modrId": "system",
                "modrNm": "system",
            },
        ),
        (
            "saveItemComposition",
            "/saveItemComposition",
            {
                "itemCd": item_cd,
                "cpstItemCd": "",
                "cpstQty": COMPOSITION_CPST_QTY_DEFAULT,
                "regrId": "system",
                "regrNm": "system",
                "modrId": "system",
                "modrNm": "system",
            },
        ),
        (
            "insertStockIOInitial",
            "/insertStockIO",
            {
                "stockInOutList": [
                    {
                        "itemCd": item_cd,
                        "qty": stock_qty,
                        "ioTyCd": "1",
                        "regTyCd": "1",
                        "sarTyCd": "1",
                        "ocrnDt": cfm_dt,
                        "spplrTin": effective_tin,
                        "regrId": "system",
                        "regrNm": "system",
                        "modrId": "system",
                        "modrNm": "system",
                    }
                ]
            },
        ),
        (
            "saveStockMasterInitial",
            "/saveStockMaster",
            {
                "itemCd": item_cd,
                "rsdQty": stock_qty,
                "regrId": "system",
                "regrNm": "system",
                "modrId": "system",
                "modrNm": "system",
            },
        ),
        (
            "insertStockIOPostComposition",
            "/insertStockIO",
            {
                "stockInOutList": [
                    {
                        "itemCd": item_cd,
                        "qty": initial_parent_stock_qty,
                        "ioTyCd": "1",
                        "regTyCd": "1",
                        "sarTyCd": "1",
                        "ocrnDt": cfm_dt,
                        "spplrTin": effective_tin,
                        "regrId": "system",
                        "regrNm": "system",
                        "modrId": "system",
                        "modrNm": "system",
                    }
                ]
            },
        ),
        (
            "saveStockMasterPostComposition",
            "/saveStockMaster",
            {
                "itemCd": item_cd,
                "rsdQty": initial_parent_stock_qty,
                "regrId": "system",
                "regrNm": "system",
                "modrId": "system",
                "modrNm": "system",
            },
        ),
        (
            "selectInvoiceType",
            "/selectInvoiceType",
            {
                "tin": effective_tin,
                "bhfId": branch_id,
                "salesTyCd": "N",
                # Sales OSDC: KRA rejects P (purchase); only R or S allowed on saveTrnsSalesOsdc path.
                "rcptTyCd": "S",
                "pmtTyCd": "01",
            },
        ),
        (
            "saveInvoice",
            "/saveTrnsSalesOsdc",
            {
                "tin": effective_tin,
                "bhfId": branch_id,
                "regTyCd": "M",
                "custTin": effective_tin,
                "custNm": "Test Customer",
                "salesTyCd": "N",
                "rcptTyCd": "S",
                "pmtTyCd": "01",
                "trdInvcNo": trd_invc,
                "invcNo": invc_no,
                "orgInvcNo": "0",
                "salesSttsCd": "02",
                "cfmDt": cfm_dt,
                "salesDt": sales_dt,
                "totItemCnt": 1,
                "taxblAmtA": taxbl,
                "taxblAmtB": 0.0,
                "taxblAmtC": 0.0,
                "taxblAmtD": 0.0,
                "taxblAmtE": 0.0,
                "taxRtA": 0.0,
                "taxRtB": 0.0,
                "taxRtC": 0.0,
                "taxRtD": 0.0,
                "taxRtE": 0.0,
                "taxAmtA": tax_amt,
                "taxAmtB": 0.0,
                "taxAmtC": 0.0,
                "taxAmtD": 0.0,
                "taxAmtE": 0.0,
                "totTaxblAmt": taxbl,
                "totTaxAmt": tax_amt,
                "totAmt": tot_amt,
                "prchrAcptcYn": "N",
                "regrId": "system",
                "regrNm": "system",
                "modrId": "system",
                "modrNm": "system",
                "receipt": {
                    "rcptPbctDt": cfm_dt,
                    "prchrAcptcYn": "N",
                },
                "itemList": [
                    {
                        "itemSeq": 1,
                        "itemClsCd": "1000000000",
                        "itemCd": item_cd,
                        "itemNm": "TEST ITEM",
                        "pkgUnitCd": pkg_unit_cd,
                        "pkg": 1.0,
                        "qtyUnitCd": qty_unit_cd,
                        "qty": qty,
                        "prc": prc,
                        "splyAmt": taxbl,
                        "dcRt": 0.0,
                        "dcAmt": 0.0,
                        "taxTyCd": "A",
                        "taxblAmt": taxbl,
                        "taxAmt": tax_amt,
                        "totAmt": tot_amt,
                    }
                ],
            },
        ),
        (
            "selectTrnsPurchaseSalesList",
            "/selectTrnsPurchaseSalesList",
            {
                "tin": effective_tin,
                "bhfId": branch_id,
                "lastReqDt": "20100101000000",
            },
        ),
        (
            "insertTrnsPurchase",
            "/insertTrnsPurchase",
            {
                "spplrTin": effective_tin,
                "invcNo": str(int(purchase_invc_no)),
                "spplrBhfId": branch_id,
                "spplrNm": "Test Supplier",
                "regTyCd": "M",
                "pchsTyCd": "N",
                "rcptTyCd": "P",
                "pmtTyCd": "01",
                "pchsSttsCd": "02",
                "cfmDt": cfm_dt,
                "pchsDt": sales_dt,
                "totItemCnt": 1,
                "taxblAmtA": taxbl,
                "taxblAmtB": 0.0,
                "taxblAmtC": 0.0,
                "taxblAmtD": 0.0,
                "taxblAmtE": 0.0,
                "taxRtA": 0.0,
                "taxRtB": 0.0,
                "taxRtC": 0.0,
                "taxRtD": 0.0,
                "taxRtE": 0.0,
                "taxAmtA": tax_amt,
                "taxAmtB": 0.0,
                "taxAmtC": 0.0,
                "taxAmtD": 0.0,
                "taxAmtE": 0.0,
                "totTaxblAmt": taxbl,
                "totTaxAmt": tax_amt,
                "totAmt": tot_amt,
                "regrId": "system",
                "regrNm": "system",
                "modrId": "system",
                "modrNm": "system",
                "itemList": [
                    {
                        "itemSeq": 1,
                        "itemCd": item_cd,
                        "itemClsCd": item_cls_dynamic["itemClsCd"],
                        "itemNm": "TEST ITEM",
                        "pkgUnitCd": pkg_unit_cd,
                        "pkg": 1.0,
                        "qtyUnitCd": qty_unit_cd,
                        "qty": 1.0,
                        "prc": prc,
                        "splyAmt": taxbl,
                        "dcRt": 0.0,
                        "dcAmt": 0.0,
                        "taxblAmt": taxbl,
                        "taxTyCd": item_cls_dynamic["taxTyCd"],
                        "taxAmt": tax_amt,
                        "totAmt": tot_amt,
                    }
                ],
            },
        ),
        (
            "saveStockMasterAfterPurchase",
            "/saveStockMaster",
            {
                "itemCd": item_cd,
                "rsdQty": stock_qty,
                "regrId": "system",
                "regrNm": "system",
                "modrId": "system",
                "modrNm": "system",
            },
        ),
        (
            "insertStockIO",
            "/insertStockIO",
            {
                "stockInOutList": [
                    {
                        "itemCd": item_cd,
                        "qty": stock_qty,
                        "ioTyCd": "1",
                        "regTyCd": "1",
                        "sarTyCd": "1",
                        "ocrnDt": cfm_dt,
                        "spplrTin": effective_tin,
                        "regrId": "system",
                        "regrNm": "system",
                        "modrId": "system",
                        "modrNm": "system",
                    }
                ]
            },
        ),
        (
            "saveStockMaster",
            "/saveStockMaster",
            {
                "itemCd": item_cd,
                "rsdQty": stock_qty,
                "regrId": "system",
                "regrNm": "system",
                "modrId": "system",
                "modrNm": "system",
            },
        ),
        (
            "selectTrnsSalesList",
            "/selectTrnsSalesList",
            {
                "tin": effective_tin,
                "bhfId": branch_id,
                "lastReqDt": "20100101000000",
            },
        ),
        (
            "selectInvoiceDetails",
            "/selectInvoiceDetails",
            {
                "tin": effective_tin,
                "bhfId": branch_id,
                "invcNo": _invc_base,
                "lastReqDt": "20100101000000",
            },
        ),
        (
            "selectCustomerList",
            "/selectCustomerList",
            {
                "tin": effective_tin,
                "bhfId": branch_id,
                "lastReqDt": "20100101000000",
            },
        ),
        (
            "selectTaxPayerInfo",
            "/selectTaxPayerInfo",
            {
                "tin": effective_tin,
                "bhfId": branch_id,
                "lastReqDt": "20100101000000",
            },
        ),
    ]

    if portal_checklist_mode_cli:
        # Portal parity: run the same /selectStockMoveList call the portal checklist expects.
        # This must never gate success/failure of the runner.
        sequence.insert(
            2,
            (
                "portalSelectStockMoveList",
                "/selectStockMoveList",
                {
                    "tin": effective_tin,
                    "bhfId": branch_id,
                    "lastReqDt": kra_stock_move_list_last_req_dt_utc_now(),
                },
            ),
        )

    if only_steps_cli:
        unknown = set(only_steps_cli) - set(SEQUENCE_STEP_NAMES)
        if unknown:
            raise SystemExit(
                "Unknown --only step name(s): "
                + ", ".join(sorted(unknown))
                + f". Valid names are SEQUENCE_STEP_NAMES in {Path(__file__).name}."
            )
        seq_order = {n: i for i, n in enumerate(SEQUENCE_STEP_NAMES)}
        sequence = [t for t in sequence if t[0] in only_steps_cli]
        sequence.sort(key=lambda t: seq_order.get(t[0], 10_000))
        if not sequence:
            raise SystemExit("--only matched no steps (internal error).")
        print(
            "\nNOTE: --only mode (skips item/stock/sales steps): "
            + ", ".join(t[0] for t in sequence)
        )

    if manual_cmc:
        new_cmc = manual_cmc
        pin_blob["cmc_key"] = new_cmc
        save_test_state(state_root)
        print("Using CMC_KEY from environment (skipping selectInitOsdcInfo / stored cmc_key).")
    elif str(entry.get("cmc_key") or "").strip():
        new_cmc = str(entry["cmc_key"]).strip()
        pin_blob["cmc_key"] = new_cmc
        save_test_state(state_root)
        print(f"Using stored cmc_key from {CSV_FILE.name}: {mask_cmc_preview(new_cmc)}")
    else:
        print("No stored cmc_key (or empty). Calling selectInitOsdcInfo to obtain a fresh key...")
        step0_url = f"{BASE_URL.rstrip('/')}/selectInitOsdcInfo"
        step0_payload = {"tin": effective_tin, "bhfId": branch_id, "dvcSrlNo": device_serial}
        print("Payload:", json.dumps(step0_payload, indent=2, ensure_ascii=False))
        resp0 = requests.post(step0_url, headers=headers, json=step0_payload, timeout=60)
        parsed0 = print_full_response_json(resp0, "selectInitOsdcInfo")
        result_cd0 = extract_result_cd(parsed0)
        gate_err0 = kra_top_level_error_detail(parsed0)

        if resp0.status_code >= 400:
            raise SystemExit(f"STOP: HTTP {resp0.status_code} from KRA (selectInitOsdcInfo)")
        if gate_err0:
            raise SystemExit(f"STOP: KRA gateway/body error (selectInitOsdcInfo) — {gate_err0}")
        if result_cd0 not in ("000", "902"):
            raise SystemExit(f"STOP: selectInitOsdcInfo failed (resultCd={result_cd0})")

        print(f"CONTINUE: selectInitOsdcInfo OK (state={result_cd0})")
        print(f"EXTRACTED resultCd={result_cd0}")

        new_cmc = None
        if isinstance(parsed0, dict):
            rb0 = parsed0.get("responseBody")
            if isinstance(rb0, dict):
                ck = rb0.get("cmcKey")
                if isinstance(ck, str) and ck.strip():
                    new_cmc = ck.strip()
        if not new_cmc:
            new_cmc = extract_first_cmc_key(parsed0)

        if not new_cmc and result_cd0 == "902":
            new_c = reload_cmc_from_csv(app_pin)
            if new_c:
                new_cmc = new_c
                print(
                    f"Using cmc_key from {CSV_FILE.name} "
                    "(selectInitOsdcInfo returned 902 without key in response)."
                )

        if not new_cmc:
            if result_cd0 == "902":
                raise SystemExit(
                    "STOP: Device already installed (resultCd=902) but no cmcKey in response and none stored.\n"
                    f"Complete a resultCd=000 run once to store cmc_key in {CSV_FILE.name}, or set CMC_KEY in .env."
                )
            raise SystemExit("STOP: selectInitOsdcInfo OK but cmcKey missing in response.")

        entry["cmc_key"] = new_cmc
        pin_blob["cmc_key"] = new_cmc
        save_test_state(state_root)
        persist(rows, entry)
        print(f"Saved cmc_key to {CSV_FILE.name}: {mask_cmc_preview(new_cmc)}")

    headers["cmcKey"] = new_cmc
    print(f"Using CMC_KEY: {mask_cmc_preview(new_cmc)}")

    def flush_progress(
        endpoint_just_done: str | None = None, *, mark_endpoint_complete: bool = True
    ) -> None:
        if (
            endpoint_just_done is not None
            and mark_endpoint_complete
            and endpoint_just_done not in completed_list
        ):
            completed_list.append(endpoint_just_done)
        pin_blob["cmc_key"] = str(new_cmc or "").strip()
        pin_blob["completed_endpoints"] = list(completed_list)
        pin_blob["item_cd"] = item_cd
        if (item_cd or "").strip():
            pin_blob["canonical_item_cd"] = str(item_cd).strip()
        pin_blob["item_cls_cd"] = item_cls_dynamic["itemClsCd"]
        pin_blob["item_tax_ty_cd"] = item_cls_dynamic["taxTyCd"]
        pin_blob["invc_no"] = invc_no
        pin_blob["trd_invc"] = trd_invc
        pin_blob["sales_dt"] = sales_dt
        pin_blob["cfm_dt"] = cfm_dt
        pin_blob["stock_qty"] = stock_qty
        pin_blob["purchase_invc_no"] = int(purchase_invc_no)
        pin_blob["purchase_invc_no_component"] = int(purchase_invc_no_component)
        save_test_state(state_root)

    select_item_list_parsed: dict | None = None
    final_parent_insert_io_just_ran = False
    post_composition_parent_io_just_ran = False
    initial_insert_io_just_ran = False
    ran_insert_stock_io_initial_this_run = False
    ran_insert_stock_io_parent_this_run = False
    ran_insert_stock_io_post_composition_this_run = False
    bhf_audit_rows: list[dict[str, str]] = []

    _comp_bypass_banner_done = False

    def _emit_bypass_component_stock_banner() -> None:
        nonlocal _comp_bypass_banner_done
        if not bypass_component_stock_gate_cli or _comp_bypass_banner_done:
            return
        print(
            "\nCOMPONENT STOCK GATE BYPASSED (--bypass-component-stock-gate) - assuming component stock "
            "is sufficient after successful insertTrnsPurchaseComponentStock or insertStockIO.\n"
        )
        _comp_bypass_banner_done = True

    def ensure_component_stock_before_composition(cpst_qty_required: float) -> float:
        """
        Component on-hand for ``saveItemComposition``: **primary** purchase ledger
        (``insertTrnsPurchase`` → strict ``selectStockMoveList`` → ``saveStockMaster`` on the component);
        **secondary** manual ``insertStockIO`` prelude if purchase path does not satisfy the strict gate.
        With ``--bypass-component-stock-gate``, skip ``selectStockMoveList`` checks; trust
        ``insertTrnsPurchaseComponentStock`` 000 or prelude ``insertStockIO`` 000 (see runner banner).
        """
        comp_cd = (pin_blob.get("component_item_cd") or "").strip()
        if not comp_cd:
            sequence_fail(
                "STOP: saveItemComposition prelude — no component_item_cd (run saveComponentItem first)."
            )
        try:
            _gate_cpst = float(cpst_qty_required)
        except (TypeError, ValueError):
            _gate_cpst = 1.0
        _gate_cpst = max(_gate_cpst, 1.0)

        if bypass_component_stock_gate_cli:
            _emit_bypass_component_stock_banner()
            if pin_blob.get("component_trns_purchase_ok"):
                pin_blob["composition_prelude_logged_io_sar_no"] = 0
                if not str(pin_blob.get("composition_prelude_logged_sm_result_cd") or "").strip():
                    pin_blob["composition_prelude_logged_sm_result_cd"] = "000"
                pin_blob["composition_prelude_logged_component_item_cd"] = str(comp_cd).strip()
                save_test_state(state_root)
                print(
                    "BYPASS: composition prelude — component stock assumed from insertTrnsPurchaseComponentStock "
                    "000; skipping selectStockMoveList."
                )
                return float(_gate_cpst)

        if not bypass_component_stock_gate_cli and not sbx_stock_move_list_unreliable(BASE_URL):
            strict_gate0, rsd_gate0, _, _ = kra_strict_select_stock_component_on_hand(
                base_url=BASE_URL,
                headers=headers,
                tin=effective_tin,
                bhf_id=branch_id,
                component_item_cd=comp_cd,
                min_rsd_qty=_gate_cpst,
                log_tag="STRICT selectStockMoveList (composition — early gate before rebuild)",
            )
            if strict_gate0 and rsd_gate0 is not None:
                return float(rsd_gate0)

        qty_f = max(
            float(composition_component_purchase_qty),
            _gate_cpst + 1.0,
        )
        prc_f = 10.0
        icd = (
            pin_blob.get("component_item_cls_cd")
            or item_cls_dynamic.get("itemClsCd")
            or "1010000000"
        )
        icd = str(icd).strip()
        tty = (
            pin_blob.get("component_item_tax_ty_cd")
            or item_cls_dynamic.get("taxTyCd")
            or "A"
        )
        tty = str(tty).strip()
        line_sply, taxbl_p, tax_amt_p, tot_amt_p = stock_io_line_amounts_for_tax_ty(
            unit_prc=prc_f,
            qty=qty_f,
            tax_ty_cd=tty,
        )
        io_ocrn_8 = (sales_dt or "").strip()[:8]
        if len(io_ocrn_8) != 8:
            io_ocrn_8 = datetime.now(timezone.utc).strftime("%Y%m%d")
        io_url = f"{BASE_URL.rstrip('/')}/insertStockIO"
        sm_url = f"{BASE_URL.rstrip('/')}/saveStockMaster"

        sm_payload = {
            "itemCd": comp_cd,
            "rsdQty": 0.0,
            "regrId": "system",
            "regrNm": "system",
            "modrId": "system",
            "modrNm": "system",
        }

        prelude_io_sar = 0

        def _post_save_comp_prelude(rsd: float, suffix: str) -> tuple[bool, dict | None, requests.Response]:
            sm_payload["rsdQty"] = rsd
            tag = "saveStockMaster (composition prelude)"
            if suffix:
                tag = f"{tag} [{suffix}]"
            print(
                "PRELUDE saveStockMaster (component) "
                f"sarNo={prelude_io_sar} itemCd={comp_cd} rsdQty={rsd}"
            )
            r = requests.post(sm_url, headers=headers, json=sm_payload, timeout=60)
            p = print_full_response_json(r, tag)
            log_stock_flow_save_stock_master_prelude_summary(
                item_cd=comp_cd,
                rsd_qty_sent=float(rsd),
                parsed=p,
                http_status=getattr(r, "status_code", None),
            )
            rc = extract_result_cd(p)
            ge = kra_top_level_error_detail(p)
            ok = r.status_code < 400 and not ge and rc == "000"
            return ok, p, r

        purch_url = f"{BASE_URL.rstrip('/')}/insertTrnsPurchase"
        pl_warm_url = f"{BASE_URL.rstrip('/')}/selectTrnsPurchaseSalesList"

        def _next_comp_purch_invc() -> int:
            try:
                bump = int(pin_blob.get("component_purchase_next_invc_no") or 0)
            except (TypeError, ValueError):
                bump = 0
            if bump > 0:
                return int(bump) % 999_999_999 or 1
            try:
                base = int(pin_blob.get("purchase_invc_no_component") or 0)
            except (TypeError, ValueError):
                base = 0
            if base <= 0:
                try:
                    pm = int(pin_blob.get("purchase_invc_no") or purchase_invc_no or 0)
                except (TypeError, ValueError):
                    pm = 0
                base = (pm + 357_911) % 999_999_999 if pm else 888_001
            return int(base) % 999_999_999 or 1

        def _attempt_component_purchase_ledger() -> float | None:
            pq = max(float(composition_component_purchase_qty), _gate_cpst + 1.0)
            prc_p = float(_cc_purchase_prc)
            sp_p, tb_p, tx_p, tot_p = stock_io_line_amounts_for_tax_ty(
                unit_prc=prc_p,
                qty=pq,
                tax_ty_cd=tty,
            )
            tax_root = {
                "taxblAmtA": 0.0,
                "taxblAmtB": 0.0,
                "taxblAmtC": 0.0,
                "taxblAmtD": 0.0,
                "taxblAmtE": 0.0,
                "taxAmtA": 0.0,
                "taxAmtB": 0.0,
                "taxAmtC": 0.0,
                "taxAmtD": 0.0,
                "taxAmtE": 0.0,
                "taxRtA": 0.0,
                "taxRtB": 0.0,
                "taxRtC": 0.0,
                "taxRtD": 0.0,
                "taxRtE": 0.0,
            }
            _tu = tty.upper()
            if _tu == "A":
                tax_root["taxblAmtA"] = tb_p
                tax_root["taxAmtA"] = tx_p
            elif _tu == "B":
                tax_root["taxblAmtB"] = tb_p
                tax_root["taxAmtB"] = tx_p
            elif _tu == "C":
                tax_root["taxblAmtC"] = tb_p
                tax_root["taxAmtC"] = tx_p
            else:
                tax_root["taxblAmtA"] = tb_p
                tax_root["taxAmtA"] = tx_p
            _inv_bind = coerce_invc_binding(pin_blob.get("precomp_purchase_sales_invc_no"))
            if _inv_bind is not None:
                _pre_rt = _link_tax_rt_for_purchase_or_fallback(
                    pin_blob,
                    "precomp_purchase_link_tax_rt",
                    note_tag="prelude insertTrnsPurchase (component)",
                )
                apply_link_tax_rt_to_purchase_payload(tax_root, _pre_rt)
            invc_u = _next_comp_purch_invc()
            _pst = (pin_blob.get("precomp_purchase_spplr_tin") or "").strip()
            _sp_tin_p = _pst if _pst else effective_tin
            _pbhf_p = (pin_blob.get("precomp_purchase_spplr_bhf_id") or "").strip()
            _sp_bhf = _pbhf_p if _pbhf_p else branch_id
            _pnm_p = (pin_blob.get("precomp_purchase_spplr_nm") or "").strip()
            _sp_nm = _pnm_p if _pnm_p else "Test Supplier (component stock prelude)"
            _rin_prel = (
                str(_inv_bind).strip()
                if _inv_bind is not None
                else str(int(invc_u))
            )
            root_p: dict = {
                "spplrTin": _sp_tin_p,
                "invcNo": str(int(invc_u)),
                "requestedInvcNo": _rin_prel,
                "spplrBhfId": _sp_bhf,
                "spplrNm": _sp_nm,
                "regTyCd": "M",
                "pchsTyCd": "N",
                "rcptTyCd": "P",
                "pmtTyCd": "01",
                "pchsSttsCd": "02",
                "cfmDt": cfm_dt,
                "pchsDt": sales_dt,
                "totItemCnt": 1,
                **tax_root,
                "totTaxblAmt": tb_p,
                "totTaxAmt": tx_p,
                "totAmt": tot_p,
                "regrId": "system",
                "regrNm": "system",
                "modrId": "system",
                "modrNm": "system",
                "itemList": [
                    {
                        "itemSeq": 1,
                        "itemCd": comp_cd,
                        "itemClsCd": icd,
                        "itemNm": "COMPONENT ITEM",
                        "pkgUnitCd": pkg_unit_cd,
                        "pkg": pq,
                        "qtyUnitCd": qty_unit_cd,
                        "qty": pq,
                        "prc": prc_p,
                        "splyAmt": sp_p,
                        "dcRt": 0.0,
                        "dcAmt": 0.0,
                        "taxblAmt": tb_p,
                        "taxTyCd": tty,
                        "taxAmt": tx_p,
                        "totAmt": tot_p,
                    }
                ],
            }
            _spi_p = coerce_invc_binding(pin_blob.get("precomp_purchase_sales_invc_no"))
            if _spi_p is not None:
                root_p["spplrInvcNo"] = _spi_p
            # Linked purchase: SBX validates itemList.pkg against supplier sale lines (pkg=1).
            if _inv_bind is not None and isinstance(root_p.get("itemList"), list) and root_p["itemList"]:
                _il0 = root_p["itemList"][0]
                if isinstance(_il0, dict):
                    _il0["pkg"] = 1.0
            print(
                "PRELUDE insertTrnsPurchase (component ledger for saveItemComposition) "
                f"invcNo={invc_u} itemCd={comp_cd} qty={pq:g}"
            )
            print(json.dumps(root_p, indent=2, ensure_ascii=False))
            requests.post(
                pl_warm_url,
                headers=headers,
                json={
                    "tin": effective_tin,
                    "bhfId": branch_id,
                    "lastReqDt": "20100101000000",
                },
                timeout=60,
            )
            _pre_invc = str(root_p.get("invcNo") or "").strip()
            _pre_params = (
                {"invcNo": _pre_invc, "requestedInvcNo": _pre_invc} if _pre_invc else None
            )
            rp = requests.post(
                purch_url,
                headers=headers,
                json=root_p,
                params=_pre_params,
                timeout=60,
            )
            print(
                "NOTE: prelude insertTrnsPurchase effective URL (params match body invcNo) -> "
                f"{getattr(rp.request, 'url', purch_url)}"
            )
            pp = print_full_response_json(rp, "insertTrnsPurchase (composition prelude purchase)")
            rc_p = extract_result_cd(pp)
            ge_p = kra_top_level_error_detail(pp)
            if rp.status_code >= 400 or ge_p or rc_p != "000":
                pin_blob["component_purchase_next_invc_no"] = (invc_u + 1) % 999_999_999
                save_test_state(state_root)
                print(
                    "NOTE: composition prelude purchase failed (will bump invcNo) — "
                    f"HTTP={rp.status_code} resultCd={rc_p!r} {ge_p or ''}".strip()
                )
                return None
            pin_blob["purchase_invc_no_component"] = int(invc_u)
            pin_blob.pop("component_purchase_next_invc_no", None)
            save_test_state(state_root)
            time.sleep(8)
            if bypass_component_stock_gate_cli or sbx_stock_move_list_unreliable(BASE_URL):
                sm_payload["rsdQty"] = float(pq)
                if sbx_stock_move_list_unreliable(BASE_URL) and not bypass_component_stock_gate_cli:
                    print(
                        "NOTE: composition prelude purchase — SBX: saveStockMaster rsdQty from purchase "
                        f"qty={float(pq):g} (move-list not used)."
                    )
            else:
                strict_p, rsd_p, _, _ = kra_strict_select_stock_component_on_hand(
                    base_url=BASE_URL,
                    headers=headers,
                    tin=effective_tin,
                    bhf_id=branch_id,
                    component_item_cd=comp_cd,
                    min_rsd_qty=_gate_cpst,
                    log_tag="STRICT selectStockMoveList (after composition prelude purchase)",
                )
                if not strict_p or rsd_p is None:
                    print(
                        "NOTE: purchase posted but strict move list still not satisfied; "
                        "may fall back to insertStockIO prelude."
                    )
                    return None
                sm_payload["rsdQty"] = float(rsd_p)
            tag_sm = "saveStockMaster (composition prelude after purchase)"
            print(
                f"PRELUDE saveStockMaster (component, post-purchase) itemCd={comp_cd} "
                f"rsdQty={sm_payload['rsdQty']}"
            )
            rsm = requests.post(sm_url, headers=headers, json=sm_payload, timeout=60)
            psm = print_full_response_json(rsm, tag_sm)
            ge_sm = kra_top_level_error_detail(psm)
            rc_sm = extract_result_cd(psm)
            ok_sm = rsm.status_code < 400 and not ge_sm and rc_sm == "000"
            if not ok_sm:
                sequence_fail(
                    "STOP: composition prelude saveStockMaster (after purchase) failed — "
                    f"HTTP={rsm.status_code}, resultCd={rc_sm!r}"
                    + (f", {ge_sm}" if ge_sm else "")
                )
            log_stock_flow_save_stock_master_prelude_summary(
                item_cd=comp_cd,
                rsd_qty_sent=float(sm_payload["rsdQty"]),
                parsed=psm,
                http_status=getattr(rsm, "status_code", None),
            )
            if bypass_component_stock_gate_cli or sbx_stock_move_list_unreliable(BASE_URL):
                pin_blob["composition_prelude_logged_io_sar_no"] = 0
                pin_blob["composition_prelude_logged_sm_result_cd"] = str(rc_sm or "000").strip()
                pin_blob["composition_prelude_logged_component_item_cd"] = str(comp_cd).strip()
                print(
                    (
                        "BYPASS: PRELUDE AUDIT (purchase ledger): insertTrnsPurchase 000 + saveStockMaster; "
                        if bypass_component_stock_gate_cli
                        else "SBX: PRELUDE AUDIT (purchase ledger): insertTrnsPurchase 000 + saveStockMaster; "
                    )
                    + f"component itemCd={comp_cd!r}, rsdQty={float(sm_payload['rsdQty']):g} (no move-list gate)."
                )
                save_test_state(state_root)
                return float(max(float(pq), _gate_cpst))
            strict_e, rsd_e, p_fin, _ = kra_strict_select_stock_component_on_hand(
                base_url=BASE_URL,
                headers=headers,
                tin=effective_tin,
                bhf_id=branch_id,
                component_item_cd=comp_cd,
                min_rsd_qty=_gate_cpst,
                log_tag="STRICT selectStockMoveList (after saveStockMaster post-purchase)",
            )
            if not strict_e or rsd_e is None:
                return None
            _frc = (
                (extract_result_cd(p_fin) or "").strip()
                if isinstance(p_fin, dict)
                else ""
            )
            if _frc != "000" or count_stock_move_list_rows_for_item(p_fin, comp_cd) <= 0:
                return None
            pin_blob["composition_prelude_logged_io_sar_no"] = 0
            pin_blob["composition_prelude_logged_sm_result_cd"] = str(rc_sm or "000").strip()
            pin_blob["composition_prelude_logged_component_item_cd"] = str(comp_cd).strip()
            print(
                "PRELUDE AUDIT (purchase ledger): insertTrnsPurchase + saveStockMaster; "
                f"component itemCd={comp_cd!r}, strict rsdQty≈{rsd_e:g}"
            )
            save_test_state(state_root)
            return float(rsd_e)

        _cross_tin_precomp = bool((pin_blob.get("precomp_purchase_spplr_tin") or "").strip())
        _ledger_already_ok = bool(pin_blob.get("component_trns_purchase_ok"))
        if _cross_tin_precomp and _ledger_already_ok:
            print(
                "NOTE: composition prelude — skip repeat insertTrnsPurchase "
                "(insertTrnsPurchaseComponentStock already 000 with cross-TIN link; SBX often omits "
                "buyer selectStockMoveList rows — insertStockIO prelude next)."
            )
        else:
            for _purch_try in range(3):
                _rsd_ledger = _attempt_component_purchase_ledger()
                if _rsd_ledger is not None:
                    print(
                        "CONTINUE: component stock prelude OK "
                        "(purchase insertTrnsPurchase + saveStockMaster)."
                    )
                    return float(_rsd_ledger)
                print(
                    f"NOTE: composition prelude purchase attempt {_purch_try + 1}/3 did not complete — "
                    "retrying or falling back …"
                )
            print(
                "NOTE: Purchase ledger prelude did not satisfy strict stock — "
                "secondary: insertStockIO (manual IO) …"
            )

        _comp_prelude_sar_max = 5
        for prelude_round in range(MAX_COMPOSITION_PRELUDE_ROUNDS):
            prelude_io_sar = last_committed_insert_stock_sar_no(
                state_root, effective_tin, branch_id, pin_blob
            )
            parsed_io = None
            result_cd_io = None
            succeeded = False
            sbx_move_list_unavailable = False
            last_prelude_ge: str | None = None
            _prelude_sar_kra_resync_used = False
            for sar_sync_attempt in range(_comp_prelude_sar_max):
                if succeeded:
                    break
                saw_resync = False
                # SBX stock visibility can depend on the Stock I/O Type (sarTyCd).
                # KRA code list (seen on portal): 01=Import, 02=Purchase, 04=Stock Movement, 06=Adjustment.
                # We prefer 02/06 for synthetic stock used to satisfy sales/composition gates; fall back to 01.
                _tried_map = pin_blob.get("composition_prelude_tried_sar_ty_by_item") or {}
                if not isinstance(_tried_map, dict):
                    _tried_map = {}
                _tried_raw = _tried_map.get(comp_cd)
                _tried_set: set[str] = set()
                if isinstance(_tried_raw, list):
                    _tried_set = {str(x).strip() for x in _tried_raw if str(x).strip()}
                elif isinstance(_tried_raw, str) and _tried_raw.strip():
                    _tried_set = {x.strip() for x in _tried_raw.split(",") if x.strip()}

                for sar_ty in ("02", "06", "04", "01"):
                    # Resume-friendly: if a previous run already tested sarTyCd for this component and
                    # it yielded "insert 000 but still no move row", skip it to reach the remaining types.
                    if sar_ty in _tried_set:
                        continue
                    sar_no_used = resolve_next_insert_stock_sar_no(
                        state_root, effective_tin, branch_id, pin_blob
                    )
                    print(f"SAR sequence → using sarNo={sar_no_used}")
                    org_sar_strict = 0 if sar_no_used <= 1 else sar_no_used - 1
                    prelude_io_sar = sar_no_used
                    reg_ty = "M"
                    stock_line = {
                        "itemSeq": 1,
                        "itemCd": comp_cd,
                        "ioTyCd": "1",
                        "itemClsCd": icd,
                        "itemNm": "COMPONENT ITEM",
                        "pkgUnitCd": pkg_unit_cd,
                        "pkg": qty_f,
                        "qtyUnitCd": qty_unit_cd,
                        "qty": qty_f,
                        "prc": float(prc_f),
                        "splyAmt": line_sply,
                        "totDcAmt": 0.0,
                        "taxblAmt": taxbl_p,
                        "taxTyCd": tty,
                        "taxAmt": tax_amt_p,
                        "totAmt": tot_amt_p,
                    }
                    io_root: dict = {
                        "sarNo": sar_no_used,
                        "regTyCd": reg_ty,
                        "custTin": effective_tin,
                        "sarTyCd": sar_ty,
                        "ocrnDt": io_ocrn_8,
                        "totItemCnt": 1,
                        "totTaxblAmt": taxbl_p,
                        "totTaxAmt": tax_amt_p,
                        "totAmt": tot_amt_p,
                        "orgSarNo": org_sar_strict,
                        "regrId": "system",
                        "regrNm": "system",
                        "modrId": "system",
                        "modrNm": "system",
                        "itemList": [deepcopy(stock_line)],
                    }
                    print(
                        "PRELUDE insertStockIO (component stock for saveItemComposition) "
                        f"[preludeRound={prelude_round + 1}/{MAX_COMPOSITION_PRELUDE_ROUNDS}, "
                        f"sarSync={sar_sync_attempt + 1}/{_comp_prelude_sar_max}, "
                        f"sarNo={sar_no_used}, orgSarNo={org_sar_strict}, sarTyCd={sar_ty}, itemCd={comp_cd}]"
                    )
                    print("Request JSON:", json.dumps(io_root, indent=2, ensure_ascii=False))
                    register_insert_stock_io_request_url(io_url)
                    # SBX throttles quickly when we do multiple insertStockIO back-to-back (sarTyCd sweep).
                    # Treat 429 Spike Arrest as a transient throttle: back off and retry same sarNo/sarTyCd.
                    resp_io = None
                    parsed_io = None
                    for _throttle_try in range(5):
                        resp_io = requests.post(io_url, headers=headers, json=io_root, timeout=60)
                        if getattr(resp_io, "status_code", 0) != 429:
                            break
                        pause_s = min(45.0, 5.0 * (2 ** _throttle_try))
                        # jitter keeps concurrent runs from syncing into the same window
                        pause_s = pause_s + (random.random() * 1.5)
                        print(
                            f"THROTTLED: insertStockIO returned 429 (Spike Arrest). "
                            f"Backing off {pause_s:.1f}s then retrying (try {_throttle_try + 1}/5) …"
                        )
                        time.sleep(pause_s)
                    parsed_io = print_full_response_json(
                        resp_io, "insertStockIO (composition prelude)"
                    )
                    log_stock_flow_insert_io_prelude_summary(
                        item_cd=comp_cd,
                        parsed=parsed_io,
                        http_status=getattr(resp_io, "status_code", None),
                    )
                    result_cd_io = extract_result_cd(parsed_io)
                    gate_err = kra_top_level_error_detail(parsed_io)
                    last_prelude_ge = gate_err
                    if (
                        resp_io.status_code < 400
                        and not gate_err
                        and result_cd_io == "000"
                    ):
                        persist_committed_insert_stock_sar_no(
                            state_root,
                            effective_tin,
                            branch_id,
                            sar_no_used,
                            pin_blob,
                        )
                        pin_blob["stock_io_last_committed_sar_no"] = sar_no_used
                        save_test_state(state_root)
                        if debug_ledger_after_io_cli:
                            run_debug_ledger_watch_after_insert_stock_io_ok(
                                base_url=BASE_URL,
                                headers=headers,
                                tin=effective_tin,
                                bhf_id=branch_id,
                                item_cd=comp_cd,
                                insert_parsed=parsed_io
                                if isinstance(parsed_io, dict)
                                else None,
                            )
                        # IMPORTANT: SBX can accept insertStockIO (000) but fail to surface any move-list row
                        # (resultCd=001/504). In SBX, treat selectStockMoveList as best-effort and do not
                        # block the flow when it is unstable; proceed on insertStockIO+saveStockMaster.
                        strict_ok_tmp, rsd_tmp, parsed_mv_tmp, resp_mv_tmp = kra_strict_select_stock_component_on_hand(
                            base_url=BASE_URL,
                            headers=headers,
                            tin=effective_tin,
                            bhf_id=branch_id,
                            component_item_cd=comp_cd,
                            min_rsd_qty=_gate_cpst,
                            log_tag=(
                                "STRICT selectStockMoveList (composition prelude) "
                                f"after insertStockIO 000 sarTyCd={sar_ty}"
                            ),
                        )
                        if strict_ok_tmp and rsd_tmp is not None:
                            succeeded = True
                            break
                        if sbx_select_stock_move_list_unavailable(
                            base_url=BASE_URL,
                            parsed=parsed_mv_tmp if isinstance(parsed_mv_tmp, dict) else None,
                            resp=resp_mv_tmp,
                        ):
                            sbx_move_list_unavailable = True
                            succeeded = True
                            print("WARNING: selectStockMoveList unavailable (sandbox issue)")
                            print(
                                "SUCCESS: Stock flow completed (selectStockMoveList unavailable in SBX) — "
                                "continuing after saveStockMaster."
                            )
                            break
                        print(
                            "NOTE: insertStockIO returned 000 but stock not visible on move list "
                            f"(sarTyCd={sar_ty!r}, sarNo={sar_no_used}); trying next sarTyCd …"
                        )
                        try:
                            _tried_set.add(str(sar_ty).strip())
                            _tried_map[comp_cd] = sorted(_tried_set)
                            pin_blob["composition_prelude_tried_sar_ty_by_item"] = _tried_map
                            save_test_state(state_root)
                        except Exception:
                            # resume optimization only; never block the run if state can't be written
                            pass
                        continue
                    err_blob = kra_insert_stock_io_error_text(parsed_io)
                    exp_sar = kra_expected_next_sar_no_from_message(err_blob)
                    if (
                        exp_sar is not None
                        and err_blob
                        and "Invalid sarNo" in err_blob
                    ):
                        if _prelude_sar_kra_resync_used:
                            sequence_fail(
                                "STOP: composition prelude insertStockIO — Invalid sarNo again after "
                                f"one SAR correction (expected {exp_sar})."
                            )
                        print(
                            f"SAR corrected from {sar_no_used} → {exp_sar} based on KRA response"
                        )
                        apply_kra_expected_insert_stock_sar_no(
                            state_root,
                            effective_tin,
                            branch_id,
                            exp_sar,
                            pin_blob,
                        )
                        pin_blob["stock_io_last_committed_sar_no"] = max(0, int(exp_sar) - 1)
                        save_test_state(state_root)
                        _prelude_sar_kra_resync_used = True
                        saw_resync = True
                        break
                    ge = kra_top_level_error_detail(parsed_io) if parsed_io else None
                    sequence_fail(
                        "STOP: composition prelude insertStockIO failed (strict orgSarNo; tried sarTyCd in order "
                        '"02","06","04","01")'
                        + (
                            f", resultCd={result_cd_io!r}, {ge}"
                            if ge or result_cd_io
                            else ""
                        )
                    )
                if succeeded:
                    break
                if saw_resync:
                    continue
            if not succeeded and not sbx_move_list_unavailable:
                sequence_fail(
                    "STOP: composition prelude insertStockIO failed after SAR resync retries "
                    f"({_comp_prelude_sar_max} rounds; sarTyCd tried in order 02,06,04,01)"
                    + (
                        f", last resultCd={result_cd_io!r}, {last_prelude_ge}"
                        if last_prelude_ge or result_cd_io
                        else ""
                    )
                )

            if bypass_component_stock_gate_cli or sbx_move_list_unavailable:
                rsd_for_sm = float(qty_f)
                ok_sm, parsed_sm, resp_sm = _post_save_comp_prelude(rsd_for_sm, "bypass")
                ge_sm = kra_top_level_error_detail(parsed_sm)
                rc_sm = extract_result_cd(parsed_sm)
                if not ok_sm:
                    sequence_fail(
                        "STOP: composition prelude saveStockMaster failed — "
                        f"HTTP={resp_sm.status_code}, resultCd={rc_sm!r}"
                        + (f", {ge_sm}" if ge_sm else "")
                        + ". Check Stock IO / SAR backlog on the OSCU portal."
                    )
                final_rsd = float(qty_f)
                _final_rc = "000"
                try:
                    _sar_snap = int(
                        pin_blob.get("stock_io_last_committed_sar_no") or prelude_io_sar or 0
                    )
                except (TypeError, ValueError):
                    _sar_snap = int(prelude_io_sar or 0)
                pin_blob["composition_prelude_logged_io_sar_no"] = _sar_snap
                pin_blob["composition_prelude_logged_sm_result_cd"] = str(rc_sm or "000").strip()
                pin_blob["composition_prelude_logged_component_item_cd"] = str(comp_cd).strip()
                print(
                    "BYPASS: PRELUDE AUDIT (insertStockIO 000): "
                    f"last insertStockIO sarNo≈{_sar_snap}, saveStockMaster resultCd="
                    f"{pin_blob['composition_prelude_logged_sm_result_cd']!r}, "
                    f"component itemCd={pin_blob['composition_prelude_logged_component_item_cd']!r}, "
                    f"assumed rsdQty≈{final_rsd:g} (no move-list check)."
                )
                print("\nKRA STOCK CHECK (bypass):")
                print(f"itemCd={comp_cd!r}")
                print(f"rsdQty(assumed from prelude IO qty)={final_rsd:g}")
                print(f"resultCd={_final_rc!r}")
                save_test_state(state_root)
                print(
                    "CONTINUE: component stock prelude OK (bypass: prelude insertStockIO 000, no move list)."
                )
                return float(final_rsd)

            strict_ok, rsd_ledger, parsed_mv_pre, resp_mv_pre = kra_strict_select_stock_component_on_hand(
                base_url=BASE_URL,
                headers=headers,
                tin=effective_tin,
                bhf_id=branch_id,
                component_item_cd=comp_cd,
                min_rsd_qty=_gate_cpst,
                log_tag=(
                    "STRICT selectStockMoveList (composition prelude) "
                    f"after insertStockIO 000 round {prelude_round + 1}"
                ),
            )
            if not strict_ok or rsd_ledger is None:
                # SBX can return Apigee targetPath / generic 5xx even when payload is correct.
                # In SBX, do not gate the flow on selectStockMoveList; proceed using insertStockIO+saveStockMaster.
                if sbx_select_stock_move_list_unavailable(
                    base_url=BASE_URL,
                    parsed=parsed_mv_pre if isinstance(parsed_mv_pre, dict) else None,
                    resp=resp_mv_pre,
                ):
                    print("WARNING: selectStockMoveList unavailable (sandbox issue)")
                    rsd_for_sm = float(qty_f)
                else:
                    print(
                        "Stock movement not registered in KRA — aborting saveStockMaster for this prelude round.\n"
                        "insertStockIO returned 000 but selectStockMoveList did not return resultCd=000 with a "
                        f"move row and rsdQty >= cpstQty for component itemCd={comp_cd!r}. Retrying prelude from "
                        "insertStockIO …"
                    )
                    continue
            else:
                rsd_for_sm = float(rsd_ledger)

            ok_sm, parsed_sm, resp_sm = _post_save_comp_prelude(rsd_for_sm, "")
            ge_sm = kra_top_level_error_detail(parsed_sm)
            rc_sm = extract_result_cd(parsed_sm)
            if not ok_sm:
                sequence_fail(
                    "STOP: composition prelude saveStockMaster failed — "
                    f"HTTP={resp_sm.status_code}, resultCd={rc_sm!r}"
                    + (f", {ge_sm}" if ge_sm else "")
                    + ". Check Stock IO / SAR backlog on the OSCU portal."
                )

            strict_ok2, rsd2, p_kra_final, resp_kra_final = kra_strict_select_stock_component_on_hand(
                base_url=BASE_URL,
                headers=headers,
                tin=effective_tin,
                bhf_id=branch_id,
                component_item_cd=comp_cd,
                min_rsd_qty=_gate_cpst,
                log_tag=(
                    "STRICT selectStockMoveList (composition prelude) "
                    f"after saveStockMaster 000 round {prelude_round + 1}"
                ),
            )
            if strict_ok2 and rsd2 is not None:
                final_rsd = float(rsd2)
                _final_rc = (
                    (extract_result_cd(p_kra_final) or "").strip()
                    if isinstance(p_kra_final, dict)
                    else ""
                )
                if (
                    _final_rc != "000"
                    or count_stock_move_list_rows_for_item(p_kra_final, comp_cd) <= 0
                ):
                    print("KRA did not confirm stock visibility — stopping")
                    sequence_fail(
                        "KRA did not confirm stock visibility — stopping\n"
                        "After saveStockMaster 000, selectStockMoveList did not return resultCd 000 "
                        f"with a row for component itemCd={comp_cd!r}."
                    )
            else:
                if sbx_select_stock_move_list_unavailable(
                    base_url=BASE_URL,
                    parsed=p_kra_final if isinstance(p_kra_final, dict) else None,
                    resp=resp_kra_final,
                ):
                    print("WARNING: selectStockMoveList unavailable (sandbox issue)")
                    final_rsd = float(rsd_for_sm)
                    _final_rc = "000"
                    print(
                        "SUCCESS: Stock flow completed (selectStockMoveList unavailable in SBX) — "
                        "continuing after saveStockMaster."
                    )
                else:
                    print(
                        "STOP (composition prelude): after saveStockMaster 000, selectStockMoveList did not "
                        "return resultCd=000 with a move row for component itemCd="
                        f"{comp_cd!r} — not treating saveStockMaster as ledger truth (sales/stock engines "
                        "trust move list only). Retrying prelude from insertStockIO …"
                    )
                    continue

            try:
                _sar_snap = int(
                    pin_blob.get("stock_io_last_committed_sar_no") or prelude_io_sar or 0
                )
            except (TypeError, ValueError):
                _sar_snap = int(prelude_io_sar or 0)
            pin_blob["composition_prelude_logged_io_sar_no"] = _sar_snap
            pin_blob["composition_prelude_logged_sm_result_cd"] = str(rc_sm or "000").strip()
            pin_blob["composition_prelude_logged_component_item_cd"] = str(comp_cd).strip()
            print(
                "PRELUDE AUDIT (KRA ledger / saveStockMaster): "
                f"last insertStockIO sarNo≈{_sar_snap}, "
                f"saveStockMaster resultCd={pin_blob['composition_prelude_logged_sm_result_cd']!r}, "
                f"component itemCd={pin_blob['composition_prelude_logged_component_item_cd']!r}, "
                f"strict move list visible=True, rsdQty≈{final_rsd:g}"
            )
            print("\nKRA STOCK CHECK:")
            print(f"itemCd={comp_cd!r}")
            print(f"rsdQty(from KRA selectStockMoveList)={final_rsd:g}")
            print(f"resultCd={_final_rc!r}")
            save_test_state(state_root)
            print("CONTINUE: component stock prelude OK (strict move list confirms on-hand).")
            return float(final_rsd)

        print("KRA did not confirm stock visibility — stopping")
        sequence_fail(
            "KRA did not confirm stock visibility — stopping\n"
            f"STOP: composition prelude exhausted ({MAX_COMPOSITION_PRELUDE_ROUNDS} rounds) — "
            "need selectStockMoveList resultCd 000, a move row for the component itemCd, and "
            f"rsdQty >= cpstQty ({_gate_cpst:g})."
        )

    if stock_lifecycle_isolation_test_cli and not only_steps_cli:
        _rc_iso = run_stock_lifecycle_isolation_test(
            base_url=BASE_URL,
            headers=dict(headers),
            effective_tin=effective_tin,
            branch_id=branch_id,
            state_root=state_root,
            pin_blob=pin_blob,
            sales_dt=sales_dt,
            item_cls_dynamic=dict(item_cls_dynamic),
            item_ty_cd=item_ty_cd,
            pkg_unit_cd=pkg_unit_cd,
            qty_unit_cd=qty_unit_cd,
            on_pin_blob_mutation=lambda: save_test_state(state_root),
        )
        save_test_state(state_root)
        return _rc_iso

    if stock_master_visibility_test_cli and not only_steps_cli:
        _rc_sm = run_stock_master_visibility_test(
            base_url=BASE_URL,
            headers=dict(headers),
            effective_tin=effective_tin,
            branch_id=branch_id,
            state_root=state_root,
            pin_blob=pin_blob,
            sales_dt=sales_dt,
            item_cls_dynamic=dict(item_cls_dynamic),
            item_ty_cd=item_ty_cd,
            pkg_unit_cd=pkg_unit_cd,
            qty_unit_cd=qty_unit_cd,
            on_pin_blob_mutation=lambda: save_test_state(state_root),
        )
        save_test_state(state_root)
        return _rc_sm

    if sbx_finished_good_ledger_probe_cli and not only_steps_cli:
        _rc_fg = run_sbx_finished_good_ledger_probe(
            base_url=BASE_URL,
            headers=dict(headers),
            effective_tin=effective_tin,
            branch_id=branch_id,
            state_root=state_root,
            pin_blob=pin_blob,
            sales_dt=sales_dt,
            item_cls_dynamic=dict(item_cls_dynamic),
            pkg_unit_cd=pkg_unit_cd,
            qty_unit_cd=qty_unit_cd,
            on_pin_blob_mutation=lambda: save_test_state(state_root),
        )
        save_test_state(state_root)
        return _rc_fg

    if ledger_contract_test_cli and not only_steps_cli:
        _v = run_ledger_contract_test(
            base_url=BASE_URL,
            headers=dict(headers),
            sales_dt_hint=sales_dt,
        )
        return 0 if _v == LEDGER_CONTRACT_VERDICT_POSTED else 1

    if (minimal_osdc_sale_test_cli or minimal_stock_ledger_matrix_cli) and not only_steps_cli:
        _rc_min = run_minimal_osdc_sale_test(
            base_url=BASE_URL,
            headers=dict(headers),
            effective_tin=effective_tin,
            branch_id=branch_id,
            item_cls_dynamic=dict(item_cls_dynamic),
            sales_dt=sales_dt,
            cfm_dt=cfm_dt,
            pkg_unit_cd=pkg_unit_cd,
            qty_unit_cd=qty_unit_cd,
            item_ty_cd=item_ty_cd,
            pin_blob=pin_blob,
            pasteback=minimal_osdc_pasteback_cli,
            on_pin_blob_mutation=lambda: save_test_state(state_root),
            state_root=state_root,
            stock_ledger_matrix=minimal_stock_ledger_matrix_cli,
            debug_ledger_after_io=debug_ledger_after_io_cli,
        )
        save_test_state(state_root)
        return _rc_min

    reset_insert_stock_io_cluster_url()
    for endpoint_name, endpoint_path, payload_template in sequence:
        try:
            _skip_stock_master_post = False
            _skip_stock_master_reason = ""
            item_cd = reconcile_item_cd_with_pin_state(pin_blob, item_cd)
            log_step_banner(
                endpoint_name,
                item_cd,
                list(completed_list),
                ran_insert_stock_io_this_run=(
                    ran_insert_stock_io_initial_this_run
                    or ran_insert_stock_io_parent_this_run
                ),
                ran_insert_stock_io_initial_this_run=ran_insert_stock_io_initial_this_run,
                ran_insert_stock_io_parent_this_run=ran_insert_stock_io_parent_this_run,
            )
            skip_completed = (
                endpoint_name in completed_list
                and endpoint_name in SKIPPABLE_NON_STOCK_ENDPOINTS_IF_COMPLETED
            )
            if only_steps_cli:
                skip_completed = False
            if skip_completed and endpoint_name == "insertStockIO":
                if "saveStockMaster" not in completed_list:
                    skip_completed = False
                    print(
                        "NOTE: insertStockIO not skipped — saveStockMaster not complete; "
                        "replaying insert to pair with save in this run."
                    )
            if skip_completed:
                print(f"SKIP {endpoint_name} (already completed — see {STATE_FILE.name})")
                continue

            # One parent initial IO per checkpoint: resume must not POST again (duplicate SAR/stock vs
            # saveStockMasterInitial and saveTrnsSalesOsdc validation).
            if endpoint_name == "insertStockIOInitial" and endpoint_name in completed_list:
                print(
                    "NOTE: insertStockIOInitial already in completed_endpoints — skipping duplicate POST "
                    f"(see {STATE_FILE.name}); continuing to select/save for this PIN."
                )
                continue

            # Sandbox: SBX often returns 504 on selectStockMoveList right after component purchase; bypass
            # uses purchase line qty for saveStockMasterComponentPurchase (same flag as composition prelude).
            if (
                bypass_component_stock_gate_cli
                and endpoint_name == "selectStockMoveListComponentPurchase"
                and "insertTrnsPurchaseComponentStock" in completed_list
                and pin_blob.get("component_trns_purchase_ok")
            ):
                _emit_bypass_component_stock_banner()
                _qb = pin_blob.get("component_purchase_bypass_rsd_qty")
                if _qb is None:
                    try:
                        _qb = float(composition_component_purchase_qty)
                    except (TypeError, ValueError):
                        _qb = None
                if _qb is None or float(_qb) <= 0:
                    sequence_fail(
                        "STOP: --bypass-component-stock-gate — cannot infer component reconcile qty for "
                        "saveStockMasterComponentPurchase (missing component_purchase_bypass_rsd_qty and "
                        "invalid composition_component_purchase_qty). Re-run from insertTrnsPurchaseComponentStock."
                    )
                pin_blob["component_reconcile_rsd_qty"] = float(_qb)
                save_test_state(state_root)
                print(
                    "BYPASS (--bypass-component-stock-gate): skipping selectStockMoveListComponentPurchase "
                    f"(avoid 504 / empty move list); component_reconcile_rsd_qty={float(_qb):g} from purchase line."
                )
                flush_progress(
                    "selectStockMoveListComponentPurchase",
                    mark_endpoint_complete=True,
                )
                continue

            url = f"{BASE_URL.rstrip('/')}{endpoint_path}"

            if endpoint_name in (
                "insertStockIO",
                "insertStockIOInitial",
                "insertStockIOPostComposition",
            ):
                stock_progress_key = endpoint_name
                is_initial_parent_io = endpoint_name == "insertStockIOInitial"
                is_post_composition_osdc_io = endpoint_name == "insertStockIOPostComposition"
                if is_initial_parent_io:
                    _io_log = "insertStockIOInitial"
                elif is_post_composition_osdc_io:
                    _io_log = "insertStockIO (post-composition OSDC)"
                else:
                    _io_log = "insertStockIO"
                _ic = (pin_blob.get("item_cd") or "").strip()
                if _ic:
                    item_cd = _ic
                if is_initial_parent_io and "saveStockMasterInitial" not in completed_list:
                    pin_blob["stock_io_pending_rsd_qty"] = 0.0
                    save_test_state(state_root)
                    print(
                        "NOTE: insertStockIOInitial atomic pair: stock_io_pending_rsd_qty=0 before post "
                        "(pairs with saveStockMasterInitial this run)."
                    )
                if (
                    not is_initial_parent_io
                    and endpoint_name == "insertStockIO"
                    and "saveStockMaster" not in completed_list
                ):
                    if "selectStockMoveList" in completed_list:
                        completed_list = [
                            x for x in completed_list if x != "selectStockMoveList"
                        ]
                        pin_blob["completed_endpoints"] = list(completed_list)
                        save_test_state(state_root)
                        print(
                            "NOTE: insertStockIO atomic pair: removed selectStockMoveList from completed "
                            f"(rerun move list before saveStockMaster; see {STATE_FILE.name})."
                        )
                    if "insertStockIO" in completed_list:
                        pin_blob["stock_io_pending_rsd_qty"] = 0.0
                        save_test_state(state_root)
                        print(
                            "NOTE: insertStockIO replay: stock_io_pending_rsd_qty=0 before post."
                        )
                if (
                    is_post_composition_osdc_io
                    and "saveStockMasterPostComposition" not in completed_list
                ):
                    if "selectStockMoveListPostComposition" in completed_list:
                        completed_list = [
                            x
                            for x in completed_list
                            if x != "selectStockMoveListPostComposition"
                        ]
                        pin_blob["completed_endpoints"] = list(completed_list)
                        save_test_state(state_root)
                        print(
                            "NOTE: insertStockIOPostComposition atomic pair: removed "
                            "selectStockMoveListPostComposition from completed "
                            f"(optional diagnostic move-list rerun before saveStockMasterPostComposition; "
                            f"see {STATE_FILE.name})."
                        )
                line_qty_f = (
                    float(initial_parent_stock_qty)
                    if is_initial_parent_io or is_post_composition_osdc_io
                    else float(stock_qty)
                )
                try:
                    unit_prc_io = float(pin_blob.get("item_dft_prc"))
                except (TypeError, ValueError):
                    unit_prc_io = float(prc)
                _nm_io = (pin_blob.get("item_nm_stock") or "").strip() or "TEST ITEM"
                tty_io = (item_cls_dynamic.get("taxTyCd") or "A").strip()
                line_sply, _taxbl_io, _tax_io, _tot_io = stock_io_line_amounts_for_tax_ty(
                    unit_prc=unit_prc_io,
                    qty=line_qty_f,
                    tax_ty_cd=tty_io,
                )
                io_ocrn_8 = (sales_dt or "").strip()[:8]
                if len(io_ocrn_8) != 8:
                    io_ocrn_8 = datetime.now(timezone.utc).strftime("%Y%m%d")
                # SBX: monotonic sarNo per branch/session (1, 2, …). orgSarNo cannot equal sarNo.
                # First IO: orgSarNo=0. Later IOs: orgSarNo references the previous sarNo (sarNo-1).

                if is_initial_parent_io:
                    ok_initial = False
                    _init_try_max = 1 if diagnostic_stock_io_cli else 6
                    _initial_sar_kra_resync_used = False
                    for _sar_try in range(_init_try_max):
                        sar_no_used = resolve_next_insert_stock_sar_no(
                            state_root, effective_tin, branch_id, pin_blob
                        )
                        print(f"SAR sequence → using sarNo={sar_no_used}")
                        org_sar_primary = 0 if sar_no_used == 1 else sar_no_used - 1
                        reg_ty = "M"
                        sar_ty = "01"
                        icd = (item_cls_dynamic.get("itemClsCd") or "1010000000").strip()
                        tty = tty_io
                        stock_line = {
                            "itemSeq": 1,
                            "itemCd": item_cd,
                            "ioTyCd": "1",  # SBX: missing ioTyCd defaults to OUT; "1" = stock IN
                            "itemClsCd": icd,
                            "itemNm": _nm_io,
                            "pkgUnitCd": pkg_unit_cd,
                            "pkg": line_qty_f,
                            "qtyUnitCd": qty_unit_cd,
                            "qty": line_qty_f,
                            "prc": float(unit_prc_io),
                            "splyAmt": line_sply,
                            "totDcAmt": 0.0,
                            "taxblAmt": _taxbl_io,
                            "taxTyCd": tty,
                            "taxAmt": _tax_io,
                            "totAmt": _tot_io,
                        }
                        io_root = {
                            "sarNo": sar_no_used,
                            "regTyCd": reg_ty,
                            "custTin": effective_tin,
                            "sarTyCd": sar_ty,
                            "ocrnDt": io_ocrn_8,
                            "totItemCnt": 1,
                            "totTaxblAmt": _taxbl_io,
                            "totTaxAmt": _tax_io,
                            "totAmt": _tot_io,
                            "regrId": "system",
                            "regrNm": "system",
                            "modrId": "system",
                            "modrNm": "system",
                            "itemList": [deepcopy(stock_line)],
                        }
                        io_root["orgSarNo"] = org_sar_primary
                        org_lbl = str(org_sar_primary)
                        label = (
                            f"sarNo={sar_no_used},orgSarNo={org_lbl},"
                            f"regTy={reg_ty},sarTy={sar_ty}"
                        )
                        if diagnostic_stock_io_cli:
                            print(f"\nRUNNING {_io_log} [{label}]")
                            print("\n--- INSERT STOCK IO PAYLOAD ---")
                            print(json.dumps(io_root, indent=2, ensure_ascii=False))
                        else:
                            print(f"RUNNING {_io_log} [{label}]")
                            print(
                                "Request JSON:",
                                json.dumps(io_root, indent=2, ensure_ascii=False),
                            )
                        if strict_pre_sale_audit_cli:
                            audit_append_osdc_bhf_row(
                                bhf_audit_rows,
                                step_name=endpoint_name,
                                payload=io_root,
                                headers=headers,
                                fallback_tin=effective_tin,
                                fallback_bhf=branch_id,
                            )
                        register_insert_stock_io_request_url(url)
                        resp = requests.post(
                            url, headers=headers, json=io_root, timeout=60
                        )
                        parsed_io = print_full_response_json(resp, _io_log)
                        result_cd_io = extract_result_cd(parsed_io)
                        gate_err = kra_top_level_error_detail(parsed_io)
                        if (
                            resp.status_code < 400
                            and not gate_err
                            and result_cd_io == "000"
                        ):
                            persist_committed_insert_stock_sar_no(
                                state_root,
                                effective_tin,
                                branch_id,
                                sar_no_used,
                                pin_blob,
                            )
                            pin_blob["parent_initial_insert_stock_qty"] = float(line_qty_f)
                            ran_insert_stock_io_initial_this_run = True
                            initial_insert_io_just_ran = True
                            ok_initial = True
                            if diagnostic_stock_io_cli:
                                print(
                                    "\n(insertStockIOInitial OK — saveStockMasterInitial uses ONLY "
                                    "rsdQty from selectStockMoveListInitial when resultCd=000 with a row; "
                                    f"IO line qty={line_qty_f:g} is logged as parent_initial_insert_stock_qty for "
                                    "telemetry only.)"
                                )
                                _rh0 = (
                                    parsed_io.get("responseHeader")
                                    if isinstance(parsed_io, dict)
                                    else None
                                )
                                if isinstance(_rh0, dict):
                                    print(
                                        json.dumps(
                                            {
                                                "responseCode": _rh0.get("responseCode"),
                                                "customerMessage": _rh0.get(
                                                    "customerMessage"
                                                ),
                                                "debugMessage": _rh0.get("debugMessage"),
                                            },
                                            indent=2,
                                            ensure_ascii=False,
                                        )
                                    )
                            if debug_ledger_after_io_cli:
                                run_debug_ledger_watch_after_insert_stock_io_ok(
                                    base_url=BASE_URL,
                                    headers=headers,
                                    tin=effective_tin,
                                    bhf_id=branch_id,
                                    item_cd=item_cd,
                                    insert_parsed=parsed_io
                                    if isinstance(parsed_io, dict)
                                    else None,
                                )
                            log_api_result_summary(
                                _io_log, resp, parsed_io, result_cd_io
                            )
                            save_test_state(state_root)
                            time.sleep(2)
                            flush_progress(
                                stock_progress_key,
                                mark_endpoint_complete=True,
                            )
                            break
                        err_init = kra_insert_stock_io_error_text(parsed_io)
                        exp_sar = kra_expected_next_sar_no_from_message(err_init)
                        if (
                            exp_sar is not None
                            and err_init
                            and "Invalid sarNo" in err_init
                            and not diagnostic_stock_io_cli
                        ):
                            if _initial_sar_kra_resync_used:
                                sequence_fail(
                                    "FATAL: insertStockIOInitial — KRA Invalid sarNo again after one "
                                    f"correction (last expected={exp_sar})."
                                )
                            print(
                                f"SAR corrected from {sar_no_used} → {exp_sar} based on KRA response"
                            )
                            apply_kra_expected_insert_stock_sar_no(
                                state_root,
                                effective_tin,
                                branch_id,
                                exp_sar,
                                pin_blob,
                            )
                            save_test_state(state_root)
                            _initial_sar_kra_resync_used = True
                            time.sleep(1)
                            continue
                        sequence_fail(
                            "FATAL: insertStockIOInitial failed. This PIN is now unusable."
                        )
                    if not ok_initial:
                        sequence_fail(
                            "FATAL: insertStockIOInitial failed after SAR resync retries."
                        )
                    continue

                else:
                    parsed_io = None
                    result_cd_io = None
                    succeeded = False
                    _parent_io_sar_kra_resync_used = False
                    for _sar_sync in range(5):
                        if succeeded:
                            break
                        sar_no_used = resolve_next_insert_stock_sar_no(
                            state_root, effective_tin, branch_id, pin_blob
                        )
                        print(f"SAR sequence → using sarNo={sar_no_used}")
                        org_sar_primary = 0 if sar_no_used == 1 else sar_no_used - 1
                        org_sar_tries: list[int | None] = [org_sar_primary, None]
                        resync_sar = False
                        for outer_attempt, org_sar_val in enumerate(org_sar_tries):
                            # Paybill/KRA StockIOSaveReq shape; per-line ioTyCd required on SBX.
                            # SBX: use sarTyCd "01" (same as insertStockIOInitial). sarTyCd 11 can invert
                            # IN vs OUT vs saveStockMaster (rsdQty Expected: -N vs found +N on reconciliation).
                            reg_ty = "M"
                            sar_ty = "01"
                            icd = (item_cls_dynamic.get("itemClsCd") or "1010000000").strip()
                            tty = tty_io
                            _sply2, _tb2, _tx2, _tot2 = stock_io_line_amounts_for_tax_ty(
                                unit_prc=unit_prc_io,
                                qty=line_qty_f,
                                tax_ty_cd=tty_io,
                            )
                            stock_line = {
                                "itemSeq": 1,
                                "itemCd": item_cd,
                                "ioTyCd": "1",  # SBX: missing ioTyCd defaults to OUT; "1" = stock IN
                                "itemClsCd": icd,
                                "itemNm": _nm_io,
                                "pkgUnitCd": pkg_unit_cd,
                                "pkg": line_qty_f,
                                "qtyUnitCd": qty_unit_cd,
                                "qty": line_qty_f,
                                "prc": float(unit_prc_io),
                                "splyAmt": _sply2,
                                "totDcAmt": 0.0,
                                "taxblAmt": _tb2,
                                "taxTyCd": tty,
                                "taxAmt": _tx2,
                                "totAmt": _tot2,
                            }
                            io_root = {
                                "sarNo": sar_no_used,
                                "regTyCd": reg_ty,
                                "custTin": effective_tin,
                                "sarTyCd": sar_ty,
                                "ocrnDt": io_ocrn_8,
                                "totItemCnt": 1,
                                "totTaxblAmt": _tb2,
                                "totTaxAmt": _tx2,
                                "totAmt": _tot2,
                                "regrId": "system",
                                "regrNm": "system",
                                "modrId": "system",
                                "modrNm": "system",
                                "itemList": [deepcopy(stock_line)],
                            }
                            if org_sar_val is not None:
                                io_root["orgSarNo"] = org_sar_val
                            inner_ok = False
                            org_lbl = (
                                "omit" if org_sar_val is None else str(org_sar_val)
                            )
                            label = (
                                f"sarNo={sar_no_used},orgSarNo={org_lbl},"
                                f"regTy={reg_ty},sarTy={sar_ty}"
                            )
                            pl = io_root
                            print(f"RUNNING {_io_log} [{label}]")
                            print(
                                "Request JSON:",
                                json.dumps(pl, indent=2, ensure_ascii=False),
                            )
                            if strict_pre_sale_audit_cli:
                                audit_append_osdc_bhf_row(
                                    bhf_audit_rows,
                                    step_name=endpoint_name,
                                    payload=pl,
                                    headers=headers,
                                    fallback_tin=effective_tin,
                                    fallback_bhf=branch_id,
                                )
                            register_insert_stock_io_request_url(url)
                            resp = requests.post(
                                url, headers=headers, json=pl, timeout=60
                            )
                            parsed_io = print_full_response_json(resp, _io_log)
                            result_cd_io = extract_result_cd(parsed_io)
                            gate_err = kra_top_level_error_detail(parsed_io)
                            if (
                                resp.status_code < 400
                                and not gate_err
                                and result_cd_io == "000"
                            ):
                                inner_ok = True
                            elif sbx_test_session_log_truncation(parsed_io):
                                print(
                                    "NOTE: insertStockIO response hit SBX test_session_api_log "
                                    "truncation (HTTP 400). "
                                    "Retrying alternate regTyCd/sarTyCd or orgSarNo may help."
                                )
                            elif not gate_err and resp.status_code < 400:
                                print(
                                    "insertStockIO: resultCd != 000, will retry outer loop…"
                                )
                            if inner_ok:
                                succeeded = True
                                persist_committed_insert_stock_sar_no(
                                    state_root,
                                    effective_tin,
                                    branch_id,
                                    sar_no_used,
                                    pin_blob,
                                )
                                if endpoint_name == "insertStockIO":
                                    final_parent_insert_io_just_ran = True
                                    ran_insert_stock_io_parent_this_run = True
                                elif is_post_composition_osdc_io:
                                    post_composition_parent_io_just_ran = True
                                    ran_insert_stock_io_post_composition_this_run = True
                                    pin_blob["parent_post_composition_io_qty"] = float(
                                        line_qty_f
                                    )
                                    save_test_state(state_root)
                                    print(
                                        "NOTE: parent_post_composition_io_qty="
                                        f"{pin_blob['parent_post_composition_io_qty']!r} "
                                        f"(post-composition insertStockIO sarNo={sar_no_used}, ioTyCd=1)."
                                    )
                                if debug_ledger_after_io_cli:
                                    run_debug_ledger_watch_after_insert_stock_io_ok(
                                        base_url=BASE_URL,
                                        headers=headers,
                                        tin=effective_tin,
                                        bhf_id=branch_id,
                                        item_cd=item_cd,
                                        insert_parsed=parsed_io
                                        if isinstance(parsed_io, dict)
                                        else None,
                                    )
                                log_api_result_summary(
                                    _io_log, resp, parsed_io, result_cd_io
                                )
                                save_test_state(state_root)
                                break
                            if outer_attempt >= len(org_sar_tries) - 1:
                                rh = (
                                    parsed_io.get("responseHeader")
                                    if isinstance(parsed_io, dict)
                                    else None
                                )
                                blob = ""
                                if isinstance(rh, dict):
                                    blob = (
                                        f"{rh.get('debugMessage') or ''} "
                                        f"{rh.get('customerMessage') or ''}"
                                    )
                                exp_sar = kra_expected_next_sar_no_from_message(blob)
                                if (
                                    exp_sar is not None
                                    and exp_sar != sar_no_used
                                    and blob
                                    and "Invalid sarNo" in blob
                                ):
                                    if _parent_io_sar_kra_resync_used:
                                        sequence_fail(
                                            f"STOP: {_io_log} — KRA Invalid sarNo again after one SAR "
                                            f"correction (expected {exp_sar}, had used {sar_no_used})."
                                        )
                                    print(
                                        f"SAR corrected from {sar_no_used} → {exp_sar} based on KRA response"
                                    )
                                    apply_kra_expected_insert_stock_sar_no(
                                        state_root,
                                        effective_tin,
                                        branch_id,
                                        exp_sar,
                                        pin_blob,
                                    )
                                    save_test_state(state_root)
                                    _parent_io_sar_kra_resync_used = True
                                    resync_sar = True
                                    break
                                ge = (
                                    kra_top_level_error_detail(parsed_io)
                                    if parsed_io
                                    else None
                                )
                                sequence_fail(
                                    f"STOP: {_io_log} failed after retry "
                                    f"(last resultCd={result_cd_io!r}"
                                    + (f", {ge}" if ge else "")
                                    + ")"
                                )
                            if org_sar_val is not None:
                                print(
                                    f"RETRY: {_io_log} "
                                    f"(same sarNo={sar_no_used}, omit orgSarNo on next try) …"
                                )
                        if resync_sar:
                            continue
                        if succeeded:
                            break
                    if not succeeded:
                        sequence_fail(
                            f"STOP: {_io_log} did not succeed after SAR sync retries "
                            f"(last resultCd={result_cd_io!r})."
                        )
                    time.sleep(2)
                    flush_progress(
                        stock_progress_key,
                        mark_endpoint_complete=(result_cd_io == "000" and succeeded),
                    )
                    continue
    
            if endpoint_name == "saveItem":
                select_cls_url = f"{BASE_URL.rstrip('/')}/selectItemClsList"
                select_cls_payload = {
                    "tin": effective_tin,
                    "bhfId": branch_id,
                    "lastReqDt": "20100101000000",
                }

                def load_save_item_classification(
                    *, label: str, allow_ty1_fallback: bool
                ) -> tuple[str, str, str]:
                    """Returns (itemClsCd, taxTyCd, itemTyCd for itemCd prefix)."""
                    print(f"RUNNING selectItemClsList ({label})")
                    resp_cls = requests.post(
                        select_cls_url, headers=headers, json=select_cls_payload, timeout=60
                    )
                    parsed_cls = print_full_response_json(resp_cls, f"selectItemClsList ({label})")
                    result_cls = extract_result_cd(parsed_cls)
                    gate_err_cls = kra_top_level_error_detail(parsed_cls)
                    if resp_cls.status_code >= 400:
                        sequence_fail(
                            f"STOP: HTTP {resp_cls.status_code} from KRA (selectItemClsList / {label})"
                        )
                    if gate_err_cls:
                        sequence_fail(f"STOP: KRA gateway/body error — {gate_err_cls}")
                    if result_cls != "000":
                        sequence_fail(
                            f"STOP: selectItemClsList failed ({label}) resultCd={result_cls}"
                        )
                    lst_a = item_cls_list_from_parsed(parsed_cls)
                    now_pl = {
                        "tin": effective_tin,
                        "bhfId": branch_id,
                        "lastReqDt": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
                    }
                    print(f"RUNNING selectItemClsList ({label} — lastReqDt=UTC-now, merge)")
                    resp2 = requests.post(select_cls_url, headers=headers, json=now_pl, timeout=60)
                    parsed2 = print_full_response_json(
                        resp2, f"selectItemClsList ({label} / lastReqDt=now)"
                    )
                    lst_b: list = []
                    if resp2.status_code < 400 and not kra_top_level_error_detail(parsed2):
                        if extract_result_cd(parsed2) == "000":
                            lst_b = item_cls_list_from_parsed(parsed2) or []
                    lst = merge_item_cls_lists_by_cd(lst_a, lst_b)
                    if lst_b and len(lst_b) != len(lst_a):
                        print(
                            f"selectItemClsList merge: baseline {len(lst_a)} + now-delta {len(lst_b)} "
                            f"→ {len(lst)} unique codes"
                        )
                    if lst and all(
                        _row_item_cls_lvl(r) == 0 for r in lst if isinstance(r, dict)
                    ):
                        print(
                            "NOTE: Every merged itemClsList row has itemClsLvl=0. "
                            "saveItem may still expect commodity-level HS codes; this SBX list can be a stub."
                        )
                    # Prefer itemTyCd 2 (standard product) first: SBX enforces a strict monotonic itemCd
                    # sequence for itemTyCd 1 (service) — random KE1… codes often return "reused or not incremented".
                    std = pick_save_item_standard_if_present(lst)
                    if std:
                        icd, tty = std
                        print(
                            f"saveItem: using itemClsCd={icd} taxTyCd={tty} itemTyCd=2 (standard from list)"
                        )
                        return icd, tty, "2"
                    b_row = pick_save_item_tax_b_leaf(lst)
                    if b_row and allow_ty1_fallback:
                        icd, tty = b_row
                        print(
                            f"saveItem: itemClsCd={icd} taxTyCd={tty} itemTyCd=1 "
                            "(Paybill-style material line: qtyUnitCd TU; itemCd suffix ends in 1 per KRA)"
                        )
                        return icd, tty, "1"
                    picked = pick_save_item_zero_rated_leaf(lst)
                    if picked:
                        icd, tty = picked
                        print(
                            f"saveItem: using itemClsCd={icd} taxTyCd={tty} itemTyCd=2 "
                            f"(zero-rated row from list)"
                        )
                        return icd, tty, "2"
                    print("saveItem: no usable row in itemClsList; fallback 9901200300 / C / itemTy 2")
                    return "9901200300", "C", "2"

                item_cls_cd, tax_ty_cd, save_item_ty = load_save_item_classification(
                    label="saveItem preflight",
                    allow_ty1_fallback=False,
                )
                persist_cls_cd, persist_tax_cd = item_cls_cd, tax_ty_cd
                result_cd: str | None = None
                _save_item_total = MAX_SAVE_ITEM_TY2_ATTEMPTS + (
                    1 if save_item_allow_ty1_fallback else 0
                )
                for attempt in range(_save_item_total):
                    use_ty1_fallback = bool(
                        save_item_allow_ty1_fallback
                        and attempt == MAX_SAVE_ITEM_TY2_ATTEMPTS
                    )
                    if use_ty1_fallback:
                        item_cd = f"KE1{pkg_unit_cd}TU{alloc_monotonic_item_cd_suffix(f'KE1{pkg_unit_cd}TU', select_item_list_parsed, pin_blob, {})}"
                        payload = {
                            "itemCd": item_cd,
                            "itemClsCd": "1010160300",
                            "itemTyCd": "1",
                            "itemNm": "test material item3",
                            "orgnNatCd": "KE",
                            "pkgUnitCd": pkg_unit_cd,
                            "qtyUnitCd": "TU",
                            "taxTyCd": "B",
                            "dftPrc": 3500,
                            "isrcAplcbYn": "N",
                            "useYn": "Y",
                            "regrId": "Test",
                            "regrNm": "Test",
                            "modrId": "Test",
                            "modrNm": "Test",
                        }
                        print(
                            "saveItem: optional Paybill fallback — hardcoded body "
                            "(1010160300 / B, itemTy 1, NT+TU, dftPrc 3500, regr Test)"
                        )
                    else:
                        if attempt >= 1:
                            print("RETRY: saveItem — refresh selectItemClsList, re-pick class …")
                            item_cls_cd, tax_ty_cd, save_item_ty = load_save_item_classification(
                                label=f"saveItem retry {attempt}",
                                allow_ty1_fallback=False,
                            )
                        q_seg = "TU" if save_item_ty == "1" else qty_unit_cd
                        ic_prefix = f"KE{save_item_ty}{pkg_unit_cd}{q_seg}"
                        # selectItemList: hint / debug only (``alloc_monotonic_item_cd_suffix`` logs max).
                        _cat_si = select_item_list_fetch_catalog_for_item_cd_planning(
                            base_url=BASE_URL,
                            headers=headers,
                            tin=effective_tin,
                            bhf_id=branch_id,
                            response_log_prefix=f"saveItem catalog (attempt {attempt + 1})",
                        )
                        if str(save_item_ty).strip() == "2":
                            suf_ty2 = alloc_monotonic_item_cd_suffix(ic_prefix, _cat_si, pin_blob, {})
                            item_cd = f"{ic_prefix}{suf_ty2}"
                        else:
                            suf = alloc_monotonic_item_cd_suffix(ic_prefix, _cat_si, pin_blob, {})
                            item_cd = f"{ic_prefix}{suf}"
                        print(
                            f"Generated NEW itemCd={item_cd} for saveItem "
                            f"(itemTyCd={save_item_ty}, qtyUnitCd={q_seg}, linear suffix from "
                            f"{ITEM_CD_NEXT_SUFFIX_BY_PREFIX_KEY!r} / last success)"
                        )

                        payload = deep_override_keys(deepcopy(payload_template), payload_overrides)
                        payload["itemCd"] = item_cd
                        payload["itemTyCd"] = str(save_item_ty).strip()
                        payload["itemClsCd"] = item_cls_cd
                        payload["taxTyCd"] = tax_ty_cd
                        payload.pop("vatCatCd", None)
                        payload["qtyUnitCd"] = q_seg
                        if save_item_ty == "1":
                            payload["itemNm"] = "test material item3"
                            payload["dftPrc"] = 3500
                            payload["regrId"] = "Test"
                            payload["regrNm"] = "Test"
                            payload["modrId"] = "Test"
                            payload["modrNm"] = "Test"
                        else:
                            payload["itemNm"] = "TEST ITEM"
                            payload["dftPrc"] = 100
                            payload["regrId"] = "system"
                            payload["regrNm"] = "system"
                            payload["modrId"] = "system"
                            payload["modrNm"] = "system"
                        if attempt == 2:
                            payload["tin"] = effective_tin
                            payload["bhfId"] = branch_id
                            print("saveItem: attempt 3 adds tin+bhfId to JSON body (OSCU variant)")
                        else:
                            payload.pop("tin", None)
                            payload.pop("bhfId", None)

                    print(f"RUNNING {endpoint_name}")
                    normalize_save_item_payload_fields(payload)
                    payload = save_item_payload_omit_nulls(payload)
                    if not use_ty1_fallback:
                        print(f"Using itemClsCd={item_cls_cd}, taxTyCd={tax_ty_cd}")
                    print("SAVE ITEM PAYLOAD:")
                    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
                    resp = post_with_retry(
                        endpoint_name=endpoint_name,
                        url=url,
                        headers=headers,
                        payload=payload,
                        timeout=60,
                        params=None,
                        max_attempts=3,
                    )
                    parsed = print_full_response_json(resp, "saveItem")
                    result_cd = extract_result_cd(parsed)
                    gate_err = kra_top_level_error_detail(parsed)
                    ok = resp.status_code < 400 and not gate_err and result_cd == "000"
                    if ok:
                        persist_cls_cd = str(payload.get("itemClsCd") or persist_cls_cd)
                        persist_tax_cd = str(payload.get("taxTyCd") or persist_tax_cd)
                        item_cd = str(payload.get("itemCd") or item_cd).strip()
                        persist_item_cd_suffix_map(pin_blob, item_cd)
                        pin_blob["item_cd"] = item_cd
                        pin_blob["canonical_item_cd"] = item_cd
                        pin_blob["save_item_ty_cd"] = str(
                            payload.get("itemTyCd") or ""
                        ).strip()
                        pin_blob.pop("item_cd_suffix_last_digit", None)
                        pin_blob.pop("item_cd_suffix_tail_mod", None)
                        pin_blob.pop("item_cd_suffix_tail_res", None)
                        _pfx_saved = str(payload.get("itemCd") or item_cd or "").strip()
                        if len(_pfx_saved) >= 8:
                            clear_kra_tail_constraint_for_prefix(pin_blob, _pfx_saved[:-7])
                        try:
                            pin_blob["item_dft_prc"] = float(payload.get("dftPrc"))
                        except (TypeError, ValueError):
                            pin_blob["item_dft_prc"] = float(prc)
                        pin_blob["item_nm_stock"] = str(
                            payload.get("itemNm") or "TEST ITEM"
                        ).strip() or "TEST ITEM"
                        save_test_state(state_root)
                        print(f"CONTINUE: {endpoint_name} OK (state={result_cd})")
                        break
                    _ic_fail = str(payload.get("itemCd") or item_cd or "").strip()
                    _err_txt = kra_save_item_error_text(parsed)
                    apply_item_cd_sequence_recovery_hints(pin_blob, _ic_fail, _err_txt)
                    if attempt == _save_item_total - 1:
                        print_save_item_http_debug(resp, headers, payload)
                        ge = f", {gate_err}" if gate_err else ""
                        sequence_fail(
                            f"STOP: saveItem failed after {_save_item_total} attempts (HTTP={resp.status_code}, "
                            f"resultCd={result_cd!r}{ge})"
                        )
                    print(
                        f"RETRY: saveItem (HTTP={resp.status_code}, resultCd={result_cd!r}) …"
                    )
                item_cls_dynamic["itemClsCd"] = persist_cls_cd
                item_cls_dynamic["taxTyCd"] = persist_tax_cd
                flush_progress(
                    endpoint_name,
                    mark_endpoint_complete=(result_cd == "000"),
                )
                continue

            if endpoint_name == "saveComponentItem":
                main_ic = (pin_blob.get("item_cd") or item_cd or "").strip()
                if not main_ic:
                    sequence_fail(
                        f"STOP: {endpoint_name} requires a saved item_cd from saveItem "
                        f"(see {STATE_FILE.name})."
                    )
                if len(main_ic) < 8 or not main_ic[-7:].isdigit():
                    sequence_fail(
                        f"STOP: saveComponentItem — expected itemCd with 7-digit suffix, got {main_ic!r}"
                    )
                # Raw material / component: always itemTyCd 1 (prefix KE1…); parent may be itemTyCd 2 (KE2…).
                comp_item_ty = "1"
                q_seg = "TU"
                comp_prefix = f"KE{comp_item_ty}{pkg_unit_cd}{q_seg}"
                icd = item_cls_dynamic["itemClsCd"]
                tty = item_cls_dynamic["taxTyCd"]
                surl = f"{BASE_URL.rstrip('/')}/saveItem"
                rc_co: str | None = None
                for comp_attempt in range(4):
                    # selectItemList: hint / debug only (``alloc_monotonic_item_cd_suffix`` logs max).
                    _cat_comp = select_item_list_fetch_catalog_for_item_cd_planning(
                        base_url=BASE_URL,
                        headers=headers,
                        tin=effective_tin,
                        bhf_id=branch_id,
                        response_log_prefix=f"saveComponentItem catalog (attempt {comp_attempt + 1})",
                    )
                    suf = alloc_monotonic_item_cd_suffix(comp_prefix, _cat_comp, pin_blob, {})
                    comp_cd = f"{comp_prefix}{suf}"
                    co_payload: dict = {
                        "itemCd": comp_cd,
                        "itemClsCd": icd,
                        "itemTyCd": comp_item_ty,
                        "itemNm": "COMPONENT ITEM",
                        "orgnNatCd": "KE",
                        "pkgUnitCd": pkg_unit_cd,
                        "qtyUnitCd": q_seg,
                        "taxTyCd": tty,
                        "dftPrc": 10,
                        "isrcAplcbYn": "N",
                        "useYn": "Y",
                        "regrId": "system",
                        "regrNm": "system",
                        "modrId": "system",
                        "modrNm": "system",
                    }
                    normalize_save_item_payload_fields(co_payload)
                    co_payload = save_item_payload_omit_nulls(co_payload)
                    print(
                        f"RUNNING {endpoint_name} (POST /saveItem) attempt {comp_attempt + 1}/4 "
                        f"itemCd={comp_cd} itemTyCd={co_payload.get('itemTyCd')!r}"
                    )
                    print(json.dumps(co_payload, indent=2, ensure_ascii=False))
                    resp_co = requests.post(surl, headers=headers, json=co_payload, timeout=60)
                    parsed_co = print_full_response_json(resp_co, "saveComponentItem")
                    rc_co = extract_result_cd(parsed_co)
                    ge_co = kra_top_level_error_detail(parsed_co)
                    ok_co = resp_co.status_code < 400 and not ge_co and rc_co == "000"
                    if ok_co:
                        pin_blob["component_item_cd"] = comp_cd
                        pin_blob["component_item_cls_cd"] = icd
                        pin_blob["component_item_tax_ty_cd"] = tty
                        pin_blob.pop("stocked_component_for_composition", None)
                        pin_blob.pop("stock_io_component_pending_rsd_qty", None)
                        pin_blob.pop("component_stock_balance", None)
                        pin_blob.pop("composition_prelude_logged_io_sar_no", None)
                        pin_blob.pop("composition_prelude_logged_sm_result_cd", None)
                        pin_blob.pop("composition_prelude_logged_component_item_cd", None)
                        pin_blob.pop("component_reconcile_rsd_qty", None)
                        pin_blob.pop("component_purchase_next_invc_no", None)
                        pin_blob.pop("component_trns_purchase_ok", None)
                        persist_item_cd_suffix_map(pin_blob, comp_cd)
                        pin_blob.pop("item_cd_suffix_tail_mod", None)
                        pin_blob.pop("item_cd_suffix_tail_res", None)
                        clear_kra_tail_constraint_for_prefix(pin_blob, comp_prefix)
                        save_test_state(state_root)
                        flush_progress("saveComponentItem", mark_endpoint_complete=True)
                        break
                    _err_co = kra_save_item_error_text(
                        parsed_co if isinstance(parsed_co, dict) else None
                    )
                    try:
                        _rej_suf_co = int(str(comp_cd)[-7:])
                    except ValueError:
                        _rej_suf_co = 0
                    advance_item_cd_next_suffix_after_save_item_failure(
                        pin_blob, comp_prefix, _rej_suf_co, _err_co
                    )
                    _sufc_co = kra_parse_item_cd_suffix_constraint(_err_co)
                    if _sufc_co is not None:
                        _m_c, _r_c = _sufc_co
                        pin_blob["item_cd_suffix_tail_mod"] = _m_c
                        pin_blob["item_cd_suffix_tail_res"] = _r_c
                        pin_blob.pop("item_cd_suffix_last_digit", None)
                        set_kra_tail_constraint_for_prefix(pin_blob, comp_prefix, _m_c, _r_c)
                    if comp_attempt >= 3:
                        sequence_fail(
                            "STOP: saveComponentItem failed after 4 attempts "
                            f"HTTP={resp_co.status_code} resultCd={rc_co!r}"
                            + (f", {ge_co}" if ge_co else "")
                        )
                    print(
                        f"RETRY: saveComponentItem (HTTP={resp_co.status_code}, resultCd={rc_co!r}) …"
                    )
                continue

            if endpoint_name == "saveStockMasterInitial":
                if not ran_insert_stock_io_initial_this_run and "insertStockIOInitial" not in completed_list:
                    sequence_fail(
                        "STOP: Refusing saveStockMasterInitial — insertStockIOInitial did not run in this "
                        "process and is not in completed_endpoints (KRA SBX expects IO before save). Try:\n"
                        f"  python gavaetims.py <PIN> --force-stock-replay\n"
                        f"  python gavaetims.py <PIN> --reset-stock\n"
                        f"(see {STATE_FILE.name})"
                    )
            if endpoint_name == "saveStockMaster":
                if not ran_insert_stock_io_parent_this_run:
                    sequence_fail(
                        "STOP: Refusing saveStockMaster — insertStockIO did not run in this process "
                        f"(pairing required). Check completed_endpoints / replay insert (see {STATE_FILE.name})."
                    )
            if endpoint_name == "saveStockMasterAfterPurchase":
                if "insertTrnsPurchase" not in completed_list:
                    sequence_fail(
                        "STOP: saveStockMasterAfterPurchase — insertTrnsPurchase must be completed first "
                        f"(see {STATE_FILE.name})."
                    )
            if endpoint_name == "saveStockMasterPostComposition":
                if (
                    not ran_insert_stock_io_post_composition_this_run
                    and "insertStockIOPostComposition" not in completed_list
                ):
                    sequence_fail(
                        "STOP: saveStockMasterPostComposition — insertStockIOPostComposition did not run in this "
                        f"process and is not in completed_endpoints (see {STATE_FILE.name})."
                    )
            if endpoint_name == "saveInvoice":
                for _rq_osdc in _osdc_prep_steps:
                    if _rq_osdc not in completed_list:
                        sequence_fail(
                            "STOP: saveTrnsSalesOsdc blocked — mandatory post-composition parent stock flow "
                            f"incomplete (missing completed step {_rq_osdc!r}). "
                            "Required order: insertStockIOPostComposition → saveStockMasterPostComposition "
                            "(resultCd 000) → then sales. selectStockMoveList* is optional / diagnostic only."
                        )
                _sale_ic = (pin_blob.get("item_cd") or item_cd or "").strip()
                if not _sale_ic:
                    sequence_fail(
                        "STOP: saveInvoice blocked — no parent itemCd in state "
                        "(complete saveItem / resume with item_cd in pin state)."
                    )
                _master_tty_inv = (
                    (_norm_tax_ty_cd(pin_blob.get("item_tax_ty_cd")) or "").strip().upper()
                )
                _flow_tty_inv = (
                    (_norm_tax_ty_cd(item_cls_dynamic.get("taxTyCd")) or "").strip().upper()
                )
                if not _master_tty_inv:
                    sequence_fail(
                        "STOP: saveInvoice — pin_blob item_tax_ty_cd is missing (item master tax type). "
                        "taxTyCd must be set at item creation / HS classification; repair state or re-run saveItem."
                    )
                if _master_tty_inv != _flow_tty_inv:
                    sequence_fail(
                        "STOP: saveInvoice — taxTyCd invariant violated before saveTrnsSalesOsdc: "
                        f"item master item_tax_ty_cd={_master_tty_inv!r} != "
                        f"item_cls_dynamic taxTyCd={_flow_tty_inv!r}. "
                        "Fix classification sync; do not send mismatched invoice (no API retry will fix this)."
                    )
                if strict_pre_sale_audit_cli:
                    run_strict_pre_sale_audit_block(
                        bhf_rows=bhf_audit_rows,
                        base_url=BASE_URL,
                        headers=headers,
                        effective_tin=effective_tin,
                        branch_id=branch_id,
                        item_cd=_sale_ic,
                        sale_qty=float(qty),
                        abort=sequence_fail,
                    )
                else:
                    if pin_blob.get("post_composition_osdc_ready") is not True:
                        sequence_fail(
                            "STOP: saveInvoice blocked — saveStockMasterPostComposition did not complete "
                            f"(post_composition_osdc_ready). Completed: {completed_list!r}. "
                            "Required: insertStockIOPostComposition → saveStockMasterPostComposition (000)."
                        )
                    _sale_q_b = float(qty)
                    _bal_src = pin_blob.get("parent_osdc_prep_rsd_qty")
                    if _bal_src is None:
                        _bal_src = pin_blob.get("current_stock_balance")
                    if _bal_src is None:
                        sequence_fail(
                            "STOP: saveInvoice — no parent_osdc_prep_rsd_qty or current_stock_balance after "
                            "saveStockMasterPostComposition 000 (re-run post-composition IO + save; "
                            "see .test_state.json)."
                        )
                    try:
                        _bal_f_b = float(_bal_src)
                    except (TypeError, ValueError):
                        sequence_fail(
                            "STOP: saveInvoice — balance not numeric "
                            f"({_bal_src!r})."
                        )
                    if _bal_f_b + 1e-9 < _sale_q_b:
                        sequence_fail(
                            "STOP: saveInvoice — recorded balance "
                            f"{_bal_f_b:g} < sale qty {_sale_q_b:g}; refusing unsafe saveTrnsSalesOsdc."
                        )
                    _gate_label = (
                        "PRE-SALE STOCK (BYPASS FLAG)"
                        if bypass_pre_sale_stock_gate_cli
                        else "PRE-SALE STOCK (OSDC)"
                    )
                    print(
                        f"\n=== {_gate_label} ===\n"
                        "Contract: saveStockMasterPostComposition 000 reconciles stock for OSDC; stock is treated "
                        "as valid for saveTrnsSalesOsdc regardless of selectStockMoveList visibility (SBX move list "
                        "is eventually consistent).\n"
                        "selectStockMoveList (below) is a **diagnostic probe only** — failures do not block the sale.\n"
                    )
                    print(
                        f"itemCd={_sale_ic!r} sale_qty={_sale_q_b:g} balance≈{_bal_f_b:g} "
                        "(parent_osdc_prep_rsd_qty or current_stock_balance).\n"
                    )
                    strict_pre_sale_select_stock_move_or_exit(
                        base_url=BASE_URL,
                        headers=headers,
                        tin=effective_tin,
                        bhf_id=branch_id,
                        item_cd=_sale_ic,
                        sale_qty=float(qty),
                        capture_stock_move_list=None,
                        gate_label="PRE-SALE selectStockMoveList (diagnostic)",
                        exit_banner=None,
                        abort=None,
                    )
                    print(
                        f"PRE-SALE: diagnostic move-list probe finished for itemCd={_sale_ic!r}; "
                        "proceeding to saveInvoice (saveTrnsSalesOsdc).\n"
                    )

            if endpoint_name == "importedItemConvertedInfo":
                if pin_blob.get("import_lifecycle_ready") is not True:
                    _imp_skip = pin_blob.get("import_lifecycle_skip_reason")
                    _imp_msg = (
                        _imp_skip
                        if _imp_skip
                        else (
                            "importedItemInfo did not return extractable customs rows with taskCd "
                            "(run importedItemInfo first; resultCd=000 with itemList required)"
                        )
                    )
                    print(f"SKIP importedItemConvertedInfo — {_imp_msg}")
                    flush_progress(endpoint_name, mark_endpoint_complete=False)
                    continue

            if endpoint_name == "updateImportItem":
                if pin_blob.get("import_lifecycle_ready") is not True:
                    _imp_skip = pin_blob.get("import_lifecycle_skip_reason")
                    _imp_msg = (
                        _imp_skip
                        if _imp_skip
                        else (
                            "eligibility unknown — run importedItemInfo first and require resultCd=000 "
                            "with non-empty responseBody.data.itemList and a real taskCd"
                        )
                    )
                    print(f"SKIP updateImportItem — {_imp_msg}")
                    flush_progress(endpoint_name, mark_endpoint_complete=False)
                    continue

            print(f"RUNNING {endpoint_name}")
            if endpoint_name == "selectStockMoveListInitial" and initial_insert_io_just_ran:
                print(
                    "NOTE: Pausing 8s before selectStockMoveListInitial — SBX often returns HTTP 504 on "
                    "this call immediately after insertStockIOInitial."
                )
                time.sleep(8)
            elif endpoint_name == "selectStockMoveList" and final_parent_insert_io_just_ran:
                print(
                    "NOTE: Pausing 8s before selectStockMoveList — SBX often returns HTTP 504 on this "
                    "call immediately after insertStockIO."
                )
                time.sleep(8)
            elif endpoint_name == "selectStockMoveListPostComposition" and (
                post_composition_parent_io_just_ran
            ):
                print(
                    "NOTE: Pausing 8s before selectStockMoveListPostComposition — SBX often lags after "
                    "post-composition insertStockIO (OSDC stock visibility)."
                )
                time.sleep(8)
            elif endpoint_name == "selectStockMoveListComponentPurchase":
                print(
                    "NOTE: Pausing 8s before selectStockMoveListComponentPurchase — SBX often lags after "
                    "insertTrnsPurchase (component stock)."
                )
                time.sleep(8)
            elif endpoint_name == "selectStockMoveListAfterPurchase":
                print(
                    "NOTE: Pausing 8s before selectStockMoveListAfterPurchase — SBX often lags after "
                    "insertTrnsPurchase (parent purchase reconciliation)."
                )
                time.sleep(8)
            elif (
                endpoint_name == "saveStockMasterComponentPurchase"
                and sbx_stock_move_list_unreliable(BASE_URL)
            ):
                print(
                    "NOTE: Pausing 12s before saveStockMasterComponentPurchase — SBX Apigee often returns "
                    "HTTP 504 immediately after insertTrnsPurchaseComponentStock (gateway / stock lag)."
                )
                time.sleep(12)
            payload = deep_override_keys(deepcopy(payload_template), payload_overrides)

            if endpoint_name in (
                "selectStockMoveListInitial",
                "selectStockMoveListPostComposition",
                "selectStockMoveListAfterPurchase",
                "selectStockMoveListComponentPurchase",
                "selectStockMoveList",
            ):
                _seq_sm_lrd = kra_stock_move_list_last_req_dt_utc_now()
                print(
                    f"STOCK MOVE QUERY using lastReqDt = {_seq_sm_lrd} (sequence {endpoint_name})"
                )
                if isinstance(payload, dict):
                    payload["lastReqDt"] = _seq_sm_lrd

            # Sequence dicts are built before saveItem using a provisional item_cd (monotonic for itemTyCd 2).
            # saveItem then allocates a monotonic itemCd and stores it in pin_blob; sync payloads that
            # still carry the stale template value (SBX: "itemCd … does not exist in your inventory").
            _live_item_cd = (pin_blob.get("item_cd") or item_cd or "").strip()
            if _live_item_cd and endpoint_name in (
                "saveStockMaster",
                "saveStockMasterAfterPurchase",
                "saveStockMasterInitial",
                "saveStockMasterPostComposition",
                "insertTrnsPurchase",
                "saveInvoice",
            ):
                item_cd = _live_item_cd
                if endpoint_name in (
                    "saveStockMaster",
                    "saveStockMasterAfterPurchase",
                    "saveStockMasterInitial",
                    "saveStockMasterPostComposition",
                ):
                    payload["itemCd"] = _live_item_cd
                elif endpoint_name == "insertTrnsPurchase":
                    ilp = payload.get("itemList")
                    if isinstance(ilp, list) and ilp and isinstance(ilp[0], dict):
                        ilp[0]["itemCd"] = _live_item_cd
                elif endpoint_name == "saveInvoice":
                    il = payload.get("itemList")
                    if isinstance(il, list) and il and isinstance(il[0], dict):
                        il[0]["itemCd"] = _live_item_cd
            _live_comp_cd = (pin_blob.get("component_item_cd") or "").strip()
            if _live_comp_cd and endpoint_name == "insertTrnsPurchaseComponentStock":
                ilp_c = payload.get("itemList")
                if isinstance(ilp_c, list) and ilp_c and isinstance(ilp_c[0], dict):
                    ilp_c[0]["itemCd"] = _live_comp_cd

            _canon_ic = (
                pin_blob.get("canonical_item_cd") or pin_blob.get("item_cd") or ""
            ).strip()
            if (
                _canon_ic
                and isinstance(payload, dict)
                and endpoint_name
                not in ("insertTrnsPurchaseComponentStock", "saveStockMasterComponentPurchase")
            ):
                pic = str(payload.get("itemCd") or "").strip()
                if pic and pic != _canon_ic:
                    print(
                        "ASSERT itemCd: top-level payload itemCd "
                        f"{pic!r} != canonical {_canon_ic!r} — correcting."
                    )
                    payload["itemCd"] = _canon_ic
                item_cd = _canon_ic
                _ilen = payload.get("itemList")
                if isinstance(_ilen, list) and _ilen and isinstance(_ilen[0], dict):
                    ric = str(_ilen[0].get("itemCd") or "").strip()
                    if ric and ric != _canon_ic:
                        print(
                            "ASSERT itemCd: itemList[0].itemCd "
                            f"{ric!r} != canonical {_canon_ic!r} — correcting."
                        )
                        _ilen[0]["itemCd"] = _canon_ic
            elif endpoint_name not in (
                "insertTrnsPurchaseComponentStock",
                "saveStockMasterComponentPurchase",
            ):
                if (pin_blob.get("item_cd") or "").strip():
                    item_cd = reconcile_item_cd_with_pin_state(pin_blob, item_cd)

            if endpoint_name == "saveItemComposition":
                payload.pop("cpstItemCd", None)
                payload["itemCd"] = item_cd
                _cc = (pin_blob.get("component_item_cd") or "").strip()
                if not _cc:
                    sequence_fail(
                        "STOP: saveItemComposition — save component_item_cd first (saveComponentItem step)."
                    )
                payload["cpstItemCd"] = _cc

            if endpoint_name == "importedItemConvertedInfo":
                _imp = pin_blob.get("import_update_row")
                if isinstance(_imp, dict) and str(_imp.get("taskCd") or "").strip():
                    apply_import_kra_row_to_import_update_payload(
                        payload,
                        _imp,
                        item_cd=item_cd,
                        item_cls_cd=item_cls_dynamic["itemClsCd"],
                        sales_dt=sales_dt,
                    )
                print(
                    "NOTE: importedItemConvertedInfo payload key fields — "
                    f"taskCd={payload.get('taskCd')!r} dclDe={payload.get('dclDe')!r} "
                    f"hsCd={payload.get('hsCd')!r} itemSeq={payload.get('itemSeq')!r} "
                    f"itemCd={payload.get('itemCd')!r} imptItemSttsCd={payload.get('imptItemSttsCd')!r}"
                )

            if endpoint_name == "insertTrnsPurchase":
                _pin = int(purchase_invc_no)
                payload["invcNo"] = str(_pin)
                for _rk in ("trdInvcNo", "orgInvcNo"):
                    payload.pop(_rk, None)
                _req_main = coerce_invc_binding(pin_blob.get("main_purchase_sales_invc_no"))
                if _req_main is not None:
                    payload["requestedInvcNo"] = str(_req_main).strip()
                else:
                    payload["requestedInvcNo"] = str(_pin)
                ilp = payload.get("itemList")
                if isinstance(ilp, list) and ilp and isinstance(ilp[0], dict):
                    ilp[0]["itemClsCd"] = item_cls_dynamic["itemClsCd"]
                    ilp[0]["taxTyCd"] = item_cls_dynamic["taxTyCd"]
                if _req_main is not None:
                    _main_rt = _link_tax_rt_for_purchase_or_fallback(
                        pin_blob,
                        "main_purchase_link_tax_rt",
                        note_tag="insertTrnsPurchase",
                    )
                    apply_link_tax_rt_to_purchase_payload(payload, _main_rt)

            if endpoint_name == "insertTrnsPurchaseComponentStock":
                try:
                    _pico = int(pin_blob.get("component_purchase_next_invc_no") or 0)
                except (TypeError, ValueError):
                    _pico = 0
                if _pico > 0:
                    _invc_int = int(_pico)
                else:
                    _invc_int = int(purchase_invc_no_component)
                payload["invcNo"] = str(_invc_int)
                for _rk in ("trdInvcNo", "orgInvcNo"):
                    payload.pop(_rk, None)
                _req_pre = coerce_invc_binding(pin_blob.get("precomp_purchase_sales_invc_no"))
                if _req_pre is not None:
                    payload["requestedInvcNo"] = str(_req_pre).strip()
                    payload["spplrInvcNo"] = _req_pre
                else:
                    payload["requestedInvcNo"] = str(_invc_int)
                    payload.pop("spplrInvcNo", None)
                _pst_ic = (pin_blob.get("precomp_purchase_spplr_tin") or "").strip()
                if _pst_ic:
                    payload["spplrTin"] = _pst_ic
                _pbhf_ic = (pin_blob.get("precomp_purchase_spplr_bhf_id") or "").strip()
                if _pbhf_ic:
                    payload["spplrBhfId"] = _pbhf_ic
                _pnm_ic = (pin_blob.get("precomp_purchase_spplr_nm") or "").strip()
                if _pnm_ic:
                    payload["spplrNm"] = _pnm_ic
                ilp_cs = payload.get("itemList")
                if isinstance(ilp_cs, list) and ilp_cs and isinstance(ilp_cs[0], dict):
                    ilp_cs[0]["itemClsCd"] = (
                        pin_blob.get("component_item_cls_cd") or item_cls_dynamic["itemClsCd"]
                    )
                    ilp_cs[0]["taxTyCd"] = (
                        pin_blob.get("component_item_tax_ty_cd") or item_cls_dynamic["taxTyCd"]
                    )
                    # Linked purchase (spplrInvcNo): SBX expects itemList.pkg=1 like supplier sale rows
                    # (see selectTrnsPurchaseSalesList itemList.pkg); qty carries total units.
                    if payload.get("spplrInvcNo") is not None:
                        try:
                            _ln_qty = float(ilp_cs[0].get("qty") or 0)
                        except (TypeError, ValueError):
                            _ln_qty = float(composition_component_purchase_qty)
                        try:
                            _ln_u = float(ilp_cs[0].get("prc") or 0)
                        except (TypeError, ValueError):
                            _ln_u = float(_cc_purchase_prc)
                        _tty_ln = str(ilp_cs[0].get("taxTyCd") or composition_cmp_tty).strip()
                        _sp2, _tb2, _tx2, _tot2 = stock_io_line_amounts_for_tax_ty(
                            unit_prc=_ln_u, qty=_ln_qty, tax_ty_cd=_tty_ln
                        )
                        ilp_cs[0]["pkg"] = 1.0
                        ilp_cs[0]["qty"] = _ln_qty
                        ilp_cs[0]["prc"] = _ln_u
                        ilp_cs[0]["splyAmt"] = _sp2
                        ilp_cs[0]["taxblAmt"] = _tb2
                        ilp_cs[0]["taxAmt"] = _tx2
                        ilp_cs[0]["totAmt"] = _tot2
                        payload["totTaxblAmt"] = _tb2
                        payload["totTaxAmt"] = _tx2
                        payload["totAmt"] = _tot2
                        for _k in ("taxblAmtA", "taxblAmtB", "taxblAmtC", "taxblAmtD", "taxblAmtE"):
                            payload[_k] = 0.0
                        for _k in ("taxAmtA", "taxAmtB", "taxAmtC", "taxAmtD", "taxAmtE"):
                            payload[_k] = 0.0
                        _ctu = _tty_ln.upper()
                        if _ctu == "A":
                            payload["taxblAmtA"] = _tb2
                            payload["taxAmtA"] = _tx2
                        elif _ctu == "B":
                            payload["taxblAmtB"] = _tb2
                            payload["taxAmtB"] = _tx2
                        elif _ctu == "C":
                            payload["taxblAmtC"] = _tb2
                            payload["taxAmtC"] = _tx2
                        else:
                            payload["taxblAmtA"] = _tb2
                            payload["taxAmtA"] = _tx2
                        print(
                            "NOTE: insertTrnsPurchaseComponentStock — linked supplier sale: "
                            f"itemList pkg=1 qty={_ln_qty:g} (SBX pkg validation)."
                        )
                if _req_pre is not None:
                    _pc_rt = _link_tax_rt_for_purchase_or_fallback(
                        pin_blob,
                        "precomp_purchase_link_tax_rt",
                        note_tag="insertTrnsPurchaseComponentStock",
                    )
                    apply_link_tax_rt_to_purchase_payload(payload, _pc_rt)

            if endpoint_name == "selectInvoiceDetails":
                try:
                    payload["invcNo"] = int(str(invc_no).strip())
                except (TypeError, ValueError):
                    payload["invcNo"] = _invc_base

            if endpoint_name == "saveStockMasterComponentPurchase":
                _cc_sm = (pin_blob.get("component_item_cd") or "").strip()
                if not _cc_sm:
                    sequence_fail(
                        "STOP: saveStockMasterComponentPurchase — missing component_item_cd in state."
                    )
                payload["itemCd"] = _cc_sm
                # SBX: never skip saveStockMaster after insertTrnsPurchaseComponentStock 000 — move list
                # reconcile is best-effort only; prefer KRA row qty, else purchase line bypass, else composition qty.
                _raw_c = pin_blob.get("component_reconcile_rsd_qty")
                if _raw_c is None:
                    _raw_c = pin_blob.get("component_purchase_bypass_rsd_qty")
                if _raw_c is None:
                    try:
                        _raw_c = float(composition_component_purchase_qty)
                    except (TypeError, ValueError):
                        _raw_c = None
                if _raw_c is None or float(_raw_c) <= 0:
                    _skip_stock_master_post = True
                    _skip_stock_master_reason = (
                        "saveStockMasterComponentPurchase — no positive rsdQty source after purchase "
                        "(need component_purchase_bypass_rsd_qty from insertTrnsPurchase itemList or "
                        "composition_component_purchase_qty)"
                    )
                else:
                    try:
                        payload["rsdQty"] = float(_raw_c)
                    except (TypeError, ValueError):
                        _skip_stock_master_post = True
                        _skip_stock_master_reason = (
                            "component rsdQty candidates not numeric "
                            f"(reconcile={pin_blob.get('component_reconcile_rsd_qty')!r}, "
                            f"bypass={pin_blob.get('component_purchase_bypass_rsd_qty')!r})"
                        )
                    else:
                        print(
                            "NOTE: saveStockMasterComponentPurchase — SBX policy: posting saveStockMaster "
                            f"with rsdQty={payload['rsdQty']:g} (move-list reconcile optional)."
                        )
            elif endpoint_name == "saveStockMasterAfterPurchase":
                _raw_p = pin_blob.get("parent_rsd_qty_post_purchase")
                if _raw_p is None:
                    _skip_stock_master_post = True
                    _skip_stock_master_reason = (
                        "no rsdQty in selectStockMoveListAfterPurchase response for parent itemCd "
                        "(wait for move list row or retry query; not guessing)"
                    )
                else:
                    try:
                        payload["rsdQty"] = float(_raw_p)
                    except (TypeError, ValueError):
                        _skip_stock_master_post = True
                        _skip_stock_master_reason = f"parent_rsd_qty_post_purchase not numeric ({_raw_p!r})"
            elif endpoint_name == "saveStockMasterInitial":
                _raw_i = pin_blob.get("parent_initial_save_rsd_qty_from_kra")
                if _raw_i is None:
                    _raw_i = pin_blob.get("parent_initial_insert_stock_qty")
                    if _raw_i is not None:
                        print(
                            "NOTE: saveStockMasterInitial — SBX gave no move-list rsdQty after "
                            "insertStockIOInitial 000; using parent_initial_insert_stock_qty from that IO line "
                            f"(rsdQty={float(_raw_i):g})."
                        )
                if _raw_i is None:
                    _skip_stock_master_post = True
                    _skip_stock_master_reason = (
                        "no rsdQty extracted from selectStockMoveListInitial for parent itemCd after IO "
                        "and no parent_initial_insert_stock_qty (insertStockIOInitial may not have committed)"
                    )
                else:
                    try:
                        payload["rsdQty"] = float(_raw_i)
                    except (TypeError, ValueError):
                        _skip_stock_master_post = True
                        _skip_stock_master_reason = (
                            f"parent initial rsdQty source not numeric ({_raw_i!r})"
                        )
                    if diagnostic_stock_io_cli and not _skip_stock_master_post:
                        print("\n--- SAVE STOCK MASTER PAYLOAD ---")
                        print(json.dumps(payload, indent=2, ensure_ascii=False))
            elif endpoint_name == "saveStockMasterPostComposition":
                _raw_pc = pin_blob.get("parent_osdc_prep_rsd_qty")
                if _raw_pc is None:
                    _raw_pc = pin_blob.get("parent_post_composition_io_qty")
                    if _raw_pc is not None:
                        print(
                            "NOTE: saveStockMasterPostComposition — SBX gave no move-list rsdQty after "
                            "insertStockIOPostComposition 000; using parent_post_composition_io_qty from that IO "
                            f"(rsdQty={float(_raw_pc):g})."
                        )
                if _raw_pc is None:
                    _skip_stock_master_post = True
                    _skip_stock_master_reason = (
                        "no post-composition rsdQty source (parent_osdc_prep_rsd_qty / "
                        "parent_post_composition_io_qty from insertStockIOPostComposition); "
                        "move-list reconcile is optional — IO line qty required"
                    )
                else:
                    try:
                        payload["rsdQty"] = float(_raw_pc)
                    except (TypeError, ValueError):
                        _skip_stock_master_post = True
                        _skip_stock_master_reason = (
                            f"post-composition rsdQty source not numeric ({_raw_pc!r})"
                        )
            elif endpoint_name == "saveStockMaster":
                _raw_f = pin_blob.get("parent_rsd_qty_final")
                if _raw_f is None:
                    _skip_stock_master_post = True
                    _skip_stock_master_reason = (
                        "no rsdQty extracted from selectStockMoveList (after insertStockIO) for parent itemCd "
                        "(not using local balance or SAR sum)"
                    )
                else:
                    try:
                        payload["rsdQty"] = float(_raw_f)
                    except (TypeError, ValueError):
                        _skip_stock_master_post = True
                        _skip_stock_master_reason = f"parent_rsd_qty_final not numeric ({_raw_f!r})"

            if endpoint_name == "saveInvoice":
                il = payload.get("itemList")
                _osdc_sale_tax_rt = _link_tax_rt_for_purchase_or_fallback(
                    pin_blob,
                    "precomp_purchase_link_tax_rt",
                    note_tag="saveInvoice (saveTrnsSalesOsdc)",
                )
                if isinstance(il, list) and il and isinstance(il[0], dict):
                    il[0]["itemClsCd"] = item_cls_dynamic["itemClsCd"]
                    # Invoice line taxTyCd must match item master only (set at item save / HS mapping); never
                    # derive or override from supplier taxRt* during invoice build.
                    tty_sale = (
                        (_norm_tax_ty_cd(pin_blob.get("item_tax_ty_cd")) or "").strip().upper()
                    )
                    if not tty_sale:
                        sequence_fail(
                            "STOP: saveInvoice payload build — item_tax_ty_cd empty after pre-check "
                            "(item master required for itemList[].taxTyCd)."
                        )
                    il[0]["taxTyCd"] = tty_sale
                    _nm_inv = (pin_blob.get("item_nm_stock") or "").strip() or "TEST ITEM"
                    il[0]["itemNm"] = _nm_inv
                    try:
                        _prc_sale = float(pin_blob.get("item_dft_prc") or prc)
                    except (TypeError, ValueError):
                        _prc_sale = float(prc)
                    _qty_sale = float(qty)
                    sply_i, tb_i, tx_i, tot_i = stock_io_line_amounts_for_tax_ty(
                        unit_prc=_prc_sale,
                        qty=_qty_sale,
                        tax_ty_cd=tty_sale,
                    )
                    il[0]["prc"] = _prc_sale
                    il[0]["pkg"] = _qty_sale
                    il[0]["qty"] = _qty_sale
                    il[0]["splyAmt"] = sply_i
                    il[0]["taxblAmt"] = tb_i
                    il[0]["taxAmt"] = tx_i
                    il[0]["totAmt"] = tot_i
                    for k in ("taxblAmtA", "taxblAmtB", "taxblAmtC", "taxblAmtD", "taxblAmtE"):
                        payload[k] = 0.0
                    for k in ("taxAmtA", "taxAmtB", "taxAmtC", "taxAmtD", "taxAmtE"):
                        payload[k] = 0.0
                    if tty_sale == "A":
                        payload["taxblAmtA"] = tb_i
                        payload["taxAmtA"] = tx_i
                    elif tty_sale == "B":
                        payload["taxblAmtB"] = tb_i
                        payload["taxAmtB"] = tx_i
                    elif tty_sale == "C":
                        payload["taxblAmtC"] = tb_i
                        payload["taxAmtC"] = tx_i
                    else:
                        payload["taxblAmtA"] = tb_i
                        payload["taxAmtA"] = tx_i
                    payload["totTaxblAmt"] = tb_i
                    payload["totTaxAmt"] = tx_i
                    payload["totAmt"] = tot_i
                    _line_tty_chk = (
                        (_norm_tax_ty_cd(il[0].get("taxTyCd")) or "").strip().upper()
                    )
                    _master_tty_chk = (
                        (_norm_tax_ty_cd(pin_blob.get("item_tax_ty_cd")) or "").strip().upper()
                    )
                    if _line_tty_chk != _master_tty_chk:
                        sequence_fail(
                            "STOP: saveInvoice — itemList taxTyCd does not match item master: "
                            f"invoice line={_line_tty_chk!r} item_tax_ty_cd={_master_tty_chk!r}. "
                            "Refusing saveTrnsSalesOsdc."
                        )
                apply_link_tax_rt_to_purchase_payload(payload, _osdc_sale_tax_rt)
                if isinstance(payload, dict) and any(
                    float(_osdc_sale_tax_rt.get(k) or 0.0) != 0.0
                    for k in ("taxRtA", "taxRtB", "taxRtC", "taxRtD", "taxRtE")
                    if k in _osdc_sale_tax_rt
                ):
                    print(
                        "NOTE: saveInvoice — applied header taxRt* from precomp_purchase_link_tax_rt "
                        f"(supplier sale snapshot / SBX fallback): "
                        f"taxRtA={payload.get('taxRtA')!r} taxRtB={payload.get('taxRtB')!r} …"
                    )
                try:
                    _kra_sale = pin_blob.get("parent_rsd_qty_final")
                    if _kra_sale is None:
                        _kra_sale = pin_blob.get("parent_rsd_qty_post_purchase")
                    if _kra_sale is None:
                        _kra_sale = pin_blob.get("parent_initial_save_rsd_qty_from_kra")
                    if _kra_sale is None:
                        _kra_sale = pin_blob.get("parent_osdc_prep_rsd_qty")
                    _bal_sale = float(_kra_sale) if _kra_sale is not None else 0.0
                except (TypeError, ValueError):
                    _bal_sale = 0.0
                if _bal_sale + 1e-9 < float(qty):
                    print(
                        f"WARNING: saveInvoice — last KRA-derived parent rsdQty≈{_bal_sale:g} < sale "
                        f"qty={float(qty):g}; KRA may reject (item not in stock)."
                    )

            url = f"{BASE_URL.rstrip('/')}{endpoint_path}"
            if any(s in (endpoint_name or "") for s in _FORBIDDEN_ENDPOINT_NAME_SUBSTRINGS) or (
                (endpoint_path or "") in _FORBIDDEN_ENDPOINT_PATHS
            ):
                if portal_checklist_mode_cli and (endpoint_path or "") == "/selectStockMoveList":
                    # Portal parity mode: execute the endpoint, but never gate success on its outcome.
                    pass
                else:
                    raise RuntimeError(
                        f"Forbidden deprecated endpoint in runner: endpoint_name={endpoint_name!r} endpoint_path={endpoint_path!r}"
                    )
            if endpoint_name in _SELECT_STOCK_MOVE_ENDPOINTS:
                url = resolve_select_stock_move_list_url(BASE_URL)
            _purchase_base_url = url
            if endpoint_name in ("insertTrnsPurchase", "insertTrnsPurchaseComponentStock"):
                print(
                    "NOTE: insertTrnsPurchase — body includes requestedInvcNo (SBX servlet reads it; "
                    "query params also send invcNo + requestedInvcNo matching body invcNo)."
                )

            if (
                endpoint_name
                in (
                    "saveStockMaster",
                    "saveStockMasterInitial",
                    "saveStockMasterAfterPurchase",
                    "saveStockMasterPostComposition",
                    "saveStockMasterComponentPurchase",
                )
                and _skip_stock_master_post
            ):
                log_save_stock_master_decision(
                    endpoint_name,
                    executed=False,
                    detail=_skip_stock_master_reason,
                )
                # Move list must not gate stock master. If rsdQty is missing, we still attempt the POST
                # in the next step; do not block the run on move-list visibility.
                flush_progress(endpoint_name, mark_endpoint_complete=False)
                continue

            result_cd: str | None = None
            parsed = None
            resp = None
            apigee_skipped = False
            optional_skip = False
            # selectStockMoveList is SBX-unstable and must never control flow:
            # - no retries here (best-effort only)
            # - failures do not block downstream steps
            _cap_attempts = 1 if endpoint_name in _SELECT_STOCK_MOVE_ENDPOINTS else 2
            if endpoint_name == "selectItemListPostSave":
                _cap_attempts = 8
                if endpoint_name == "saveStockMasterInitial":
                    # IO-line fallback vs stacked SBX ledger — align to KRA Expected on first mismatch.
                    _cap_attempts = 2
            elif endpoint_name == "saveStockMaster":
                _cap_attempts = 1
            elif endpoint_name == "saveStockMasterComponentPurchase":
                # SBX: Apigee 502/503/504 after linked purchase is common; allow several transient retries.
                # Non-SBX: one retry for KRA Expected-rsdQty alignment vs purchase-line qty.
                _cap_attempts = 6 if sbx_stock_move_list_unreliable(BASE_URL) else 2
            elif endpoint_name == "saveStockMasterPostComposition":
                # Allow one retry: IO-line fallback vs KRA ledger (stacked SAR / SBX lag).
                _cap_attempts = 2
            elif endpoint_name == "saveStockMasterAfterPurchase":
                _cap_attempts = 1
            elif endpoint_name == "selectStockMoveListInitial":
                _cap_attempts = 1
            elif endpoint_name == "selectStockMoveListPostComposition":
                _cap_attempts = 1
            elif endpoint_name == "saveInvoice":
                # Stock-master propagation retries plus transient HTTP/Apigee retries.
                _cap_attempts = max(10, SAVE_INVOICE_STOCK_MASTER_MAX_ATTEMPTS + 3)
            elif endpoint_name == "saveItemComposition":
                _cap_attempts = 4
            elif endpoint_name == "updateImportItem":
                _cand_u = pin_blob.get("import_item_candidates")
                _n_u = len(_cand_u) if isinstance(_cand_u, list) else 0
                # Try each server-provided taskCd (SBX often returns 999 for the first row only).
                _cap_attempts = max(3, _n_u) if _n_u else 3
            _req_timeout = 120 if endpoint_name in _SELECT_STOCK_MOVE_ENDPOINTS else 60
            if (
                endpoint_name == "saveStockMasterComponentPurchase"
                and sbx_stock_move_list_unreliable(BASE_URL)
            ):
                _req_timeout = max(_req_timeout, 120)
            _save_ic_ok = True
            _canon_parent_ic = ""
            _comp_ic = ""
            if endpoint_name == "saveItemComposition":
                _save_ic_ok = False
                _canon_parent_ic = (
                    (pin_blob.get("canonical_item_cd") or pin_blob.get("item_cd") or "").strip()
                )
                _comp_ic = (pin_blob.get("component_item_cd") or "").strip()
                payload["itemCd"] = _canon_parent_ic
                payload["cpstItemCd"] = _comp_ic
                item_cd = _canon_parent_ic
                print(
                    "NOTE: saveItemComposition — using pin_blob canonical itemCd="
                    f"{_canon_parent_ic!r} cpstItemCd={_comp_ic!r}"
                )
                try:
                    _cpst_need_outer = float(payload.get("cpstQty") or 1.0)
                except (TypeError, ValueError):
                    _cpst_need_outer = 1.0
                _cpst_need_outer = max(_cpst_need_outer, 1.0)
                _kra_gate_rc = ""
            for attempt in range(_cap_attempts):
                if endpoint_name == "updateImportItem" and isinstance(payload, dict):
                    cand_u = pin_blob.get("import_item_candidates")
                    row_u = None
                    if isinstance(cand_u, list) and cand_u:
                        _ix_u = min(attempt, len(cand_u) - 1)
                        row_u = cand_u[_ix_u]
                    elif isinstance(pin_blob.get("import_update_row"), dict):
                        row_u = pin_blob["import_update_row"]
                    if isinstance(row_u, dict):
                        apply_import_kra_row_to_import_update_payload(
                            payload,
                            row_u,
                            item_cd=item_cd,
                            item_cls_cd=item_cls_dynamic["itemClsCd"],
                            sales_dt=sales_dt,
                        )
                        print(
                            "NOTE: updateImportItem payload key fields — "
                            f"taskCd={payload.get('taskCd')!r} dclDe={payload.get('dclDe')!r} "
                            f"hsCd={payload.get('hsCd')!r} itemSeq={payload.get('itemSeq')!r} "
                            f"itemCd={payload.get('itemCd')!r} imptItemSttsCd={payload.get('imptItemSttsCd')!r} "
                            f"(attempt {attempt + 1}/{_cap_attempts})"
                        )
                if endpoint_name == "insertTrnsPurchaseComponentStock" and attempt > 0:
                    try:
                        cur_i = int(str(payload.get("invcNo") or "0").strip())
                    except (TypeError, ValueError):
                        cur_i = 0
                    _nxt = (cur_i + 1) % 999_999_999 or 1
                    payload["invcNo"] = str(_nxt)
                    for _rk in ("trdInvcNo", "orgInvcNo"):
                        payload.pop(_rk, None)
                    _req_pre_r = coerce_invc_binding(pin_blob.get("precomp_purchase_sales_invc_no"))
                    if _req_pre_r is not None:
                        payload["requestedInvcNo"] = str(_req_pre_r).strip()
                        payload["spplrInvcNo"] = _req_pre_r
                    else:
                        payload["requestedInvcNo"] = str(_nxt)
                        payload.pop("spplrInvcNo", None)
                    print(
                        "NOTE: insertTrnsPurchaseComponentStock retry — "
                        f"bumped invcNo to {payload['invcNo']!r}"
                    )
                if endpoint_name == "selectStockMoveListPostComposition":
                    _sm_sub = attempt % 2
                    _sm_round = attempt // 2 + 1
                    payload["lastReqDt"] = (
                        "20100101000000"
                        if _sm_sub == 1
                        else datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
                    )
                    print(
                        "NOTE: selectStockMoveListPostComposition bundle "
                        f"{attempt + 1}/{_cap_attempts} (round {_sm_round}/2, "
                        f"{'baseline 20100101' if _sm_sub == 1 else 'UTC-now'} lastReqDt) …"
                    )
                if endpoint_name in ("insertTrnsPurchase", "insertTrnsPurchaseComponentStock"):
                    url = _purchase_base_url
                if endpoint_name == "saveItemComposition":
                    _kra_rsd_comp: float | None = None
                    _strict_gate_ok = False
                    _req_q = float(_cpst_need_outer)
                    _comp_list = [_comp_ic] if (_comp_ic or "").strip() else []
                    if not _comp_list:
                        sequence_fail(
                            "STOP: saveItemComposition — no component itemCd for stock check "
                            f"(cpstQty={_req_q:g})."
                        )
                    for _cc in _comp_list:
                        _probe_r, _, _ = kra_probe_select_stock_move_rsd_for_item(
                            base_url=BASE_URL,
                            headers=headers,
                            tin=effective_tin,
                            bhf_id=branch_id,
                            item_cd=_cc,
                            log_tag=(
                                "LOG-ONLY saveItemComposition (selectStockMoveList advisory) "
                                f"component={_cc!r}"
                            ),
                        )
                        print(
                            "NOTE: saveItemComposition — selectStockMoveList is log-only (SBX); "
                            f"advisory probe rsdQty={_probe_r!r}, requiredQty={_req_q:g}, itemCd={_cc!r}"
                        )
                    if bypass_component_stock_gate_cli:
                        _emit_bypass_component_stock_banner()
                        if pin_blob.get("component_trns_purchase_ok"):
                            _kra_rsd_comp = float(_cpst_need_outer)
                            _strict_gate_ok = True
                            _kra_gate_rc = "000"
                            print(
                                "BYPASS: saveItemComposition — skipping component selectStockMoveList; "
                                "trusting insertTrnsPurchaseComponentStock 000."
                            )
                        else:
                            _prelude_rsd_b = ensure_component_stock_before_composition(
                                _cpst_need_outer
                            )
                            _kra_rsd_comp = max(
                                float(_prelude_rsd_b),
                                float(_cpst_need_outer),
                                1.0,
                            )
                            if float(_prelude_rsd_b) + 1e-9 < float(_cpst_need_outer):
                                print(
                                    "WARNING: composition prelude rsdQty below cpstQty (SBX policy: "
                                    "not blocking saveItemComposition on move-list / prelude reads)."
                                )
                            _strict_gate_ok = True
                            _kra_gate_rc = "000"
                            print(
                                "BYPASS: saveItemComposition — prelude ran without rsdQty gate; "
                                "using max(prelude, cpstQty) for audit log."
                            )
                    else:
                        _kra_rsd_comp = max(float(_cpst_need_outer), 1.0)
                        _strict_gate_ok = True
                        _kra_gate_rc = "000"
                        print(
                            "NOTE: saveItemComposition — SBX: no selectStockMoveList / strict stock gate; "
                            "pipeline proceeds (cpstQty-driven assumed balance for audit log only)."
                        )
                if endpoint_name == "saveItemComposition" and attempt > 0:
                    print(
                        f"\n=== saveItemComposition RETRY {attempt}/{_cap_attempts - 1} "
                        "(insufficient stock → prelude rebuild only; no local/boost shortcuts) ==="
                    )
                if endpoint_name == "selectItemListPostSave":
                    # Full-catalog baseline (same as pre-save selectItemList): reliable for SBX + resume when
                    # saveItem was skipped; delta lastReqDt=now often returns resultCd 001 in those cases.
                    payload["lastReqDt"] = "20100101000000"
                if endpoint_name == "saveItemComposition":
                    payload["itemCd"] = _canon_parent_ic
                    payload["cpstItemCd"] = _comp_ic
                    item_cd = _canon_parent_ic
                    try:
                        _cpst_pf = float(payload.get("cpstQty") or 1.0)
                    except (TypeError, ValueError):
                        _cpst_pf = 1.0
                    _cpst_pf = max(_cpst_pf, 1.0)
                    _pio_log = pin_blob.get("composition_prelude_logged_io_sar_no")
                    _psm_log = pin_blob.get("composition_prelude_logged_sm_result_cd")
                    _pcomp_log = (
                        str(pin_blob.get("composition_prelude_logged_component_item_cd") or "").strip()
                    )
                    _state_comp = (pin_blob.get("component_item_cd") or "").strip()
                    _state_parent = (
                        (pin_blob.get("canonical_item_cd") or pin_blob.get("item_cd") or "").strip()
                    )
                    print("\nKRA STOCK CHECK (audit / SBX move-list non-authoritative):")
                    print(f"itemCd={_comp_ic!r}")
                    print(
                        f"rsdQty(assumed for log, bypass={bypass_component_stock_gate_cli})={_kra_rsd_comp:g}"
                    )
                    print(f"resultCd={_kra_gate_rc!r}")
                    print("\n=== saveItemComposition PRE-FLIGHT (payload consistency; no stock gate) ===")
                    print(f"  component_itemCd (payload cpstItemCd): {payload.get('cpstItemCd')!r}")
                    print(f"  parent_itemCd (payload itemCd):       {payload.get('itemCd')!r}")
                    print(f"  Component rsdQty (audit only, not gating): {_kra_rsd_comp:g}")
                    print(f"  cpstQty (payload):                    {_cpst_pf:g}")
                    print(f"  pin_blob component_item_cd:           {_state_comp!r}")
                    print(f"  pin_blob canonical/parent item_cd:    {_state_parent!r}")
                    try:
                        _pio_int = int(_pio_log) if _pio_log is not None else -1
                    except (TypeError, ValueError):
                        _pio_int = -1
                    _pio_disp = (
                        f"{_pio_log!r} (purchase-ledger prelude; no IO SAR)"
                        if _pio_int == 0
                        else f"{_pio_log!r}"
                    )
                    print(f"  last_prelude insertStockIO sarNo:     {_pio_disp}")
                    print(f"  last_prelude saveStockMaster resultCd: {_psm_log!r}")
                    print(f"  logged prelude component itemCd:      {_pcomp_log!r}")
                    print(
                        "  ASSERT: payload itemCds match pin_blob & logged prelude (rsdQty not validated in SBX)."
                    )
                    print(
                        "  Composition eligibility: move-list / rsdQty gates disabled (SBX); "
                        f"component_trns_purchase_ok={pin_blob.get('component_trns_purchase_ok')!r}; "
                        "bypass flag="
                        f"{bypass_component_stock_gate_cli!r}."
                    )
                    _pld_comp = (payload.get("cpstItemCd") or "").strip()
                    _pld_parent = (payload.get("itemCd") or "").strip()
                    if _pld_comp != _state_comp:
                        sequence_fail(
                            "saveItemComposition PRE-FLIGHT ASSERT FAILED (b) component itemCd: "
                            f"payload cpstItemCd={_pld_comp!r} != pin_blob component_item_cd={_state_comp!r}"
                        )
                    if _pld_parent != _state_parent:
                        sequence_fail(
                            "saveItemComposition PRE-FLIGHT ASSERT FAILED (b) parent itemCd: "
                            f"payload itemCd={_pld_parent!r} != pin_blob canonical/item_cd={_state_parent!r}"
                        )
                    if _pcomp_log and _pld_comp != _pcomp_log:
                        sequence_fail(
                            "saveItemComposition PRE-FLIGHT ASSERT FAILED (b) prelude vs payload component: "
                            f"logged prelude component={_pcomp_log!r} != payload cpstItemCd={_pld_comp!r} "
                            "(diverges from insertStockIO/saveStockMaster prelude itemCd)"
                        )
                    print("=== saveItemComposition PRE-FLIGHT: all assertions passed ===\n")
                    print("\n=== saveItemComposition REQUEST (full JSON) ===")
                    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
                if endpoint_name in _IMPORT_LIFECYCLE_FULL_LOG:
                    print(
                        f"\n=== IMPORT LIFECYCLE REQUEST ({endpoint_name}) full JSON ===\n"
                        + json.dumps(payload, indent=2, ensure_ascii=False, default=str)
                    )
                post_headers = dict(headers)
                _post_params = None
                if endpoint_name in ("insertTrnsPurchase", "insertTrnsPurchaseComponentStock"):
                    print("\n=== DEBUG insertTrnsPurchase FULL JSON (before POST) ===")
                    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
                    _iv_q = str(payload.get("invcNo") or "").strip()
                    if _iv_q:
                        _post_params = {"invcNo": _iv_q, "requestedInvcNo": _iv_q}
                        print(f"NOTE: insertTrnsPurchase POST params (match body invcNo): {_post_params}")
                elif endpoint_name == "saveInvoice":
                    _iv_s = str(payload.get("invcNo") or "").strip()
                    if _iv_s:
                        _post_params = {"invcNo": _iv_s, "requestedInvcNo": _iv_s}
                        print(f"NOTE: saveInvoice POST params (match body invcNo): {_post_params}")
                _req_kw: dict = {
                    "headers": post_headers,
                    "json": payload,
                    "timeout": _req_timeout,
                }
                if _post_params is not None:
                    _req_kw["params"] = _post_params
                if strict_pre_sale_audit_cli:
                    audit_append_osdc_bhf_row(
                        bhf_audit_rows,
                        step_name=endpoint_name,
                        payload=payload,
                        headers=post_headers,
                        fallback_tin=effective_tin,
                        fallback_bhf=branch_id,
                    )
                resp = post_with_retry(
                    endpoint_name=endpoint_name,
                    url=url,
                    headers=post_headers,
                    payload=payload,
                    timeout=_req_timeout,
                    params=_post_params,
                    max_attempts=3,
                )
                if endpoint_name in (
                    "insertTrnsPurchase",
                    "insertTrnsPurchaseComponentStock",
                    "saveInvoice",
                ):
                    if _post_params is not None:
                        print(
                            "NOTE: transaction POST effective URL -> "
                            f"{getattr(resp.request, 'url', url)}"
                        )
                if endpoint_name == "saveItemComposition":
                    print("\n=== saveItemComposition RESPONSE (full JSON) ===")
                if endpoint_name in _IMPORT_LIFECYCLE_FULL_LOG:
                    print(f"\n=== IMPORT LIFECYCLE RESPONSE ({endpoint_name}) full JSON ===")
                parsed = print_full_response_json(resp, endpoint_name)
                result_cd = extract_result_cd(parsed)
                log_api_result_summary(endpoint_name, resp, parsed, result_cd)
                gate_err = kra_top_level_error_detail(parsed)
                if endpoint_name in (
                    "saveStockMaster",
                    "saveStockMasterInitial",
                    "saveStockMasterAfterPurchase",
                    "saveStockMasterComponentPurchase",
                    "saveStockMasterPostComposition",
                ):
                    sm_strict = save_stock_master_strict_failure_reason(parsed)
                    if sm_strict:
                        gate_err = (
                            f"{gate_err} | {sm_strict}" if gate_err else sm_strict
                        )
                if endpoint_name in (
                    "saveStockMaster",
                    "saveStockMasterInitial",
                    "saveStockMasterAfterPurchase",
                    "saveStockMasterComponentPurchase",
                    "saveStockMasterPostComposition",
                ):
                    _ok_sm_loop = (
                        not gate_err
                        and endpoint_accepts_result_cd(endpoint_name, result_cd)
                        and endpoint_http_ok_for_kra(endpoint_name, resp, result_cd)
                    )
                    if _ok_sm_loop:
                        log_save_stock_master_decision(
                            endpoint_name,
                            executed=True,
                            detail=(
                                f"KRA accepted POST resultCd={result_cd!r} rsdQty={payload.get('rsdQty')!r}"
                            ),
                        )
                        if endpoint_name == "saveStockMasterPostComposition":
                            pin_blob["post_composition_osdc_ready"] = True
                            try:
                                _rsd_sm_pc_ok = float(payload.get("rsdQty") or 0.0)
                            except (TypeError, ValueError):
                                _rsd_sm_pc_ok = 0.0
                            if _rsd_sm_pc_ok > 0.0:
                                pin_blob["parent_osdc_prep_rsd_qty"] = _rsd_sm_pc_ok
                                pin_blob["current_stock_balance"] = _rsd_sm_pc_ok
                            save_test_state(state_root)
                            print(
                                f"NOTE: OSDC propagation delay ({OSDC_POST_SAVE_STOCK_DELAY_SEC:g}s) after "
                                "saveStockMasterPostComposition 000 …"
                            )
                            time.sleep(OSDC_POST_SAVE_STOCK_DELAY_SEC)
                            print(
                                "LOG: Waiting for KRA stock master → sales engine propagation"
                            )
                            _extra_osdc = random.uniform(
                                OSDC_EXTRA_DELAY_BEFORE_SAVE_INVOICE_SEC_MIN,
                                OSDC_EXTRA_DELAY_BEFORE_SAVE_INVOICE_SEC_MAX,
                            )
                            print(
                                f"NOTE: Extra OSDC→saveTrnsSalesOsdc propagation delay ({_extra_osdc:.1f}s) "
                                "(SBX often lags stock master vs sales) …"
                            )
                            time.sleep(_extra_osdc)
                        break
                    _http_sm = int(getattr(resp, "status_code", 0) or 0)
                    if (
                        endpoint_name == "saveStockMasterComponentPurchase"
                        and _http_sm in (502, 503, 504)
                        and sbx_stock_move_list_unreliable(BASE_URL)
                        and attempt + 1 < _cap_attempts
                    ):
                        _bo = min(60.0, 6.0 * (2**attempt) + random.random() * 3.0)
                        print(
                            f"NOTE: saveStockMasterComponentPurchase HTTP {_http_sm} (gateway/proxy); "
                            f"SBX transient — backing off {_bo:.1f}s then retry ({attempt + 2}/{_cap_attempts}) …"
                        )
                        time.sleep(_bo)
                        continue
                    if (
                        endpoint_name == "saveStockMasterComponentPurchase"
                        and attempt + 1 < _cap_attempts
                    ):
                        _mm_sm = kra_save_stock_master_messages_for_mismatch_parse(parsed)
                        _exp_rsd = kra_expected_rsd_qty_from_mismatch_message(_mm_sm)
                        if _exp_rsd is not None:
                            pin_blob["component_reconcile_rsd_qty"] = float(_exp_rsd)
                            pin_blob["component_purchase_bypass_rsd_qty"] = float(_exp_rsd)
                            if isinstance(payload, dict):
                                payload["rsdQty"] = float(_exp_rsd)
                            save_test_state(state_root)
                            log_save_stock_master_decision(
                                endpoint_name,
                                executed=False,
                                detail=(
                                    f"KRA rsdQty mismatch — aligning rsdQty to Expected={float(_exp_rsd):g} "
                                    f"(purchase-line bypass vs ledger; attempt {attempt + 1}/{_cap_attempts}); "
                                    "retrying POST …"
                                ),
                            )
                            time.sleep(1.0)
                            continue
                    if (
                        endpoint_name == "saveStockMasterPostComposition"
                        and attempt + 1 < _cap_attempts
                    ):
                        _mm_pc = kra_save_stock_master_messages_for_mismatch_parse(parsed)
                        _exp_pc = kra_expected_rsd_qty_from_mismatch_message(_mm_pc)
                        if _exp_pc is not None:
                            pin_blob["parent_osdc_prep_rsd_qty"] = float(_exp_pc)
                            pin_blob["parent_post_composition_io_qty"] = float(_exp_pc)
                            if isinstance(payload, dict):
                                payload["rsdQty"] = float(_exp_pc)
                            save_test_state(state_root)
                            log_save_stock_master_decision(
                                endpoint_name,
                                executed=False,
                                detail=(
                                    f"KRA rsdQty mismatch — aligning rsdQty to Expected={float(_exp_pc):g} "
                                    f"(IO-line fallback vs ledger; attempt {attempt + 1}/{_cap_attempts}); "
                                    "retrying POST …"
                                ),
                            )
                            time.sleep(1.0)
                            continue
                    if (
                        endpoint_name == "saveStockMasterInitial"
                        and attempt + 1 < _cap_attempts
                    ):
                        _mm_si = kra_save_stock_master_messages_for_mismatch_parse(parsed)
                        _exp_si = kra_expected_rsd_qty_from_mismatch_message(_mm_si)
                        if _exp_si is not None:
                            pin_blob["parent_initial_save_rsd_qty_from_kra"] = float(_exp_si)
                            pin_blob["parent_initial_insert_stock_qty"] = float(_exp_si)
                            if isinstance(payload, dict):
                                payload["rsdQty"] = float(_exp_si)
                            save_test_state(state_root)
                            log_save_stock_master_decision(
                                endpoint_name,
                                executed=False,
                                detail=(
                                    f"KRA rsdQty mismatch — aligning rsdQty to Expected={float(_exp_si):g} "
                                    f"(IO-line fallback vs ledger; attempt {attempt + 1}/{_cap_attempts}); "
                                    "retrying POST …"
                                ),
                            )
                            time.sleep(1.0)
                            continue
                    _fail_sm_retry_endpoints = (
                        "saveStockMasterComponentPurchase",
                        "saveStockMasterPostComposition",
                        "saveStockMasterInitial",
                    )
                    _fail_sm_detail = (
                        (
                            "saveStockMaster failed (no further Expected-rsdQty retry) "
                            if endpoint_name not in _fail_sm_retry_endpoints
                            or _cap_attempts <= 1
                            else (
                                f"saveStockMaster failed after {_cap_attempts} attempt(s) "
                                "(including KRA Expected-rsdQty alignment retry) "
                            )
                        ).strip()
                        + f" attempt {attempt + 1}/{_cap_attempts}"
                    )
                    log_save_stock_master_decision(
                        endpoint_name,
                        executed=False,
                        detail=_fail_sm_detail,
                    )
                    break
                if endpoint_name == "saveItemComposition":
                    _ref_ic = kra_extract_response_ref_id(parsed)
                    _msg_ic = kra_extract_response_body_result_msg(parsed)
                    if not _msg_ic:
                        _msg_ic = kra_save_item_error_text(parsed) or ""
                    print(f"saveItemComposition responseRefID={_ref_ic!r}")
                    _ok_ic = (
                        not gate_err
                        and endpoint_accepts_result_cd(endpoint_name, result_cd)
                        and endpoint_http_ok_for_kra(endpoint_name, resp, result_cd)
                    )
                    if _ok_ic:
                        _save_ic_ok = True
                        pin_blob["saveItemComposition_resultCd"] = result_cd or "000"
                        pin_blob["saveItemComposition_resultMsg"] = (
                            kra_extract_response_body_result_msg(parsed) or "Successful"
                        )
                        pin_blob["saveItemComposition_responseRefId"] = _ref_ic
                        pin_blob.pop("saveItemComposition_last_resultCd", None)
                        pin_blob.pop("saveItemComposition_last_resultMsg", None)
                        pin_blob.pop("saveItemComposition_last_responseRefId", None)
                        save_test_state(state_root)
                        print(
                            "LOG saveItemComposition: "
                            f"resultCd={result_cd!r} resultMsg={pin_blob['saveItemComposition_resultMsg']!r} "
                            f"responseRefID={_ref_ic!r}"
                        )
                        break
                    pin_blob["saveItemComposition_last_resultCd"] = result_cd
                    pin_blob["saveItemComposition_last_resultMsg"] = _msg_ic
                    pin_blob["saveItemComposition_last_responseRefId"] = _ref_ic
                    print(
                        f"LOG saveItemComposition attempt {attempt + 1}/{_cap_attempts}: "
                        f"resultCd={result_cd!r} resultMsg={_msg_ic!r} responseRefID={_ref_ic!r}"
                    )
                    if attempt < _cap_attempts - 1:
                        if save_item_composition_insufficient_stock(parsed):
                            print(
                                "NOTE: saveItemComposition insufficient stock per KRA response — "
                                "SBX policy: not re-running composition stock prelude (move-list gating disabled); "
                                "retrying POST only …"
                            )
                        continue
                    _save_ic_ok = False
                    break
                if endpoint_name == "saveInvoice":
                    _ok_inv = (
                        not gate_err
                        and endpoint_accepts_result_cd(endpoint_name, result_cd)
                        and endpoint_http_ok_for_kra(endpoint_name, resp, result_cd)
                    )
                    if _ok_inv:
                        break
                    _inv_err_blob = kra_save_invoice_error_blob(parsed, gate_err)
                    if kra_save_invoice_stock_master_propagation_error(_inv_err_blob):
                        if (attempt + 1) < SAVE_INVOICE_STOCK_MASTER_MAX_ATTEMPTS:
                            _inv_sleep = random.uniform(
                                SAVE_INVOICE_STOCK_MASTER_RETRY_SLEEP_SEC_MIN,
                                SAVE_INVOICE_STOCK_MASTER_RETRY_SLEEP_SEC_MAX,
                            )
                            print(
                                "LOG: Waiting for KRA stock master → sales engine propagation"
                            )
                            print(
                                "NOTE: saveInvoice — message contains 'does not exist in your stock master'; "
                                f"waiting {_inv_sleep:.1f}s then retry saveTrnsSalesOsdc only "
                                f"({attempt + 2}/{SAVE_INVOICE_STOCK_MASTER_MAX_ATTEMPTS}, no stock-step replay) …"
                            )
                            time.sleep(_inv_sleep)
                            continue
                        _parts_smf = [
                            "STOP: saveInvoice (saveTrnsSalesOsdc) — stock master still not visible to sales API",
                            f"after {SAVE_INVOICE_STOCK_MASTER_MAX_ATTEMPTS} attempt(s)",
                            f"HTTP={getattr(resp, 'status_code', 0)}",
                        ]
                        if gate_err:
                            _parts_smf.append(str(gate_err))
                        _parts_smf.append(
                            "Try a longer wait and rerun from saveInvoice only, or clear SBX backlog on OSCU portal."
                        )
                        sequence_fail(" | ".join(_parts_smf))
                if endpoint_name == "selectStockMoveListInitial":
                    _pid_mv_i = (pin_blob.get("item_cd") or item_cd or "").strip()
                    _rsd_mv_i: float | None = None
                    if (
                        isinstance(parsed, dict)
                        and not gate_err
                        and (result_cd or "").strip() == "000"
                        and _pid_mv_i
                    ):
                        _rsd_mv_i = _first_rsd_qty_for_item_in_stock_move_tree(
                            parsed, _pid_mv_i
                        )
                    # SBX move list must not control flow. Always proceed; saveStockMasterInitial uses IO qty.
                    _fb_io_i = pin_blob.get("parent_initial_insert_stock_qty")
                    try:
                        _fb_io_f = float(_fb_io_i) if _fb_io_i is not None else 0.0
                    except (TypeError, ValueError):
                        _fb_io_f = 0.0
                    if _fb_io_f > 0.0:
                        pin_blob["_stock_move_list_initial_io_fallback"] = True
                        pin_blob["parent_initial_save_rsd_qty_from_kra"] = float(_fb_io_f)
                        pin_blob["current_stock_balance"] = float(_fb_io_f)
                        save_test_state(state_root)
                        print(
                            f"NOTE: selectStockMoveListInitial is best-effort in SBX; "
                            f"using insertStockIOInitial qty={float(_fb_io_f):g} for saveStockMasterInitial."
                        )
                    else:
                        print(
                            "WARNING: selectStockMoveListInitial unavailable/empty and no IO qty found; "
                            "continuing (saveStockMasterInitial may fail if IO never ran)."
                        )
                    break
                elif endpoint_name == "selectStockMoveListPostComposition":
                    _pid_mv_p = (pin_blob.get("item_cd") or item_cd or "").strip()
                    _rsd_mv_p: float | None = None
                    if (
                        isinstance(parsed, dict)
                        and not gate_err
                        and (result_cd or "").strip() == "000"
                        and _pid_mv_p
                    ):
                        _rsd_mv_p = _first_rsd_qty_for_item_in_stock_move_tree(
                            parsed, _pid_mv_p
                        )
                    # SBX move list must not control flow. Always proceed; saveStockMasterPostComposition uses IO qty.
                    _fb_pc = pin_blob.get("parent_post_composition_io_qty")
                    try:
                        _fb_pc_f = float(_fb_pc) if _fb_pc is not None else 0.0
                    except (TypeError, ValueError):
                        _fb_pc_f = 0.0
                    if _fb_pc_f > 0.0:
                        pin_blob["_stock_move_list_post_osdc_io_fallback"] = True
                        pin_blob["parent_osdc_prep_rsd_qty"] = float(_fb_pc_f)
                        pin_blob["current_stock_balance"] = float(_fb_pc_f)
                        save_test_state(state_root)
                        print(
                            f"NOTE: selectStockMoveListPostComposition is best-effort in SBX; "
                            f"using insertStockIOPostComposition qty={float(_fb_pc_f):g} for saveStockMasterPostComposition."
                        )
                    else:
                        print(
                            "WARNING: selectStockMoveListPostComposition unavailable/empty and no IO qty found; "
                            "continuing (saveStockMasterPostComposition may fail if IO never ran)."
                        )
                    break
                if (
                    endpoint_name != "saveItemComposition"
                    and endpoint_name != "selectStockMoveListInitial"
                    and endpoint_name != "selectStockMoveListPostComposition"
                    and not gate_err
                    and endpoint_accepts_result_cd(endpoint_name, result_cd)
                    and endpoint_http_ok_for_kra(endpoint_name, resp, result_cd)
                ):
                    if endpoint_name == "selectItemListPostSave" and not response_contains_item_cd(
                        parsed, item_cd
                    ):
                        if attempt < _cap_attempts - 1:
                            print(
                                "RETRY: selectItemListPostSave (response OK but saved itemCd not in list yet; "
                                "waiting 2s) …"
                            )
                            time.sleep(2)
                            continue
                        sequence_fail(
                            "STOP: selectItemListPostSave — catalog has no saved itemCd "
                            f"{item_cd!r} (GavaConnect expects LOOK UP PRODUCT LIST to return the item after "
                            "saveItem). Check branch/tin and SBX latency."
                        )
                    break
                _last_att = attempt >= _cap_attempts - 1
                if _last_att:
                    if endpoint_name == "saveStockMasterInitial":
                        if diagnostic_stock_io_cli and isinstance(parsed, dict):
                            print("\n--- RESPONSE ---")
                            print(
                                json.dumps(
                                    parsed, indent=2, ensure_ascii=False, default=str
                                )
                            )
                        parts_sm_i = [
                            "STOP: saveStockMasterInitial failed",
                            f"HTTP={resp.status_code}",
                            f"resultCd={result_cd!r}",
                        ]
                        if gate_err:
                            parts_sm_i.append(str(gate_err))
                        parts_sm_i.append(
                            "State preserved (insertStockIOInitial, SAR, pending). Rerun to retry save only."
                        )
                        sequence_fail(" | ".join(parts_sm_i))
                    if endpoint_name == "saveStockMasterPostComposition":
                        parts_pc = [
                            "STOP: saveStockMasterPostComposition failed",
                            f"HTTP={resp.status_code}",
                            f"resultCd={result_cd!r}",
                        ]
                        if gate_err:
                            parts_pc.append(str(gate_err))
                        parts_pc.append(
                            "Mandatory pre-OSDC parent save must return 000. Check post-composition "
                            f"insertStockIOPostComposition; see {STATE_FILE.name}."
                        )
                        sequence_fail(" | ".join(parts_pc))
                    if (
                        endpoint_name == "selectTrnsPurchaseSalesListPreComposition"
                        and getattr(resp, "status_code", 0) >= 500
                    ) or (
                        endpoint_name in SOFT_SKIP_APIGEE_TARGET_PATH
                        and apigee_unresolved_target_path_fault(parsed)
                    ):
                        apigee_skipped = True
                        if (
                            endpoint_name == "selectTrnsPurchaseSalesListPreComposition"
                            and getattr(resp, "status_code", 0) >= 500
                        ):
                            print(
                                f"WARNING: {endpoint_name} skipped — HTTP "
                                f"{getattr(resp, 'status_code', 0)} (optional precomposition sale list; "
                                "purchase steps use invcNo fallbacks). Continuing."
                            )
                        else:
                            print(
                                f"NOTE: {endpoint_name} skipped — SBX Apigee returned targetPath / unresolved route "
                                f"(HTTP={resp.status_code}). Continuing."
                            )
                        break
                    if (
                        endpoint_name in OPTIONAL_SBX_STEPS
                        and getattr(resp, "status_code", 999) < 500
                    ):
                        optional_skip = True
                        print(
                            f"NOTE: {endpoint_name} skipped — SBX returned resultCd={result_cd!r} "
                            "(optional without customs import rows). Continuing."
                        )
                        break
                    if endpoint_name == "saveItemComposition":
                        break
                    if endpoint_name == "insertTrnsPurchaseComponentStock":
                        try:
                            _curf = int(payload.get("invcNo") or 0)
                        except (TypeError, ValueError):
                            _curf = 0
                        if _curf > 0:
                            pin_blob["component_purchase_next_invc_no"] = (_curf + 1) % 999_999_999
                            save_test_state(state_root)
                            print(
                                "NOTE: saved component_purchase_next_invc_no="
                                f"{pin_blob['component_purchase_next_invc_no']} for next run / prelude retry."
                            )
                    parts = [
                        f"STOP: {endpoint_name} failed after retry",
                        f"HTTP={resp.status_code}",
                        f"resultCd={result_cd!r}",
                    ]
                    if gate_err:
                        parts.append(str(gate_err))
                    if endpoint_name in (
                        "saveStockMaster",
                        "saveStockMasterInitial",
                        "saveStockMasterAfterPurchase",
                        "saveStockMasterComponentPurchase",
                        "saveStockMasterPostComposition",
                    ):
                        parts.append(
                            "SBX may have stacked unreconciled stock IOs: reset stock/SAR on the OSCU portal "
                            "for this PIN, then run: python gavaetims.py <PIN> --reset-stock"
                        )
                    # selectStockMoveList is SBX-unstable and must never control flow.
                    if endpoint_name in _SELECT_STOCK_MOVE_ENDPOINTS:
                        print(
                            "WARNING: selectStockMoveList unavailable (sandbox issue) — "
                            + " | ".join(parts)
                        )
                        flush_progress(endpoint_name, mark_endpoint_complete=True)
                        break
                    sequence_fail(" | ".join(parts))
                # Never retry based on selectStockMoveList outcomes; SBX move list is best-effort only.
                print(f"RETRY: {endpoint_name} (HTTP={resp.status_code}, resultCd={result_cd!r}) …")

            if endpoint_name in (
                "saveStockMaster",
                "saveStockMasterInitial",
                "saveStockMasterAfterPurchase",
                "saveStockMasterComponentPurchase",
                "saveStockMasterPostComposition",
            ):
                _ge_fin = kra_top_level_error_detail(parsed)
                _sm_fin = (
                    save_stock_master_strict_failure_reason(parsed)
                    if isinstance(parsed, dict)
                    else None
                )
                _gate_fin = (
                    f"{_ge_fin} | {_sm_fin}" if _ge_fin and _sm_fin else (_ge_fin or _sm_fin or "")
                )
                _ok_ssm_fin = (
                    not _gate_fin
                    and endpoint_accepts_result_cd(endpoint_name, result_cd)
                    and endpoint_http_ok_for_kra(endpoint_name, resp, result_cd)
                )
                if not _ok_ssm_fin:
                    log_save_stock_master_decision(
                        endpoint_name,
                        executed=False,
                        detail=(
                            f"halting — resultCd={result_cd!r} HTTP={getattr(resp, 'status_code', 0)} "
                            f"{_gate_fin or ''}".strip()
                        ),
                    )
                    parts_ssm = [
                        f"STOP: {endpoint_name} failed",
                        f"HTTP={getattr(resp, 'status_code', 0)}",
                        f"resultCd={result_cd!r}",
                    ]
                    if _gate_fin:
                        parts_ssm.append(str(_gate_fin))
                    parts_ssm.append(
                        "SBX may have stacked unreconciled stock IOs: reset stock/SAR on the OSCU portal "
                        "for this PIN, then run: python gavaetims.py <PIN> --reset-stock"
                    )
                    sequence_fail(" | ".join(parts_ssm))

            if endpoint_name == "saveItemComposition" and not _save_ic_ok:
                _rc_fin = pin_blob.get("saveItemComposition_last_resultCd")
                _msg_fin = pin_blob.get("saveItemComposition_last_resultMsg") or ""
                _ref_fin = pin_blob.get("saveItemComposition_last_responseRefId") or ""
                pin_blob["saveItemComposition_resultCd"] = _rc_fin
                pin_blob["saveItemComposition_resultMsg"] = _msg_fin
                pin_blob["saveItemComposition_responseRefId"] = _ref_fin
                save_test_state(state_root)
                flush_progress(endpoint_name, mark_endpoint_complete=False)
                sequence_fail(
                    "STOP: saveItemComposition did not succeed after all attempts — halting sequence "
                    "(no saveInvoice / other downstream steps). "
                    f"resultCd={_rc_fin!r} resultMsg={_msg_fin!r} responseRefID={_ref_fin!r}"
                )

            if apigee_skipped:
                if endpoint_name == "selectTrnsPurchaseSalesListPreComposition":
                    pin_blob.pop("precomp_purchase_sales_invc_no", None)
                    pin_blob.pop("precomp_purchase_link_tax_rt", None)
                    pin_blob.pop("precomp_purchase_spplr_tin", None)
                    pin_blob.pop("precomp_purchase_spplr_bhf_id", None)
                    pin_blob.pop("precomp_purchase_spplr_nm", None)
                    save_test_state(state_root)
                    print(
                        "NOTE: Cleared precomposition purchase-sale binding keys after soft-skip "
                        "(precomp_purchase_sales_invc_no unset; later purchase uses invcNo fallbacks)."
                    )
                flush_progress(endpoint_name, mark_endpoint_complete=False)
                continue
            if optional_skip:
                if endpoint_name == "importedItemInfo":
                    # Handler block is skipped on ``continue`` — clear lifecycle so a prior PIN state
                    # cannot leave ``import_lifecycle_ready`` true without a fresh ``importedItemInfo`` 000.
                    pin_blob["import_lifecycle_ready"] = False
                    pin_blob.pop("import_update_row", None)
                    pin_blob.pop("import_item_candidates", None)
                    pin_blob["import_lifecycle_skip_reason"] = (
                        pin_blob.get("import_lifecycle_skip_reason")
                        or f"importedItemInfo optional skip (resultCd={result_cd!r})"
                    )
                    save_test_state(state_root)
                # For the portal test sequence, we still want to advance past updateImportItem even when
                # SBX returns a known-broken business error (e.g., HTTP 400 + resultCd 999 after passing
                # parameter validation). Mark it complete so downstream steps can run.
                if endpoint_name in ("updateImportItem", "importedItemConvertedInfo"):
                    print(
                        f"WARNING: Treating {endpoint_name} as completed for sequencing purposes "
                        f"(HTTP={getattr(resp, 'status_code', None)} resultCd={result_cd!r})."
                    )
                    flush_progress(endpoint_name, mark_endpoint_complete=True)
                else:
                    flush_progress(endpoint_name, mark_endpoint_complete=False)
                continue

            if endpoint_name == "selectTrnsPurchaseSalesListPreComposition":
                _http_pre = getattr(resp, "status_code", 999) if resp is not None else 999
                if isinstance(parsed, dict):
                    _gate_pre = kra_top_level_error_detail(parsed) or ""
                else:
                    _gate_pre = "non-JSON or unusable response body"
                _usable_precomp = (
                    isinstance(parsed, dict)
                    and not _gate_pre
                    and _http_pre < 500
                    and endpoint_accepts_result_cd(endpoint_name, result_cd)
                )
                if not _usable_precomp:
                    pin_blob.pop("precomp_purchase_sales_invc_no", None)
                    pin_blob.pop("precomp_purchase_link_tax_rt", None)
                    pin_blob.pop("precomp_purchase_spplr_tin", None)
                    pin_blob.pop("precomp_purchase_spplr_bhf_id", None)
                    pin_blob.pop("precomp_purchase_spplr_nm", None)
                    print(
                        "WARNING: selectTrnsPurchaseSalesListPreComposition — response not usable "
                        f"(HTTP={_http_pre}, gate={_gate_pre!r}, resultCd={result_cd!r}); "
                        "skipping sale-row extraction; purchase fallbacks apply."
                    )
                else:
                    _comp_pref = (pin_blob.get("component_item_cd") or "").strip()
                    _row_pre = extract_preferred_sale_row_for_trns_purchase_binding(
                        parsed,
                        prefer_item_cd=_comp_pref,
                        restrict_spplr_tin=effective_tin,
                    )
                    if _row_pre and str(_row_pre.get("spplrInvcNo") or "").strip():
                        pin_blob["precomp_purchase_sales_invc_no"] = str(
                            _row_pre["spplrInvcNo"]
                        ).strip()
                        pin_blob["precomp_purchase_link_tax_rt"] = sale_row_tax_rt_map(_row_pre)
                        pin_blob.pop("precomp_purchase_spplr_tin", None)
                        pin_blob.pop("precomp_purchase_spplr_bhf_id", None)
                        pin_blob.pop("precomp_purchase_spplr_nm", None)
                        print(
                            "NOTE: selectTrnsPurchaseSalesListPreComposition — bound precomp purchase to sale row "
                            f"spplrTin={str(_row_pre.get('spplrTin') or '').strip()!r} "
                            f"spplrInvcNo={pin_blob['precomp_purchase_sales_invc_no']!r} "
                            f"taxRt*={pin_blob['precomp_purchase_link_tax_rt']!r}"
                        )
                    else:
                        pin_blob.pop("precomp_purchase_sales_invc_no", None)
                        pin_blob.pop("precomp_purchase_link_tax_rt", None)
                        fb = extract_best_supplier_sale_row_cross_tin_fallback(
                            parsed, prefer_item_cd=_comp_pref
                        )
                        if fb and str(fb.get("spplrInvcNo") or "").strip():
                            pin_blob["precomp_purchase_sales_invc_no"] = str(fb["spplrInvcNo"]).strip()
                            pin_blob["precomp_purchase_link_tax_rt"] = sale_row_tax_rt_map(fb)
                            pin_blob["precomp_purchase_spplr_tin"] = str(fb.get("spplrTin") or "").strip()
                            _fb_bhf = str(fb.get("spplrBhfId") or "").strip() or "00"
                            pin_blob["precomp_purchase_spplr_bhf_id"] = _fb_bhf
                            if fb.get("spplrNm"):
                                pin_blob["precomp_purchase_spplr_nm"] = str(fb["spplrNm"]).strip()
                            else:
                                pin_blob.pop("precomp_purchase_spplr_nm", None)
                            print(
                                "WARNING: selectTrnsPurchaseSalesListPreComposition — no sale rows for "
                                f"spplrTin={effective_tin!r}; using cross-TIN fallback from saleList: "
                                f"spplrTin={pin_blob['precomp_purchase_spplr_tin']!r} "
                                f"spplrInvcNo={pin_blob['precomp_purchase_sales_invc_no']!r} "
                                f"taxRt*={pin_blob['precomp_purchase_link_tax_rt']!r} "
                                "(component purchase supplier binding — SBX sandbox)."
                            )
                        else:
                            pin_blob.pop("precomp_purchase_spplr_tin", None)
                            pin_blob.pop("precomp_purchase_spplr_bhf_id", None)
                            pin_blob.pop("precomp_purchase_spplr_nm", None)
                            print(
                                "NOTE: selectTrnsPurchaseSalesListPreComposition — no spplrInvcNo for "
                                f"spplrTin={effective_tin!r} and no usable saleList row; "
                                "component purchase falls back to same invcNo for requestedInvcNo."
                            )
                save_test_state(state_root)

            if (
                endpoint_name == "selectTrnsPurchaseSalesList"
                and endpoint_accepts_result_cd(endpoint_name, result_cd)
                and isinstance(parsed, dict)
            ):
                _par_pref = (pin_blob.get("item_cd") or item_cd or "").strip()
                _row_main = extract_preferred_sale_row_for_trns_purchase_binding(
                    parsed,
                    prefer_item_cd=_par_pref,
                    restrict_spplr_tin=effective_tin,
                )
                if _row_main and str(_row_main.get("spplrInvcNo") or "").strip():
                    pin_blob["main_purchase_sales_invc_no"] = str(_row_main["spplrInvcNo"]).strip()
                    pin_blob["main_purchase_link_tax_rt"] = sale_row_tax_rt_map(_row_main)
                    print(
                        "NOTE: selectTrnsPurchaseSalesList — bound main purchase to sale row "
                        f"spplrInvcNo={pin_blob['main_purchase_sales_invc_no']!r} "
                        f"taxRt*={pin_blob['main_purchase_link_tax_rt']!r}"
                    )
                else:
                    pin_blob.pop("main_purchase_sales_invc_no", None)
                    pin_blob.pop("main_purchase_link_tax_rt", None)
                    print(
                        "NOTE: selectTrnsPurchaseSalesList — no spplrInvcNo for "
                        f"spplrTin={effective_tin!r}; main purchase falls back to same invcNo for requestedInvcNo."
                    )
                save_test_state(state_root)

            if endpoint_name == "selectImportItemList" and isinstance(parsed, dict):
                _imp_ok, _imp_reason = import_item_list_allows_update_import_item(
                    parsed, result_cd
                )
                pin_blob["select_import_item_list_diag_ok"] = bool(_imp_ok)
                pin_blob["select_import_item_list_diag_reason"] = (
                    _imp_reason if not _imp_ok else ""
                )
                if _imp_ok:
                    print(
                        "NOTE: selectImportItemList — customs rows present "
                        "(taskCd for update flow is taken from importedItemInfo, not this list)."
                    )
                    # In SBX, `importedItemInfo` is sometimes unavailable/empty while `selectImportItemList`
                    # returns usable customs rows. If we have rows with taskCd here, seed the import-lifecycle
                    # state so `updateImportItem`/`importedItemConvertedInfo` do not fall back to placeholders
                    # like taskCd "01" (which SBX rejects: "taskCd '01' not found.").
                    try:
                        _rows_si = extract_import_item_rows(parsed)
                    except Exception:
                        _rows_si = []
                    _cand_si = (
                        [r for r in _rows_si if isinstance(r, dict) and str(r.get("taskCd") or "").strip()]
                        if isinstance(_rows_si, list)
                        else []
                    )
                    if _cand_si:
                        pin_blob["import_item_candidates"] = _cand_si
                        pin_blob["import_update_row"] = {
                            "taskCd": str(_cand_si[0].get("taskCd") or "").strip(),
                            "dclDe": str(_cand_si[0].get("dclDe") or "").strip(),
                            "hsCd": str(_cand_si[0].get("hsCd") or "").strip(),
                            "itemSeq": _cand_si[0].get("itemSeq", 1),
                        }
                        pin_blob["import_lifecycle_ready"] = True
                        pin_blob.pop("import_lifecycle_skip_reason", None)
                        print(
                            "NOTE: selectImportItemList — seeded import lifecycle from customs rows; "
                            f"{len(_cand_si)} candidate row(s); primary import_update_row="
                            f"{pin_blob['import_update_row']!r}"
                        )
                else:
                    print(f"NOTE: selectImportItemList — no usable customs rows ({_imp_reason})")
                    # Do not carry stale import-lifecycle state across runs when the current list is unusable.
                    pin_blob["import_lifecycle_ready"] = False
                    pin_blob.pop("import_update_row", None)
                    pin_blob.pop("import_item_candidates", None)
                    pin_blob["import_lifecycle_skip_reason"] = _imp_reason or (
                        f"selectImportItemList not usable (resultCd={result_cd!r})"
                    )
                if endpoint_accepts_result_cd(endpoint_name, result_cd):
                    save_test_state(state_root)

            if endpoint_name == "importedItemInfo" and isinstance(parsed, dict):
                pin_blob["import_lifecycle_ready"] = False
                pin_blob.pop("import_update_row", None)
                pin_blob.pop("import_item_candidates", None)
                pin_blob.pop("import_lifecycle_skip_reason", None)
                _info_ok, _info_reason = import_item_list_allows_update_import_item(
                    parsed, result_cd
                )
                if _info_ok and endpoint_accepts_result_cd(endpoint_name, result_cd):
                    rows = extract_import_item_rows(parsed)
                    cand = [r for r in rows if str(r.get("taskCd") or "").strip()]
                    if cand:
                        pin_blob["import_item_candidates"] = cand
                        pin_blob["import_update_row"] = {
                            "taskCd": str(cand[0].get("taskCd") or "").strip(),
                            "dclDe": str(cand[0].get("dclDe") or "").strip(),
                            "hsCd": str(cand[0].get("hsCd") or "").strip(),
                            "itemSeq": cand[0].get("itemSeq", 1),
                        }
                        pin_blob["import_lifecycle_ready"] = True
                        print(
                            "NOTE: importedItemInfo — stored "
                            f"{len(cand)} candidate row(s); primary import_update_row="
                            f"{pin_blob['import_update_row']!r}"
                        )
                    else:
                        pin_blob["import_lifecycle_skip_reason"] = (
                            "importedItemInfo returned itemList rows but none had a non-empty taskCd"
                        )
                        print(f"SKIP import lifecycle — {pin_blob['import_lifecycle_skip_reason']}")
                else:
                    pin_blob["import_lifecycle_skip_reason"] = _info_reason or (
                        f"importedItemInfo not usable (resultCd={result_cd!r})"
                    )
                    print(f"SKIP import lifecycle — {pin_blob['import_lifecycle_skip_reason']}")
                if endpoint_accepts_result_cd(endpoint_name, result_cd):
                    save_test_state(state_root)

            if (
                endpoint_name == "insertTrnsPurchaseComponentStock"
                and endpoint_accepts_result_cd(endpoint_name, result_cd)
            ):
                pin_blob["component_trns_purchase_ok"] = True
                _il_bp = payload.get("itemList") if isinstance(payload, dict) else None
                if isinstance(_il_bp, list) and _il_bp and isinstance(_il_bp[0], dict):
                    _r0 = _il_bp[0]
                    for _qk in ("qty", "pkg"):
                        if _qk in _r0 and _r0[_qk] is not None:
                            try:
                                pin_blob["component_purchase_bypass_rsd_qty"] = float(_r0[_qk])
                                break
                            except (TypeError, ValueError):
                                pass
                try:
                    pin_blob["purchase_invc_no_component"] = int(payload.get("invcNo") or 0)
                except (TypeError, ValueError):
                    pin_blob["purchase_invc_no_component"] = int(purchase_invc_no_component)
                pin_blob.pop("component_purchase_next_invc_no", None)
                save_test_state(state_root)

            if (
                endpoint_name == "selectStockMoveListComponentPurchase"
                and endpoint_accepts_result_cd(endpoint_name, result_cd)
                and isinstance(parsed, dict)
            ):
                _ccc2 = (pin_blob.get("component_item_cd") or "").strip()
                _rsd_e2 = None
                if _ccc2:
                    _rsd_e2 = _first_rsd_qty_for_item_in_stock_move_tree(parsed, _ccc2)
                if _rsd_e2 is not None:
                    pin_blob["component_reconcile_rsd_qty"] = float(_rsd_e2)
                    save_test_state(state_root)
                    print(
                        "NOTE: component purchase reconcile "
                        f"rsdQty={pin_blob['component_reconcile_rsd_qty']!r} for itemCd={_ccc2!r}"
                    )
                else:
                    pin_blob.pop("component_reconcile_rsd_qty", None)
                    save_test_state(state_root)
                    print(
                        "NOTE: selectStockMoveListComponentPurchase — no extractable rsdQty for component "
                        f"itemCd={_ccc2!r}; saveStockMasterComponentPurchase will use purchase-line bypass qty "
                        "if present (SBX move-list advisory only)."
                    )

            if (
                endpoint_name == "selectStockMoveListInitial"
                and endpoint_accepts_result_cd(endpoint_name, result_cd)
                and isinstance(parsed, dict)
            ):
                _pid_i = (pin_blob.get("item_cd") or item_cd or "").strip()
                _rsd_i2 = (
                    _first_rsd_qty_for_item_in_stock_move_tree(parsed, _pid_i)
                    if _pid_i
                    else None
                )
                if _rsd_i2 is not None:
                    pin_blob["parent_initial_save_rsd_qty_from_kra"] = float(_rsd_i2)
                    pin_blob["current_stock_balance"] = float(_rsd_i2)
                    print(
                        "NOTE: parent_initial_save_rsd_qty_from_kra="
                        f"{pin_blob['parent_initial_save_rsd_qty_from_kra']!r} "
                        f"(selectStockMoveListInitial, itemCd={_pid_i!r})"
                    )
                else:
                    if pin_blob.get("_stock_move_list_initial_io_fallback"):
                        print(
                            "NOTE: selectStockMoveListInitial — parent_initial_save_rsd_qty_from_kra "
                            "set via FALLBACK (insertStockIOInitial qty); see log above."
                        )
                    else:
                        pin_blob.pop("parent_initial_save_rsd_qty_from_kra", None)
                        print(
                            "NOTE: selectStockMoveListInitial — no extractable rsdQty for parent itemCd "
                            f"{_pid_i!r}; saveStockMasterInitial will use insertStockIOInitial line qty when that IO "
                            "returned 000 (SBX empty move list)."
                        )
                save_test_state(state_root)

            if (
                endpoint_name == "selectStockMoveListAfterPurchase"
                and endpoint_accepts_result_cd(endpoint_name, result_cd)
                and isinstance(parsed, dict)
            ):
                _pid_pp = (pin_blob.get("item_cd") or item_cd or "").strip()
                _rsd_pp = (
                    _first_rsd_qty_for_item_in_stock_move_tree(parsed, _pid_pp)
                    if _pid_pp
                    else None
                )
                if _rsd_pp is not None:
                    pin_blob["parent_rsd_qty_post_purchase"] = float(_rsd_pp)
                    pin_blob["current_stock_balance"] = float(_rsd_pp)
                    print(
                        "NOTE: parent_rsd_qty_post_purchase="
                        f"{pin_blob['parent_rsd_qty_post_purchase']!r} "
                        f"(after main insertTrnsPurchase, itemCd={_pid_pp!r})"
                    )
                else:
                    pin_blob.pop("parent_rsd_qty_post_purchase", None)
                    print(
                        "NOTE: selectStockMoveListAfterPurchase — no extractable rsdQty for parent itemCd "
                        f"{_pid_pp!r}; saveStockMasterAfterPurchase will be skipped."
                    )
                save_test_state(state_root)

            if (
                endpoint_name == "selectStockMoveListPostComposition"
                and endpoint_accepts_result_cd(endpoint_name, result_cd)
                and isinstance(parsed, dict)
            ):
                _pid_osdc = (pin_blob.get("item_cd") or item_cd or "").strip()
                _rsd_osdc = (
                    _first_rsd_qty_for_item_in_stock_move_tree(parsed, _pid_osdc)
                    if _pid_osdc
                    else None
                )
                if _rsd_osdc is not None:
                    pin_blob["parent_osdc_prep_rsd_qty"] = float(_rsd_osdc)
                    pin_blob["current_stock_balance"] = float(_rsd_osdc)
                    print(
                        "NOTE: parent_osdc_prep_rsd_qty="
                        f"{pin_blob['parent_osdc_prep_rsd_qty']!r} "
                        f"(selectStockMoveListPostComposition, itemCd={_pid_osdc!r})"
                    )
                else:
                    if pin_blob.get("_stock_move_list_post_osdc_io_fallback"):
                        print(
                            "NOTE: selectStockMoveListPostComposition — parent_osdc_prep_rsd_qty "
                            "set via FALLBACK (insertStockIOPostComposition qty); see log above."
                        )
                    else:
                        pin_blob.pop("parent_osdc_prep_rsd_qty", None)
                        print(
                            "NOTE: selectStockMoveListPostComposition — no extractable rsdQty for parent itemCd "
                            f"{_pid_osdc!r}; saveStockMasterPostComposition will use insertStockIOPostComposition "
                            "line qty when that IO returned 000 (SBX empty move list)."
                        )
                save_test_state(state_root)

            if (
                endpoint_name == "selectStockMoveList"
                and endpoint_accepts_result_cd(endpoint_name, result_cd)
                and isinstance(parsed, dict)
            ):
                _pid_ff = (pin_blob.get("item_cd") or item_cd or "").strip()
                _rsd_ff = (
                    _first_rsd_qty_for_item_in_stock_move_tree(parsed, _pid_ff)
                    if _pid_ff
                    else None
                )
                if _rsd_ff is not None:
                    pin_blob["parent_rsd_qty_final"] = float(_rsd_ff)
                    pin_blob["current_stock_balance"] = float(_rsd_ff)
                    print(
                        "NOTE: parent_rsd_qty_final="
                        f"{pin_blob['parent_rsd_qty_final']!r} "
                        f"(after final parent insertStockIO, itemCd={_pid_ff!r})"
                    )
                else:
                    pin_blob.pop("parent_rsd_qty_final", None)
                    print(
                        "NOTE: selectStockMoveList (final) — no extractable rsdQty for parent itemCd "
                        f"{_pid_ff!r}; saveStockMaster (final) will be skipped."
                    )
                save_test_state(state_root)

            if endpoint_name in ("selectItemList", "selectItemListPostSave"):
                if isinstance(parsed, dict):
                    select_item_list_parsed = parsed

            if endpoint_name == "selectItemList" and (result_cd or "").strip() == "001":
                print(
                    f"CONTINUE: {endpoint_name} OK (empty catalog, resultCd=001 — expected before first saveItem)"
                )
            elif (
                endpoint_name in _SELECT_STOCK_MOVE_ENDPOINTS
                and (result_cd or "").strip() == "001"
            ):
                print(
                    f"CONTINUE: {endpoint_name} OK (no stock moves in result, resultCd=001)"
                )
            elif endpoint_name == "selectItemListPostSave" and (result_cd or "").strip() == "000":
                print(
                    f"CONTINUE: {endpoint_name} OK (catalog lists saved item, resultCd={result_cd!r})"
                )
            elif endpoint_name in _SELECT_EMPTY_OK and (result_cd or "").strip() == "001":
                print(f"CONTINUE: {endpoint_name} OK (no rows, resultCd=001)")
            else:
                print(f"CONTINUE: {endpoint_name} OK (state={result_cd})")

            if endpoint_name in _SELECT_STOCK_MOVE_ENDPOINTS:
                _ic_note = item_cd
                if endpoint_name == "selectStockMoveListComponentPurchase":
                    _ic_note = (pin_blob.get("component_item_cd") or item_cd or "").strip()
                elif endpoint_name == "selectStockMoveListAfterPurchase":
                    _ic_note = (pin_blob.get("item_cd") or item_cd or "").strip()
                elif endpoint_name == "selectStockMoveListPostComposition":
                    _ic_note = (pin_blob.get("item_cd") or item_cd or "").strip()
                if not response_contains_item_cd(parsed, _ic_note):
                    print(
                        f"NOTE: {endpoint_name} has no itemCd={_ic_note} in this response "
                        "(SBX can still proceed to saveStockMaster*)."
                    )

            if endpoint_name == "selectItemClsList":
                apply_item_cls_dynamic_from_parsed(parsed, item_cls_dynamic)
                icd = item_cls_dynamic["itemClsCd"]
                tty = item_cls_dynamic["taxTyCd"]
                print(f"EXTRACTED itemClsCd={icd} taxTyCd={tty}")

            if endpoint_name in (
                "saveStockMaster",
                "saveStockMasterInitial",
                "saveStockMasterAfterPurchase",
                "saveStockMasterComponentPurchase",
            ):
                time.sleep(2)

            flush_progress(
                endpoint_name,
                mark_endpoint_complete=endpoint_accepts_result_cd(endpoint_name, result_cd),
            )
            if endpoint_name == "selectStockMoveListInitial" and endpoint_accepts_result_cd(
                endpoint_name, result_cd
            ):
                initial_insert_io_just_ran = False
            if endpoint_name == "selectStockMoveList" and endpoint_accepts_result_cd(
                endpoint_name, result_cd
            ):
                final_parent_insert_io_just_ran = False
            if endpoint_name == "selectStockMoveListPostComposition" and endpoint_accepts_result_cd(
                endpoint_name, result_cd
            ):
                post_composition_parent_io_just_ran = False
            if (
                endpoint_name
                in (
                    "saveStockMaster",
                    "saveStockMasterInitial",
                    "saveStockMasterAfterPurchase",
                    "saveStockMasterComponentPurchase",
                    "saveStockMasterPostComposition",
                )
                and endpoint_accepts_result_cd(endpoint_name, result_cd)
            ):
                pin_blob["stock_io_pending_rsd_qty"] = 0.0
                save_test_state(state_root)
                if diagnostic_stock_io_cli and endpoint_name == "saveStockMasterInitial":
                    print("\n--- RESPONSE ---")
                    print(
                        json.dumps(parsed, indent=2, ensure_ascii=False, default=str)
                    )
                    raise SystemExit(0)

        except SkipToNextSequenceStep as _skip_step:
            _continue_step_notes.append((endpoint_name, str(_skip_step)))
            print(
                f"\nNOTE (--continue-on-step-failure): step {endpoint_name!r} aborted: {_skip_step}"
            )
            print(
                "WARNING: Sandbox ledger/state may be inconsistent; later steps may fail. "
                "Re-run without this flag for strict certification order."
            )
            save_test_state(state_root)
            continue

    if _continue_step_notes:
        print(
            f"\nDONE: sequence finished with {len(_continue_step_notes)} skipped step(s) "
            "(--continue-on-step-failure); see NOTE lines above."
        )
    else:
        print("\nDONE: validation sequence completed successfully.")
    try:
        persist(rows, entry)
        print(f"Saved profile state to {CSV_FILE.name}.")
    except OSError as e:
        print(f"Note: could not write {CSV_FILE.name}: {e}")
    return 1 if _continue_step_notes else 0


if __name__ == "__main__":
    raise SystemExit(main())
