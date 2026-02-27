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


class Settings(BaseSettings):
    """Application settings"""
    
    # App
    APP_NAME: str = "PharmaSight"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    
    # Database (Supabase)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")  # Anon key (for frontend)
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")  # Service role key (admin, server-side only)
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

    # Build connection string if not provided
    @property
    def database_connection_string(self) -> str:
        """Build database connection string"""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        
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
    APP_PUBLIC_URL: str = os.getenv("APP_PUBLIC_URL", "http://localhost:3000")

    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production")
    ALGORITHM: str = "HS256"
    # Access token lifetime: extended for long pharmacy sessions (approx. 12 hours)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "720"))
    # Refresh token lifetime: extended to reduce re-logins while still bounded (approx. 60 days)
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "60"))
    RESET_TOKEN_EXPIRE_MINUTES: int = 60

    class Config:
        env_file = _ENV_FILE if _ENV_FILE else [".env", "../.env"]
        case_sensitive = True


settings = Settings()


def is_supabase_owner_email(email: str) -> bool:
    """
    True if email is the configured Supabase project/account owner (case-insensitive).
    When set, this email should not be used as tenant admin to avoid Auth conflicts.
    """
    owner = (getattr(settings, "SUPABASE_OWNER_EMAIL", None) or "").strip().lower()
    if not owner:
        return False
    return (email or "").strip().lower() == owner

