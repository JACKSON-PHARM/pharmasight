"""
Supabase Storage for tenant assets (logos, stamps, signatures, PO PDFs).

Two modes:
- Single project (default): Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in env.
  One bucket "tenant-assets"; isolation by path tenant-assets/{tenant_id}/...
- Per-tenant project: Optional. Store supabase_storage_url and supabase_storage_service_role_key
  on the Tenant row (master DB). When set, that tenant's storage uses their Supabase project
  (e.g. for different clients with their own Supabase). Same bucket name "tenant-assets" per project.

Never expose raw storage paths to frontend; use signed URLs (5–15 min expiry).
"""
import logging
from typing import Optional, Tuple, Any
from uuid import UUID
from supabase import Client

from app.config import settings

logger = logging.getLogger(__name__)

BUCKET = "tenant-assets"
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
ALLOWED_IMAGE_CONTENT_TYPES = {"image/png", "image/jpeg"}
MAX_IMAGE_BYTES = 2 * 1024 * 1024  # 2MB
# Signed URL expiry: 5–15 min (10 min default). Never expose raw paths to frontend.
SIGNED_URL_EXPIRY_SECONDS = 600  # 10 minutes


def _client(tenant: Optional[Any] = None) -> Optional[Client]:
    """
    Supabase client for storage. If tenant has supabase_storage_url and supabase_storage_service_role_key,
    use that project; otherwise use global SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.
    """
    url = None
    key = None
    if tenant:
        url = (getattr(tenant, "supabase_storage_url", None) or "").strip()
        key = (getattr(tenant, "supabase_storage_service_role_key", None) or "").strip()
    if not url or not key:
        url = (settings.SUPABASE_URL or "").strip()
        key = (settings.SUPABASE_SERVICE_ROLE_KEY or "").strip()
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


def path_user_signature(tenant_id: UUID, user_id: UUID) -> str:
    return f"{tenant_id}/users/{user_id}/signature.png"


def path_po_pdf(tenant_id: UUID, po_id: UUID) -> str:
    return f"{tenant_id}/documents/purchase_orders/{po_id}.pdf"


def ensure_bucket(client: Client) -> None:
    """
    Ensure the single shared bucket exists and is private. Idempotent.
    Do NOT create per-tenant buckets; all tenants share tenant-assets.
    """
    try:
        buckets = client.storage.list_buckets()
        names = [b.name for b in (buckets or [])]
        if BUCKET not in names:
            client.storage.create_bucket(BUCKET, options={"private": True})
            logger.info("Created single shared storage bucket %s (private)", BUCKET)
    except Exception as e:
        logger.warning("ensure_bucket %s: %s", BUCKET, e)


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
                "x-upsert": "true",
            },
        )
        return f"{BUCKET}/{relative}"
    except Exception as e:
        logger.exception("upload_file %s: %s", relative, e)
        return None


def upload_logo(
    tenant_id: UUID, content: bytes, content_type: str, *, tenant: Optional[Any] = None
) -> Optional[str]:
    ct = content_type or "image/png"
    if ct not in ALLOWED_IMAGE_CONTENT_TYPES:
        ct = "image/png"
    return upload_file(tenant_id, "logo.png", content, ct, validate_image=True, tenant=tenant)


def upload_stamp(
    tenant_id: UUID, content: bytes, content_type: str, *, tenant: Optional[Any] = None
) -> Optional[str]:
    ct = content_type or "image/png"
    if ct not in ALLOWED_IMAGE_CONTENT_TYPES:
        ct = "image/png"
    return upload_file(tenant_id, "stamp.png", content, ct, validate_image=True, tenant=tenant)


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
    """Download file bytes from tenant-assets by stored path. Pass tenant to use per-tenant Supabase."""
    client = _client(tenant)
    if not client or not stored_path or not stored_path.startswith(BUCKET + "/"):
        return None
    try:
        object_path = stored_path[len(BUCKET) + 1:]
        data = client.storage.from_(BUCKET).download(object_path)
        return data if isinstance(data, bytes) else None
    except Exception as e:
        logger.warning("download_file %s: %s", stored_path, e)
        return None


def get_signed_url(
    stored_path: str,
    expires_in: int = SIGNED_URL_EXPIRY_SECONDS,
    tenant: Optional[Any] = None,
) -> Optional[str]:
    """
    stored_path: e.g. tenant-assets/{tenant_id}/stamp.png (path stored in DB; never expose to frontend).
    Returns a signed URL for temporary read access. Pass tenant to use per-tenant Supabase project.
    """
    client = _client(tenant)
    if not client:
        logger.warning(
            "get_signed_url: Supabase client not available. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
        )
        return None
    if not stored_path or not stored_path.startswith(BUCKET + "/"):
        logger.warning("get_signed_url: invalid stored_path (expected %s/...): %s", BUCKET, stored_path[:80] if stored_path else "")
        return None
    try:
        object_path = stored_path[len(BUCKET) + 1:]
        result = client.storage.from_(BUCKET).create_signed_url(object_path, expires_in)
        url = None
        if isinstance(result, dict):
            url = result.get("signedUrl") or result.get("signed_url") or result.get("url")
            if not url and result:
                logger.warning("get_signed_url: dict result has no signedUrl/signed_url; keys=%s", list(result.keys()))
        elif hasattr(result, "signed_url"):
            url = result.signed_url
        elif hasattr(result, "signedUrl"):
            url = result.signedUrl
        elif hasattr(result, "url"):
            url = result.url
        if not url:
            logger.warning("get_signed_url: could not extract URL from result type=%s", type(result).__name__)
        return url
    except Exception as e:
        logger.warning("get_signed_url %s: %s", stored_path, e, exc_info=True)
        return None
