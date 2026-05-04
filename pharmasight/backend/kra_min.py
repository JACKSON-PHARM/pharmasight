#!/usr/bin/env python3
"""
Minimal KRA OSCU Sandbox runner – full 23‑step sequence.
- Recursive None replacement.
- Auto‑syncs SAR sequence with ledger (retries + fallback).
- Auto‑recovers from SAR and rsdQty errors.
- Respects KRA itemCd suffix rules (e.g., "********5").
- Forces item tax type to B (VAT) for normal sale.
- Clears itemCd on sequence error to force regeneration.
- Separate suffix handling for parent and component items.
- Ensures component stock exists before composition.
- **Dynamically** obtains supplier invoice + tax rates from selectTrnsPurchaseSalesListPreComposition.
- Component purchase uses tax type A and linked supplier tax rates.
- selectInvoiceType / selectTaxPayerInfo: query params + soft‑skip.
- Added selectTaxPayerInfo step (after selectBhfList, before selectNotices).
- Purchase insertion (insertTrnsPurchaseComponentStock, insertTrnsPurchase) send JSON body only.
"""

import csv
import json
import os
import re
import sys
import time
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

# Prefixes and supplier defaults (fallback only)
PARENT_PREFIX = "KE2NTTU"
COMPONENT_PREFIX = "KE1NTTU"
DEFAULT_ITEM_TAX_TYPE = "B"        # VAT for parent item

# ----------------------------------------------------------------------
# SEQUENCE (same as original, but we keep it)
# ----------------------------------------------------------------------
SEQUENCE = [
    ("initialize", "/initialize", {"tin": None, "bhfId": None, "dvcSrlNo": None}),
    ("selectCodeList", "/selectCodeList", {"tin": None, "bhfId": None, "lastReqDt": "20100101000000"}),
    ("selectItemClsList", "/selectItemClsList", {"tin": None, "bhfId": None, "lastReqDt": "20100101000000"}),
    ("selectBhfList", "/selectBhfList", {"tin": None, "bhfId": None, "lastReqDt": "20100101000000"}),
    ("selectTaxPayerInfo", "/selectTaxpayerInfo", {"tin": None}),
    ("selectNotices", "/selectNotices", {"tin": None, "bhfId": None, "lastReqDt": "20100101000000"}),
    ("saveBhfCustomer", "/saveBhfCustomer", {"custNo": None, "custTin": None, "custNm": "TEST BHF CUSTOMER", "useYn": "Y", "regrNm": "system", "regrId": "system", "modrNm": "system", "modrId": "system"}),
    ("saveBhfUser", "/saveBhfUser", {"userId": None, "userNm": None, "pwd": "Test#Pass1", "useYn": "Y", "regrNm": "system", "regrId": "system", "modrNm": "system", "modrId": "system"}),
    ("saveBhfInsurance", "/saveBhfInsurance", {"isrccCd": "PS001", "isrccNm": "Test Insurance Co", "isrcRt": 10, "useYn": "Y", "regrNm": "system", "regrId": "system", "modrNm": "system", "modrId": "system"}),
    ("selectItemList", "/selectItemList", {"tin": None, "bhfId": None, "lastReqDt": "20100101000000"}),
    ("saveItem", "/saveItem", {"itemCd": None, "itemClsCd": "1010000000", "itemTyCd": "2", "itemNm": "TEST ITEM", "orgnNatCd": "KE", "pkgUnitCd": "NT", "qtyUnitCd": "TU", "taxTyCd": None, "dftPrc": 100, "isrcAplcbYn": "N", "useYn": "Y", "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system"}),
    ("selectItemListPostSave", "/selectItemList", {"tin": None, "bhfId": None, "lastReqDt": "20100101000000"}),
    ("saveComponentItem", "/saveItem", {"itemCd": None, "itemClsCd": "1010000000", "itemTyCd": "1", "itemNm": "COMPONENT ITEM", "orgnNatCd": "KE", "pkgUnitCd": "NT", "qtyUnitCd": "TU", "taxTyCd": "A", "dftPrc": 10, "isrcAplcbYn": "N", "useYn": "Y", "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system"}),
    ("selectTrnsPurchaseSalesListPreComposition", "/selectTrnsPurchaseSalesList", {"tin": None, "bhfId": None, "lastReqDt": "20100101000000"}),
    ("selectImportItemList", "/selectImportItemList", {"tin": None, "bhfId": None, "lastReqDt": "20100101000000"}),
    ("importedItemInfo", "/importedItemInfo", {"tin": None, "bhfId": None, "lastReqDt": "20100101000000"}),
    ("importedItemConvertedInfo", "/importedItemConvertedInfo", {"taskCd": "", "dclDe": "", "itemSeq": 1, "hsCd": "", "itemClsCd": None, "itemCd": None, "imptItemSttsCd": "3", "remark": "remark", "modrId": "system", "modrNm": "system"}),
    ("updateImportItem", "/updateImportItem", {"taskCd": "", "dclDe": None, "itemSeq": 1, "hsCd": "", "itemClsCd": None, "itemCd": None, "imptItemSttsCd": "3", "remark": "remark", "modrId": "system", "modrNm": "system"}),
    ("insertTrnsPurchaseComponentStock", "/insertTrnsPurchase", {"spplrTin": None, "invcNo": None, "spplrBhfId": None, "spplrNm": "Test Supplier", "regTyCd": "M", "pchsTyCd": "N", "rcptTyCd": "P", "pmtTyCd": "01", "pchsSttsCd": "02", "cfmDt": None, "pchsDt": None, "totItemCnt": 1, "totTaxblAmt": 20, "totTaxAmt": 0, "totAmt": 20, "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system", "itemList": [{"itemSeq": 1, "itemCd": None, "itemClsCd": "1010000000", "itemNm": "COMPONENT ITEM", "pkgUnitCd": "NT", "pkg": 2, "qtyUnitCd": "TU", "qty": 2, "prc": 10, "splyAmt": 20, "dcRt": 0, "dcAmt": 0, "taxblAmt": 20, "taxTyCd": "A", "taxAmt": 0, "totAmt": 20}]}),
    ("insertStockIOComponentPurchase", "/insertStockIO", {"sarNo": None, "regTyCd": "M", "custTin": None, "sarTyCd": "01", "ocrnDt": None, "totItemCnt": 1, "totTaxblAmt": 0, "totTaxAmt": 0, "totAmt": 0, "orgSarNo": 0, "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system", "itemList": [{"itemSeq": 1, "itemCd": None, "ioTyCd": "1", "itemClsCd": "1010000000", "itemNm": "COMPONENT ITEM", "pkgUnitCd": "NT", "pkg": 1, "qtyUnitCd": "TU", "qty": 1, "prc": 10, "splyAmt": 10, "totDcAmt": 0, "taxblAmt": 10, "taxTyCd": "A", "taxAmt": 0, "totAmt": 10}]}),
    ("saveStockMasterComponentPurchase", "/saveStockMaster", {"itemCd": None, "rsdQty": None, "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system"}),
    ("saveItemComposition", "/saveItemComposition", {"itemCd": None, "cpstItemCd": None, "cpstQty": 1, "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system"}),
    ("insertStockIOInitial", "/insertStockIO", {"sarNo": None, "regTyCd": "M", "custTin": None, "sarTyCd": "01", "ocrnDt": None, "totItemCnt": 1, "totTaxblAmt": 10000, "totTaxAmt": 0, "totAmt": 10000, "orgSarNo": 0, "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system", "itemList": [{"itemSeq": 1, "itemCd": None, "ioTyCd": "1", "itemClsCd": "1010000000", "itemNm": "TEST ITEM", "pkgUnitCd": "NT", "pkg": 100, "qtyUnitCd": "TU", "qty": 100, "prc": 100, "splyAmt": 10000, "totDcAmt": 0, "taxblAmt": 10000, "taxTyCd": None, "taxAmt": 0, "totAmt": 10000}]}),
    ("saveStockMasterInitial", "/saveStockMaster", {"itemCd": None, "rsdQty": None, "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system"}),
    ("insertStockIOPostComposition", "/insertStockIO", {"sarNo": None, "regTyCd": "M", "custTin": None, "sarTyCd": "01", "ocrnDt": None, "totItemCnt": 1, "totTaxblAmt": 10000, "totTaxAmt": 0, "totAmt": 10000, "orgSarNo": 0, "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system", "itemList": [{"itemSeq": 1, "itemCd": None, "ioTyCd": "1", "itemClsCd": "1010000000", "itemNm": "TEST ITEM", "pkgUnitCd": "NT", "pkg": 100, "qtyUnitCd": "TU", "qty": 100, "prc": 100, "splyAmt": 10000, "totDcAmt": 0, "taxblAmt": 10000, "taxTyCd": None, "taxAmt": 0, "totAmt": 10000}]}),
    ("saveStockMasterPostComposition", "/saveStockMaster", {"itemCd": None, "rsdQty": None, "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system"}),
    ("selectInvoiceType", "/selectInvoiceType", {"tin": None, "bhfId": None, "salesTyCd": "N", "rcptTyCd": "S", "pmtTyCd": "01"}),
    ("saveInvoice", "/saveTrnsSalesOsdc", {"tin": None, "bhfId": None, "regTyCd": "M", "salesTyCd": "N", "rcptTyCd": "S", "pmtTyCd": "01", "trdInvcNo": None, "invcNo": None, "orgInvcNo": "0", "salesSttsCd": "02", "cfmDt": None, "salesDt": None, "stockRlsDt": None, "totItemCnt": 1, "taxblAmtA": 100, "taxblAmtB": 0, "taxblAmtC": 0, "taxblAmtD": 0, "taxblAmtE": 0, "taxRtA": 0, "taxRtB": 0, "taxRtC": 0, "taxRtD": 0, "taxRtE": 0, "taxAmtA": 0, "taxAmtB": 0, "taxAmtC": 0, "taxAmtD": 0, "taxAmtE": 0, "totTaxblAmt": 100, "totTaxAmt": 0, "totAmt": 100, "prchrAcptcYn": "N", "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system", "receipt": {"rcptPbctDt": None, "prchrAcptcYn": "N"}, "itemList": [{"itemSeq": 1, "itemClsCd": "1010000000", "itemCd": None, "itemNm": "TEST ITEM", "pkgUnitCd": "NT", "pkg": 1, "qtyUnitCd": "TU", "qty": 1, "prc": 100, "splyAmt": 100, "dcRt": 0, "dcAmt": 0, "taxTyCd": None, "taxblAmt": 100, "taxAmt": 0, "totAmt": 100}]}),
    ("selectTrnsPurchaseSalesList", "/selectTrnsPurchaseSalesList", {"tin": None, "bhfId": None, "lastReqDt": "20100101000000"}),
    ("insertTrnsPurchase", "/insertTrnsPurchase", {"spplrTin": None, "invcNo": None, "spplrBhfId": None, "spplrNm": "Test Supplier", "regTyCd": "M", "pchsTyCd": "N", "rcptTyCd": "P", "pmtTyCd": "01", "pchsSttsCd": "02", "cfmDt": None, "pchsDt": None, "totItemCnt": 1, "totTaxblAmt": 100, "totTaxAmt": 0, "totAmt": 100, "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system", "itemList": [{"itemSeq": 1, "itemCd": None, "itemClsCd": "1010000000", "itemNm": "TEST ITEM", "pkgUnitCd": "NT", "pkg": 1, "qtyUnitCd": "TU", "qty": 1, "prc": 100, "splyAmt": 100, "dcRt": 0, "dcAmt": 0, "taxblAmt": 100, "taxTyCd": None, "taxAmt": 0, "totAmt": 100}]}),
    ("saveStockMasterAfterPurchase", "/saveStockMaster", {"itemCd": None, "rsdQty": None, "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system"}),
    ("insertStockIO", "/insertStockIO", {"sarNo": None, "regTyCd": "M", "custTin": None, "sarTyCd": "01", "ocrnDt": None, "totItemCnt": 1, "totTaxblAmt": 10000, "totTaxAmt": 0, "totAmt": 10000, "orgSarNo": 0, "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system", "itemList": [{"itemSeq": 1, "itemCd": None, "ioTyCd": "1", "itemClsCd": "1010000000", "itemNm": "TEST ITEM", "pkgUnitCd": "NT", "pkg": 100, "qtyUnitCd": "TU", "qty": 100, "prc": 100, "splyAmt": 10000, "totDcAmt": 0, "taxblAmt": 10000, "taxTyCd": None, "taxAmt": 0, "totAmt": 10000}]}),
    ("saveStockMaster", "/saveStockMaster", {"itemCd": None, "rsdQty": None, "regrId": "system", "regrNm": "system", "modrId": "system", "modrNm": "system"}),
    ("selectTrnsSalesList", "/selectTrnsSalesList", {"tin": None, "bhfId": None, "lastReqDt": "20100101000000"}),
    ("selectInvoiceDetails", "/selectInvoiceDetails", {"tin": None, "bhfId": None, "invcNo": None, "lastReqDt": "20100101000000"}),
    ("selectCustomerList", "/selectCustomerList", {"tin": None, "bhfId": None, "lastReqDt": "20100101000000"}),
]

# ----------------------------------------------------------------------
# Helper functions (with additions for tax rate linking)
# ----------------------------------------------------------------------
def get_bearer_token(consumer_key, consumer_secret):
    url = f"{OAUTH_BASE}{OAUTH_TOKEN_PATH}"
    resp = requests.get(url, auth=(consumer_key, consumer_secret), params={"grant_type": "client_credentials"}, timeout=30)
    if resp.status_code != 200:
        raise Exception(f"OAuth failed: {resp.text}")
    return resp.json()["access_token"]

def load_state(pin):
    if STATE_FILE.exists():
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
        return data.get(pin, {})
    return {}

def save_state(pin, state):
    if STATE_FILE.exists():
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
    else:
        data = {}
    data[pin] = state
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_current_max_sar(headers, tin, bhf, state):
    key = f"sar_{tin}|{bhf}"
    url = f"{BASE_URL}/selectStockMoveList"
    payload = {"tin": tin, "bhfId": bhf, "lastReqDt": "20100101000000"}
    for attempt in range(1, 4):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            data = resp.json()
            print(f"DEBUG selectStockMoveList attempt {attempt}: HTTP {resp.status_code}")
            if resp.status_code == 200:
                result_cd = data.get("responseBody", {}).get("resultCd")
                if result_cd == "000":
                    moves = data.get("responseBody", {}).get("data", {}).get("stockMoveList", [])
                    max_sar = 0
                    for m in moves:
                        sar = m.get("sarNo")
                        if isinstance(sar, int) and sar > max_sar:
                            max_sar = sar
                        elif isinstance(sar, str) and sar.isdigit():
                            max_sar = max(max_sar, int(sar))
                    return max_sar
                else:
                    print(f"⚠️ selectStockMoveList resultCd={result_cd}")
            else:
                print(f"⚠️ HTTP {resp.status_code}")
        except Exception as e:
            print(f"⚠️ Exception on attempt {attempt}: {e}")
        time.sleep(2)
    stored = state.get(key, 0)
    print(f"⚠️ Ledger query failed after 3 attempts. Falling back to stored SAR = {stored}")
    return stored

def sync_sar_with_ledger(state, headers, tin, bhf, force_sar=None):
    key = f"sar_{tin}|{bhf}"
    if force_sar is not None:
        print(f"⚠️ Manual SAR override: setting {key} to {force_sar}")
        state[key] = force_sar
        save_state(tin, state)
        return
    ledger_max = get_current_max_sar(headers, tin, bhf, state)
    current_state = state.get(key, 0)
    if ledger_max > current_state:
        print(f"SAR sync: ledger max = {ledger_max}, state had {current_state}. Updating state to {ledger_max}.")
        state[key] = ledger_max
        save_state(tin, state)
    elif ledger_max < current_state:
        print(f"⚠️ SAR state ({current_state}) ahead of ledger ({ledger_max}). Keeping state as is.")
    else:
        print(f"SAR in sync: ledger = {ledger_max}, state = {current_state}")

def get_next_sar_no(state, tin, bhf):
    key = f"sar_{tin}|{bhf}"
    sar = state.get(key, 0) + 1
    state[key] = sar
    return sar

def update_sar_after_success(state, tin, bhf, used_sar):
    key = f"sar_{tin}|{bhf}"
    state[key] = used_sar

def prompt_for_missing_fields(row, required_fields):
    for f in required_fields:
        if not row.get(f):
            default = "00" if f == "branch_id" else ""
            val = input(f"Enter {f} for PIN {row['app_pin']} [{default}]: ").strip()
            row[f] = val or default
    return row

def extract_import_item_rows(parsed):
    out = []
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

# ---- NEW: Supplier extraction that also returns tax rates ----
def extract_supplier_info_from_salelist(data):
    try:
        sale_list = data.get("responseBody", {}).get("data", {}).get("saleList", [])
        for sale in sale_list:
            tin = str(sale.get("spplrTin") or "").strip()
            bhf = str(sale.get("spplrBhfId") or "").strip()
            name = str(sale.get("spplrNm") or "").strip()
            inv = str(sale.get("spplrInvcNo") or "").strip()
            if tin and inv:
                tax_rates = {
                    "taxRtA": sale.get("taxRtA", 0.0),
                    "taxRtB": sale.get("taxRtB", 0.0),
                    "taxRtC": sale.get("taxRtC", 0.0),
                    "taxRtD": sale.get("taxRtD", 0.0),
                    "taxRtE": sale.get("taxRtE", 0.0),
                }
                return tin, bhf, name, inv, tax_rates
    except Exception:
        pass
    return None, None, None, None, {}

def sale_row_tax_rt_map(row):
    """Extract taxRtA..E from a sale row."""
    if not row or not isinstance(row, dict):
        return {}
    out = {}
    for k in ("taxRtA", "taxRtB", "taxRtC", "taxRtD", "taxRtE"):
        v = row.get(k)
        try:
            out[k] = float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            out[k] = 0.0
    return out

def apply_link_tax_rt_to_purchase_payload(payload, tax_rt_map):
    """Copy taxRt* from sale row to purchase payload."""
    if not isinstance(payload, dict) or not isinstance(tax_rt_map, dict):
        return
    for k in ("taxRtA", "taxRtB", "taxRtC", "taxRtD", "taxRtE"):
        if k in tax_rt_map:
            try:
                payload[k] = float(tax_rt_map[k])
            except (TypeError, ValueError):
                pass

def recover_sar_from_error(error_msg, state, tin, bhf):
    match = re.search(r"Expected:\s*(\d+)", error_msg)
    if match:
        expected = int(match.group(1))
        key = f"sar_{tin}|{bhf}"
        new_state_val = expected - 1
        print(f"🔄 Auto‑recovery (SAR): KRA expected SAR {expected}, setting {key} to {new_state_val}")
        state[key] = new_state_val
        save_state(tin, state)
        return True
    return False

def compute_tax_amounts(sply_amt, tax_ty_cd):
    """Return (taxbl_amt, tax_amt, rate) based on tax type."""
    sply = float(sply_amt)
    if tax_ty_cd == "B":
        taxbl = round(sply / 1.16, 2)
        tax = round(sply - taxbl, 2)
        rate = 16.0
    else:
        # For "A" and anything else – taxbl = sply, tax = 0
        taxbl = sply
        tax = 0.0
        rate = 0.0
    return taxbl, tax, rate

def get_item_tax_type_from_kra(item_cd, headers, pin, branch_id):
    url = f"{BASE_URL}/selectItemList"
    payload = {
        "tin": pin,
        "bhfId": branch_id,
        "lastReqDt": "20100101000000",
        "itemCd": item_cd
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        data = resp.json()
        result_cd = data.get("responseBody", {}).get("resultCd")
        if result_cd == "000":
            items = data.get("responseBody", {}).get("data", {}).get("itemList", [])
            for it in items:
                if it.get("itemCd") == item_cd:
                    return it.get("taxTyCd")
    except Exception as e:
        print(f"⚠️ Failed to fetch item tax type from KRA: {e}")
    return None

def get_max_suffix_for_prefix(prefix, headers, pin, branch_id, state):
    url = f"{BASE_URL}/selectItemList"
    payload = {"tin": pin, "bhfId": branch_id, "lastReqDt": "20100101000000"}
    max_suffix = 0
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        data = resp.json()
        result_cd = data.get("responseBody", {}).get("resultCd")
        if result_cd == "000":
            items = data.get("responseBody", {}).get("data", {}).get("itemList", [])
            for it in items:
                cd = it.get("itemCd", "")
                if cd.startswith(prefix) and len(cd) == len(prefix) + 7:
                    try:
                        suf = int(cd[-7:])
                        if suf > max_suffix:
                            max_suffix = suf
                    except ValueError:
                        pass
    except Exception as e:
        print(f"⚠️ Failed to query item list for {prefix}: {e}")
    return max_suffix

def generate_next_item_cd(prefix, headers, pin, branch_id, state, hint_digit=None):
    max_suffix = get_max_suffix_for_prefix(prefix, headers, pin, branch_id, state)
    next_suffix = max_suffix + 1
    if hint_digit is not None:
        while next_suffix % 10 != hint_digit:
            next_suffix += 1
    return f"{prefix}{next_suffix:07d}", next_suffix

def query_component_stock(component_cd, headers, pin, branch_id):
    url = f"{BASE_URL}/selectStockMaster"
    payload = {
        "tin": pin,
        "bhfId": branch_id,
        "itemCd": component_cd,
        "lastReqDt": "20100101000000"
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        data = resp.json()
        result_cd = data.get("responseBody", {}).get("resultCd")
        if result_cd == "000":
            items = data.get("responseBody", {}).get("data", {}).get("stockMasterList", [])
            for it in items:
                if it.get("itemCd") == component_cd:
                    rsd = it.get("rsdQty")
                    if rsd is not None:
                        return float(rsd)
    except Exception as e:
        print(f"⚠️ Failed to query stock for {component_cd}: {e}")
    return None

def reset_item_state(pin):
    state = load_state(pin)
    to_delete = [k for k in state.keys() if k.startswith("suffix_") or (k.startswith("last_") and "suffix" in k)]
    for k in to_delete:
        del state[k]
    state.pop("item_cd", None)
    state.pop("component_cd", None)
    state.pop("canonical_item_cd", None)
    state.pop("current_stock_balance", None)
    state.pop("item_tax_ty_cd", None)
    state.pop("kra_item_suffix_hint", None)
    state.pop("kra_component_suffix_hint", None)
    state.pop("items", None)
    completed = state.get("completed", [])
    keep = []
    for step in completed:
        if step not in ("saveItem", "selectItemListPostSave", "saveComponentItem",
                        "insertStockIOInitial", "saveStockMasterInitial",
                        "insertStockIOPostComposition", "saveStockMasterPostComposition",
                        "saveItemComposition",
                        "insertTrnsPurchaseComponentStock", "insertStockIOComponentPurchase",
                        "saveStockMasterComponentPurchase",
                        "insertTrnsPurchase", "saveStockMasterAfterPurchase",
                        "insertStockIO", "saveStockMaster", "saveInvoice"):
            keep.append(step)
    state["completed"] = keep
    save_state(pin, state)
    print("Item state, suffix counters, and stock steps reset. Next run will recreate everything cleanly.")

def main():
    force_sar = None
    pin = None
    reset_item = False
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--force-sar" and i+1 < len(args):
            try:
                force_sar = int(args[i+1])
            except ValueError:
                print("ERROR: --force-sar requires an integer")
                sys.exit(1)
            args.pop(i)
            args.pop(i)
            break
    if "--reset-item" in args:
        reset_item = True
        args.remove("--reset-item")
    if args:
        pin = args[0].strip()
    else:
        print("Enter the Application Test PIN for this run.")
        pin = input("PIN: ").strip()
        if not pin:
            print("PIN is required.")
            sys.exit(1)

    if reset_item:
        reset_item_state(pin)
        return

    if not CSV_FILE.exists():
        with open(CSV_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["app_pin","consumer_key","consumer_secret","integ_pin","branch_id","device_serial","apigee_app_id","cmc_key"])
            writer.writeheader()

    with open(CSV_FILE, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    row = next((r for r in rows if r.get("app_pin") == pin), None)
    if not row:
        row = {"app_pin": pin, "consumer_key": "", "consumer_secret": "", "integ_pin": "", "branch_id": "", "device_serial": "", "apigee_app_id": "", "cmc_key": ""}
        rows.append(row)

    required_fields = ["consumer_key", "consumer_secret", "branch_id", "device_serial", "apigee_app_id"]
    if not all(row.get(f) for f in required_fields):
        row = prompt_for_missing_fields(row, required_fields)
        with open(CSV_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            writer.writeheader()
            writer.writerows(rows)

    consumer_key = row["consumer_key"]
    consumer_secret = row["consumer_secret"]
    branch_id = row["branch_id"]
    device_serial = row["device_serial"]
    apigee_app_id = row["apigee_app_id"]
    cmc_key = row.get("cmc_key", "")

    manual_bearer = os.getenv("BEARER_TOKEN")
    if manual_bearer:
        bearer = manual_bearer
        print("Using BEARER_TOKEN from .env")
    else:
        print("Obtaining OAuth token...")
        bearer = get_bearer_token(consumer_key, consumer_secret)

    headers = {
        "Authorization": f"Bearer {bearer}",
        "tin": pin,
        "bhfId": branch_id,
        "apigee_app_id": apigee_app_id,
        "dvcSrlNo": device_serial,
        "Content-Type": "application/json",
    }
    if cmc_key:
        headers["cmcKey"] = cmc_key

    state = load_state(pin)

    print("\n🔍 Syncing SAR sequence...")
    sync_sar_with_ledger(state, headers, pin, branch_id, force_sar)

    completed = state.get("completed", [])
    item_cd = state.get("item_cd", "")
    component_cd = state.get("component_cd", "")
    invc_no = state.get("invc_no", 1)
    trd_invc = f"TRD-{invc_no}"
    now = datetime.now(timezone.utc)
    sales_dt = now.strftime("%Y%m%d")
    cfm_dt = now.strftime("%Y%m%d%H%M%S")
    import_update_row = state.get("import_update_row")
    import_lifecycle_ready = state.get("import_lifecycle_ready", False)

    # Supplier info captured from pre‑composition sale list
    supplier_tin = state.get("supplier_tin")
    supplier_bhf = state.get("supplier_bhf")
    supplier_name = state.get("supplier_name")
    supplier_invoice_no = state.get("supplier_invoice_no")
    supplier_tax_rates = state.get("supplier_tax_rates", {})
    component_purchased_qty = state.get("component_purchased_qty", 1.0)

    current_stock_balance = state.get("current_stock_balance", 0.0)

    def get_item_tax_info(item_code):
        items_db = state.get("items", {})
        if item_code in items_db:
            return items_db[item_code]
        if item_code and item_code.startswith("KE1"):
            return {"taxTyCd": "A", "taxRt": 0.0}
        return {"taxTyCd": DEFAULT_ITEM_TAX_TYPE, "taxRt": 16.0 if DEFAULT_ITEM_TAX_TYPE == "B" else 0.0}

    def ensure_item_cd(step_name):
        nonlocal item_cd
        if not item_cd:
            item_cd = state.get("item_cd", "")
            if not item_cd:
                raise Exception(f"STOP: {step_name} requires item_cd but none found. Did saveItem complete successfully?")
        return item_cd

    def deep_replace(obj, step_name, ctx):
        if isinstance(obj, dict):
            for k, v in list(obj.items()):
                if v is None:
                    if k in ("tin", "custTin"): obj[k] = ctx["pin"]
                    elif k in ("bhfId", "spplrBhfId"): obj[k] = ctx["branch_id"]
                    elif k == "dvcSrlNo": obj[k] = ctx["device_serial"]
                    elif k == "custNo": obj[k] = str(ctx["invc_no"]).zfill(9)
                    elif k in ("userId", "userNm"): obj[k] = f"user_{ctx['invc_no']}"[:15]
                    elif k == "invcNo": obj[k] = str(ctx["invc_no"])
                    elif k == "trdInvcNo": obj[k] = ctx["trd_invc"]
                    elif k in ("cfmDt", "stockRlsDt", "rcptPbctDt"): obj[k] = ctx["cfm_dt"]
                    elif k == "ocrnDt": obj[k] = ctx["sales_dt"]
                    elif k == "salesDt": obj[k] = ctx["sales_dt"]
                    elif k == "pchsDt": obj[k] = ctx["sales_dt"]
                    elif k == "itemCd":
                        if step_name == "saveComponentItem":
                            if not ctx["component_cd"]:
                                hint = ctx["state"].get("kra_component_suffix_hint")
                                new_cd, new_suffix = generate_next_item_cd(
                                    COMPONENT_PREFIX, ctx["headers"], ctx["pin"], ctx["branch_id"], ctx["state"], hint
                                )
                                ctx["component_cd"] = new_cd
                                ctx["state"]["pending_component_suffix"] = new_suffix
                            obj[k] = ctx["component_cd"]
                        elif step_name in ("saveItem", "insertStockIOInitial", "insertStockIOPostComposition", "saveInvoice"):
                            if not ctx["item_cd"]:
                                hint = ctx["state"].get("kra_item_suffix_hint")
                                new_cd, new_suffix = generate_next_item_cd(
                                    PARENT_PREFIX, ctx["headers"], ctx["pin"], ctx["branch_id"], ctx["state"], hint
                                )
                                ctx["item_cd"] = new_cd
                                ctx["state"]["pending_parent_suffix"] = new_suffix
                            obj[k] = ctx["item_cd"]
                        elif step_name in ("insertTrnsPurchaseComponentStock", "saveStockMasterComponentPurchase", "insertStockIOComponentPurchase"):
                            obj[k] = ctx["component_cd"]
                        else:
                            if not ctx["item_cd"]:
                                raise Exception(f"item_cd missing for step {step_name}")
                            obj[k] = ctx["item_cd"]
                    elif k == "cpstItemCd":
                        obj[k] = ctx["component_cd"]
                    elif k == "sarNo":
                        obj[k] = get_next_sar_no(ctx["state"], ctx["pin"], ctx["branch_id"])
                else:
                    deep_replace(v, step_name, ctx)
        elif isinstance(obj, list):
            for item in obj:
                deep_replace(item, step_name, ctx)

    def prepare_payload(step_name, template):
        nonlocal item_cd, component_cd, import_update_row, import_lifecycle_ready
        nonlocal supplier_tin, supplier_bhf, supplier_name, supplier_invoice_no, supplier_tax_rates
        nonlocal current_stock_balance
        payload = json.loads(json.dumps(template))

        ctx = {
            "pin": pin, "branch_id": branch_id, "device_serial": device_serial,
            "invc_no": invc_no, "trd_invc": trd_invc,
            "cfm_dt": cfm_dt, "sales_dt": sales_dt,
            "state": state, "item_cd": item_cd, "component_cd": component_cd,
            "headers": headers,
        }
        deep_replace(payload, step_name, ctx)
        item_cd = ctx["item_cd"]
        component_cd = ctx["component_cd"]

        if "sarNo" in payload and "orgSarNo" in payload and payload["orgSarNo"] == 0:
            sar = payload["sarNo"]
            payload["orgSarNo"] = sar - 1 if sar > 1 else 0

        # ---- Tax handling for parent item steps ----
        if step_name == "saveItem":
            payload["taxTyCd"] = DEFAULT_ITEM_TAX_TYPE
        elif step_name in ("insertStockIOInitial", "insertStockIOPostComposition", "insertStockIO", "insertTrnsPurchase"):
            if item_cd:
                tax_info = get_item_tax_info(item_cd)
            else:
                tax_info = {"taxTyCd": DEFAULT_ITEM_TAX_TYPE, "taxRt": 16.0 if DEFAULT_ITEM_TAX_TYPE == "B" else 0.0}
            if isinstance(payload.get("itemList"), list) and len(payload["itemList"]) > 0:
                line = payload["itemList"][0]
                line["taxTyCd"] = tax_info["taxTyCd"]
                prc = line.get("prc", 100)
                qty = line.get("qty", 100) if "qty" in line else 1
                sply = float(prc) * float(qty)
                taxbl, tax, rate = compute_tax_amounts(sply, tax_info["taxTyCd"])
                line["splyAmt"] = sply
                line["taxblAmt"] = taxbl
                line["taxAmt"] = tax
                line["totAmt"] = sply
                for k in ["taxblAmtA","taxblAmtB","taxblAmtC","taxblAmtD","taxblAmtE"]:
                    payload[k] = 0.0
                for k in ["taxAmtA","taxAmtB","taxAmtC","taxAmtD","taxAmtE"]:
                    payload[k] = 0.0
                for k in ["taxRtA","taxRtB","taxRtC","taxRtD","taxRtE"]:
                    payload[k] = 0.0
                if tax_info["taxTyCd"] == "B":
                    payload["taxblAmtB"] = taxbl
                    payload["taxAmtB"] = tax
                    payload["taxRtB"] = rate
                else:
                    payload["taxblAmtA"] = taxbl
                    payload["taxAmtA"] = tax
                    payload["taxRtA"] = rate
                payload["totTaxblAmt"] = taxbl
                payload["totTaxAmt"] = tax
                payload["totAmt"] = sply

        # ---- Component purchase: dynamic supplier info + linked tax rates ----
        if step_name == "insertTrnsPurchaseComponentStock":
            if not supplier_invoice_no:
                raise Exception("No supplier invoice number captured from selectTrnsPurchaseSalesListPreComposition. "
                                "Ensure that step completed successfully and returned a sale row with spplrInvcNo.")
            payload["spplrTin"] = supplier_tin or ""
            payload["spplrBhfId"] = supplier_bhf or "00"
            payload["spplrNm"] = supplier_name or "Test Supplier"
            payload["invcNo"] = str(supplier_invoice_no)
            payload["requestedInvcNo"] = str(supplier_invoice_no)
            payload["spplrInvcNo"] = str(supplier_invoice_no)

            # Apply the linked tax rates from the supplier sale row.
            if supplier_tax_rates:
                print(f"  applying supplier tax rates: {supplier_tax_rates}")
                apply_link_tax_rt_to_purchase_payload(payload, supplier_tax_rates)
            else:
                # Fallback: Kenyan SBX defaults (the sale row should have these)
                payload["taxRtA"] = 0.0
                payload["taxRtB"] = 16.0
                payload["taxRtC"] = 0.0
                payload["taxRtD"] = 0.0
                payload["taxRtE"] = 0.0

            # Component item tax type is A (standard VAT, but may be exempt)
            if isinstance(payload.get("itemList"), list) and len(payload["itemList"]) > 0:
                line = payload["itemList"][0]
                line["taxTyCd"] = "A"
                line["pkg"] = 1
                line["qty"] = 1.0
                line["prc"] = 10.0
                sply = 10.0

                # Determine VAT rate from supplier (default 16% if not found)
                vat_rate = supplier_tax_rates.get("taxRtA", 16.0)
                tax_amount = round(sply * vat_rate / 100, 2)

                line["splyAmt"] = sply
                line["taxblAmt"] = sply
                line["taxAmt"] = tax_amount
                line["totAmt"] = sply

                # Header tax buckets: set only the A bucket
                for k in ["taxblAmtA","taxblAmtB","taxblAmtC","taxblAmtD","taxblAmtE"]:
                    payload[k] = 0.0
                for k in ["taxAmtA","taxAmtB","taxAmtC","taxAmtD","taxAmtE"]:
                    payload[k] = 0.0
                payload["taxblAmtA"] = sply
                payload["taxAmtA"] = tax_amount

                payload["totTaxblAmt"] = sply
                payload["totTaxAmt"] = tax_amount
                payload["totAmt"] = sply

                print(f"Component purchase: using supplier {supplier_tin}, invoice {supplier_invoice_no}, tax type A, sply={sply}, VAT rate={vat_rate}%, tax={tax_amount}")
                if supplier_tax_rates:
                    print(f"  linked tax rates: {supplier_tax_rates}")

        # ---- Component stock IO ----
        if step_name == "insertStockIOComponentPurchase":
            if isinstance(payload.get("itemList"), list) and len(payload["itemList"]) > 0:
                line = payload["itemList"][0]
                line["qty"] = 10.0
                line["pkg"] = 10.0
                prc = line.get("prc", 10.0)
                sply = prc * 10.0
                taxbl, tax, rate = compute_tax_amounts(sply, "A")
                line["splyAmt"] = sply
                line["taxblAmt"] = taxbl
                line["taxAmt"] = tax
                line["totAmt"] = sply
                payload["totTaxblAmt"] = taxbl
                payload["totTaxAmt"] = tax
                payload["totAmt"] = sply
        if step_name == "saveStockMasterComponentPurchase":
            payload["rsdQty"] = 10.0
            payload["itemCd"] = component_cd
            print(f"Component stock master: setting rsdQty=10 for {component_cd}")

        # ---- saveInvoice: query KRA for authoritative tax type (should be B) ----
        if step_name == "saveInvoice":
            if not item_cd:
                raise Exception("No item_cd available for invoice")
            kra_tax_type = get_item_tax_type_from_kra(item_cd, headers, pin, branch_id)
            if kra_tax_type is None:
                kra_tax_type = get_item_tax_info(item_cd).get("taxTyCd", DEFAULT_ITEM_TAX_TYPE)
                print(f"⚠️ Could not fetch tax type from KRA, using state value: {kra_tax_type}")
            else:
                print(f"✅ Retrieved item tax type from KRA: {kra_tax_type}")

            if kra_tax_type != "B":
                print(f"❌ ERROR: Item {item_cd} has tax type {kra_tax_type}, but sandbox normal sale requires 'B' (VAT).")
                print("   Please delete the item on the KRA portal or run with --reset-item to recreate it with correct tax type.")
                raise Exception(f"Item tax type mismatch: expected B, got {kra_tax_type}")

            if isinstance(payload.get("itemList"), list) and len(payload["itemList"]) > 0:
                line = payload["itemList"][0]
                line["taxTyCd"] = kra_tax_type
                prc = line.get("prc", 100)
                qty = line.get("qty", 1)
                sply = float(prc) * float(qty)
                taxbl, tax, rate = compute_tax_amounts(sply, kra_tax_type)
                line["splyAmt"] = sply
                line["taxblAmt"] = taxbl
                line["taxAmt"] = tax
                line["totAmt"] = sply
                for k in ["taxblAmtA","taxblAmtB","taxblAmtC","taxblAmtD","taxblAmtE"]:
                    payload[k] = 0.0
                for k in ["taxAmtA","taxAmtB","taxAmtC","taxAmtD","taxAmtE"]:
                    payload[k] = 0.0
                for k in ["taxRtA","taxRtB","taxRtC","taxRtD","taxRtE"]:
                    payload[k] = 0.0
                payload["taxblAmtB"] = taxbl
                payload["taxAmtB"] = tax
                payload["taxRtB"] = rate
                payload["totTaxblAmt"] = taxbl
                payload["totTaxAmt"] = tax
                payload["totAmt"] = sply
                print(f"saveInvoice: using tax_type={kra_tax_type}, sply={sply}, taxbl={taxbl}, tax={tax}")

        # For saveStockMaster steps, use tracked balance
        if step_name in ("saveStockMasterInitial", "saveStockMasterPostComposition", "saveStockMasterAfterPurchase", "saveStockMaster"):
            if "rsdQty" in payload:
                pass
            else:
                rsd = current_stock_balance
                payload["rsdQty"] = rsd
                payload["itemCd"] = item_cd
                print(f"{step_name}: using rsdQty={rsd} (tracked balance)")

        # Import handling (unchanged)
        if step_name in ("importedItemConvertedInfo", "updateImportItem"):
            if import_update_row and isinstance(import_update_row, dict):
                payload["taskCd"] = str(import_update_row.get("taskCd", "")).strip()
                payload["dclDe"] = str(import_update_row.get("dclDe", "")).strip()[:8]
                payload["hsCd"] = str(import_update_row.get("hsCd", "")).strip()
                payload["itemSeq"] = int(import_update_row.get("itemSeq", 1))
                payload["itemClsCd"] = state.get("item_cls_cd", "1010000000")
                payload["itemCd"] = item_cd
                print(f"Import payload populated: taskCd={payload['taskCd']}, dclDe={payload['dclDe']}, hsCd={payload['hsCd']}")
            else:
                print("WARNING: No import_update_row; using empty taskCd (will likely fail)")

        return payload

    i = 0
    while i < len(SEQUENCE):
        step_name, endpoint, template = SEQUENCE[i]
        # Special logic: before saveItemComposition, ensure component stock exists
        if step_name == "saveItemComposition":
            if component_cd:
                stock_qty = query_component_stock(component_cd, headers, pin, branch_id)
                if stock_qty is None or stock_qty <= 0:
                    print(f"⚠️ Component {component_cd} has no stock. Creating stock via insertStockIOComponentPurchase and saveStockMasterComponentPurchase...")
                    if "insertStockIOComponentPurchase" in completed:
                        completed.remove("insertStockIOComponentPurchase")
                        state["completed"] = completed
                        save_state(pin, state)
                    if "saveStockMasterComponentPurchase" in completed:
                        completed.remove("saveStockMasterComponentPurchase")
                        state["completed"] = completed
                        save_state(pin, state)

        if step_name in completed:
            print(f"SKIP {step_name} (already completed)")
            i += 1
            continue

        # Step guard: non‑idempotent steps should not be replayed if already succeeded
        if step_name == "saveItem" and state.get("item_cd"):
            print(f"SKIP {step_name} (item already exists: {state['item_cd']})")
            completed.append(step_name)
            state["completed"] = completed
            save_state(pin, state)
            i += 1
            continue
        if step_name == "saveComponentItem" and state.get("component_cd"):
            print(f"SKIP {step_name} (component already exists: {state['component_cd']})")
            completed.append(step_name)
            state["completed"] = completed
            save_state(pin, state)
            i += 1
            continue

        max_retries = 3
        payload = None
        for retry in range(max_retries):
            print(f"\n=== {step_name} ===")
            url = f"{BASE_URL}{endpoint}"
            payload = prepare_payload(step_name, template)

            # Only selectInvoiceType and selectTaxPayerInfo use query parameters
            if step_name in ("selectInvoiceType", "selectTaxPayerInfo"):
                query_params = {k: str(v) for k, v in payload.items() if v is not None}
                print(f"Using query parameters for {step_name}: {query_params}")
                resp = requests.post(url, headers=headers, params=query_params, timeout=60)
            else:
                resp = requests.post(url, headers=headers, json=payload, timeout=60)

            try:
                data = resp.json()
            except:
                data = {"error": resp.text}
            print("Response:", json.dumps(data, indent=2))

            if step_name in ("selectInvoiceType", "selectTaxPayerInfo") and isinstance(data, dict) and "fault" in data:
                if "targetPath" in str(data):
                    print(f"⚠️ {step_name} returned Apigee targetPath fault. Treating as soft skip.")
                    completed.append(step_name)
                    state["completed"] = completed
                    save_state(pin, state)
                    break

            result_cd = None
            debug_msg = None
            customer_msg = None
            if isinstance(data.get("responseBody"), dict):
                result_cd = data["responseBody"].get("resultCd")
                debug_msg = data["responseBody"].get("debugMessage", "")
            elif isinstance(data.get("responseHeader"), dict):
                debug_msg = data["responseHeader"].get("debugMessage", "")
                customer_msg = data["responseHeader"].get("customerMessage", "")

            # Handle itemCd sequence errors (saveItem / saveComponentItem)
            if step_name == "saveItem" and debug_msg and "Expected sequence ending with" in debug_msg:
                match = re.search(r"\*+(\d+)$", debug_msg)
                if match:
                    hinted_suffix = int(match.group(1))
                    last_digit = hinted_suffix % 10
                    state["kra_item_suffix_hint"] = last_digit
                    save_state(pin, state)
                    print(f"📌 KRA expects suffix ending with digit {last_digit}. Clearing itemCd and retrying.")
                    item_cd = ""
                    state["item_cd"] = ""
                    save_state(pin, state)
                    continue
            if step_name == "saveComponentItem" and debug_msg and "Expected sequence ending with" in debug_msg:
                match = re.search(r"\*+(\d+)$", debug_msg)
                if match:
                    hinted_suffix = int(match.group(1))
                    last_digit = hinted_suffix % 10
                    state["kra_component_suffix_hint"] = last_digit
                    save_state(pin, state)
                    print(f"📌 KRA expects component suffix ending with digit {last_digit}. Clearing component_cd and retrying.")
                    component_cd = ""
                    state["component_cd"] = ""
                    save_state(pin, state)
                    continue

            if debug_msg and "Invalid sarNo" in debug_msg and "Expected:" in debug_msg:
                print(f"⚠️ SAR error detected: {debug_msg}")
                if recover_sar_from_error(debug_msg, state, pin, branch_id):
                    print("🔄 State updated. Retrying...")
                    time.sleep(1)
                    continue
                else:
                    raise Exception(f"Could not parse expected SAR from: {debug_msg}")

            full_msg = f"{debug_msg} {customer_msg}"
            if step_name.startswith("saveStockMaster") and "rsdQty mismatch" in full_msg:
                match = re.search(r"Expected:\s*(\d+(?:\.\d+)?)", full_msg)
                if match:
                    expected = float(match.group(1))
                    print(f"🔄 rsdQty mismatch. KRA expects {expected}. Updating balance and retrying...")
                    current_stock_balance = expected
                    state["current_stock_balance"] = current_stock_balance
                    save_state(pin, state)
                    if retry + 1 < max_retries:
                        print(f"Retrying {step_name} (attempt {retry+2}/{max_retries})...")
                        time.sleep(1)
                        continue
                    else:
                        raise Exception(f"rsdQty mismatch after {max_retries} retries: {full_msg}")
                else:
                    raise Exception(f"rsdQty mismatch but cannot parse Expected: {full_msg}")

            if step_name == "initialize" and result_cd == "902":
                pass
            elif result_cd != "000":
                if step_name in ("selectInvoiceType", "selectTaxPayerInfo") and result_cd == "001":
                    print(f"CONTINUE: {step_name} returned resultCd=001 (empty, acceptable)")
                else:
                    raise Exception(f"resultCd={result_cd}")
            if resp.status_code >= 400:
                raise Exception(f"HTTP {resp.status_code}")

            break

        # Skip to next step if this was a soft-skip (targetPath fault)
        if step_name in ("selectInvoiceType", "selectTaxPayerInfo") and isinstance(data, dict) and "fault" in data and "targetPath" in str(data):
            i += 1
            continue

        # Update tracked balance after successful IO (IN only)
        if step_name in ("insertStockIOInitial", "insertStockIOPostComposition", "insertStockIO"):
            item_list = payload.get("itemList", [])
            if item_list and isinstance(item_list, list) and len(item_list) > 0:
                qty = item_list[0].get("qty", 0)
                ioty = item_list[0].get("ioTyCd", "1")
                if ioty == "1":
                    current_stock_balance += float(qty)
                else:
                    current_stock_balance -= float(qty)
            state["current_stock_balance"] = current_stock_balance
            save_state(pin, state)
            print(f"Stock balance updated to {current_stock_balance} after {step_name}")

        if step_name in ("saveStockMasterInitial", "saveStockMasterPostComposition", "saveStockMasterAfterPurchase", "saveStockMaster"):
            if "rsdQty" in payload:
                current_stock_balance = payload["rsdQty"]
                state["current_stock_balance"] = current_stock_balance
                save_state(pin, state)
                print(f"Stock balance confirmed as {current_stock_balance} after {step_name}")

        # Post‑success processing: capture supplier info from PreComposition step
        if step_name == "selectTrnsPurchaseSalesListPreComposition" and isinstance(data, dict):
            s_tin, s_bhf, s_name, s_inv, s_tax = extract_supplier_info_from_salelist(data)
            if s_tin and s_inv:
                supplier_tin = s_tin
                supplier_bhf = s_bhf
                supplier_name = s_name
                supplier_invoice_no = s_inv
                supplier_tax_rates = s_tax
                state["supplier_tin"] = supplier_tin
                state["supplier_bhf"] = supplier_bhf
                state["supplier_name"] = supplier_name
                state["supplier_invoice_no"] = supplier_invoice_no
                state["supplier_tax_rates"] = supplier_tax_rates
                print(f"✅ Captured supplier: {supplier_name} ({supplier_tin}), branch {supplier_bhf}, invoice: {supplier_invoice_no}")
            else:
                print("⚠️ No supplier sale found – component purchase will fail later.")
            save_state(pin, state)

        if step_name == "selectImportItemList" and isinstance(data, dict):
            rows_imp = extract_import_item_rows(data)
            cand = [r for r in rows_imp if str(r.get("taskCd") or "").strip()]
            if cand:
                import_update_row = {
                    "taskCd": str(cand[0].get("taskCd", "")).strip(),
                    "dclDe": str(cand[0].get("dclDe", "")).strip(),
                    "hsCd": str(cand[0].get("hsCd", "")).strip(),
                    "itemSeq": cand[0].get("itemSeq", 1),
                }
                import_lifecycle_ready = True
                state["import_update_row"] = import_update_row
                state["import_lifecycle_ready"] = True
                state["item_cls_cd"] = state.get("item_cls_cd", "1010000000")
                print(f"Stored import row from selectImportItemList: {import_update_row}")
            else:
                print("selectImportItemList returned no usable customs row with taskCd")
                import_lifecycle_ready = False
                state["import_lifecycle_ready"] = False
            save_state(pin, state)

        if step_name == "importedItemInfo" and isinstance(data, dict):
            rows_imp = extract_import_item_rows(data)
            cand = [r for r in rows_imp if str(r.get("taskCd") or "").strip()]
            if cand:
                import_update_row = {
                    "taskCd": str(cand[0].get("taskCd", "")).strip(),
                    "dclDe": str(cand[0].get("dclDe", "")).strip(),
                    "hsCd": str(cand[0].get("hsCd", "")).strip(),
                    "itemSeq": cand[0].get("itemSeq", 1),
                }
                import_lifecycle_ready = True
                state["import_update_row"] = import_update_row
                state["import_lifecycle_ready"] = True
                state["item_cls_cd"] = state.get("item_cls_cd", "1010000000")
                print(f"Stored import row from importedItemInfo: {import_update_row}")
            else:
                print("importedItemInfo returned no usable customs row with taskCd")
                if not import_update_row:
                    import_lifecycle_ready = False
                    state["import_lifecycle_ready"] = False
            save_state(pin, state)

        completed.append(step_name)
        state["completed"] = completed
        if step_name == "saveItem":
            state["item_cd"] = item_cd
            if item_cd.startswith(PARENT_PREFIX) and len(item_cd) == len(PARENT_PREFIX) + 7:
                try:
                    suffix = int(item_cd[-7:])
                    state["last_parent_suffix"] = suffix
                except ValueError:
                    pass
            if "items" not in state:
                state["items"] = {}
            state["items"][item_cd] = {"taxTyCd": DEFAULT_ITEM_TAX_TYPE, "taxRt": 16.0 if DEFAULT_ITEM_TAX_TYPE == "B" else 0.0}
            state.pop("kra_item_suffix_hint", None)
            state.pop("pending_parent_suffix", None)
            print(f"Saved item {item_cd} with tax type {DEFAULT_ITEM_TAX_TYPE}")
        if step_name == "saveComponentItem":
            state["component_cd"] = component_cd
            if "items" not in state:
                state["items"] = {}
            state["items"][component_cd] = {"taxTyCd": "A", "taxRt": 0.0}
            if component_cd.startswith(COMPONENT_PREFIX) and len(component_cd) == len(COMPONENT_PREFIX) + 7:
                try:
                    suffix = int(component_cd[-7:])
                    state["last_component_suffix"] = suffix
                except ValueError:
                    pass
            state.pop("kra_component_suffix_hint", None)
            state.pop("pending_component_suffix", None)
            print(f"Saved component {component_cd} with tax type A")
        if step_name in ("insertStockIOInitial", "insertStockIOPostComposition", "insertStockIO", "insertStockIOComponentPurchase"):
            used_sar = payload["sarNo"]
            update_sar_after_success(state, pin, branch_id, used_sar)
        if step_name == "saveInvoice":
            state["invc_no"] = int(payload["invcNo"]) + 1
        if step_name == "insertTrnsPurchaseComponentStock":
            state["component_purchased_qty"] = component_purchased_qty
        state["import_update_row"] = import_update_row
        state["import_lifecycle_ready"] = import_lifecycle_ready
        if supplier_tin and supplier_name and supplier_invoice_no:
            state["supplier_tin"] = supplier_tin
            state["supplier_bhf"] = supplier_bhf
            state["supplier_name"] = supplier_name
            state["supplier_invoice_no"] = supplier_invoice_no
            state["supplier_tax_rates"] = supplier_tax_rates
        save_state(pin, state)

        time.sleep(1)
        i += 1

    print("\n✅ All steps completed successfully!")

if __name__ == "__main__":
    main()