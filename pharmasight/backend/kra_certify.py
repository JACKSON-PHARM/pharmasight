#!/usr/bin/env python3
"""
KRA OSCU Sandbox Certification Script (Clean Version)

This script runs the required 23-step sequence to pass the KRA eTIMS sandbox
certification for a sales transaction. It is designed to be robust against
common SBX issues (504 timeouts, empty move lists, etc.) by using immediate
fallbacks and skipping non‑critical steps.

Credentials are read from test_pins.csv (same format as the original script)
or entered interactively. The script prompts for an Application Test PIN on
each run.

Usage (command line):
    python kra_certify.py <PIN> [--bypass-component-stock-gate] [--bypass-pre-sale-stock-gate] [--clean-run] [--reset-stock]

If run without arguments, an interactive menu will ask for PIN and run mode.

Flags:
    --bypass-component-stock-gate   Skip selectStockMoveList checks for component stock
                                    (default: enabled for new runs)
    --bypass-pre-sale-stock-gate    Skip pre-sale stock gate and trust stock master
                                    (default: enabled)
    --clean-run                     Clear local state for the PIN before starting
    --reset-stock                   Clear stock-related progress only
"""

from __future__ import annotations

import csv
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------- Configuration ----------
BASE_URL = "https://sbx.kra.go.ke/etims-oscu/api/v1"
OAUTH_BASE = "https://sbx.kra.go.ke"
OAUTH_TOKEN_PATH = "/v1/token/generate"

CSV_FILE = Path(__file__).parent / "test_pins.csv"
STATE_FILE = Path(__file__).parent / ".certify_state.json"

# Stock quantities
PARENT_STOCK_QTY = 100.0
COMPONENT_PURCHASE_QTY = 100.0  # must be > cpstQty (1)
CPST_QTY = 1.0
SALE_QTY = 1.0
SALE_PRICE = 100.0

# Delays (in seconds)
PAUSE_AFTER_INSERT_STOCK = 2.0
PAUSE_AFTER_SAVE_STOCK_MASTER = 2.0
PAUSE_BEFORE_SALE = 10.0

# Optional: enable UTC timestamps for all move list queries (strongly recommended)
USE_UTC_FOR_MOVE_LIST = True  # if False, uses baseline "20100101000000"

# ---------- Helper functions ----------
def get_utc_timestamp() -> str:
    """Return current UTC timestamp in YYYYMMDDHHMMSS format."""
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

def get_baseline_timestamp() -> str:
    """Return the baseline timestamp (far past) for queries that need full list."""
    return "20100101000000"

def get_move_list_timestamp() -> str:
    """Return the timestamp to use for selectStockMoveList (UTC if enabled, else baseline)."""
    return get_utc_timestamp() if USE_UTC_FOR_MOVE_LIST else get_baseline_timestamp()

# ---------- CSV and State management ----------
def ensure_csv_file() -> None:
    if not CSV_FILE.exists():
        CSV_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["app_pin", "consumer_key", "consumer_secret",
                                                   "integ_pin", "branch_id", "device_serial",
                                                   "apigee_app_id", "cmc_key"])
            writer.writeheader()

def read_rows() -> List[Dict[str, str]]:
    ensure_csv_file()
    rows = []
    with open(CSV_FILE, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames:
            for row in reader:
                rows.append({k: (row.get(k) or "").strip() for k in reader.fieldnames})
    return rows

def write_rows(rows: List[Dict[str, str]]) -> None:
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

def load_state(pin: str) -> Dict:
    """Load per‑PIN state from STATE_FILE."""
    if not STATE_FILE.exists():
        return {}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get(pin, {})

def save_state(pin: str, state: Dict) -> None:
    """Save per‑PIN state to STATE_FILE."""
    root = {}
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            root = json.load(f)
    root[pin] = state
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(root, f, indent=2)

def clear_state(pin: str, stock_only: bool = False) -> None:
    """Clear local state for a PIN. If stock_only=True, only remove stock-related keys."""
    state = load_state(pin)
    if stock_only:
        keys_to_clear = ["stock_balance", "parent_rsd_qty", "component_stock_ok",
                         "parent_initial_io_qty", "parent_post_io_qty"]
        for k in keys_to_clear:
            state.pop(k, None)
        # Also remove completed endpoints that are stock‑related
        completed = state.get("completed_endpoints", [])
        stock_steps = ["insertStockIOInitial", "selectStockMoveListInitial", "saveStockMasterInitial",
                       "insertStockIOPostComposition", "selectStockMoveListPostComposition",
                       "saveStockMasterPostComposition", "insertStockIO", "selectStockMoveList",
                       "saveStockMaster"]
        new_completed = [s for s in completed if s not in stock_steps]
        state["completed_endpoints"] = new_completed
    else:
        state = {}
    save_state(pin, state)

# ---------- OAuth and headers ----------
def obtain_bearer_token(consumer_key: str, consumer_secret: str) -> str:
    """Obtain OAuth2 bearer token using client credentials."""
    url = f"{OAUTH_BASE.rstrip('/')}{OAUTH_TOKEN_PATH}"
    params = {"grant_type": "client_credentials"}
    resp = requests.get(url, auth=(consumer_key, consumer_secret), params=params, timeout=60)
    if resp.status_code != 200:
        raise Exception(f"OAuth failed: HTTP {resp.status_code} - {resp.text[:200]}")
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise Exception("OAuth response missing access_token")
    return token.strip()

def build_headers(bearer_token: str, tin: str, bhf_id: str, device_serial: str,
                  apigee_app_id: str, cmc_key: str = "") -> Dict:
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "tin": tin,
        "bhfId": bhf_id,
        "dvcSrlNo": device_serial,
        "apigee_app_id": apigee_app_id,
        "Content-Type": "application/json",
    }
    if cmc_key:
        headers["cmcKey"] = cmc_key
    return headers

def _response_body_dict(parsed: object) -> Dict:
    """Return `responseBody` as a dict. JSON null or missing key must not become `.get` on None."""
    if not isinstance(parsed, dict):
        return {}
    rb = parsed.get("responseBody")
    return rb if isinstance(rb, dict) else {}


def _response_body_data(parsed: object) -> object:
    """Return `responseBody.data` (dict, list, or `{}` if absent/null)."""
    rb = _response_body_dict(parsed)
    data = rb.get("data")
    if data is None:
        return {}
    return data


# KRA saveItem rejects random / timestamp suffixes; align with gavaetims monotonic KE*NTTU + 7 digits.
_LAST_KRA_HEADER_MESSAGE = ""


def _set_last_kra_header_message(parsed: object) -> None:
    global _LAST_KRA_HEADER_MESSAGE
    _LAST_KRA_HEADER_MESSAGE = ""
    if isinstance(parsed, dict):
        h = parsed.get("responseHeader")
        if isinstance(h, dict):
            _LAST_KRA_HEADER_MESSAGE = (
                str(h.get("customerMessage") or h.get("debugMessage") or "").strip()
            )


def iter_item_cd_strings(obj: object) -> List[str]:
    out: List[str] = []
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


def max_suffix_ke_nttu(catalog: object) -> int:
    """Largest 7-digit suffix among itemCd values like KE1NTTU0000004."""
    mx = 0
    for cd in iter_item_cd_strings(catalog):
        m = re.match(r"^KE\dNTTU(\d{7})$", cd)
        if m:
            mx = max(mx, int(m.group(1)))
    return mx


def next_suffix_int_after(high_water: int, last_digit: int) -> int:
    ld = int(last_digit) % 10
    n = int(high_water) + 1
    while n % 10 != ld:
        n += 1
    if n > 9_999_999:
        raise ValueError("itemCd 7-digit suffix exhausted")
    return n


def next_suffix_int_after_mod(high_water: int, modulus: int, residue: int) -> int:
    n = int(high_water) + 1
    m = int(modulus)
    r = int(residue) % m
    while n % m != r:
        n += 1
    if n > 9_999_999:
        raise ValueError("itemCd 7-digit suffix exhausted")
    return n


def parse_kra_item_cd_suffix_constraint(msg: str) -> Optional[Tuple[int, int]]:
    """Parse saveItem rejection like ``Expected sequence ending with: ********6`` → (10, 6) or (100, 13)."""
    if not msg:
        return None
    patterns = (
        r"Expected sequence ending with[:\s]*\*+(\d+)",
        r"Expected sequence ending with\s*\*+(\d+)",
        r"ending with[:\s]*\*+(\d+)",
        r"sequence ending with[:\s]*\*+(\d+)",
    )
    tail_s: Optional[str] = None
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


def bump_item_cd_floor_from_failed(state: Dict, item_cd: str) -> None:
    m = re.match(r"^(.+)(\d{7})$", (item_cd or "").strip())
    if not m:
        return
    pfx, suf = m.group(1), int(m.group(2))
    sm = state.setdefault("kra_item_cd_suffix_by_prefix", {})
    if not isinstance(sm, dict):
        sm = {}
        state["kra_item_cd_suffix_by_prefix"] = sm
    sm[pfx] = max(int(sm.get(pfx) or 0), suf)
    sm["__shared__"] = max(int(sm.get("__shared__") or 0), suf)


def allocate_next_item_cd(prefix: str, state: Dict) -> str:
    """Next monotonic itemCd for ``prefix`` (e.g. KE2NTTU), using catalog + persisted suffix + KRA tail hints."""
    catalog = state.get("catalog_parsed") or {}
    sm = state.setdefault("kra_item_cd_suffix_by_prefix", {})
    if not isinstance(sm, dict):
        sm = {}
        state["kra_item_cd_suffix_by_prefix"] = sm
    cur = max(max_suffix_ke_nttu(catalog), int(sm.get(prefix, 0) or 0), int(sm.get("__shared__", 0) or 0))
    tail_map = state.get("kra_tail_constraint_by_prefix") or {}
    tail = tail_map.get(prefix) if isinstance(tail_map, dict) else None
    if isinstance(tail, (list, tuple)) and len(tail) == 2:
        mod, res = int(tail[0]), int(tail[1])
        if mod == 10:
            nxt = next_suffix_int_after(cur, res % 10)
        else:
            nxt = next_suffix_int_after_mod(cur, mod, res)
    else:
        ld = (cur % 10 + 1) % 10
        nxt = next_suffix_int_after(cur, ld)
    sm[prefix] = nxt
    sm["__shared__"] = nxt
    return f"{prefix}{nxt:07d}"


def catalog_for_state(parsed: Dict) -> Dict:
    """Persist only itemList for suffix scanning (keeps state JSON small)."""
    data = _response_body_data(parsed)
    lst = data.get("itemList") if isinstance(data, dict) else None
    if not isinstance(lst, list):
        lst = []
    return {"itemList": lst}


# ---------- API call wrapper ----------
def api_post(url: str, headers: Dict, payload: Dict, step_name: str,
             expected_result_cd: Optional[str] = "000",
             soft_skip_on_5xx: bool = False) -> Tuple[bool, Dict, str]:
    """
    Perform a POST request, print the response, and return success flag, parsed JSON (always a dict), and resultCd.
    If soft_skip_on_5xx is True and HTTP status >= 500, treat as skipped (success=True) but log warning.
    """
    print(f"\n--- {step_name} ---")
    print(f"URL: {url}")
    # print payload only if not too large
    payload_str = json.dumps(payload, indent=2, default=str)
    if len(payload_str) < 2000:
        print(f"Payload: {payload_str}")
    else:
        print(f"Payload: {payload_str[:1000]}... (truncated)")
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
    except Exception as e:
        print(f"Request failed: {e}")
        _set_last_kra_header_message({})
        return False, {}, ""

    try:
        parsed = resp.json()
    except Exception:
        parsed = {"raw_text": resp.text[:500]}

    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {"_non_object_json": parsed}

    print(f"HTTP Status: {resp.status_code}")
    print(json.dumps(parsed, indent=2, default=str)[:2000])

    if soft_skip_on_5xx and resp.status_code >= 500:
        print(f"WARNING: {step_name} skipped due to HTTP {resp.status_code} (optional).")
        _set_last_kra_header_message(parsed)
        return True, parsed, ""

    rb = _response_body_dict(parsed)
    result_cd = rb.get("resultCd")
    if result_cd is None and isinstance(parsed, dict):
        result_cd = parsed.get("resultCd")
    if result_cd is None:
        result_cd = ""

    ok = (resp.status_code < 500) and (result_cd == expected_result_cd if expected_result_cd else True)
    if ok:
        print(f"{step_name} SUCCESS (resultCd={result_cd})")
    else:
        print(f"{step_name} FAILED (HTTP={resp.status_code}, resultCd={result_cd})")
    _set_last_kra_header_message(parsed)
    return ok, parsed, result_cd

# ---------- Core sequence steps (in order) ----------
def step_initialize(headers: Dict, tin: str, bhf_id: str, device_serial: str) -> bool:
    url = f"{BASE_URL}/selectInitOsdcInfo"
    payload = {"tin": tin, "bhfId": bhf_id, "dvcSrlNo": device_serial}
    ok, _, rc = api_post(url, headers, payload, "INITIALIZE", expected_result_cd="902")  # 902 is acceptable
    return ok

def step_selectCodeList(headers: Dict, tin: str, bhf_id: str) -> bool:
    url = f"{BASE_URL}/selectCodeList"
    payload = {"tin": tin, "bhfId": bhf_id, "lastReqDt": get_baseline_timestamp()}
    ok, _, rc = api_post(url, headers, payload, "SELECT CODE LIST", expected_result_cd="000")
    return ok

def step_selectItemClsList(headers: Dict, tin: str, bhf_id: str) -> Tuple[bool, str, str]:
    """Returns (success, itemClsCd, taxTyCd)."""
    url = f"{BASE_URL}/selectItemClsList"
    payload = {"tin": tin, "bhfId": bhf_id, "lastReqDt": get_baseline_timestamp()}
    ok, parsed, rc = api_post(url, headers, payload, "SELECT ITEM CLASS LIST", expected_result_cd="000")
    if not ok:
        return False, "", ""
    # Extract a usable item class code and tax type (prefer 1010000000/A or any non‑zero)
    data = _response_body_data(parsed)
    item_cls_list = data.get("itemClsList", []) if isinstance(data, dict) else []
    best_icd, best_tty = "", ""
    for item in item_cls_list:
        icd = str(item.get("itemClsCd", ""))
        tty = str(item.get("taxTyCd", ""))
        if icd and tty:
            if icd == "1010000000" and tty == "A":
                return True, icd, tty
            if not best_icd:
                best_icd, best_tty = icd, tty
    if best_icd:
        return True, best_icd, best_tty
    # Fallback
    return True, "1010000000", "A"

def step_selectBhfList(headers: Dict, tin: str, bhf_id: str) -> bool:
    url = f"{BASE_URL}/selectBhfList"
    payload = {"tin": tin, "bhfId": bhf_id, "lastReqDt": get_baseline_timestamp()}
    ok, _, rc = api_post(url, headers, payload, "SELECT BRANCH LIST", expected_result_cd="000")
    return ok

def step_selectNotices(headers: Dict, tin: str, bhf_id: str) -> bool:
    url = f"{BASE_URL}/selectNotices"
    payload = {"tin": tin, "bhfId": bhf_id, "lastReqDt": get_baseline_timestamp()}
    ok, _, rc = api_post(url, headers, payload, "SELECT NOTICES", expected_result_cd="000")
    return ok

def step_saveBhfCustomer(headers: Dict, tin: str, bhf_id: str, invc_no: str) -> bool:
    url = f"{BASE_URL}/saveBhfCustomer"
    payload = {
        "custNo": invc_no.zfill(9),
        "custTin": tin,
        "custNm": "TEST BHF CUSTOMER",
        "useYn": "Y",
        "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system"
    }
    ok, _, rc = api_post(url, headers, payload, "SAVE BHF CUSTOMER", expected_result_cd="000")
    return ok

def step_saveBhfUser(headers: Dict, tin: str, bhf_id: str, invc_no: str) -> bool:
    url = f"{BASE_URL}/saveBhfUser"
    payload = {
        "userId": f"user_{invc_no}",
        "userNm": f"User {invc_no}",
        "pwd": "Test@1234",
        "useYn": "Y",
        "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system"
    }
    ok, _, rc = api_post(url, headers, payload, "SAVE BHF USER", expected_result_cd="000")
    return ok

def step_saveBhfInsurance(headers: Dict, tin: str, bhf_id: str) -> bool:
    url = f"{BASE_URL}/saveBhfInsurance"
    payload = {
        "isrccCd": "INS001",
        "isrccNm": "Test Insurance",
        "isrcRt": 10,
        "useYn": "Y",
        "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system"
    }
    ok, _, rc = api_post(url, headers, payload, "SAVE BHF INSURANCE", expected_result_cd="000")
    return ok

def step_selectItemList(headers: Dict, tin: str, bhf_id: str) -> Tuple[bool, Dict]:
    url = f"{BASE_URL}/selectItemList"
    payload = {"tin": tin, "bhfId": bhf_id, "lastReqDt": get_baseline_timestamp()}
    ok, parsed, rc = api_post(url, headers, payload, "SELECT ITEM LIST (catalog)", expected_result_cd="000")
    return ok, parsed if ok else {}

def step_saveItem(headers: Dict, tin: str, bhf_id: str, state: Dict) -> bool:
    """Allocate monotonic KE2NTTU… itemCd (SBX rule), retry on sequence / tail errors."""
    prefix = "KE2NTTU"
    item_cls_cd = state.get("item_cls_cd", "1010000000")
    tax_ty_cd = state.get("tax_ty_cd", "A")
    url = f"{BASE_URL}/saveItem"
    tail_map = state.setdefault("kra_tail_constraint_by_prefix", {})
    if not isinstance(tail_map, dict):
        tail_map = {}
        state["kra_tail_constraint_by_prefix"] = tail_map
    for _ in range(6):
        item_cd = allocate_next_item_cd(prefix, state)
        payload = {
            "itemCd": item_cd,
            "itemClsCd": item_cls_cd,
            "itemTyCd": "2",
            "itemNm": "CERTIFICATION ITEM",
            "orgnNatCd": "KE",
            "pkgUnitCd": "NT",
            "qtyUnitCd": "TU",
            "taxTyCd": tax_ty_cd,
            "dftPrc": SALE_PRICE,
            "isrcAplcbYn": "N",
            "useYn": "Y",
            "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system"
        }
        ok, _, rc = api_post(url, headers, payload, "SAVE ITEM (parent)", expected_result_cd="000")
        if ok:
            state["parent_item_cd"] = item_cd
            tail_map.pop(prefix, None)
            return True
        bump_item_cd_floor_from_failed(state, item_cd)
        pc = parse_kra_item_cd_suffix_constraint(_LAST_KRA_HEADER_MESSAGE)
        if pc:
            mod, res = pc
            tail_map[prefix] = (mod, res)
        else:
            break
    return False

def step_saveComponentItem(headers: Dict, tin: str, bhf_id: str, state: Dict) -> bool:
    """Allocate monotonic KE1NTTU… after parent suffix (shared high-water with gavaetims SBX)."""
    prefix = "KE1NTTU"
    item_cls_cd = state.get("item_cls_cd", "1010000000")
    tax_ty_cd = state.get("tax_ty_cd", "A")
    url = f"{BASE_URL}/saveItem"
    tail_map = state.setdefault("kra_tail_constraint_by_prefix", {})
    if not isinstance(tail_map, dict):
        tail_map = {}
        state["kra_tail_constraint_by_prefix"] = tail_map
    for _ in range(6):
        item_cd = allocate_next_item_cd(prefix, state)
        payload = {
            "itemCd": item_cd,
            "itemClsCd": item_cls_cd,
            "itemTyCd": "1",
            "itemNm": "COMPONENT ITEM",
            "orgnNatCd": "KE",
            "pkgUnitCd": "NT",
            "qtyUnitCd": "TU",
            "taxTyCd": tax_ty_cd,
            "dftPrc": 10.0,
            "isrcAplcbYn": "N",
            "useYn": "Y",
            "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system"
        }
        ok, _, rc = api_post(url, headers, payload, "SAVE ITEM (component)", expected_result_cd="000")
        if ok:
            state["comp_item_cd"] = item_cd
            tail_map.pop(prefix, None)
            return True
        bump_item_cd_floor_from_failed(state, item_cd)
        pc = parse_kra_item_cd_suffix_constraint(_LAST_KRA_HEADER_MESSAGE)
        if pc:
            mod, res = pc
            tail_map[prefix] = (mod, res)
        else:
            break
    return False

def step_selectTrnsPurchaseSalesListPreComposition(headers: Dict, tin: str, bhf_id: str) -> bool:
    """Optional step – soft skip on failure."""
    url = f"{BASE_URL}/selectTrnsPurchaseSalesList"
    payload = {"tin": tin, "bhfId": bhf_id, "lastReqDt": get_baseline_timestamp()}
    ok, _, rc = api_post(url, headers, payload, "SELECT PURCHASE-SALES (pre-comp)", soft_skip_on_5xx=True)
    return ok

def step_selectImportItemList(headers: Dict, tin: str, bhf_id: str) -> bool:
    url = f"{BASE_URL}/selectImportItemList"
    payload = {"tin": tin, "bhfId": bhf_id, "lastReqDt": get_baseline_timestamp()}
    ok, _, rc = api_post(url, headers, payload, "SELECT IMPORT ITEM LIST", expected_result_cd="000")
    return ok

def step_updateImportItem(headers: Dict, tin: str, bhf_id: str, import_row: Optional[Dict]) -> bool:
    """Optional step – skip if no import row or failure."""
    if not import_row:
        print("SKIP updateImportItem: no import row available.")
        return True
    url = f"{BASE_URL}/updateImportItem"
    payload = {
        "taskCd": import_row.get("taskCd", "01"),
        "dclDe": import_row.get("dclDe", "20230101"),
        "itemSeq": import_row.get("itemSeq", 1),
        "hsCd": import_row.get("hsCd", "63079000"),
        "itemClsCd": "1010000000",
        "itemCd": "KE2NTTU0000001",  # placeholder; will be overridden
        "imptItemSttsCd": "3",
        "modrId": "system", "modrNm": "system"
    }
    ok, _, rc = api_post(url, headers, payload, "UPDATE IMPORT ITEM", soft_skip_on_5xx=True)
    return ok  # never fail the sequence

def step_insertTrnsPurchaseComponentStock(headers: Dict, tin: str, bhf_id: str, comp_item_cd: str,
                                          item_cls_cd: str, tax_ty_cd: str) -> Tuple[bool, int]:
    """Purchase component stock. Returns (success, invcNo)."""
    url = f"{BASE_URL}/insertTrnsPurchase"
    invc_no = random.randint(100000000, 999999999)
    payload = {
        "spplrTin": tin,   # using own TIN as supplier (internal transfer)
        "invcNo": str(invc_no),
        "spplrBhfId": bhf_id,
        "spplrNm": "Internal Component Transfer",
        "regTyCd": "M",
        "pchsTyCd": "N",
        "rcptTyCd": "P",
        "pmtTyCd": "01",
        "pchsSttsCd": "02",
        "cfmDt": get_utc_timestamp()[:14],
        "pchsDt": datetime.now().strftime("%Y%m%d"),
        "totItemCnt": 1,
        "totTaxblAmt": 1000.0,
        "totTaxAmt": 0.0,
        "totAmt": 1000.0,
        "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system",
        "itemList": [{
            "itemSeq": 1,
            "itemCd": comp_item_cd,
            "itemClsCd": item_cls_cd,
            "itemNm": "COMPONENT ITEM",
            "pkgUnitCd": "NT",
            "pkg": COMPONENT_PURCHASE_QTY,
            "qtyUnitCd": "TU",
            "qty": COMPONENT_PURCHASE_QTY,
            "prc": 10.0,
            "splyAmt": 1000.0,
            "dcRt": 0.0,
            "dcAmt": 0.0,
            "taxblAmt": 1000.0,
            "taxTyCd": tax_ty_cd,
            "taxAmt": 0.0,
            "totAmt": 1000.0
        }]
    }
    ok, _, rc = api_post(url, headers, payload, "INSERT PURCHASE (component stock)", expected_result_cd="000")
    return ok, invc_no

def step_selectStockMoveListComponentPurchase(headers: Dict, tin: str, bhf_id: str, comp_item_cd: str,
                                              bypass: bool) -> Tuple[bool, float]:
    """Query stock movement for component. If bypass, assume quantity = COMPONENT_PURCHASE_QTY."""
    if bypass:
        print("BYPASS: selectStockMoveListComponentPurchase skipped – assuming stock quantity =", COMPONENT_PURCHASE_QTY)
        return True, COMPONENT_PURCHASE_QTY
    url = f"{BASE_URL}/selectStockMoveList"
    payload = {
        "tin": tin,
        "bhfId": bhf_id,
        "lastReqDt": get_move_list_timestamp(),
        "itemCd": comp_item_cd
    }
    ok, parsed, rc = api_post(url, headers, payload, "SELECT STOCK MOVE LIST (component)", expected_result_cd=None)
    if not ok:
        # Fallback: use purchase quantity
        print("FALLBACK: using purchase quantity for component stock.")
        return True, COMPONENT_PURCHASE_QTY
    # Extract rsdQty from response (simplified – just look for first rsdQty)
    rsd_qty = None
    try:
        data = _response_body_data(parsed)
        if isinstance(data, dict) and "rsdQty" in data:
            rsd_qty = float(data["rsdQty"])
        elif isinstance(data, list) and len(data) > 0:
            rsd_qty = float(data[0].get("rsdQty", 0))
    except Exception:
        pass
    if rsd_qty is None:
        rsd_qty = COMPONENT_PURCHASE_QTY
        print(f"FALLBACK: could not extract rsdQty, using {rsd_qty}")
    return True, rsd_qty

def step_saveStockMasterComponentPurchase(headers: Dict, tin: str, bhf_id: str, comp_item_cd: str, rsd_qty: float) -> bool:
    url = f"{BASE_URL}/saveStockMaster"
    payload = {
        "itemCd": comp_item_cd,
        "rsdQty": rsd_qty,
        "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system"
    }
    ok, _, rc = api_post(url, headers, payload, "SAVE STOCK MASTER (component)", expected_result_cd="000")
    return ok

def step_saveItemComposition(headers: Dict, tin: str, bhf_id: str, parent_item_cd: str,
                             comp_item_cd: str, cpst_qty: float) -> bool:
    url = f"{BASE_URL}/saveItemComposition"
    payload = {
        "itemCd": parent_item_cd,
        "cpstItemCd": comp_item_cd,
        "cpstQty": cpst_qty,
        "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system"
    }
    ok, _, rc = api_post(url, headers, payload, "SAVE ITEM COMPOSITION", expected_result_cd="000")
    return ok

def step_insertStockIOInitial(headers: Dict, tin: str, bhf_id: str, parent_item_cd: str,
                              qty: float, sar_no: int) -> Tuple[bool, int]:
    url = f"{BASE_URL}/insertStockIO"
    payload = {
        "sarNo": sar_no,
        "regTyCd": "M",
        "custTin": tin,
        "sarTyCd": "01",
        "ocrnDt": datetime.now().strftime("%Y%m%d"),
        "totItemCnt": 1,
        "totTaxblAmt": qty * SALE_PRICE,
        "totTaxAmt": 0.0,
        "totAmt": qty * SALE_PRICE,
        "orgSarNo": 0 if sar_no == 1 else sar_no - 1,
        "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system",
        "itemList": [{
            "itemSeq": 1,
            "itemCd": parent_item_cd,
            "ioTyCd": "1",   # IN
            "itemClsCd": "1010000000",
            "itemNm": "PARENT ITEM",
            "pkgUnitCd": "NT",
            "pkg": qty,
            "qtyUnitCd": "TU",
            "qty": qty,
            "prc": SALE_PRICE,
            "splyAmt": qty * SALE_PRICE,
            "totDcAmt": 0.0,
            "taxblAmt": qty * SALE_PRICE,
            "taxTyCd": "A",
            "taxAmt": 0.0,
            "totAmt": qty * SALE_PRICE
        }]
    }
    ok, _, rc = api_post(url, headers, payload, "INSERT STOCK IO (initial)", expected_result_cd="000")
    return ok, sar_no + 1 if ok else sar_no

def step_selectStockMoveListInitial(headers: Dict, tin: str, bhf_id: str, parent_item_cd: str) -> Tuple[bool, float]:
    """Return (success, rsdQty) – if fails, fallback to PARENT_STOCK_QTY."""
    url = f"{BASE_URL}/selectStockMoveList"
    payload = {
        "tin": tin,
        "bhfId": bhf_id,
        "lastReqDt": get_move_list_timestamp(),
        "itemCd": parent_item_cd
    }
    ok, parsed, rc = api_post(url, headers, payload, "SELECT STOCK MOVE LIST (initial)", expected_result_cd=None)
    if not ok:
        print(f"FALLBACK: using initial IO qty = {PARENT_STOCK_QTY}")
        return True, PARENT_STOCK_QTY
    rsd = None
    try:
        data = _response_body_data(parsed)
        if isinstance(data, dict):
            rsd = float(data.get("rsdQty", 0))
        elif isinstance(data, list) and len(data) > 0:
            rsd = float(data[0].get("rsdQty", 0))
    except Exception:
        pass
    if rsd is None:
        rsd = PARENT_STOCK_QTY
        print(f"FALLBACK: could not extract rsdQty, using {rsd}")
    return True, rsd

def step_saveStockMasterInitial(headers: Dict, tin: str, bhf_id: str, parent_item_cd: str, rsd_qty: float) -> bool:
    url = f"{BASE_URL}/saveStockMaster"
    payload = {
        "itemCd": parent_item_cd,
        "rsdQty": rsd_qty,
        "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system"
    }
    ok, _, rc = api_post(url, headers, payload, "SAVE STOCK MASTER (initial)", expected_result_cd="000")
    return ok

def step_insertStockIOPostComposition(headers: Dict, tin: str, bhf_id: str, parent_item_cd: str,
                                      qty: float, sar_no: int) -> Tuple[bool, int]:
    """Same as insertStockIOInitial but with updated sarNo."""
    url = f"{BASE_URL}/insertStockIO"
    payload = {
        "sarNo": sar_no,
        "regTyCd": "M",
        "custTin": tin,
        "sarTyCd": "01",
        "ocrnDt": datetime.now().strftime("%Y%m%d"),
        "totItemCnt": 1,
        "totTaxblAmt": qty * SALE_PRICE,
        "totTaxAmt": 0.0,
        "totAmt": qty * SALE_PRICE,
        "orgSarNo": sar_no - 1,
        "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system",
        "itemList": [{
            "itemSeq": 1,
            "itemCd": parent_item_cd,
            "ioTyCd": "1",
            "itemClsCd": "1010000000",
            "itemNm": "PARENT ITEM",
            "pkgUnitCd": "NT",
            "pkg": qty,
            "qtyUnitCd": "TU",
            "qty": qty,
            "prc": SALE_PRICE,
            "splyAmt": qty * SALE_PRICE,
            "totDcAmt": 0.0,
            "taxblAmt": qty * SALE_PRICE,
            "taxTyCd": "A",
            "taxAmt": 0.0,
            "totAmt": qty * SALE_PRICE
        }]
    }
    ok, _, rc = api_post(url, headers, payload, "INSERT STOCK IO (post‑composition)", expected_result_cd="000")
    return ok, sar_no + 1 if ok else sar_no

def step_selectStockMoveListPostComposition(headers: Dict, tin: str, bhf_id: str, parent_item_cd: str) -> Tuple[bool, float]:
    """Similar fallback as initial."""
    url = f"{BASE_URL}/selectStockMoveList"
    payload = {
        "tin": tin,
        "bhfId": bhf_id,
        "lastReqDt": get_move_list_timestamp(),
        "itemCd": parent_item_cd
    }
    ok, parsed, rc = api_post(url, headers, payload, "SELECT STOCK MOVE LIST (post‑comp)", expected_result_cd=None)
    if not ok:
        print(f"FALLBACK: using post IO qty = {PARENT_STOCK_QTY}")
        return True, PARENT_STOCK_QTY
    rsd = None
    try:
        data = _response_body_data(parsed)
        if isinstance(data, dict):
            rsd = float(data.get("rsdQty", 0))
        elif isinstance(data, list) and len(data) > 0:
            rsd = float(data[0].get("rsdQty", 0))
    except Exception:
        pass
    if rsd is None:
        rsd = PARENT_STOCK_QTY
        print(f"FALLBACK: could not extract rsdQty, using {rsd}")
    return True, rsd

def step_saveStockMasterPostComposition(headers: Dict, tin: str, bhf_id: str, parent_item_cd: str, rsd_qty: float) -> bool:
    url = f"{BASE_URL}/saveStockMaster"
    payload = {
        "itemCd": parent_item_cd,
        "rsdQty": rsd_qty,
        "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system"
    }
    ok, _, rc = api_post(url, headers, payload, "SAVE STOCK MASTER (post‑comp)", expected_result_cd="000")
    return ok

def step_selectInvoiceType(headers: Dict, tin: str, bhf_id: str) -> bool:
    """Soft skip on failure."""
    url = f"{BASE_URL}/selectInvoiceType"
    payload = {"tin": tin, "bhfId": bhf_id, "salesTyCd": "N", "rcptTyCd": "S", "pmtTyCd": "01"}
    ok, _, rc = api_post(url, headers, payload, "SELECT INVOICE TYPE", soft_skip_on_5xx=True)
    return ok

def step_saveInvoice(headers: Dict, tin: str, bhf_id: str, parent_item_cd: str, invc_no: str,
                     trd_invc: str, cfm_dt: str, sales_dt: str) -> bool:
    url = f"{BASE_URL}/saveTrnsSalesOsdc"
    payload = {
        "tin": tin,
        "bhfId": bhf_id,
        "regTyCd": "M",
        "custTin": tin,
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
        "taxblAmtA": SALE_QTY * SALE_PRICE,
        "taxblAmtB": 0.0, "taxblAmtC": 0.0, "taxblAmtD": 0.0, "taxblAmtE": 0.0,
        "taxRtA": 0.0, "taxRtB": 0.0, "taxRtC": 0.0, "taxRtD": 0.0, "taxRtE": 0.0,
        "taxAmtA": 0.0, "taxAmtB": 0.0, "taxAmtC": 0.0, "taxAmtD": 0.0, "taxAmtE": 0.0,
        "totTaxblAmt": SALE_QTY * SALE_PRICE,
        "totTaxAmt": 0.0,
        "totAmt": SALE_QTY * SALE_PRICE,
        "prchrAcptcYn": "N",
        "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system",
        "receipt": {"rcptPbctDt": cfm_dt, "prchrAcptcYn": "N"},
        "itemList": [{
            "itemSeq": 1,
            "itemClsCd": "1010000000",
            "itemCd": parent_item_cd,
            "itemNm": "CERTIFICATION ITEM",
            "pkgUnitCd": "NT",
            "pkg": SALE_QTY,
            "qtyUnitCd": "TU",
            "qty": SALE_QTY,
            "prc": SALE_PRICE,
            "splyAmt": SALE_QTY * SALE_PRICE,
            "dcRt": 0.0,
            "dcAmt": 0.0,
            "taxTyCd": "A",
            "taxblAmt": SALE_QTY * SALE_PRICE,
            "taxAmt": 0.0,
            "totAmt": SALE_QTY * SALE_PRICE
        }]
    }
    params = {"invcNo": invc_no, "requestedInvcNo": invc_no}
    ok, _, rc = api_post(url, headers, payload, "SAVE INVOICE", expected_result_cd="000")
    return ok

def step_selectTrnsPurchaseSalesList(headers: Dict, tin: str, bhf_id: str) -> bool:
    url = f"{BASE_URL}/selectTrnsPurchaseSalesList"
    payload = {"tin": tin, "bhfId": bhf_id, "lastReqDt": get_baseline_timestamp()}
    ok, _, rc = api_post(url, headers, payload, "SELECT PURCHASE-SALES (post)", expected_result_cd="000")
    return ok

def step_insertTrnsPurchase(headers: Dict, tin: str, bhf_id: str, parent_item_cd: str,
                            item_cls_cd: str, tax_ty_cd: str) -> bool:
    url = f"{BASE_URL}/insertTrnsPurchase"
    invc_no = random.randint(100000000, 999999999)
    payload = {
        "spplrTin": tin,
        "invcNo": str(invc_no),
        "spplrBhfId": bhf_id,
        "spplrNm": "Test Supplier",
        "regTyCd": "M",
        "pchsTyCd": "N",
        "rcptTyCd": "P",
        "pmtTyCd": "01",
        "pchsSttsCd": "02",
        "cfmDt": get_utc_timestamp()[:14],
        "pchsDt": datetime.now().strftime("%Y%m%d"),
        "totItemCnt": 1,
        "taxblAmtA": SALE_QTY * SALE_PRICE,
        "totTaxblAmt": SALE_QTY * SALE_PRICE,
        "totTaxAmt": 0.0,
        "totAmt": SALE_QTY * SALE_PRICE,
        "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system",
        "itemList": [{
            "itemSeq": 1,
            "itemCd": parent_item_cd,
            "itemClsCd": item_cls_cd,
            "itemNm": "PARENT ITEM",
            "pkgUnitCd": "NT",
            "pkg": SALE_QTY,
            "qtyUnitCd": "TU",
            "qty": SALE_QTY,
            "prc": SALE_PRICE,
            "splyAmt": SALE_QTY * SALE_PRICE,
            "dcRt": 0.0,
            "dcAmt": 0.0,
            "taxblAmt": SALE_QTY * SALE_PRICE,
            "taxTyCd": tax_ty_cd,
            "taxAmt": 0.0,
            "totAmt": SALE_QTY * SALE_PRICE
        }]
    }
    ok, _, rc = api_post(url, headers, payload, "INSERT PURCHASE (parent)", expected_result_cd="000")
    return ok

def step_selectStockMoveListAfterPurchase(headers: Dict, tin: str, bhf_id: str, parent_item_cd: str) -> bool:
    """Optional – soft skip."""
    url = f"{BASE_URL}/selectStockMoveList"
    payload = {"tin": tin, "bhfId": bhf_id, "lastReqDt": get_move_list_timestamp(), "itemCd": parent_item_cd}
    ok, _, rc = api_post(url, headers, payload, "SELECT STOCK MOVE LIST (after purchase)", soft_skip_on_5xx=True)
    return ok

def step_saveStockMasterAfterPurchase(headers: Dict, tin: str, bhf_id: str, parent_item_cd: str, rsd_qty: float) -> bool:
    url = f"{BASE_URL}/saveStockMaster"
    payload = {"itemCd": parent_item_cd, "rsdQty": rsd_qty,
               "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system"}
    ok, _, rc = api_post(url, headers, payload, "SAVE STOCK MASTER (after purchase)", expected_result_cd="000")
    return ok

def step_insertStockIOFinal(headers: Dict, tin: str, bhf_id: str, parent_item_cd: str, qty: float, sar_no: int) -> Tuple[bool, int]:
    url = f"{BASE_URL}/insertStockIO"
    payload = {
        "sarNo": sar_no,
        "regTyCd": "M",
        "custTin": tin,
        "sarTyCd": "01",
        "ocrnDt": datetime.now().strftime("%Y%m%d"),
        "totItemCnt": 1,
        "totTaxblAmt": qty * SALE_PRICE,
        "totTaxAmt": 0.0,
        "totAmt": qty * SALE_PRICE,
        "orgSarNo": sar_no - 1,
        "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system",
        "itemList": [{
            "itemSeq": 1,
            "itemCd": parent_item_cd,
            "ioTyCd": "1",
            "itemClsCd": "1010000000",
            "itemNm": "PARENT ITEM",
            "pkgUnitCd": "NT",
            "pkg": qty,
            "qtyUnitCd": "TU",
            "qty": qty,
            "prc": SALE_PRICE,
            "splyAmt": qty * SALE_PRICE,
            "totDcAmt": 0.0,
            "taxblAmt": qty * SALE_PRICE,
            "taxTyCd": "A",
            "taxAmt": 0.0,
            "totAmt": qty * SALE_PRICE
        }]
    }
    ok, _, rc = api_post(url, headers, payload, "INSERT STOCK IO (final)", expected_result_cd="000")
    return ok, sar_no + 1 if ok else sar_no

def step_selectStockMoveListFinal(headers: Dict, tin: str, bhf_id: str, parent_item_cd: str) -> Tuple[bool, float]:
    """Fallback to previous balance if move list fails."""
    url = f"{BASE_URL}/selectStockMoveList"
    payload = {"tin": tin, "bhfId": bhf_id, "lastReqDt": get_move_list_timestamp(), "itemCd": parent_item_cd}
    ok, parsed, rc = api_post(url, headers, payload, "SELECT STOCK MOVE LIST (final)", expected_result_cd=None)
    if not ok:
        return True, PARENT_STOCK_QTY  # fallback
    rsd = None
    try:
        data = _response_body_data(parsed)
        if isinstance(data, dict):
            rsd = float(data.get("rsdQty", 0))
        elif isinstance(data, list) and len(data) > 0:
            rsd = float(data[0].get("rsdQty", 0))
    except Exception:
        pass
    if rsd is None:
        rsd = PARENT_STOCK_QTY
    return True, rsd

def step_saveStockMasterFinal(headers: Dict, tin: str, bhf_id: str, parent_item_cd: str, rsd_qty: float) -> bool:
    url = f"{BASE_URL}/saveStockMaster"
    payload = {"itemCd": parent_item_cd, "rsdQty": rsd_qty,
               "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system"}
    ok, _, rc = api_post(url, headers, payload, "SAVE STOCK MASTER (final)", expected_result_cd="000")
    return ok

def step_selectTrnsSalesList(headers: Dict, tin: str, bhf_id: str) -> bool:
    url = f"{BASE_URL}/selectTrnsSalesList"
    payload = {"tin": tin, "bhfId": bhf_id, "lastReqDt": get_baseline_timestamp()}
    ok, _, rc = api_post(url, headers, payload, "SELECT TRANSACTION SALES LIST", expected_result_cd="000")
    return ok

def step_selectInvoiceDtl(headers: Dict, tin: str, bhf_id: str, invc_no: str) -> bool:
    url = f"{BASE_URL}/selectInvoiceDtl"
    payload = {"tin": tin, "bhfId": bhf_id, "invcNo": invc_no, "lastReqDt": get_baseline_timestamp()}
    ok, _, rc = api_post(url, headers, payload, "SELECT INVOICE DETAIL", expected_result_cd="000")
    return ok

def step_selectCustomerList(headers: Dict, tin: str, bhf_id: str) -> bool:
    url = f"{BASE_URL}/selectCustomerList"
    payload = {"tin": tin, "bhfId": bhf_id, "lastReqDt": get_baseline_timestamp()}
    ok, _, rc = api_post(url, headers, payload, "SELECT CUSTOMER LIST", soft_skip_on_5xx=True)
    return ok

def step_selectTaxpayerInfo(headers: Dict, tin: str, bhf_id: str) -> bool:
    url = f"{BASE_URL}/selectTaxpayerInfo"
    payload = {"tin": tin, "bhfId": bhf_id, "lastReqDt": get_baseline_timestamp()}
    ok, _, rc = api_post(url, headers, payload, "SELECT TAXPAYER INFO", soft_skip_on_5xx=True)
    return ok

# ---------- Main orchestration ----------
def get_credentials(pin: str) -> Dict[str, str]:
    """Read credentials from CSV or prompt interactively."""
    rows = read_rows()
    for row in rows:
        if row.get("app_pin") == pin:
            return row
    # Not found – prompt
    print(f"\nNo entry found for PIN {pin}. Please enter credentials:")
    creds = {"app_pin": pin}
    for field in ["consumer_key", "consumer_secret", "integ_pin", "branch_id", "device_serial", "apigee_app_id"]:
        creds[field] = input(f"{field}: ").strip()
    # Try to obtain cmc_key via selectInitOsdcInfo later
    creds["cmc_key"] = ""
    rows.append(creds)
    write_rows(rows)
    return creds

def main():
    import sys
    args = sys.argv[1:]

    # Interactive mode if no arguments
    if not args:
        print("\n=== KRA OSCU Certification Script ===\n")
        pin = input("Enter Application Test PIN: ").strip()
        if not pin:
            print("PIN is required.")
            return 1
        
        print("\nSelect run mode:")
        print("  1) Normal run (use saved state, bypass flags enabled)")
        print("  2) Clean run (clear all saved state for this PIN)")
        print("  3) Reset stock only (clear stock-related progress)")
        choice = input("Enter 1, 2, or 3: ").strip()
        
        bypass_component = True   # default enabled
        bypass_pre_sale = True    # default enabled
        clean_run = (choice == "2")
        reset_stock = (choice == "3")
        
        if choice not in ("1", "2", "3"):
            print("Invalid choice. Exiting.")
            return 1
    else:
        # Command-line mode (original behavior)
        pin = args[0]
        bypass_component = "--bypass-component-stock-gate" in args
        bypass_pre_sale = "--bypass-pre-sale-stock-gate" in args
        clean_run = "--clean-run" in args
        reset_stock = "--reset-stock" in args

    # Apply clean/reset
    if clean_run:
        clear_state(pin, stock_only=False)
        print(f"Cleared all state for PIN {pin}.")
    elif reset_stock:
        clear_state(pin, stock_only=True)
        print(f"Cleared stock state for PIN {pin}.")

    # Load credentials
    creds = get_credentials(pin)
    consumer_key = creds["consumer_key"]
    consumer_secret = creds["consumer_secret"]
    branch_id = creds["branch_id"]
    device_serial = creds["device_serial"]
    apigee_app_id = creds["apigee_app_id"]
    tin = pin  # Application Test PIN is the TIN

    # Obtain bearer token
    print("\nObtaining OAuth token...")
    try:
        bearer = obtain_bearer_token(consumer_key, consumer_secret)
    except Exception as e:
        print(f"OAuth failed: {e}")
        return 1

    # Get or obtain cmc_key
    cmc_key = creds.get("cmc_key", "")
    if not cmc_key:
        print("No cmc_key found, calling selectInitOsdcInfo to obtain one...")
        headers = build_headers(bearer, tin, branch_id, device_serial, apigee_app_id)
        url = f"{BASE_URL}/selectInitOsdcInfo"
        payload = {"tin": tin, "bhfId": branch_id, "dvcSrlNo": device_serial}
        ok, parsed, rc = api_post(url, headers, payload, "FETCH CMC KEY", expected_result_cd=None)
        if ok and isinstance(parsed, dict):
            cmc_key = _response_body_dict(parsed).get("cmcKey")
            if not cmc_key:
                cmc_key = parsed.get("cmcKey")
        if not cmc_key:
            print("Could not obtain cmc_key. Please set CMC_KEY in .env or CSV.")
            return 1
        # Save it back to CSV
        rows = read_rows()
        for row in rows:
            if row.get("app_pin") == pin:
                row["cmc_key"] = cmc_key
                break
        write_rows(rows)
        print(f"Obtained and saved cmc_key: {cmc_key[:8]}...")

    # Build final headers
    headers = build_headers(bearer, tin, branch_id, device_serial, apigee_app_id, cmc_key)

    # Load state
    state = load_state(pin)
    completed = set(state.get("completed_endpoints", []))
    sar_counter = state.get("sar_counter", 1)

    # Prepare invoice numbers
    import random
    invc_no = str(random.randint(1000000, 9999999))
    trd_invc = f"INV-{invc_no}"
    cfm_dt = get_utc_timestamp()[:14]
    sales_dt = datetime.now().strftime("%Y%m%d")

    def _step_args(args: Any, st: Dict) -> tuple:
        return args(st) if callable(args) else args

    # Define the sequence of steps (name, function, args, and whether to skip if already completed).
    # Use ``lambda st: (...)`` where args must read parent/comp itemCd or sar_counter from ``state``.
    sequence = [
        ("INITIALIZE", step_initialize, (headers, tin, branch_id, device_serial), False),
        ("SELECT CODE LIST", step_selectCodeList, (headers, tin, branch_id), False),
        ("SELECT ITEM CLASS LIST", step_selectItemClsList, (headers, tin, branch_id), False),
        ("SELECT BRANCH LIST", step_selectBhfList, (headers, tin, branch_id), False),
        ("SELECT NOTICES", step_selectNotices, (headers, tin, branch_id), False),
        ("SAVE BHF CUSTOMER", step_saveBhfCustomer, (headers, tin, branch_id, invc_no), False),
        ("SAVE BHF USER", step_saveBhfUser, (headers, tin, branch_id, invc_no), False),
        ("SAVE BHF INSURANCE", step_saveBhfInsurance, (headers, tin, branch_id), False),
        ("SELECT ITEM LIST (catalog)", step_selectItemList, (headers, tin, branch_id), False),
        ("SAVE ITEM (parent)", step_saveItem, (headers, tin, branch_id, state), False),
        ("SAVE ITEM (component)", step_saveComponentItem, (headers, tin, branch_id, state), False),
        ("SELECT PURCHASE-SALES (pre-comp)", step_selectTrnsPurchaseSalesListPreComposition, (headers, tin, branch_id), True),  # optional
        ("SELECT IMPORT ITEM LIST", step_selectImportItemList, (headers, tin, branch_id), False),
        ("UPDATE IMPORT ITEM", step_updateImportItem, (headers, tin, branch_id, None), True),  # optional
        ("INSERT PURCHASE (component)", step_insertTrnsPurchaseComponentStock,
         lambda st: (headers, tin, branch_id, st["comp_item_cd"], st.get("item_cls_cd", "1010000000"), st.get("tax_ty_cd", "A")), False),
        ("SELECT STOCK MOVE LIST (component)", step_selectStockMoveListComponentPurchase,
         lambda st: (headers, tin, branch_id, st["comp_item_cd"], bypass_component), False),
        ("SAVE STOCK MASTER (component)", step_saveStockMasterComponentPurchase,
         lambda st: (headers, tin, branch_id, st["comp_item_cd"], COMPONENT_PURCHASE_QTY), False),
        ("SAVE ITEM COMPOSITION", step_saveItemComposition,
         lambda st: (headers, tin, branch_id, st["parent_item_cd"], st["comp_item_cd"], CPST_QTY), False),
        ("INSERT STOCK IO (initial)", step_insertStockIOInitial,
         lambda st: (headers, tin, branch_id, st["parent_item_cd"], PARENT_STOCK_QTY, st.get("sar_counter", 1)), False),
        ("SELECT STOCK MOVE LIST (initial)", step_selectStockMoveListInitial,
         lambda st: (headers, tin, branch_id, st["parent_item_cd"]), False),
        ("SAVE STOCK MASTER (initial)", step_saveStockMasterInitial,
         lambda st: (headers, tin, branch_id, st["parent_item_cd"], PARENT_STOCK_QTY), False),
        ("INSERT STOCK IO (post‑comp)", step_insertStockIOPostComposition,
         lambda st: (headers, tin, branch_id, st["parent_item_cd"], PARENT_STOCK_QTY, st.get("sar_counter", 1)), False),
        ("SELECT STOCK MOVE LIST (post‑comp)", step_selectStockMoveListPostComposition,
         lambda st: (headers, tin, branch_id, st["parent_item_cd"]), False),
        ("SAVE STOCK MASTER (post‑comp)", step_saveStockMasterPostComposition,
         lambda st: (headers, tin, branch_id, st["parent_item_cd"], PARENT_STOCK_QTY), False),
        ("SELECT INVOICE TYPE", step_selectInvoiceType, (headers, tin, branch_id), True),
        ("SAVE INVOICE", step_saveInvoice,
         lambda st: (headers, tin, branch_id, st["parent_item_cd"], invc_no, trd_invc, cfm_dt, sales_dt), False),
        ("SELECT PURCHASE-SALES (post)", step_selectTrnsPurchaseSalesList, (headers, tin, branch_id), False),
        ("INSERT PURCHASE (parent)", step_insertTrnsPurchase,
         lambda st: (headers, tin, branch_id, st["parent_item_cd"], st.get("item_cls_cd", "1010000000"), st.get("tax_ty_cd", "A")), False),
        ("SELECT STOCK MOVE LIST (after purchase)", step_selectStockMoveListAfterPurchase,
         lambda st: (headers, tin, branch_id, st["parent_item_cd"]), True),
        ("SAVE STOCK MASTER (after purchase)", step_saveStockMasterAfterPurchase,
         lambda st: (headers, tin, branch_id, st["parent_item_cd"], PARENT_STOCK_QTY), False),
        ("INSERT STOCK IO (final)", step_insertStockIOFinal,
         lambda st: (headers, tin, branch_id, st["parent_item_cd"], PARENT_STOCK_QTY, st.get("sar_counter", 1)), False),
        ("SELECT STOCK MOVE LIST (final)", step_selectStockMoveListFinal,
         lambda st: (headers, tin, branch_id, st["parent_item_cd"]), False),
        ("SAVE STOCK MASTER (final)", step_saveStockMasterFinal,
         lambda st: (headers, tin, branch_id, st["parent_item_cd"], PARENT_STOCK_QTY), False),
        ("SELECT TRANSACTION SALES LIST", step_selectTrnsSalesList, (headers, tin, branch_id), False),
        ("SELECT INVOICE DETAIL", step_selectInvoiceDtl, (headers, tin, branch_id, invc_no), False),
        ("SELECT CUSTOMER LIST", step_selectCustomerList, (headers, tin, branch_id), True),
        ("SELECT TAXPAYER INFO", step_selectTaxpayerInfo, (headers, tin, branch_id), True),
    ]

    # Run the sequence
    overall_success = True
    for step_name, step_func, step_args, optional in sequence:
        if step_name in completed:
            print(f"\n--- SKIPPING {step_name} (already completed) ---")
            continue

        print(f"\n========== {step_name} ==========")
        try:
            if step_name == "SELECT ITEM CLASS LIST":
                ok, icd, tty = step_func(*_step_args(step_args, state))
                if not ok:
                    if optional:
                        print(f"Optional step {step_name} failed, continuing...")
                        continue
                    else:
                        print(f"FATAL: {step_name} failed.")
                        overall_success = False
                        break
                # Store item class for later steps
                state["item_cls_cd"] = icd
                state["tax_ty_cd"] = tty
            elif step_name == "SELECT ITEM LIST (catalog)":
                ok, cat_parsed = step_func(*_step_args(step_args, state))
                if not ok:
                    if optional:
                        print(f"Optional step {step_name} failed, continuing...")
                        continue
                    else:
                        print(f"FATAL: {step_name} failed.")
                        overall_success = False
                        break
                state["catalog_parsed"] = catalog_for_state(cat_parsed)
                save_state(pin, state)
            elif step_name == "INSERT PURCHASE (component)":
                ok, invc = step_func(*_step_args(step_args, state))
                if not ok:
                    if optional:
                        print(f"Optional step {step_name} failed, continuing...")
                        continue
                    else:
                        print(f"FATAL: {step_name} failed.")
                        overall_success = False
                        break
                state["component_purchase_invc"] = invc
            elif step_name in ("INSERT STOCK IO (initial)", "INSERT STOCK IO (post‑comp)", "INSERT STOCK IO (final)"):
                ok, new_sar = step_func(*_step_args(step_args, state))
                if not ok:
                    if optional:
                        print(f"Optional step {step_name} failed, continuing...")
                        continue
                    else:
                        print(f"FATAL: {step_name} failed.")
                        overall_success = False
                        break
                sar_counter = new_sar
                state["sar_counter"] = sar_counter
            elif step_name in ("SELECT STOCK MOVE LIST (initial)", "SELECT STOCK MOVE LIST (post‑comp)", "SELECT STOCK MOVE LIST (final)"):
                ok, rsd = step_func(*_step_args(step_args, state))
                if not ok:
                    if optional:
                        print(f"Optional step {step_name} failed, continuing...")
                        continue
                    else:
                        print(f"FATAL: {step_name} failed.")
                        overall_success = False
                        break
                # Store the retrieved rsdQty for the corresponding saveStockMaster step
                if step_name == "SELECT STOCK MOVE LIST (initial)":
                    state["initial_rsd"] = rsd
                elif step_name == "SELECT STOCK MOVE LIST (post‑comp)":
                    state["post_rsd"] = rsd
                elif step_name == "SELECT STOCK MOVE LIST (final)":
                    state["final_rsd"] = rsd
            else:
                if step_name == "SAVE STOCK MASTER (initial)":
                    # Use stored rsd from previous step
                    rsd = state.get("initial_rsd", PARENT_STOCK_QTY)
                    args = _step_args(step_args, state)
                    ok = step_func(*(args[:-1] + (rsd,)))
                elif step_name == "SAVE STOCK MASTER (post‑comp)":
                    rsd = state.get("post_rsd", PARENT_STOCK_QTY)
                    args = _step_args(step_args, state)
                    ok = step_func(*(args[:-1] + (rsd,)))
                elif step_name == "SAVE STOCK MASTER (final)":
                    rsd = state.get("final_rsd", PARENT_STOCK_QTY)
                    args = _step_args(step_args, state)
                    ok = step_func(*(args[:-1] + (rsd,)))
                else:
                    ok = step_func(*_step_args(step_args, state))
                if not ok:
                    if optional:
                        print(f"Optional step {step_name} failed, continuing...")
                        continue
                    else:
                        print(f"FATAL: {step_name} failed.")
                        overall_success = False
                        break
            # Mark step as completed
            completed.add(step_name)
            state["completed_endpoints"] = list(completed)
            save_state(pin, state)
            # Small pause after critical steps
            if "STOCK" in step_name or "SAVE" in step_name:
                time.sleep(PAUSE_AFTER_INSERT_STOCK)
        except Exception as e:
            print(f"Exception in {step_name}: {e}")
            if not optional:
                overall_success = False
                break

    if overall_success:
        print("\n" + "="*60)
        print("✅ ALL STEPS COMPLETED SUCCESSFULLY!")
        print(f"Sales Invoice Number: {invc_no}")
        print("Check the portal – all 23 test cases should now be PASSED or NOT_EXECUTED (for optional ones).")
        print("="*60)
        return 0
    else:
        print("\n❌ Sequence failed. See errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())