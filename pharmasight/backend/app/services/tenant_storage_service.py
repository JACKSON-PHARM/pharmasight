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
from urllib.parse import urlparse
from uuid import UUID
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
    tenant_url = ""
    tenant_key = ""
    if tenant and _tenant_storage_overrides_enabled():
        tenant_url = (getattr(tenant, "supabase_storage_url", None) or "").strip()
        tenant_key = (getattr(tenant, "supabase_storage_service_role_key", None) or "").strip()
    elif tenant and ((getattr(tenant, "supabase_storage_url", None) or "").strip() or (getattr(tenant, "supabase_storage_service_role_key", None) or "").strip()):
        logger.info("Supabase storage: tenant overrides present but ignored in single_project mode.")

    # Python client requires JWT (eyJ...). If tenant row has sb_secret_/sb_publishable_, fall back to env.
    if tenant_key and (tenant_key.startswith("sb_secret_") or tenant_key.startswith("sb_publishable_")):
        logger.warning(
            "Supabase storage: tenant key is sb_secret_/sb_publishable_; using env SUPABASE_SERVICE_ROLE_KEY instead."
        )
        tenant_key = ""
    env_url = _normalize_supabase_base_url(getattr(settings, "SUPABASE_URL", "") or "", source="SUPABASE_URL")
    tenant_url = _normalize_supabase_base_url(tenant_url, source="tenant.supabase_storage_url") if tenant_url else ""
    url = tenant_url or env_url
    key = tenant_key or (settings.SUPABASE_SERVICE_ROLE_KEY or "").strip()
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


def ensure_bucket(client: Client, bucket_name: Optional[str] = None) -> None:
    """
    Ensure the given bucket exists and is private. Idempotent.
    If bucket_name is None, uses BUCKET (tenant-assets).
    """
    name = bucket_name or BUCKET
    try:
        buckets = client.storage.list_buckets()
        names = [b.name for b in (buckets or [])]
        if name not in names:
            client.storage.create_bucket(name, options={"private": True})
            logger.info("Created storage bucket %s (private)", name)
    except Exception as e:
        logger.warning("ensure_bucket %s: %s", name, e)


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
    client = _client(tenant)
    if not client:
        return None
    ensure_bucket(client)
    # Enforced folder structure: tenant-assets/{tenant_id}/...
    relative = f"{tenant_id}/{file_path}" if not file_path.startswith(str(tenant_id)) else file_path
    try:
        client.storage.from_(BUCKET).upload(
            relative,
            content,
            file_options={
                "content-type": content_type,
                # Prevent stale cached assets when overwriting the same key (e.g. stamp.png)
                # Supabase storage uses Cache-Control headers; 0 = no cache.
                "cacheControl": "0",
                "x-upsert": "true",
            },
        )
        return f"{BUCKET}/{relative}"
    except Exception as e:
        logger.exception("upload_file %s: %s", relative, e)
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
    if bucket_name == BUCKET and tenant is not None and not _path_belongs_to_tenant(stored_path, tenant):
        logger.warning("download_file: path tenant mismatch, refusing cross-tenant access: %s", stored_path[:80])
        return None
    client = _client(tenant) if (bucket_name == BUCKET and tenant is not None) else _client(None)
    if not client:
        client = _client(None)
    if not client:
        return None
    ensure_bucket(client, bucket_name)
    try:
        data = client.storage.from_(bucket_name).download(object_path)
        return data if isinstance(data, bytes) else None
    except Exception as e:
        logger.warning("download_file %s: %s", stored_path, e)
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
    client = _client(path_tenant)
    if not client:
        return None
    try:
        object_path = stored_path[len(BUCKET) + 1:]
        data = client.storage.from_(BUCKET).download(object_path)
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
    if bucket_name == BUCKET and tenant is not None and not _path_belongs_to_tenant(stored_path, tenant):
        logger.warning("get_signed_url: path tenant mismatch, refusing cross-tenant access: %s", stored_path[:80])
        return None
    client = _client(tenant) if (bucket_name == BUCKET and tenant is not None) else _client(None)
    if not client:
        client = _client(None)
    if not client:
        logger.warning(
            "get_signed_url: Supabase client not available. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
        )
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
    client = _client(path_tenant)
    if not client or not stored_path or not stored_path.startswith(BUCKET + "/"):
        return None
    try:
        object_path = stored_path[len(BUCKET) + 1:]
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
