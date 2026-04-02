"""
Configuration settings for PharmaSight
"""
import os
from pathlib import Path
from typing import Optional, List
from pydantic import field_validator
from pydantic_settings import BaseSettings

# Resolve .env paths relative to this file so SMTP/email works regardless of cwd.
_CONFIG_DIR = Path(__file__).resolve().parent.parent  # backend/
_PHARMASIGHT_ROOT = _CONFIG_DIR.parent               # pharmasight/
_ENV_CANDIDATES = [
    _CONFIG_DIR / ".env",      # backend/.env
    _PHARMASIGHT_ROOT / ".env", # pharmasight/.env (your .env location)
]
_ENV_FILE = [str(p) for p in _ENV_CANDIDATES if p.is_file()]

# Load .env into os.environ so SMTP and other vars are set even if pydantic env_file is skipped.
try:
    import dotenv
    for p in _ENV_CANDIDATES:
        if p.is_file():
            dotenv.load_dotenv(p, override=False)
            break
except Exception:
    pass


def normalize_postgres_url(url: str) -> str:
    """Convert postgres:// to postgresql:// for SQLAlchemy (NoSuchModuleError: postgres)."""
    if not url:
        return url
    u = url.strip()
    if u.startswith("postgres://"):
        # IMPORTANT: keep the `//` intact; otherwise libpq/psycopg2 will think
        # there's no host and try a local unix socket (/var/run/postgresql/.s.PGSQL.5432).
        return u.replace("postgres://", "postgresql://", 1)
    return u


class Settings(BaseSettings):
    """Application settings"""
    
    # App
    APP_NAME: str = "PharmaSight"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    
    # Database (Supabase)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")  # Anon key (for frontend)
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")  # Service role key (admin, server-side only)
    # Storage routing mode:
    # - single_project (default): ignore tenant.supabase_storage_* and use env SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY
    # - tenant_project: allow tenant.supabase_storage_* overrides (legacy/per-tenant mode)
    STORAGE_MODE: str = os.getenv("STORAGE_MODE", "single_project").strip().lower()
    # Legacy migration fallback for stored tenant-assets paths that resolve via path tenant row.
    # Keep disabled by default to avoid silent reintroduction of per-tenant project behavior.
    ENABLE_LEGACY_PATH_TENANT_FALLBACK: bool = os.getenv("ENABLE_LEGACY_PATH_TENANT_FALLBACK", "false").lower() in ("true", "1", "yes")
    SUPABASE_DB_PASSWORD: str = os.getenv("SUPABASE_DB_PASSWORD", "")
    SUPABASE_DB_HOST: str = os.getenv("SUPABASE_DB_HOST", "db.kwvkkbofubsjiwqlqakt.supabase.co")
    SUPABASE_DB_NAME: str = os.getenv("SUPABASE_DB_NAME", "postgres")
    SUPABASE_DB_PORT: int = int(os.getenv("SUPABASE_DB_PORT", "5432"))
    SUPABASE_DB_USER: str = os.getenv("SUPABASE_DB_USER", "postgres")
    # Optional: Supabase project/account owner email. If set, this email cannot be used as tenant admin
    # (avoids "already registered" in Auth when same email is used for Supabase dashboard login).
    SUPABASE_OWNER_EMAIL: str = os.getenv("SUPABASE_OWNER_EMAIL", "").strip().lower()
    # Optional: verify Supabase JWTs for dual-auth (Project Settings -> API -> JWT Secret)
    SUPABASE_JWT_SECRET: str = os.getenv("SUPABASE_JWT_SECRET", "").strip()
    # Use Supabase pooler for tenant DBs when direct connection (IPv6) is unreachable (e.g. Render).
    # Set to true on Render; auto-enabled when RENDER=true.
    # When true, rewrites tenant db.xxx.supabase.co URLs to session pooler (IPv4-friendly).
    USE_SUPABASE_POOLER_FOR_TENANTS: bool = (
        os.getenv("USE_SUPABASE_POOLER_FOR_TENANTS", "").lower() in ("true", "1", "yes")
        or os.getenv("RENDER", "").lower() == "true"
    )
    # Session pooler host for tenant DBs (e.g. aws-1-eu-west-1.pooler.supabase.com).
    # If unset, derived from DATABASE_URL when it contains pooler.supabase.com.
    SUPABASE_POOLER_HOST: str = os.getenv("SUPABASE_POOLER_HOST", "").strip()

    @field_validator("STORAGE_MODE", mode="before")
    @classmethod
    def validate_storage_mode(cls, value: str) -> str:
        mode = (value or "single_project").strip().lower()
        if mode not in {"single_project", "tenant_project"}:
            return "single_project"
        return mode

    # Build connection string if not provided
    @property
    def database_connection_string(self) -> str:
        """Build database connection string. Normalizes postgres:// to postgresql:// for SQLAlchemy."""
        if self.DATABASE_URL:
            return normalize_postgres_url(self.DATABASE_URL)

        # Build from Supabase components
        return (
            f"postgresql://{self.SUPABASE_DB_USER}:{self.SUPABASE_DB_PASSWORD}"
            f"@{self.SUPABASE_DB_HOST}:{self.SUPABASE_DB_PORT}/{self.SUPABASE_DB_NAME}"
        )
    
    # CORS - parse from comma-separated string or use default
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173,http://localhost:8000,http://127.0.0.1:5500,http://127.0.0.1:3000"
    
    # Dev origins we always include so local frontend (different port) works even if CORS_ORIGINS is overridden
    _DEV_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Get CORS origins as a list. Always includes common dev origins so frontend on :3000 works."""
        if not self.CORS_ORIGINS:
            return list(dict.fromkeys(self._DEV_ORIGINS))  # dedupe, preserve order
        # Split by comma and strip whitespace
        origins = [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]
        # If "*" is in the list, we still can't use it with allow_credentials=True; use explicit list instead
        if "*" in origins:
            return list(dict.fromkeys(self._DEV_ORIGINS))
        # Always merge in dev origins so localhost:3000 is never blocked
        merged = list(dict.fromkeys(origins + self._DEV_ORIGINS))
        return merged if merged else list(dict.fromkeys(self._DEV_ORIGINS))
    
    # Email (tenant invites via SMTP)
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    EMAIL_FROM: str = os.getenv("EMAIL_FROM", "PharmaSight <noreply@pharmasight.com>")
    # Base URL for invite/password-reset links. Set to your public frontend URL (e.g. https://app.pharmasight.com)
    # so links work for recipients; if unset or localhost, links will point to localhost and fail for external users.
    APP_PUBLIC_URL: str = os.getenv("APP_PUBLIC_URL", "http://localhost:3000")

    # Single-DB mode: when no tenant row exists for DATABASE_URL, use this UUID for storage paths
    # (logo, stamp, signatures, PO PDFs). Set to a fixed UUID so logo/stamp upload works without
    # adding a row to the master tenants table. Leave empty to require a tenant row.
    DEFAULT_STORAGE_TENANT_ID: Optional[str] = os.getenv("DEFAULT_STORAGE_TENANT_ID", "").strip() or None

    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production")
    ALGORITHM: str = "HS256"
    # Access token lifetime (short for security; refresh used for long sessions)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    # Refresh token lifetime
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "14"))
    RESET_TOKEN_EXPIRE_MINUTES: int = 60

    # KRA eTIMS OSCU (OAuth: prefer ETIMS_APP_* from developer.go.ke; never store these in DB or expose to frontend)
    # Sandbox OSCU API root (Postman: https://sbx.kra.go.ke/etims-oscu/api/v1)
    ETIMS_SANDBOX_API_BASE: str = os.getenv(
        "ETIMS_SANDBOX_API_BASE", "https://sbx.kra.go.ke/etims-oscu/api/v1"
    ).rstrip("/")
    # Sandbox OAuth host only (token path /v1/token/generate); not the same prefix as OSCU on Apigee
    ETIMS_SANDBOX_OAUTH_BASE: str = os.getenv("ETIMS_SANDBOX_OAUTH_BASE", "https://sbx.kra.go.ke").rstrip(
        "/"
    )
    ETIMS_PRODUCTION_API_BASE: str = os.getenv(
        "ETIMS_PRODUCTION_API_BASE", "https://etims-api.kra.go.ke/etims-api"
    ).rstrip("/")
    # KRA developer portal app (Consumer Key / Consumer Secret) — use in .env locally and Render env secrets in prod
    ETIMS_APP_CONSUMER_KEY: str = os.getenv("ETIMS_APP_CONSUMER_KEY", "").strip()
    ETIMS_APP_CONSUMER_SECRET: str = os.getenv("ETIMS_APP_CONSUMER_SECRET", "").strip()
    # When "sandbox" or "production", overrides branch.environment for KRA API base + token path (single-tenant deploys)
    ETIMS_ENVIRONMENT: str = os.getenv("ETIMS_ENVIRONMENT", "").strip().lower()
    # Legacy names (optional fallback if ETIMS_APP_* not set)
    ETIMS_OAUTH_USERNAME: str = os.getenv("ETIMS_OAUTH_USERNAME", "").strip()
    ETIMS_OAUTH_PASSWORD: str = os.getenv("ETIMS_OAUTH_PASSWORD", "").strip()
    # VAT code mapping (override if sandbox code list differs)
    ETIMS_VAT_CAT_STANDARD: str = os.getenv("ETIMS_VAT_CAT_STANDARD", "A").strip() or "A"
    ETIMS_VAT_CAT_ZERO: str = os.getenv("ETIMS_VAT_CAT_ZERO", "B").strip() or "B"
    ETIMS_TAX_TY_STANDARD: str = os.getenv("ETIMS_TAX_TY_STANDARD", "V").strip() or "V"
    ETIMS_TAX_TY_ZERO: str = os.getenv("ETIMS_TAX_TY_ZERO", "B").strip() or "B"

    class Config:
        env_file = _ENV_FILE if _ENV_FILE else [".env", "../.env"]
        case_sensitive = True


settings = Settings()

# Production: SECRET_KEY must be set to a non-default value
if getattr(settings, "ENVIRONMENT", "development") == "production":
    if getattr(settings, "SECRET_KEY", "") == "change-me-in-production" or not (settings.SECRET_KEY or "").strip():
        raise RuntimeError(
            "SECRET_KEY must be set in production. Set ENVIRONMENT=production and a strong SECRET_KEY in your environment."
        )


def is_supabase_owner_email(email: str) -> bool:
    """
    True if email is the configured Supabase project/account owner (case-insensitive).
    When set, this email should not be used as tenant admin to avoid Auth conflicts.
    """
    owner = (getattr(settings, "SUPABASE_OWNER_EMAIL", None) or "").strip().lower()
    if not owner:
        return False
    return (email or "").strip().lower() == owner

