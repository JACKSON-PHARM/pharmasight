"""
selectInitOsdcInfo — OAuth device init and CMC key handling (aligned with gavaetims.py / kra_certify.py).

When no CMC is stored, POST without ``cmcKey`` header so KRA can return one in the response body.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple

import requests

from app.services.etims.branch_credentials import get_cmc_key_plain
from app.services.etims.constants import SELECT_INIT_OSDC_PATH
from app.services.etims.credential_crypto import encrypt_secret
from app.services.etims.etims_invoice_submitter import find_etims_result_cd

logger = logging.getLogger(__name__)

_INIT_TRANSIENT_HTTP = frozenset({502, 503, 504})
_DEFAULT_MAX_ATTEMPTS = 8
_DEFAULT_BACKOFF_SEC = 1.6


def extract_first_cmc_key(obj: Any) -> Optional[str]:
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


def extract_cmc_key_from_select_init_parsed(parsed: dict | list | str | None) -> Optional[str]:
    """``cmcKey`` from selectInitOsdcInfo — ``responseBody`` / ``body`` / nested ``data``, then deep scan."""
    if not isinstance(parsed, dict):
        return None
    for root_key in ("responseBody", "body"):
        blk = parsed.get(root_key)
        if not isinstance(blk, dict):
            continue
        ck = blk.get("cmcKey")
        if isinstance(ck, str) and ck.strip():
            return ck.strip()
        data = blk.get("data")
        if isinstance(data, dict):
            ck2 = data.get("cmcKey")
            if isinstance(ck2, str) and ck2.strip():
                return ck2.strip()
    return extract_first_cmc_key(parsed)


def _gateway_transient(resp: requests.Response | None, parsed: Any) -> bool:
    if resp is not None:
        try:
            if int(resp.status_code) in _INIT_TRANSIENT_HTTP:
                return True
        except (TypeError, ValueError):
            pass
    if not isinstance(parsed, dict):
        return False
    for hk in ("responseHeader", "header"):
        h = parsed.get(hk)
        if not isinstance(h, dict):
            continue
        rc = h.get("responseCode")
        try:
            ri = int(rc) if rc is not None else None
        except (TypeError, ValueError):
            continue
        if ri in _INIT_TRANSIENT_HTTP:
            return True
    return False


def build_select_init_headers(
    *,
    bearer_token: str,
    tin: str,
    bhf_id: str,
    dvc_serial: str,
    apigee_app_id: Optional[str],
    cmc_key_plain: Optional[str],
) -> Dict[str, str]:
    h: Dict[str, str] = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {(bearer_token or '').strip()}",
        "tin": (tin or "").strip(),
        "bhfId": (bhf_id or "").strip(),
        "dvcSrlNo": (dvc_serial or "").strip(),
    }
    aid = (apigee_app_id or "").strip()
    if aid:
        h["apigee_app_id"] = aid
    cmc = (cmc_key_plain or "").strip()
    if cmc:
        h["cmcKey"] = cmc
    return h


def post_select_init_osdc_info_with_retries(
    *,
    api_base: str,
    tin: str,
    bhf_id: str,
    dvc_serial: str,
    bearer_token: str,
    apigee_app_id: Optional[str],
    cmc_key_plain: Optional[str],
    timeout: int = 60,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    backoff_sec: float = _DEFAULT_BACKOFF_SEC,
) -> Tuple[requests.Response, Optional[dict]]:
    """
    POST ``selectInitOsdcInfo``. Retries on SBX gateway 502/503/504 (HTTP or envelope), like gavaetims.
    """
    url = f"{api_base.rstrip('/')}{SELECT_INIT_OSDC_PATH}"
    payload = {"tin": tin, "bhfId": bhf_id, "dvcSrlNo": dvc_serial}
    headers = build_select_init_headers(
        bearer_token=bearer_token,
        tin=tin,
        bhf_id=bhf_id,
        dvc_serial=dvc_serial,
        apigee_app_id=apigee_app_id,
        cmc_key_plain=cmc_key_plain,
    )
    last_resp: Optional[requests.Response] = None
    last_parsed: Optional[dict] = None
    attempt = 0
    while attempt < max_attempts:
        attempt += 1
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            logger.warning("selectInitOsdcInfo request error attempt=%s: %s", attempt, e)
            if attempt >= max_attempts:
                raise
            time.sleep(backoff_sec * attempt)
            continue
        last_resp = r
        parsed: Optional[dict] = None
        try:
            if (r.text or "").strip():
                j = r.json()
                parsed = j if isinstance(j, dict) else None
        except Exception:
            parsed = None
        last_parsed = parsed
        if _gateway_transient(r, parsed) and attempt < max_attempts:
            logger.info(
                "selectInitOsdcInfo transient gateway HTTP=%s attempt=%s/%s",
                r.status_code,
                attempt,
                max_attempts,
            )
            time.sleep(backoff_sec * attempt)
            continue
        return r, parsed
    assert last_resp is not None
    return last_resp, last_parsed


def summarize_select_init_probe(
    *,
    parsed: Optional[dict],
    response: requests.Response,
    creds: object,
) -> Dict[str, Any]:
    """
    If KRA returns ``cmcKey``, encrypt and assign to ``creds.cmc_key_encrypted``.
    """
    new_cmc = extract_cmc_key_from_select_init_parsed(parsed)
    cmc_extracted = False
    if new_cmc:
        creds.cmc_key_encrypted = encrypt_secret(new_cmc)
        cmc_extracted = True

    cmc_after = get_cmc_key_plain(creds).strip()
    rc = find_etims_result_cd(parsed) if isinstance(parsed, dict) else None
    http_ok = 200 <= response.status_code < 300
    # 902 = device already registered on SBX (gavaetims); still OK if we have or obtain CMC.
    envelope_ok = rc is None or rc in ("000", "902")
    verified = http_ok and envelope_ok and bool(cmc_after)

    return {
        "verified": verified,
        "http_ok": http_ok,
        "result_cd": rc,
        "envelope_ok": envelope_ok,
        "cmc_extracted_from_response": cmc_extracted,
        "has_cmc_key": bool(cmc_after),
    }
