#!/usr/bin/env python3
"""
Standalone OSCU GavaConnect sandbox sequence runner.

Credentials live in ``test_pins.csv`` beside this script, keyed by **app_pin**
(Application Test PIN). Columns:

  app_pin, consumer_key, consumer_secret, integ_pin, branch_id,
  device_serial, apigee_app_id, cmc_key

Each run you are prompted: ``Enter Application Test PIN:``, or pass ``python gavaetims.py <PIN>``
(never read from env). After clearing stock/SAR on the **OSCU portal**, use
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

**Customer / taxpayer lookups without running the full sequence** (e.g. item or stock steps failed):
``python gavaetims.py <PIN> --only selectCustomerList,selectTaxpayerInfo`` — runs only those
endpoints (same headers as the full run). Does not require prior steps to have succeeded.

If ``cmc_key`` is empty in CSV, the script validates OAuth + ``selectInitOsdcInfo``
before saving a new key. New PINs are validated the same way before any CSV write.
Clear ``cmc_key`` in the CSV manually to force a refresh (re-validation runs first).

Resume progress is stored in ``.test_state.json`` (keyed by ``app_pin``): ``cmc_key``,
``completed_endpoints``, and run context (``item_cd``, class codes, invoice fields)
so a failed mid-sequence run can continue with the same PIN.

**Gavaconnect (developer.go.ke) progress bar:** advancing the on-screen “X/23” checklist is
owned by the portal’s certification session, not by raw KRA OSCU calls. A timer at 00:00:00
usually means the validation window ended — request a new/extended session. Follow their
published testcase order and any required screenshots/submissions; otherwise the bar can stay
at “initialization” even when APIs return ``resultCd=000``.

**Product lookup:** the portal testcase “LOOK UP PRODUCT LIST” is ``/selectItemList`` (existing
items for the branch). That is separate from ``/selectItemClsList`` (HS/class codes). This
script calls ``selectItemList`` before ``saveItem`` (empty catalog ``resultCd=001`` is normal),
then **``selectItemListPostSave``** (same route with ``lastReqDt=now``) so GavaConnect sees the
saved product and typically gets ``resultCd=000``.
**Portal testcase names ↔ this script (same API order):**
``SAVE ITEM COMPOSITION`` → ``saveItemComposition``; ``UPDATE IMPORTED ITEMS`` → ``updateImportItem``
(after ``selectImportItemList``); ``SAVE SALES TRANSACTION`` → ``saveInvoice`` (POST
``/saveTrnsSalesOsdc``); ``LOOK UP PURCHASES-SALES LIST`` → ``selectTrnsPurchaseSalesList``;
``SAVE PURCHASES INFORMATION`` → ``insertTrnsPurchase``.
**``saveStockMaster`` appears twice in flow:** (1) ``saveStockMasterInitial`` right after the first
parent ``insertStockIOInitial`` — *before* composition, import, sales, and purchases — so the parent
item has on-hand qty for the later sale; (2) ``saveStockMaster`` after ``insertTrnsPurchase`` and the
final ``insertStockIO`` + ``selectStockMoveList``. Skipping later steps does **not** explain
``saveStockMasterInitial`` failing with rsdQty vs Stock IO mismatch; that pattern is often sandbox
**stacked stock IO / SAR** (clear OSCU stock for the PIN, then ``--reset-stock``).
**Hybrid order (SBX + GavaConnect):** ``selectItemList`` → ``saveItem`` → ``selectItemListPostSave`` →
**initial** ``insertStockIOInitial`` + ``selectStockMoveListInitial`` + ``saveStockMasterInitial`` (minimal parent stock so sales can succeed) →
``saveComponentItem`` / ``saveItemComposition`` → import steps → ``saveInvoice`` (``/saveTrnsSalesOsdc``) →
``selectTrnsPurchaseSalesList`` + ``insertTrnsPurchase`` → **final** ``insertStockIO`` + ``selectStockMoveList`` +
``saveStockMaster`` (reconciliation). Use ``--clean-run`` to drop stale ``item_cd`` / completed steps;
``--reset-stock`` only clears stock-step keys.
**Stock IO + save:** run ``insertStockIO`` and ``saveStockMaster`` in the **same** process invocation.
The runner tracks ``current_stock_balance`` (on-hand qty) and sends ``rsdQty`` equal to that balance
after each STOCK IN/OUT (``sarTyCd`` 11 is treated as IN in this testcase). Resuming after
``insertStockIO`` alone can leave SBX out of sync with local state; if saves keep failing,
**KRA may still hold stacked IOs** (local restarts do not fix that): reset stock/SAR on the **OSCU
sandbox portal** for the PIN, then run ``python gavaetims.py <PIN> --reset-stock`` and a full
sequence once.
**Customer/supplier master POSTs** (``/saveCustomer``, ``/saveSupplier``) and legacy **``/selectCustomer``**
often hit Apigee ``targetPath`` faults; this runner uses **``/selectCustomerList``** and
**``/selectTaxpayerInfo``** (skipped automatically if SBX returns the same fault).
Invoice transaction list uses **``/selectTrnsSalesList``** and **``/selectInvoiceDtl``** (paths
are taken from the KRA integrator SDK naming; if your SBX product uses a different route name,
adjust the path in the ``sequence`` table). **``updateImportItem``** is optional when there are
no imported-item rows (result not ``000`` → logged and skipped).
**``saveItemComposition``** requires **on-hand stock** for ``cpstItemCd``. In this order it runs
right after ``saveComponentItem``; the runner’s **composition prelude** posts component-only
``insertStockIO`` + ``saveStockMaster`` so SAR/parent sequencing stays consistent. **Parent** stock IO
and ``saveStockMaster`` run later (after purchases). If SBX stacks unreconciled component IOs, clear
``component_stock_balance`` in ``.test_state.json`` or reset stock on the OSCU portal.
**Quantity unit:** sandbox ``saveItem`` rejects ``qtyUnitCd`` values that are not on KRA’s allow-list
(e.g. ``XU`` → HTTP 400 “Invalid Quantity Unit Code”). Use a listed code such as ``TU`` (unit /
standard measure); ``itemCd`` embeds the same 2-letter segment for type-1 items.
"""

from __future__ import annotations

import csv
import json
import os
import random
import re
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://sbx.kra.go.ke/etims-oscu/api/v1"
OAUTH_BASE = "https://sbx.kra.go.ke"
OAUTH_TOKEN_PATH = "/v1/token/generate"

CSV_FILE = Path(__file__).parent / "test_pins.csv"
STATE_FILE = Path(__file__).parent / ".test_state.json"

# Always run these during sandbox validation even if listed in ``completed_endpoints``.
ALWAYS_EXECUTE_ENDPOINTS = frozenset(
    {
        "selectCodeList",
        "selectItemClsList",
        "selectBhfList",
        "selectNotices",
        "saveBhfCustomer",
        "saveBhfUser",
        "saveBhfInsurance",
        "selectItemList",
    }
)

# SBX Apigee sometimes returns HTTP 500 fault "Unresolved variable : targetPath" for routes not wired to this product.
SOFT_SKIP_APIGEE_TARGET_PATH = frozenset(
    {
        "selectInvoiceType",
        "selectCustomerList",
        "selectTaxpayerInfo",
        "selectTrnsSalesList",
        "selectInvoiceDtl",
    }
)

# SBX may have no customs import rows; still call the testcase but do not fail the whole run.
OPTIONAL_SBX_STEPS = frozenset({"updateImportItem"})

# ``select*`` calls that may legitimately return resultCd 001 (empty list).
_SELECT_EMPTY_OK = frozenset(
    {
        "selectImportItemList",
        "selectTrnsPurchaseSalesList",
        "selectTrnsSalesList",
        "selectInvoiceDtl",
        "selectCustomerList",
        "selectTaxpayerInfo",
    }
)

# Same /selectStockMoveList route; separate step ids for initial vs final IO→save pairs.
_SELECT_STOCK_MOVE_ENDPOINTS = frozenset(
    {"selectStockMoveList", "selectStockMoveListInitial"}
)

# Before ``saveStockMasterInitial``: local |pending| or move-list row count above this suggests SBX SAR /
# historical Stock IO backlog (fail fast; do not alter rsdQty or add retries).
INITIAL_SAVE_STOCKMASTER_DIRTY_THRESHOLD = 10
# Unreconciled SAR count (stock_io_next_sar_no - 1) at or above this → likely stacked IO / SBX rsdQty deadlock.
INITIAL_SAVE_STOCKMASTER_SAR_BACKLOG_DIRTY = 3

# Stock IOSaveReq: ``sarTyCd`` 11 is treated as STOCK IN (increases on-hand qty) per OSCU testcase.
SAR_TY_CD_STOCK_IN = "11"


def stock_balance_delta_for_sar_line(sar_ty_cd: str, line_qty: float) -> float:
    """Signed change to on-hand balance for one Stock IO line: IN adds, OUT subtracts."""
    ty = (sar_ty_cd or "").strip()
    q = float(line_qty)
    if ty == SAR_TY_CD_STOCK_IN:
        return q
    # Extend when this runner posts other sarTyCd values (e.g. stock OUT).
    return q


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
    "insertStockIOInitial",
    "selectStockMoveListInitial",
    "saveStockMasterInitial",
    "saveComponentItem",
    "saveItemComposition",
    "selectImportItemList",
    "updateImportItem",
    "selectInvoiceType",
    "saveInvoice",
    "selectTrnsPurchaseSalesList",
    "insertTrnsPurchase",
    "insertStockIO",
    "selectStockMoveList",
    "saveStockMaster",
    "selectTrnsSalesList",
    "selectInvoiceDtl",
    "selectCustomerList",
    "selectTaxpayerInfo",
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
    ce = list(pin_blob.get("completed_endpoints") or [])
    drop = {
        "saveItem",
        "selectItemListPostSave",
        "insertStockIOInitial",
        "selectStockMoveListInitial",
        "saveStockMasterInitial",
        "saveComponentItem",
        "saveItemComposition",
        "selectImportItemList",
        "updateImportItem",
        "selectInvoiceType",
        "saveInvoice",
        "selectTrnsPurchaseSalesList",
        "insertTrnsPurchase",
        "insertStockIO",
        "selectStockMoveList",
        "saveStockMaster",
    }
    pin_blob["completed_endpoints"] = [x for x in ce if x not in drop]
    for k in (
        "item_cd",
        "canonical_item_cd",
        "component_item_cd",
        "stock_io_next_sar_no",
        "stock_io_pending_rsd_qty",
        "stock_io_component_pending_rsd_qty",
        "current_stock_balance",
        "component_stock_balance",
        "stocked_component_for_composition",
        "kra_item_cd_suffix_by_prefix",
    ):
        pin_blob.pop(k, None)
    pin_blob["stock_io_pending_rsd_qty"] = 0.0


def reset_pin_stock_progress(pin_blob: dict) -> None:
    """Drop local stock-step progress so the sequence can run again after a portal-side stock/SAR reset."""
    ce = list(pin_blob.get("completed_endpoints") or [])
    drop = {
        "insertStockIOInitial",
        "selectStockMoveListInitial",
        "saveStockMasterInitial",
        "insertStockIO",
        "selectStockMoveList",
        "saveStockMaster",
        "saveComponentItem",
        "saveItemComposition",
    }
    pin_blob["completed_endpoints"] = [x for x in ce if x not in drop]
    for k in (
        "stock_io_component_pending_rsd_qty",
        "current_stock_balance",
        "component_stock_balance",
        "stocked_component_for_composition",
    ):
        pin_blob.pop(k, None)
    # Do not force sarNo=1: KRA keeps the real sequence (e.g. next is 9 after failed runs).
    # Omit key so the first attempt defaults to 1, or run again; insertStockIO syncs from KRA errors.
    pin_blob.pop("stock_io_next_sar_no", None)
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
            "selectStockMoveListInitial",
            "saveStockMasterInitial",
        )
    ]
    pin_blob["stock_io_pending_rsd_qty"] = 0.0
    pin_blob.pop("stock_io_next_sar_no", None)
    pin_blob.pop("current_stock_balance", None)


def apply_diagnostic_stock_io_reset(pin_blob: dict) -> None:
    """Single SBX check: drop local resume for the initial IO → move list → save triple; SAR 1; balance 0."""
    ce = list(pin_blob.get("completed_endpoints") or [])
    drop = {
        "insertStockIOInitial",
        "selectStockMoveListInitial",
        "saveStockMasterInitial",
    }
    pin_blob["completed_endpoints"] = [x for x in ce if x not in drop]
    pin_blob["stock_io_next_sar_no"] = 1
    pin_blob["current_stock_balance"] = 0.0
    pin_blob["stock_io_pending_rsd_qty"] = 0.0


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


def cli_pin_and_flags() -> tuple[str, bool, bool, bool, frozenset[str] | None, bool]:
    """PIN + ``--reset-stock`` + ``--clean-run`` + ``--force-stock-replay`` + optional ``--only`` + ``--diagnostic-stock-io``."""
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
    return pin, reset_stock, clean_run, force_stock_replay, only_steps, diagnostic_stock_io


def prompt_app_pin() -> str:
    pin, _, _, _, _, _ = cli_pin_and_flags()
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

    if resp0.status_code >= 400:
        return (
            False,
            f"VALIDATION: HTTP {resp0.status_code} from selectInitOsdcInfo",
            bearer,
            None,
        )
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
    KRA OSCU saveItem (sandbox): itemCd must not be \"reused\" and the numeric suffix must end
    with digit 1 (error text: Expected sequence ending with ********1). Applies to itemTyCd 1 and 2.
    """
    _ = item_ty_cd  # prefix KE{ty}… is set by caller; suffix rule is the same in SBX runs observed
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


def next_suffix_int_after(high_water: int) -> int:
    """Smallest value greater than high_water whose last digit is 1 (KRA SBX itemCd sequence rule)."""
    n = int(high_water) + 1
    while n % 10 != 1:
        n += 1
    if n > 9_999_999:
        raise ValueError("itemCd 7-digit suffix exhausted (>9999999)")
    return n


def alloc_monotonic_item_cd_suffix(
    prefix: str,
    select_item_parsed: dict | None,
    pin_blob: dict,
    attempt_hw: dict[str, int],
) -> str:
    """
    Next itemCd suffix for ``prefix``, strictly increasing within this saveItem attempt chain.
    Baseline comes from the latest selectItemList response plus ``kra_item_cd_suffix_by_prefix`` in state.
    """
    prefix = (prefix or "").strip()
    sm = pin_blob.get("kra_item_cd_suffix_by_prefix")
    if not isinstance(sm, dict):
        sm = {}
    stored = 0
    if prefix in sm:
        try:
            stored = int(sm[prefix])
        except (TypeError, ValueError):
            stored = 0
    api_max = max_numeric_suffix_for_prefix(select_item_parsed, prefix)
    base_floor = max(api_max, stored)
    cur = attempt_hw.get(prefix)
    if cur is None:
        cur = base_floor
    nxt = next_suffix_int_after(cur)
    attempt_hw[prefix] = nxt
    return f"{nxt:07d}"


def next_item_cd_for_composition_branch(
    main_item_cd: str,
    select_item_parsed: dict | None,
) -> str:
    """
    Next ``itemCd`` for a second ``/saveItem`` (component) after ``main_item_cd``.

    SBX rejects ``alloc_monotonic_item_cd_suffix`` here: that helper advances suffixes that **end in 1**
    (initial product chain), while the **next** product after ``…0000001`` must end in **2**, etc.
    Stale ``kra_item_cd_suffix_by_prefix`` in ``.test_state.json`` must not override the live catalog.
    """
    ic = (main_item_cd or "").strip()
    m = re.match(r"(.+?)(\d{7})$", ic)
    if not m:
        raise ValueError(f"expected … + 7 digit suffix on itemCd, got {ic!r}")
    pfx, suf_s = m.group(1), m.group(2)
    main_n = int(suf_s)
    api_max = max_numeric_suffix_for_prefix(select_item_parsed, pfx)
    nxt = max(main_n, api_max) + 1
    if nxt > 9_999_999:
        raise ValueError("itemCd 7-digit suffix exhausted")
    return f"{pfx}{nxt:07d}"


def persist_item_cd_suffix_map(pin_blob: dict, item_cd: str) -> None:
    """Store last successful numeric suffix per itemCd prefix (before ``flush_progress`` writes state)."""
    ic = (item_cd or "").strip()
    if len(ic) < 7 or not ic[-7:].isdigit():
        return
    pfx, suf_s = ic[:-7], ic[-7:]
    suf = int(suf_s)
    pin_blob.setdefault("kra_item_cd_suffix_by_prefix", {})
    if not isinstance(pin_blob["kra_item_cd_suffix_by_prefix"], dict):
        pin_blob["kra_item_cd_suffix_by_prefix"] = {}
    pin_blob["kra_item_cd_suffix_by_prefix"][pfx] = suf


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

    surl = f"{base_url.rstrip('/')}/selectStockMoveList"
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


def main():
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
            print(
                "The provided consumer credentials do not match this Application Test PIN. "
                "Please re-enter."
            )
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
    ) = cli_pin_and_flags()
    if clean_run_cli:
        reset_pin_clean_run(pin_blob)
        save_test_state(state_root)
        completed_list = list(pin_blob.get("completed_endpoints") or [])
        print(
            "NOTE: --clean-run applied: cleared item_cd / canonical_item_cd / composition / stock / "
            f"import / sales / purchase steps for this PIN (see {STATE_FILE.name})."
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
        save_test_state(state_root)

    _parent_io_done_tags = frozenset({"insertStockIO", "insertStockIOInitial"})
    _any_parent_insert_done = bool(_parent_io_done_tags.intersection(completed_list))

    _sq_heal = int(pin_blob.get("stock_qty") or 100)
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
    if (
        not only_steps_cli
        and _any_parent_insert_done
        and pin_blob.get("current_stock_balance") is None
    ):
        try:
            _n_heal = int(pin_blob.get("stock_io_next_sar_no") or 1)
        except (TypeError, ValueError):
            _n_heal = 1
        if _n_heal > 1:
            pin_blob["current_stock_balance"] = float((_n_heal - 1) * _sq_heal)
            save_test_state(state_root)
            print(
                "NOTE: Healed current_stock_balance from SAR sequence "
                f"({pin_blob['current_stock_balance']}), matching Stock IO depth before saveStockMaster."
            )

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
        if _bal_w > 1e-9:
            print(
                "NOTE: Stock pipeline wedged (pending saveStockMaster with unreconciled "
                "current_stock_balance but that step never completed). This is parent-item insertStockIO "
                "reconciliation (saveItemComposition already ran earlier with its own component stock "
                "prelude). Removing insertStockIO and selectStockMoveList from completed_endpoints so they "
                "run again in this process together with saveStockMaster. If insertStockIO then fails, "
                "reset OSCU stock/SAR for this PIN and adjust current_stock_balance / stock_io_* keys in "
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
        apply_diagnostic_stock_io_reset(pin_blob)
        completed_list = list(pin_blob.get("completed_endpoints") or [])
        save_test_state(state_root)
        print(
            "\n"
            + "=" * 78
            + "\nDIAGNOSTIC SBX STOCK IO (--diagnostic-stock-io)\n"
            "  • Resume disabled for insertStockIOInitial / selectStockMoveListInitial / saveStockMasterInitial\n"
            "  • Single SAR: stock_io_next_sar_no=1 → first IO uses sarNo=1, orgSarNo=0; "
            "current_stock_balance=0 before POST\n"
            "  • initial_parent_stock_qty forced to 1 (line qty)\n"
            "  • insertStockIOInitial: one POST only (no retry loop). saveStockMasterInitial: _cap_attempts=1\n"
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
    elif set(SEQUENCE_STEP_NAMES).issubset(set(completed_list)):
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
            item_cd = f"KE{item_ty_cd}{pkg_unit_cd}{qty_unit_cd}{item_cd_numeric_suffix(item_ty_cd=item_ty_cd)}"
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
        item_cd = f"KE{item_ty_cd}{pkg_unit_cd}{qty_unit_cd}{item_cd_numeric_suffix(item_ty_cd=item_ty_cd)}"
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

    item_cd = reconcile_item_cd_with_pin_state(pin_blob, item_cd)
    initial_parent_stock_qty = 1.0
    if diagnostic_stock_io_cli:
        initial_parent_stock_qty = 1.0
        stock_qty = 1

    qty = 1.0
    prc = 100.0
    taxbl = prc * qty
    tax_amt = 0.0
    tot_amt = taxbl + tax_amt

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
                "lastReqDt": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
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
            "selectStockMoveListInitial",
            "/selectStockMoveList",
            {
                "tin": effective_tin,
                "bhfId": branch_id,
                "lastReqDt": "20100101000000",
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
        ("saveComponentItem", "/saveItem", {}),
        (
            "saveItemComposition",
            "/saveItemComposition",
            {
                "itemCd": item_cd,
                "cpstItemCd": "",
                "cpstQty": 1.0,
                "regrId": "system",
                "regrNm": "system",
                "modrId": "system",
                "modrNm": "system",
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
            "updateImportItem",
            "/updateImportItem",
            {
                "taskCd": "01",
                "dclDe": sales_dt,
                "itemSeq": 1,
                "hsCd": "0101210000",
                "itemClsCd": item_cls_dynamic["itemClsCd"],
                "itemCd": item_cd,
                "imptItemSttsCd": "3",
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
                "rcptTyCd": "S",
                "pmtTyCd": "01",
            },
        ),
        (
            "saveInvoice",
            "/saveTrnsSalesOsdc",
            {
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
                "invcNo": purchase_invc_no,
                "orgInvcNo": 0,
                "spplrBhfId": branch_id,
                "spplrNm": "Test Supplier",
                "regTyCd": "M",
                "pchsTyCd": "1",
                "rcptTyCd": "S",
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
            "selectStockMoveList",
            "/selectStockMoveList",
            {
                "tin": effective_tin,
                "bhfId": branch_id,
                "lastReqDt": "20100101000000",
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
            "selectInvoiceDtl",
            "/selectInvoiceDtl",
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
            "selectTaxpayerInfo",
            "/selectTaxpayerInfo",
            {
                "tin": effective_tin,
                "bhfId": branch_id,
                "lastReqDt": "20100101000000",
            },
        ),
    ]

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
        save_test_state(state_root)

    select_item_list_parsed: dict | None = None
    final_parent_insert_io_just_ran = False
    initial_insert_io_just_ran = False
    ran_insert_stock_io_initial_this_run = False
    ran_insert_stock_io_parent_this_run = False

    def ensure_component_stock_before_composition() -> None:
        """KRA rejects saveItemComposition with Insufficient Stock unless cpstItemCd has inventory."""
        if pin_blob.get("stocked_component_for_composition"):
            print(
                "NOTE: Stock prelude for saveItemComposition skipped (already done for this component)."
            )
            return
        comp_cd = (pin_blob.get("component_item_cd") or "").strip()
        if not comp_cd:
            raise SystemExit(
                "STOP: saveItemComposition prelude — no component_item_cd (run saveComponentItem first)."
            )
        qty_f = max(float(stock_qty), 1.0)
        prc_f = 10.0
        line_sply = float(prc_f) * qty_f
        icd = (item_cls_dynamic.get("itemClsCd") or "1010000000").strip()
        tty = (item_cls_dynamic.get("taxTyCd") or "A").strip()
        io_ocrn_8 = (sales_dt or "").strip()[:8]
        if len(io_ocrn_8) != 8:
            io_ocrn_8 = datetime.now(timezone.utc).strftime("%Y%m%d")
        io_url = f"{BASE_URL.rstrip('/')}/insertStockIO"
        sm_url = f"{BASE_URL.rstrip('/')}/saveStockMaster"

        prelude_io_sar = int(pin_blob.get("stock_io_next_sar_no") or 1) - 1

        try:
            _comp_bal_skip = float(pin_blob.get("component_stock_balance") or 0.0)
        except (TypeError, ValueError):
            _comp_bal_skip = 0.0
        if _comp_bal_skip >= 1e-9 and not pin_blob.get("stocked_component_for_composition"):
            print(
                "PRELUDE: component Stock IO already increased on-hand balance "
                f"({_comp_bal_skip:g}); skipping insertStockIO, reconciling via saveStockMaster only."
            )
        else:
            try:
                sar_no_used = int(pin_blob.get("stock_io_next_sar_no") or 1)
            except (TypeError, ValueError):
                sar_no_used = 1
            if sar_no_used < 1:
                sar_no_used = 1
            org_sar_primary = 0 if sar_no_used == 1 else sar_no_used - 1
            org_sar_tries: list[int | None] = [org_sar_primary, None]
            parsed_io = None
            result_cd_io = None
            succeeded = False
            prelude_io_sar = sar_no_used
            for outer_attempt, org_sar_val in enumerate(org_sar_tries):
                reg_ty = "M"
                sar_ty = SAR_TY_CD_STOCK_IN
                stock_line = {
                    "itemSeq": 1,
                    "itemCd": comp_cd,
                    "itemClsCd": icd,
                    "itemNm": "COMPONENT ITEM",
                    "pkgUnitCd": pkg_unit_cd,
                    "pkg": qty_f,
                    "qtyUnitCd": qty_unit_cd,
                    "qty": qty_f,
                    "prc": float(prc_f),
                    "splyAmt": line_sply,
                    "totDcAmt": 0.0,
                    "taxblAmt": line_sply,
                    "taxTyCd": tty,
                    "taxAmt": 0.0,
                    "totAmt": line_sply,
                }
                io_root: dict = {
                    "sarNo": sar_no_used,
                    "regTyCd": reg_ty,
                    "custTin": effective_tin,
                    "sarTyCd": sar_ty,
                    "ocrnDt": io_ocrn_8,
                    "totItemCnt": 1,
                    "totTaxblAmt": line_sply,
                    "totTaxAmt": 0.0,
                    "totAmt": line_sply,
                    "regrId": "system",
                    "regrNm": "system",
                    "modrId": "system",
                    "modrNm": "system",
                    "itemList": [deepcopy(stock_line)],
                }
                if org_sar_val is not None:
                    io_root["orgSarNo"] = org_sar_val
                print(
                    "PRELUDE insertStockIO (component stock for saveItemComposition) "
                    f"[sarNo={sar_no_used}, itemCd={comp_cd}]"
                )
                print("Request JSON:", json.dumps(io_root, indent=2, ensure_ascii=False))
                resp_io = requests.post(io_url, headers=headers, json=io_root, timeout=60)
                parsed_io = print_full_response_json(resp_io, "insertStockIO (composition prelude)")
                result_cd_io = extract_result_cd(parsed_io)
                gate_err = kra_top_level_error_detail(parsed_io)
                if (
                    resp_io.status_code < 400
                    and not gate_err
                    and result_cd_io == "000"
                ):
                    succeeded = True
                    prelude_io_sar = sar_no_used
                    pin_blob["stock_io_next_sar_no"] = sar_no_used + 1
                    _prev_c = float(pin_blob.get("component_stock_balance") or 0.0)
                    pin_blob["component_stock_balance"] = _prev_c + stock_balance_delta_for_sar_line(
                        sar_ty, qty_f
                    )
                    save_test_state(state_root)
                    break
                if outer_attempt >= len(org_sar_tries) - 1:
                    ge = kra_top_level_error_detail(parsed_io) if parsed_io else None
                    raise SystemExit(
                        "STOP: composition prelude insertStockIO failed "
                        f"(last resultCd={result_cd_io!r}" + (f", {ge}" if ge else "") + ")"
                    )
                if org_sar_val is not None:
                    print(
                        "RETRY: composition prelude insertStockIO (omit orgSarNo on next try) …"
                    )
            if not succeeded:
                raise SystemExit("STOP: composition prelude insertStockIO did not succeed.")
            time.sleep(2)

        try:
            _rsd = float(pin_blob.get("component_stock_balance") or 0.0)
        except (TypeError, ValueError):
            _rsd = float(qty_f)
        sm_payload = {
            "itemCd": comp_cd,
            "rsdQty": _rsd,
            "regrId": "system",
            "regrNm": "system",
            "modrId": "system",
            "modrNm": "system",
        }

        def _hdr_blob(p: dict | None) -> str:
            if not isinstance(p, dict):
                return ""
            hdr = p.get("responseHeader")
            if not isinstance(hdr, dict):
                return ""
            return f"{hdr.get('debugMessage') or ''} {hdr.get('customerMessage') or ''}"

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
            rc = extract_result_cd(p)
            ge = kra_top_level_error_detail(p)
            ok = r.status_code < 400 and not ge and rc == "000"
            return ok, p, r

        ok_sm, parsed_sm, resp_sm = _post_save_comp_prelude(_rsd, "")
        ge_sm = kra_top_level_error_detail(parsed_sm)
        rc_sm = extract_result_cd(parsed_sm)
        if not ok_sm:
            blob = _hdr_blob(parsed_sm)
            exp = kra_expected_rsd_qty_from_mismatch_message(blob)
            if exp is not None:
                _try_vals: list[float] = [abs(exp)]
                for j, rsd_try in enumerate(_try_vals):
                    pin_blob["component_stock_balance"] = rsd_try
                    save_test_state(state_root)
                    ok_sm, parsed_sm, resp_sm = _post_save_comp_prelude(
                        rsd_try, f"KRA Expected mismatch attempt {j + 1}"
                    )
                    ge_sm = kra_top_level_error_detail(parsed_sm)
                    rc_sm = extract_result_cd(parsed_sm)
                    if ok_sm:
                        break
        if not ok_sm:
            raise SystemExit(
                "STOP: composition prelude saveStockMaster failed "
                f"(HTTP={resp_sm.status_code}, resultCd={rc_sm!r}"
                + (f", {ge_sm}" if ge_sm else "")
                + ")"
            )
        pin_blob["stocked_component_for_composition"] = True
        save_test_state(state_root)
        print("CONTINUE: component stock prelude OK (ready for saveItemComposition).")

    for endpoint_name, endpoint_path, payload_template in sequence:
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
            and endpoint_name not in ALWAYS_EXECUTE_ENDPOINTS
        )
        if only_steps_cli:
            skip_completed = False
        if (
            skip_completed
            and endpoint_name == "insertStockIOInitial"
            and not diagnostic_stock_io_cli
        ):
            if "saveStockMasterInitial" not in completed_list:
                try:
                    _ns_skip = int(pin_blob.get("stock_io_next_sar_no") or 1)
                except (TypeError, ValueError):
                    _ns_skip = 1
                _line_skip = float(initial_parent_stock_qty)
                _have_bal = False
                _raw_b = pin_blob.get("current_stock_balance")
                if _raw_b is not None and str(_raw_b).strip() != "":
                    try:
                        _bv = float(_raw_b)
                        if abs(_bv) >= 1e-9:
                            _have_bal = True
                            pin_blob["current_stock_balance"] = _bv
                    except (TypeError, ValueError):
                        pass
                if not _have_bal:
                    _est = float(max(0, _ns_skip - 1) * _line_skip)
                    try:
                        _rp = pin_blob.get("stock_io_pending_rsd_qty")
                        if _rp is not None and str(_rp).strip() != "":
                            _est = abs(float(_rp))
                    except (TypeError, ValueError):
                        pass
                    pin_blob["current_stock_balance"] = _est
                ran_insert_stock_io_initial_this_run = True
                save_test_state(state_root)
                print(
                    "NOTE: insertStockIOInitial already on SBX — not re-posting; "
                    f"stock_io_next_sar_no={_ns_skip}, "
                    f"current_stock_balance={pin_blob['current_stock_balance']!r} "
                    "(saveStockMasterInitial still pending)."
                )
                continue
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

        url = f"{BASE_URL.rstrip('/')}{endpoint_path}"

        if endpoint_name in ("insertStockIO", "insertStockIOInitial"):
            stock_progress_key = endpoint_name
            is_initial_parent_io = endpoint_name == "insertStockIOInitial"
            _io_log = (
                "insertStockIOInitial"
                if is_initial_parent_io
                else "insertStockIO"
            )
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
            if not is_initial_parent_io and "saveStockMaster" not in completed_list:
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
            line_qty_f = (
                float(initial_parent_stock_qty)
                if is_initial_parent_io
                else float(stock_qty)
            )
            line_sply = float(prc) * line_qty_f
            io_ocrn_8 = (sales_dt or "").strip()[:8]
            if len(io_ocrn_8) != 8:
                io_ocrn_8 = datetime.now(timezone.utc).strftime("%Y%m%d")
            # SBX: monotonic sarNo per branch/session (1, 2, …). orgSarNo cannot equal sarNo.
            # First IO: orgSarNo=0. Later IOs: orgSarNo references the previous sarNo (sarNo-1).

            if is_initial_parent_io:
                try:
                    sar_no_used = int(pin_blob.get("stock_io_next_sar_no") or 1)
                except (TypeError, ValueError):
                    sar_no_used = 1
                if sar_no_used < 1:
                    sar_no_used = 1
                org_sar_primary = 0 if sar_no_used == 1 else sar_no_used - 1
                reg_ty = "M"
                # insertStockIOInitial: diagnostic — testing sarTyCd "01" vs SBX Stock IO / saveStockMaster rsdQty.
                sar_ty = "01"
                icd = (item_cls_dynamic.get("itemClsCd") or "1010000000").strip()
                tty = (item_cls_dynamic.get("taxTyCd") or "A").strip()
                stock_line = {
                    "itemSeq": 1,
                    "itemCd": item_cd,
                    "itemClsCd": icd,
                    "itemNm": "TEST ITEM",
                    "pkgUnitCd": pkg_unit_cd,
                    "pkg": line_qty_f,
                    "qtyUnitCd": qty_unit_cd,
                    "qty": line_qty_f,
                    "prc": float(prc),
                    "splyAmt": line_sply,
                    "totDcAmt": 0.0,
                    "taxblAmt": line_sply,
                    "taxTyCd": tty,
                    "taxAmt": 0.0,
                    "totAmt": line_sply,
                }
                io_root = {
                    "sarNo": sar_no_used,
                    "regTyCd": reg_ty,
                    "custTin": effective_tin,
                    "sarTyCd": sar_ty,
                    "ocrnDt": io_ocrn_8,
                    "totItemCnt": 1,
                    "totTaxblAmt": line_sply,
                    "totTaxAmt": 0.0,
                    "totAmt": line_sply,
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
                    print(
                        "\n"
                        + "=" * 78
                        + "\nDIAGNOSTIC insertStockIOInitial — FULL PAYLOAD (before POST)\n"
                        + f"RUNNING {_io_log} [{label}]\n"
                        + "=" * 78
                    )
                    print(json.dumps(io_root, indent=2, ensure_ascii=False))
                    print(
                        "=" * 78
                        + f"\nExpect after success (HTTP OK, resultCd 000): "
                        f"current_stock_balance = {line_qty_f:g}\n"
                        + "=" * 78
                        + "\n"
                    )
                else:
                    print(f"RUNNING {_io_log} [{label}]")
                    print(
                        "Request JSON:",
                        json.dumps(io_root, indent=2, ensure_ascii=False),
                    )
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
                    pin_blob["stock_io_next_sar_no"] = sar_no_used + 1
                    _prev = float(pin_blob.get("current_stock_balance") or 0.0)
                    pin_blob["current_stock_balance"] = _prev + stock_balance_delta_for_sar_line(
                        sar_ty, line_qty_f
                    )
                    ran_insert_stock_io_initial_this_run = True
                    initial_insert_io_just_ran = True
                    if diagnostic_stock_io_cli:
                        print(
                            "\nDIAGNOSTIC: after insertStockIOInitial success — "
                            f"current_stock_balance={pin_blob.get('current_stock_balance')!r}\n"
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
                    continue
                raise SystemExit(
                    "FATAL: insertStockIOInitial failed. This PIN is now unusable."
                )

            else:
                parsed_io = None
                result_cd_io = None
                succeeded = False
                for _sar_sync in range(5):
                    if succeeded:
                        break
                    try:
                        sar_no_used = int(pin_blob.get("stock_io_next_sar_no") or 1)
                    except (TypeError, ValueError):
                        sar_no_used = 1
                    if sar_no_used < 1:
                        sar_no_used = 1
                    org_sar_primary = 0 if sar_no_used == 1 else sar_no_used - 1
                    org_sar_tries: list[int | None] = [org_sar_primary, None]
                    resync_sar = False
                    for outer_attempt, org_sar_val in enumerate(org_sar_tries):
                        # Paybill/KRA StockIOSaveReq shape (not stockInOutList / per-line ioTyCd).
                        reg_ty = "M"
                        sar_ty = SAR_TY_CD_STOCK_IN
                        icd = (item_cls_dynamic.get("itemClsCd") or "1010000000").strip()
                        tty = (item_cls_dynamic.get("taxTyCd") or "A").strip()
                        stock_line = {
                            "itemSeq": 1,
                            "itemCd": item_cd,
                            "itemClsCd": icd,
                            "itemNm": "TEST ITEM",
                            "pkgUnitCd": pkg_unit_cd,
                            "pkg": line_qty_f,
                            "qtyUnitCd": qty_unit_cd,
                            "qty": line_qty_f,
                            "prc": float(prc),
                            "splyAmt": line_sply,
                            "totDcAmt": 0.0,
                            "taxblAmt": line_sply,
                            "taxTyCd": tty,
                            "taxAmt": 0.0,
                            "totAmt": line_sply,
                        }
                        io_root = {
                            "sarNo": sar_no_used,
                            "regTyCd": reg_ty,
                            "custTin": effective_tin,
                            "sarTyCd": sar_ty,
                            "ocrnDt": io_ocrn_8,
                            "totItemCnt": 1,
                            "totTaxblAmt": line_sply,
                            "totTaxAmt": 0.0,
                            "totAmt": line_sply,
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
                            pin_blob["stock_io_next_sar_no"] = sar_no_used + 1
                            _prev = float(pin_blob.get("current_stock_balance") or 0.0)
                            pin_blob["current_stock_balance"] = _prev + stock_balance_delta_for_sar_line(
                                sar_ty, line_qty_f
                            )
                            final_parent_insert_io_just_ran = True
                            ran_insert_stock_io_parent_this_run = True
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
                            if exp_sar is not None and exp_sar != sar_no_used:
                                pin_blob["stock_io_next_sar_no"] = exp_sar
                                save_test_state(state_root)
                                print(
                                    "NOTE: KRA expects insertStockIO sarNo="
                                    f"{exp_sar} (request used {sar_no_used}); "
                                    f"updated stock_io_next_sar_no in {STATE_FILE.name} "
                                    "and retrying."
                                )
                                resync_sar = True
                                break
                            ge = (
                                kra_top_level_error_detail(parsed_io)
                                if parsed_io
                                else None
                            )
                            raise SystemExit(
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
                    raise SystemExit(
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

            def load_save_item_classification(*, label: str) -> tuple[str, str, str]:
                """Returns (itemClsCd, taxTyCd, itemTyCd for itemCd prefix)."""
                print(f"RUNNING selectItemClsList ({label})")
                resp_cls = requests.post(
                    select_cls_url, headers=headers, json=select_cls_payload, timeout=60
                )
                parsed_cls = print_full_response_json(resp_cls, f"selectItemClsList ({label})")
                result_cls = extract_result_cd(parsed_cls)
                gate_err_cls = kra_top_level_error_detail(parsed_cls)
                if resp_cls.status_code >= 400:
                    raise SystemExit(
                        f"STOP: HTTP {resp_cls.status_code} from KRA (selectItemClsList / {label})"
                    )
                if gate_err_cls:
                    raise SystemExit(f"STOP: KRA gateway/body error — {gate_err_cls}")
                if result_cls != "000":
                    raise SystemExit(
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
                if b_row:
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
                label="saveItem preflight"
            )
            persist_cls_cd, persist_tax_cd = item_cls_cd, tax_ty_cd
            item_cd_attempt_hw: dict[str, int] = {}
            result_cd: str | None = None
            for attempt in range(4):
                if attempt == 3:
                    item_cd = f"KE1{pkg_unit_cd}TU{alloc_monotonic_item_cd_suffix(f'KE1{pkg_unit_cd}TU', select_item_list_parsed, pin_blob, item_cd_attempt_hw)}"
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
                        "saveItem: attempt 4 — hardcoded Paybill-like body "
                        "(1010160300 Live turkeys / B, itemTy 1, NT+TU, dftPrc 3500, regr Test)"
                    )
                else:
                    if attempt >= 1:
                        print("RETRY: saveItem — refresh selectItemClsList, re-pick class …")
                        item_cls_cd, tax_ty_cd, save_item_ty = load_save_item_classification(
                            label=f"saveItem retry {attempt}"
                        )
                    q_seg = "TU" if save_item_ty == "1" else qty_unit_cd
                    ic_prefix = f"KE{save_item_ty}{pkg_unit_cd}{q_seg}"
                    suf = alloc_monotonic_item_cd_suffix(
                        ic_prefix, select_item_list_parsed, pin_blob, item_cd_attempt_hw
                    )
                    item_cd = f"{ic_prefix}{suf}"
                    print(
                        f"Generated NEW itemCd={item_cd} for saveItem "
                        f"(itemTyCd={save_item_ty}, qtyUnitCd={q_seg}, monotonic suffix from item list/state)"
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
                if attempt != 3:
                    print(f"Using itemClsCd={item_cls_cd}, taxTyCd={tax_ty_cd}")
                print("SAVE ITEM PAYLOAD:")
                print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
                resp = requests.post(url, headers=headers, json=payload, timeout=60)
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
                    save_test_state(state_root)
                    print(f"CONTINUE: {endpoint_name} OK (state={result_cd})")
                    break
                if attempt == 3:
                    print_save_item_http_debug(resp, headers, payload)
                    ge = f", {gate_err}" if gate_err else ""
                    raise SystemExit(
                        f"STOP: saveItem failed after 4 attempts (HTTP={resp.status_code}, "
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
                raise SystemExit(
                    f"STOP: {endpoint_name} requires a saved item_cd from saveItem "
                    f"(see {STATE_FILE.name})."
                )
            save_ty = item_ty_cd
            mo = re.search(r"^KE(\d)", main_ic)
            if mo and mo.group(1).isdigit():
                save_ty = mo.group(1)
            q_seg = "TU" if save_ty == "1" else qty_unit_cd
            try:
                comp_cd = next_item_cd_for_composition_branch(
                    main_ic, select_item_list_parsed
                )
            except ValueError as e:
                raise SystemExit(f"STOP: saveComponentItem — {e}") from e
            icd = item_cls_dynamic["itemClsCd"]
            tty = item_cls_dynamic["taxTyCd"]
            co_payload: dict = {
                "itemCd": comp_cd,
                "itemClsCd": icd,
                "itemTyCd": str(save_ty),
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
            surl = f"{BASE_URL.rstrip('/')}/saveItem"
            print(f"RUNNING {endpoint_name} (POST /saveItem) itemCd={comp_cd}")
            print(json.dumps(co_payload, indent=2, ensure_ascii=False))
            resp_co = requests.post(surl, headers=headers, json=co_payload, timeout=60)
            parsed_co = print_full_response_json(resp_co, "saveComponentItem")
            rc_co = extract_result_cd(parsed_co)
            ge_co = kra_top_level_error_detail(parsed_co)
            ok_co = resp_co.status_code < 400 and not ge_co and rc_co == "000"
            if not ok_co:
                raise SystemExit(
                    f"STOP: saveComponentItem failed HTTP={resp_co.status_code} resultCd={rc_co!r}"
                    + (f", {ge_co}" if ge_co else "")
                )
            pin_blob["component_item_cd"] = comp_cd
            pin_blob.pop("stocked_component_for_composition", None)
            pin_blob.pop("stock_io_component_pending_rsd_qty", None)
            pin_blob.pop("component_stock_balance", None)
            persist_item_cd_suffix_map(pin_blob, comp_cd)
            save_test_state(state_root)
            flush_progress("saveComponentItem", mark_endpoint_complete=True)
            continue

        if endpoint_name == "saveItemComposition":
            ensure_component_stock_before_composition()

        if endpoint_name == "saveStockMasterInitial":
            if not ran_insert_stock_io_initial_this_run:
                raise SystemExit(
                    "STOP: Refusing saveStockMasterInitial — insertStockIOInitial did not run in this "
                    "process (KRA SBX expects both in the same execution). Try:\n"
                    f"  python gavaetims.py <PIN> --force-stock-replay\n"
                    f"  python gavaetims.py <PIN> --reset-stock\n"
                    f"(see {STATE_FILE.name})"
                )
        if endpoint_name == "saveStockMaster":
            if not ran_insert_stock_io_parent_this_run:
                raise SystemExit(
                    "STOP: Refusing saveStockMaster — insertStockIO did not run in this process "
                    f"(pairing required). Check completed_endpoints / replay insert (see {STATE_FILE.name})."
                )

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
        payload = deep_override_keys(deepcopy(payload_template), payload_overrides)

        # Sequence dicts are built before saveItem using a provisional item_cd (random suffix).
        # saveItem then allocates a monotonic itemCd and stores it in pin_blob; sync payloads that
        # still carry the stale template value (SBX: "itemCd … does not exist in your inventory").
        _live_item_cd = (pin_blob.get("item_cd") or item_cd or "").strip()
        if _live_item_cd and endpoint_name in (
            "saveStockMaster",
            "saveStockMasterInitial",
            "insertTrnsPurchase",
            "saveInvoice",
        ):
            item_cd = _live_item_cd
            if endpoint_name in ("saveStockMaster", "saveStockMasterInitial"):
                payload["itemCd"] = _live_item_cd
            elif endpoint_name == "insertTrnsPurchase":
                ilp = payload.get("itemList")
                if isinstance(ilp, list) and ilp and isinstance(ilp[0], dict):
                    ilp[0]["itemCd"] = _live_item_cd
            elif endpoint_name == "saveInvoice":
                il = payload.get("itemList")
                if isinstance(il, list) and il and isinstance(il[0], dict):
                    il[0]["itemCd"] = _live_item_cd

        _canon_ic = (
            pin_blob.get("canonical_item_cd") or pin_blob.get("item_cd") or ""
        ).strip()
        if _canon_ic and isinstance(payload, dict):
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

        if endpoint_name == "saveItemComposition":
            payload.pop("cpstItemCd", None)
            payload["itemCd"] = item_cd
            _cc = (pin_blob.get("component_item_cd") or "").strip()
            if not _cc:
                raise SystemExit(
                    "STOP: saveItemComposition — save component_item_cd first (saveComponentItem step)."
                )
            payload["cpstItemCd"] = _cc

        if endpoint_name == "updateImportItem":
            payload["itemClsCd"] = item_cls_dynamic["itemClsCd"]
            payload["itemCd"] = item_cd
            payload["dclDe"] = (sales_dt or "").strip()[:8]

        if endpoint_name == "insertTrnsPurchase":
            payload["invcNo"] = int(purchase_invc_no)
            ilp = payload.get("itemList")
            if isinstance(ilp, list) and ilp and isinstance(ilp[0], dict):
                ilp[0]["itemClsCd"] = item_cls_dynamic["itemClsCd"]
                ilp[0]["taxTyCd"] = item_cls_dynamic["taxTyCd"]

        if endpoint_name == "selectInvoiceDtl":
            try:
                payload["invcNo"] = int(str(invc_no).strip())
            except (TypeError, ValueError):
                payload["invcNo"] = _invc_base

        if endpoint_name in ("saveStockMaster", "saveStockMasterInitial"):
            try:
                _bal_sm = float(pin_blob.get("current_stock_balance") or 0.0)
            except (TypeError, ValueError):
                _bal_sm = 0.0
            payload["rsdQty"] = _bal_sm
            print(
                f"{endpoint_name}: rsdQty = current_stock_balance (call selectStockMoveList* before this)"
            )
            print(f"{endpoint_name} rsdQty={payload['rsdQty']!r}")
            if endpoint_name == "saveStockMasterInitial" and diagnostic_stock_io_cli:
                print(
                    "\n"
                    + "=" * 78
                    + "\nDIAGNOSTIC saveStockMasterInitial — FULL PAYLOAD (before POST)\n"
                    + "=" * 78
                )
                print(json.dumps(payload, indent=2, ensure_ascii=False))
                print(
                    "=" * 78
                    + "\nExpect rsdQty = 1 when diagnostic reset ran with line qty 1 (balance from 0).\n"
                    "If KRA returns Expected: -1 vs your rsdQty, SBX internal sign may disagree with this balance.\n"
                    + "=" * 78
                    + "\n"
                )

        if endpoint_name == "saveInvoice":
            il = payload.get("itemList")
            if isinstance(il, list) and il and isinstance(il[0], dict):
                il[0]["itemClsCd"] = item_cls_dynamic["itemClsCd"]
                il[0]["taxTyCd"] = item_cls_dynamic["taxTyCd"]

        result_cd: str | None = None
        parsed = None
        resp = None
        apigee_skipped = False
        optional_skip = False
        _cap_attempts = 10 if endpoint_name in _SELECT_STOCK_MOVE_ENDPOINTS else 2
        if endpoint_name == "selectItemListPostSave":
            _cap_attempts = 8
        if endpoint_name == "saveStockMasterInitial":
            _cap_attempts = 1
        elif endpoint_name == "saveStockMaster":
            _cap_attempts = 2
        _req_timeout = 120 if endpoint_name in _SELECT_STOCK_MOVE_ENDPOINTS else 60
        for attempt in range(_cap_attempts):
            if endpoint_name == "selectItemListPostSave":
                payload["lastReqDt"] = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            resp = requests.post(url, headers=headers, json=payload, timeout=_req_timeout)
            parsed = print_full_response_json(resp, endpoint_name)
            result_cd = extract_result_cd(parsed)
            log_api_result_summary(endpoint_name, resp, parsed, result_cd)
            gate_err = kra_top_level_error_detail(parsed)
            if (
                not gate_err
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
                    raise SystemExit(
                        "STOP: selectItemListPostSave — catalog has no saved itemCd "
                        f"{item_cd!r} (GavaConnect expects LOOK UP PRODUCT LIST to return the item after "
                        "saveItem). Check branch/tin and SBX latency."
                    )
                break
            _last_att = attempt >= _cap_attempts - 1
            if _last_att:
                if endpoint_name == "saveStockMasterInitial":
                    parts_sm_i = [
                        "STOP: saveStockMasterInitial failed after retry",
                        f"HTTP={resp.status_code}",
                        f"resultCd={result_cd!r}",
                    ]
                    if gate_err:
                        parts_sm_i.append(str(gate_err))
                    parts_sm_i.append(
                        "State preserved (insertStockIOInitial, SAR, pending). Rerun to retry save only."
                    )
                    raise SystemExit(" | ".join(parts_sm_i))
                if (
                    endpoint_name in SOFT_SKIP_APIGEE_TARGET_PATH
                    and apigee_unresolved_target_path_fault(parsed)
                ):
                    apigee_skipped = True
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
                parts = [
                    f"STOP: {endpoint_name} failed after retry",
                    f"HTTP={resp.status_code}",
                    f"resultCd={result_cd!r}",
                ]
                if gate_err:
                    parts.append(str(gate_err))
                if endpoint_name in ("saveStockMaster", "saveStockMasterInitial"):
                    parts.append(
                        "SBX may have stacked unreconciled stock IOs: reset stock/SAR on the OSCU portal "
                        "for this PIN, then run: python gavaetims.py <PIN> --reset-stock"
                    )
                raise SystemExit(" | ".join(parts))
            if endpoint_name in _SELECT_STOCK_MOVE_ENDPOINTS and getattr(resp, "status_code", 0) == 504:
                _504_wait = min(60, 12 * (attempt + 1))
                print(
                    f"RETRY: {endpoint_name} (504 Gateway Timeout, waiting {_504_wait}s, "
                    f"attempt {attempt + 1}/{_cap_attempts}) …"
                )
                time.sleep(_504_wait)
            else:
                print(
                    f"RETRY: {endpoint_name} (HTTP={resp.status_code}, resultCd={result_cd!r}) …"
                )

        if apigee_skipped:
            flush_progress(endpoint_name, mark_endpoint_complete=False)
            continue
        if optional_skip:
            flush_progress(endpoint_name, mark_endpoint_complete=False)
            continue

        if (
            endpoint_name in _SELECT_STOCK_MOVE_ENDPOINTS
            and (result_cd or "").strip() == "001"
            and isinstance(parsed, dict)
        ):
            surl = f"{BASE_URL.rstrip('/')}/selectStockMoveList"
            pl_now = {
                "tin": effective_tin,
                "bhfId": branch_id,
                "lastReqDt": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
            }
            print(
                f"RUNNING {endpoint_name} (lastReqDt=UTC-now — SBX often returns 001 for baseline "
                "20100101 right after insertStockIO; retrying for current moves.)"
            )
            for _sm_now_attempt in range(8):
                pl_now["lastReqDt"] = datetime.now(timezone.utc).strftime(
                    "%Y%m%d%H%M%S"
                )
                resp_n = requests.post(
                    surl, headers=headers, json=pl_now, timeout=120
                )
                parsed_n = print_full_response_json(
                    resp_n, "selectStockMoveList / lastReqDt=now"
                )
                if getattr(resp_n, "status_code", 0) == 504:
                    w = min(60, 10 * (_sm_now_attempt + 1))
                    print(
                        "RETRY: selectStockMoveList / lastReqDt=now "
                        f"(504 Gateway Timeout, waiting {w}s, "
                        f"attempt {_sm_now_attempt + 1}/8) …"
                    )
                    time.sleep(w)
                    continue
                rc_n = extract_result_cd(parsed_n)
                ge_n = kra_top_level_error_detail(parsed_n)
                if (
                    resp_n.status_code < 500
                    and not ge_n
                    and endpoint_accepts_result_cd(endpoint_name, rc_n)
                    and endpoint_http_ok_for_kra(endpoint_name, resp_n, rc_n)
                ):
                    parsed = parsed_n
                    result_cd = rc_n
                    resp = resp_n
                break

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
            if not response_contains_item_cd(parsed, item_cd):
                print(
                    f"NOTE: {endpoint_name} has no itemCd={item_cd} in this response "
                    "(SBX can still proceed to saveStockMaster*)."
                )

        if endpoint_name == "selectItemClsList":
            apply_item_cls_dynamic_from_parsed(parsed, item_cls_dynamic)
            icd = item_cls_dynamic["itemClsCd"]
            tty = item_cls_dynamic["taxTyCd"]
            print(f"EXTRACTED itemClsCd={icd} taxTyCd={tty}")

        if endpoint_name in ("saveStockMaster", "saveStockMasterInitial"):
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
        if endpoint_name in ("saveStockMaster", "saveStockMasterInitial") and endpoint_accepts_result_cd(
            endpoint_name, result_cd
        ):
            pin_blob["stock_io_pending_rsd_qty"] = 0.0
            save_test_state(state_root)

    print("\nDONE: validation sequence completed successfully.")
    try:
        persist(rows, entry)
        print(f"Saved profile state to {CSV_FILE.name}.")
    except OSError as e:
        print(f"Note: could not write {CSV_FILE.name}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
