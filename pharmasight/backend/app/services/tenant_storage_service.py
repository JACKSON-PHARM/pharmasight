"""
Supabase Storage for tenant assets (logos, stamps, signatures, PO PDFs).

Supports company-based and user-based paths (no tenant required) plus legacy tenant paths:
- company-assets/{company_id}/logo.png, company-assets/{company_id}/stamp.png
- user-assets/{user_id}/signature.png
- tenant-assets/{tenant_id}/... (legacy; resolved by path or tenant)

Single bucket per prefix. When generating signed URLs or downloading, company-assets and user-assets
use global Supabase client (no tenant). tenant-assets can use tenant or, when tenant is None,
global client for backward compatibility.

Two modes for tenant-assets:
- Single project (default): Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in env.
- Per-tenant project: Optional. Store supabase_storage_url and supabase_storage_service_role_key
  on the Tenant row (master DB).

Never expose raw storage paths to frontend; use signed URLs (5–15 min expiry).
"""
import logging
from typing import Optional, Tuple, Any
from urllib.parse import urlparse, quote
from uuid import UUID
import httpx
from supabase import Client

from app.config import settings

logger = logging.getLogger(__name__)

BUCKET = "tenant-assets"
COMPANY_ASSETS_PREFIX = "company-assets/"
USER_ASSETS_PREFIX = "user-assets/"
TENANT_ASSETS_PREFIX = "tenant-assets/"
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
ALLOWED_IMAGE_CONTENT_TYPES = {"image/png", "image/jpeg"}
MAX_IMAGE_BYTES = 2 * 1024 * 1024  # 2MB
# Signed URL expiry: 5–15 min (10 min default). Never expose raw paths to frontend.
SIGNED_URL_EXPIRY_SECONDS = 600  # 10 minutes


def _tenant_storage_overrides_enabled() -> bool:
    """True only when explicitly running in tenant_project mode."""
    return (getattr(settings, "STORAGE_MODE", "single_project") or "single_project").strip().lower() == "tenant_project"


def _normalize_supabase_base_url(raw_url: str, *, source: str) -> str:
    """
    Normalize and validate Supabase project base URL.
    Expected format: https://<project-ref>.supabase.co
    """
    url = (raw_url or "").strip().strip('"').strip("'")
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        logger.warning("Supabase storage: invalid %s URL scheme", source)
        return ""
    if not parsed.netloc:
        logger.warning("Supabase storage: invalid %s URL host", source)
        return ""
    path = (parsed.path or "").strip("/")
    if path:
        logger.warning(
            "Supabase storage: %s URL contains path '%s'; use base project URL only (https://<ref>.supabase.co).",
            source,
            path,
        )
        return ""
    # Drop query/fragment if present; keep only scheme + host.
    return f"{parsed.scheme}://{parsed.netloc}"


def _build_effective_storage_config(tenant: Optional[Any] = None) -> Tuple[str, str]:
    """Return effective (url, key) based on storage mode and optional tenant."""
    tenant_url = ""
    tenant_key = ""
    if tenant and _tenant_storage_overrides_enabled():
        tenant_url = (getattr(tenant, "supabase_storage_url", None) or "").strip()
        tenant_key = (getattr(tenant, "supabase_storage_service_role_key", None) or "").strip()
    elif tenant and ((getattr(tenant, "supabase_storage_url", None) or "").strip() or (getattr(tenant, "supabase_storage_service_role_key", None) or "").strip()):
        logger.info("Supabase storage: tenant overrides present but ignored in single_project mode.")

    if tenant_key and (tenant_key.startswith("sb_secret_") or tenant_key.startswith("sb_publishable_")):
        logger.warning(
            "Supabase storage: tenant key is sb_secret_/sb_publishable_; using env SUPABASE_SERVICE_ROLE_KEY instead."
        )
        tenant_key = ""

    env_url = _normalize_supabase_base_url(getattr(settings, "SUPABASE_URL", "") or "", source="SUPABASE_URL")
    normalized_tenant_url = _normalize_supabase_base_url(tenant_url, source="tenant.supabase_storage_url") if tenant_url else ""
    url = normalized_tenant_url or env_url
    key = tenant_key or (settings.SUPABASE_SERVICE_ROLE_KEY or "").strip()

    # Supabase Storage REST expects a JWT for service-role auth.
    # Legacy service_role keys are JWTs starting with `eyJ...`.
    # If someone pastes the newer `sb_secret_...` key, Storage returns "Invalid Compact JWS".
    if key:
        if key.startswith(("sb_secret_", "sb_publishable_")):
            logger.warning(
                "Supabase storage: SUPABASE_SERVICE_ROLE_KEY looks like sb_secret_/sb_publishable_; using JWT service_role key is required."
            )
            key = ""
        elif not key.startswith("eyJ"):
            logger.warning(
                "Supabase storage: SUPABASE_SERVICE_ROLE_KEY does not look like a JWT (expected prefix 'eyJ'). Value prefix=%r",
                key[:8],
            )
            key = ""

    return (url, key)


def _create_signed_url_via_rest(
    *,
    base_url: str,
    service_role_key: str,
    bucket_name: str,
    object_path: str,
    expires_in: int,
) -> Optional[str]:
    """
    Direct Storage API fallback for signed URLs.
    Useful when storage3 SDK receives a non-JSON response and raises JSONDecodeError.
    """
    if not base_url or not service_role_key:
        return None
    # Supabase path params capture the "object name/path" including folders separated by `/`.
    # We should NOT encode the `/` separators; instead, encode each segment while preserving slashes.
    # Keep RFC3986 unreserved characters unencoded so UUIDs (with '-') match storage expectations.
    safe_bucket = quote((bucket_name or "").strip(), safe="-._~")
    raw_object = (object_path or "").lstrip("/")
    segments = [quote(seg, safe="-._~") for seg in raw_object.split("/") if seg != ""]
    encoded_object = "/".join(segments)
    endpoint = f"{base_url.rstrip('/')}/storage/v1/object/sign/{safe_bucket}/{encoded_object}"
    # Try with Authorization first; if it fails due to invalid JWS, retry without Authorization.
    headers = {
        **_storage_rest_auth_headers(service_role_key, include_authorization=True),
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(endpoint, headers=headers, json={"expiresIn": int(expires_in)})
        if resp.status_code >= 400:
            snippet = (resp.text or "")[:300]
            msg = ""
            try:
                msg = resp.json().get("message", "")  # type: ignore[union-attr]
            except Exception:
                msg = ""
            if "Invalid Compact JWS" in str(msg):
                headers = {
                    **_storage_rest_auth_headers(service_role_key, include_authorization=False),
                    "Content-Type": "application/json",
                }
                with httpx.Client(timeout=15.0) as client:
                    resp2 = client.post(endpoint, headers=headers, json={"expiresIn": int(expires_in)})
                if resp2.status_code >= 400:
                    snippet2 = (resp2.text or "")[:300]
                    logger.warning(
                        "storage REST sign failed status=%s endpoint=%s body=%r",
                        resp2.status_code,
                        endpoint,
                        snippet2,
                    )
                    return None
                resp = resp2
                snippet = snippet2 if 'snippet2' in locals() else snippet
            else:
                logger.warning(
                    "storage REST sign failed status=%s endpoint=%s body=%r",
                    resp.status_code,
                    endpoint,
                    snippet,
                )
                return None
        try:
            payload = resp.json() if resp.content else {}
        except Exception:
            snippet = (resp.text or "")[:300]
            logger.warning(
                "storage REST sign returned non-JSON status=%s endpoint=%s body=%r",
                resp.status_code,
                endpoint,
                snippet,
            )
            return None
        path = payload.get("signedURL") or payload.get("signedUrl") or payload.get("signed_url") or payload.get("url")
        if not path:
            logger.warning("storage REST sign response missing URL keys=%s", list(payload.keys()) if isinstance(payload, dict) else [])
            return None
        if isinstance(path, str) and (path.startswith("http://") or path.startswith("https://")):
            return path
        # Supabase often returns /storage/v1/object/sign/... so prefix base URL.
        return f"{base_url.rstrip('/')}{path if str(path).startswith('/') else '/' + str(path)}"
    except Exception as e:
        logger.warning("storage REST sign exception endpoint=%s err=%s", endpoint, e)
        return None


def _encode_storage_object_path_for_url(object_path: str) -> str:
    """
    Encode Supabase Storage object paths for URL path parameters.
    Preserves `/` separators while encoding each segment.
    """
    raw = (object_path or "").lstrip("/")
    segments = [quote(seg, safe="-._~") for seg in raw.split("/") if seg != ""]
    return "/".join(segments)


def _storage_rest_auth_headers(service_role_key: str, *, include_authorization: bool = True) -> dict:
    """
    Storage REST endpoints require service role JWT for private buckets.
    We send both Authorization and apikey for maximum compatibility.
    """
    anon_key = (getattr(settings, "SUPABASE_KEY", "") or "").strip()
    headers = {
        "apikey": anon_key or service_role_key,
    }
    if include_authorization:
        headers["Authorization"] = f"Bearer {service_role_key}"
    return headers


def _list_buckets_via_rest(*, base_url: str, service_role_key: str) -> Optional[list]:
    endpoint = f"{base_url.rstrip('/')}/storage/v1/bucket"
    # Some environments reject service-role key in Authorization; retry without Authorization on specific failure.
    headers = _storage_rest_auth_headers(service_role_key, include_authorization=True)
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(endpoint, headers=headers)
        if resp.status_code >= 400:
            msg = ""
            try:
                msg = resp.json().get("message", "")  # type: ignore[union-attr]
            except Exception:
                msg = ""
            if "Invalid Compact JWS" in str(msg):
                headers = _storage_rest_auth_headers(service_role_key, include_authorization=False)
                with httpx.Client(timeout=15.0) as client:
                    resp2 = client.get(endpoint, headers=headers)
                if resp2.status_code >= 400:
                    logger.warning(
                        "storage REST list buckets failed status=%s body=%r",
                        resp2.status_code,
                        (resp2.text or "")[:300],
                    )
                    return None
                return resp2.json() if resp2.content else []
            logger.warning("storage REST list buckets failed status=%s body=%r", resp.status_code, (resp.text or "")[:300])
            return None
        return resp.json() if resp.content else []
    except Exception as e:
        logger.warning("storage REST list buckets exception endpoint=%s err=%s", endpoint, e)
        return None


def _create_bucket_via_rest(*, base_url: str, service_role_key: str, bucket_name: str) -> bool:
    endpoint = f"{base_url.rstrip('/')}/storage/v1/bucket"
    headers = {**_storage_rest_auth_headers(service_role_key, include_authorization=True), "Content-Type": "application/json"}
    payload = {"name": bucket_name, "public": False}
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(endpoint, headers=headers, json=payload)
        if resp.status_code >= 400:
            msg = ""
            try:
                msg = resp.json().get("message", "")  # type: ignore[union-attr]
            except Exception:
                msg = ""
            if "Invalid Compact JWS" in str(msg):
                headers = {**_storage_rest_auth_headers(service_role_key, include_authorization=False), "Content-Type": "application/json"}
                with httpx.Client(timeout=15.0) as client:
                    resp2 = client.post(endpoint, headers=headers, json=payload)
                if resp2.status_code >= 400:
                    logger.warning("storage REST create bucket failed status=%s body=%r", resp2.status_code, (resp2.text or "")[:300])
                    return False
                return True
            logger.warning("storage REST create bucket failed status=%s body=%r", resp.status_code, (resp.text or "")[:300])
            return False
        return True
    except Exception as e:
        logger.warning("storage REST create bucket exception endpoint=%s err=%s", endpoint, e)
        return False


def _upload_object_via_rest(
    *,
    base_url: str,
    service_role_key: str,
    bucket_name: str,
    object_path: str,
    content: bytes,
    content_type: str,
) -> bool:
    endpoint = (
        f"{base_url.rstrip('/')}/storage/v1/object/{quote(bucket_name, safe='')}/{_encode_storage_object_path_for_url(object_path)}"
    )
    headers = {
        **_storage_rest_auth_headers(service_role_key, include_authorization=True),
        "Content-Type": content_type or "application/octet-stream",
        "x-upsert": "true",
        "cache-control": "0",
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(endpoint, headers=headers, content=content)
        if resp.status_code >= 400:
            msg = ""
            try:
                msg = resp.json().get("message", "")  # type: ignore[union-attr]
            except Exception:
                msg = ""
            if "Invalid Compact JWS" in str(msg):
                headers = {
                    **_storage_rest_auth_headers(service_role_key, include_authorization=False),
                    "Content-Type": content_type or "application/octet-stream",
                    "x-upsert": "true",
                    "cache-control": "0",
                }
                with httpx.Client(timeout=20.0) as client:
                    resp2 = client.post(endpoint, headers=headers, content=content)
                if resp2.status_code >= 400:
                    logger.warning(
                        "storage REST upload failed status=%s endpoint=%s body=%r",
                        resp2.status_code,
                        endpoint,
                        (resp2.text or "")[:300],
                    )
                    return False
                return True
            logger.warning("storage REST upload failed status=%s endpoint=%s body=%r", resp.status_code, endpoint, (resp.text or "")[:300])
            return False
        return True
    except Exception as e:
        logger.warning("storage REST upload exception endpoint=%s err=%s", endpoint, e)
        return False


def _download_object_authenticated_via_rest(
    *,
    base_url: str,
    service_role_key: str,
    bucket_name: str,
    object_path: str,
) -> Optional[bytes]:
    endpoint = (
        f"{base_url.rstrip('/')}/storage/v1/object/authenticated/{quote(bucket_name, safe='')}/{_encode_storage_object_path_for_url(object_path)}"
    )
    headers = _storage_rest_auth_headers(service_role_key, include_authorization=True)
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(endpoint, headers=headers)
        if resp.status_code >= 400:
            msg = ""
            try:
                msg = resp.json().get("message", "")  # type: ignore[union-attr]
            except Exception:
                msg = ""
            if "Invalid Compact JWS" in str(msg):
                headers = _storage_rest_auth_headers(service_role_key, include_authorization=False)
                with httpx.Client(timeout=20.0) as client:
                    resp2 = client.get(endpoint, headers=headers)
                if resp2.status_code >= 400:
                    logger.warning(
                        "storage REST download failed status=%s endpoint=%s body=%r",
                        resp2.status_code,
                        endpoint,
                        (resp2.text or "")[:300],
                    )
                    return None
                return resp2.content
            logger.warning(
                "storage REST download failed status=%s endpoint=%s body=%r",
                resp.status_code,
                endpoint,
                (resp.text or "")[:300],
            )
            return None
        return resp.content
    except Exception as e:
        logger.warning("storage REST download exception endpoint=%s err=%s", endpoint, e)
        return None


def _bucket_and_key(stored_path: str) -> Optional[Tuple[str, str]]:
    """
    Parse stored_path into (bucket_name, object_key) for company-assets, user-assets, or tenant-assets.
    Returns None if path is not a supported prefix.
    """
    if not stored_path or not isinstance(stored_path, str):
        return None
    path = stored_path.strip()
    if path.startswith(COMPANY_ASSETS_PREFIX):
        return ("company-assets", path[len(COMPANY_ASSETS_PREFIX):])
    if path.startswith(USER_ASSETS_PREFIX):
        return ("user-assets", path[len(USER_ASSETS_PREFIX):])
    if path.startswith(TENANT_ASSETS_PREFIX):
        return (BUCKET, path[len(TENANT_ASSETS_PREFIX):])
    return None


def tenant_id_from_stored_path(stored_path: str) -> Optional[str]:
    """
    Extract tenant_id (first path segment) from stored_path.
    Path format: tenant-assets/{tenant_id}/...
    Returns None if path is invalid or not tenant-scoped.
    Public so API can resolve legacy path tenant (e.g. post single-DB migration).
    """
    if not stored_path or not stored_path.startswith(BUCKET + "/"):
        return None
    rest = stored_path[len(BUCKET) + 1 :].strip()
    if not rest:
        return None
    parts = rest.split("/")
    return parts[0] if parts else None


def _tenant_id_from_stored_path(stored_path: str) -> Optional[str]:
    """Alias for tenant_id_from_stored_path (internal use)."""
    return tenant_id_from_stored_path(stored_path)


def _path_belongs_to_tenant(stored_path: str, tenant: Any) -> bool:
    """Return True only if stored_path is under tenant.id (prevents cross-tenant access)."""
    path_tenant_id = _tenant_id_from_stored_path(stored_path)
    if not path_tenant_id:
        return False
    try:
        return str(getattr(tenant, "id", None)) == path_tenant_id
    except Exception:
        return False


def _client(tenant: Optional[Any] = None) -> Optional[Client]:
    """
    Supabase client for storage.

    In single_project mode (default), always use global env SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY.
    In tenant_project mode, tenant.supabase_storage_* overrides are allowed.
    """
    url, key = _build_effective_storage_config(tenant)
    if not url or not key:
        return None
    try:
        from supabase import create_client
        url = url.rstrip("/") + "/"
        return create_client(url, key)
    except Exception as e:
        logger.warning("Supabase storage client: %s", e)
        return None


def path_logo(tenant_id: UUID) -> str:
    return f"{tenant_id}/logo.png"


def path_stamp(tenant_id: UUID) -> str:
    return f"{tenant_id}/stamp.png"


def path_company_logo(tenant_id: UUID, company_id: UUID) -> str:
    """Company-scoped logo so multiple companies in one tenant do not overwrite each other."""
    return f"{tenant_id}/companies/{company_id}/logo.png"


def path_company_stamp(tenant_id: UUID, company_id: UUID) -> str:
    """Company-scoped stamp so multiple companies in one tenant do not overwrite each other."""
    return f"{tenant_id}/companies/{company_id}/stamp.png"


def path_user_signature(tenant_id: UUID, user_id: UUID) -> str:
    return f"{tenant_id}/users/{user_id}/signature.png"


def path_po_pdf(tenant_id: UUID, po_id: UUID) -> str:
    return f"{tenant_id}/documents/purchase_orders/{po_id}.pdf"


def ensure_bucket(tenant: Optional[Any], bucket_name: Optional[str] = None) -> None:
    """
    Ensure the given bucket exists and is private. Idempotent.
    If bucket_name is None, uses BUCKET (tenant-assets).
    """
    name = bucket_name or BUCKET
    base_url, key = _build_effective_storage_config(tenant)
    if not base_url or not key:
        logger.warning("ensure_bucket: missing storage config; cannot ensure bucket %s", name)
        return

    buckets = _list_buckets_via_rest(base_url=base_url, service_role_key=key)
    if buckets is None:
        return
    bucket_names = []
    for b in buckets:
        # Supabase returns `id` and `name`; support either.
        bn = b.get("name") if isinstance(b, dict) else None
        if not bn and isinstance(b, dict):
            bn = b.get("id")
        if bn:
            bucket_names.append(bn)

    if name not in bucket_names:
        ok = _create_bucket_via_rest(base_url=base_url, service_role_key=key, bucket_name=name)
        if ok:
            logger.info("Created storage bucket %s (private)", name)


def validate_image_upload(
    content: bytes,
    content_type: str,
) -> Tuple[bool, str]:
    """
    Validate image upload: PNG/JPG only, max 2MB, content-type.
    Returns (ok, error_message).
    """
    if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        return False, f"Invalid content-type. Allowed: image/png, image/jpeg"
    if len(content) > MAX_IMAGE_BYTES:
        return False, "File too large. Maximum size is 2MB"
    if len(content) == 0:
        return False, "File is empty"
    return True, ""


def upload_file(
    tenant_id: UUID,
    file_path: str,
    content: bytes,
    content_type: str,
    *,
    validate_image: bool = False,
    tenant: Optional[Any] = None,
) -> Optional[str]:
    """
    Upload bytes to tenant-assets bucket at path {tenant_id}/{file_path}.
    Returns stored path for DB only (e.g. tenant-assets/{tenant_id}/stamp.png). Do not expose to frontend.
    If tenant has per-tenant Supabase storage credentials, uses that project; else global env.
    If validate_image=True, enforces PNG/JPG, 2MB, content-type.
    """
    if validate_image:
        ok, err = validate_image_upload(content, content_type)
        if not ok:
            return None
    base_url, key = _build_effective_storage_config(tenant)
    if not base_url or not key:
        return None
    ensure_bucket(tenant)
    # Enforced folder structure: tenant-assets/{tenant_id}/...
    relative = f"{tenant_id}/{file_path}" if not file_path.startswith(str(tenant_id)) else file_path
    ok = _upload_object_via_rest(
        base_url=base_url,
        service_role_key=key,
        bucket_name=BUCKET,
        object_path=relative,
        content=content,
        content_type=content_type,
    )
    if ok:
        return f"{BUCKET}/{relative}"

    # Fallback to SDK (kept as backup). Avoid raising: signed URL generation depends on this.
    try:
        # Only fallback when we still have a plausible JWT; otherwise SDK will also fail.
        if not (key and key.startswith("eyJ")):
            return None
        client = _client(tenant)
        if client:
            client.storage.from_(BUCKET).upload(
                relative,
                content,
                file_options={
                    "content-type": content_type,
                    "cacheControl": "0",
                    "x-upsert": "true",
                },
            )
            return f"{BUCKET}/{relative}"
    except Exception as e:
        logger.exception("upload_file SDK fallback %s: %s", relative, e)
    return None


def upload_logo(
    tenant_id: UUID,
    content: bytes,
    content_type: str,
    *,
    tenant: Optional[Any] = None,
    company_id: Optional[UUID] = None,
) -> Optional[str]:
    """Upload logo. Pass company_id so multiple companies in one tenant use separate paths."""
    ct = content_type or "image/png"
    if ct not in ALLOWED_IMAGE_CONTENT_TYPES:
        ct = "image/png"
    rel = f"companies/{company_id}/logo.png" if company_id is not None else "logo.png"
    return upload_file(tenant_id, rel, content, ct, validate_image=True, tenant=tenant)


def upload_stamp(
    tenant_id: UUID,
    content: bytes,
    content_type: str,
    *,
    tenant: Optional[Any] = None,
    company_id: Optional[UUID] = None,
) -> Optional[str]:
    """Upload stamp. Pass company_id so multiple companies in one tenant use separate paths."""
    ct = content_type or "image/png"
    if ct not in ALLOWED_IMAGE_CONTENT_TYPES:
        ct = "image/png"
    rel = f"companies/{company_id}/stamp.png" if company_id is not None else "stamp.png"
    return upload_file(tenant_id, rel, content, ct, validate_image=True, tenant=tenant)


def upload_user_signature(
    tenant_id: UUID,
    user_id: UUID,
    content: bytes,
    content_type: str,
    *,
    tenant: Optional[Any] = None,
) -> Optional[str]:
    ct = content_type or "image/png"
    if ct not in ALLOWED_IMAGE_CONTENT_TYPES:
        ct = "image/png"
    path = f"users/{user_id}/signature.png"
    return upload_file(tenant_id, path, content, ct, validate_image=True, tenant=tenant)


def upload_po_pdf(
    tenant_id: UUID, po_id: UUID, content: bytes, *, tenant: Optional[Any] = None
) -> Optional[str]:
    path = f"documents/purchase_orders/{po_id}.pdf"
    return upload_file(tenant_id, path, content, "application/pdf", tenant=tenant)


def download_file(stored_path: str, tenant: Optional[Any] = None) -> Optional[bytes]:
    """
    Download file bytes by stored path from Supabase.
    Paths: company-assets/{company_id}/..., user-assets/{user_id}/..., or tenant-assets/{tenant_id}/...
    For company-assets and user-assets no tenant is required (uses global client).
    For tenant-assets with tenant=None uses global client (backward compatibility).
    """
    parsed = _bucket_and_key(stored_path)
    if not parsed:
        return None
    bucket_name, object_path = parsed
    # tenant-assets: when tenant is set, enforce path belongs to tenant
    # In single_project mode, tenant-scoped prefix mismatches can happen after consolidation;
    # DB-level ownership checks are responsible for authorization, so we don't hard-fail here.
    if (
        bucket_name == BUCKET
        and tenant is not None
        and _tenant_storage_overrides_enabled()
        and not _path_belongs_to_tenant(stored_path, tenant)
    ):
        logger.warning("download_file: path tenant mismatch, refusing cross-tenant access: %s", stored_path[:80])
        return None
    # tenant-assets: enforce tenant match; otherwise use global env.
    effective_tenant = tenant if bucket_name == BUCKET and tenant is not None else None
    base_url, key = _build_effective_storage_config(effective_tenant)
    if not base_url or not key:
        return None
    ensure_bucket(effective_tenant, bucket_name=bucket_name)
    data = _download_object_authenticated_via_rest(
        base_url=base_url,
        service_role_key=key,
        bucket_name=bucket_name,
        object_path=object_path,
    )
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    return None


def download_file_with_path_tenant(
    stored_path: str, path_tenant: Any
) -> Optional[bytes]:
    """
    Download file using the tenant that owns the path (for legacy assets).
    Use when the stored_path is under a different tenant_id (e.g. pre-migration)
    but the document belongs to the current user's company. Caller must ensure
    the asset is scoped to the same company. path_tenant is the Tenant row for
    the tenant_id extracted from stored_path.
    """
    if not stored_path or not stored_path.startswith(BUCKET + "/"):
        return None
    base_url, key = _build_effective_storage_config(path_tenant)
    if not base_url or not key:
        return None
    try:
        object_path = stored_path[len(BUCKET) + 1:]
        data = _download_object_authenticated_via_rest(
            base_url=base_url,
            service_role_key=key,
            bucket_name=BUCKET,
            object_path=object_path,
        )
        return data if isinstance(data, bytes) else None
    except Exception as e:
        logger.warning("download_file_with_path_tenant %s: %s", stored_path, e)
        return None


def get_signed_url(
    stored_path: str,
    expires_in: int = SIGNED_URL_EXPIRY_SECONDS,
    tenant: Optional[Any] = None,
) -> Optional[str]:
    """
    Return signed URL for stored_path (company-assets/, user-assets/, or tenant-assets/).
    For company-assets and user-assets no tenant is required. For tenant-assets with tenant=None
    uses global client (backward compatibility). Path must be as stored in DB.
    """
    parsed = _bucket_and_key(stored_path)
    if not parsed:
        logger.warning("get_signed_url: unsupported path prefix: %s", stored_path[:80] if stored_path else "")
        return None
    bucket_name, object_path = parsed
    # In single_project mode, allow signing even if tenant id prefix doesn't match the resolved tenant row.
    # Authorization is enforced by the calling API via DB ownership checks (e.g. order.company_id).
    if (
        bucket_name == BUCKET
        and tenant is not None
        and _tenant_storage_overrides_enabled()
        and not _path_belongs_to_tenant(stored_path, tenant)
    ):
        logger.warning("get_signed_url: path tenant mismatch, refusing cross-tenant access: %s", stored_path[:80])
        return None
    effective_tenant = tenant if (bucket_name == BUCKET and tenant is not None) else None

    # REST-first: avoids storage3 SDK JSON parsing issues when Supabase returns a non-JSON body (HTML error page, etc).
    base_url, key = _build_effective_storage_config(effective_tenant)
    rest_url = _create_signed_url_via_rest(
        base_url=base_url,
        service_role_key=key,
        bucket_name=bucket_name,
        object_path=object_path,
        expires_in=expires_in,
    )
    if rest_url:
        return rest_url

    client = _client(effective_tenant) or _client(None)
    if not client:
        logger.warning("get_signed_url: Supabase client not available. Check SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY.")
        return None
    try:
        result = client.storage.from_(bucket_name).create_signed_url(object_path, expires_in)
        url = None
        if isinstance(result, dict):
            url = (
                result.get("signedURL")
                or result.get("signedUrl")
                or result.get("signed_url")
                or result.get("url")
            )
            if not url and result:
                logger.warning("get_signed_url: dict result has no signedUrl/signed_url; keys=%s", list(result.keys()))
        elif hasattr(result, "signed_url"):
            url = result.signed_url
        elif hasattr(result, "signedUrl"):
            url = result.signedUrl
        elif hasattr(result, "signedURL"):
            url = result.signedURL
        elif hasattr(result, "url"):
            url = result.url
        if not url:
            logger.warning("get_signed_url: could not extract URL from result type=%s", type(result).__name__)
        return url
    except Exception as e:
        logger.warning("get_signed_url %s: %s", stored_path, e, exc_info=True)
        return None


def get_signed_url_with_path_tenant(
    stored_path: str,
    path_tenant: Any,
    expires_in: int = SIGNED_URL_EXPIRY_SECONDS,
) -> Optional[str]:
    """
    Return signed URL using the tenant that owns the path (for legacy stored PDFs).
    Use when pdf_path is under a different tenant_id (e.g. pre single-DB migration).
    """
    if not stored_path or not stored_path.startswith(BUCKET + "/"):
        return None

    object_path = stored_path[len(BUCKET) + 1:]

    # REST-first for legacy path-tenant signing.
    base_url, key = _build_effective_storage_config(path_tenant)
    rest_url = _create_signed_url_via_rest(
        base_url=base_url,
        service_role_key=key,
        bucket_name=BUCKET,
        object_path=object_path,
        expires_in=expires_in,
    )
    if rest_url:
        return rest_url

    client = _client(path_tenant) or _client(None)
    if not client:
        return None
    try:
        result = client.storage.from_(BUCKET).create_signed_url(object_path, expires_in)
        url = None
        if isinstance(result, dict):
            url = (
                result.get("signedURL")
                or result.get("signedUrl")
                or result.get("signed_url")
                or result.get("url")
            )
        elif hasattr(result, "signed_url"):
            url = result.signed_url
        elif hasattr(result, "signedUrl"):
            url = result.signedUrl
        elif hasattr(result, "signedURL"):
            url = result.signedURL
        elif hasattr(result, "url"):
            url = result.url
        return url
    except Exception as e:
        logger.warning("get_signed_url_with_path_tenant %s: %s", stored_path, e)
        return None
