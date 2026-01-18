"""
Configuration settings for PharmaSight
"""
import os
from typing import Optional, List
from pydantic import field_validator
from pydantic_settings import BaseSettings


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
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Get CORS origins as a list"""
        if not self.CORS_ORIGINS:
            return ["http://localhost:3000", "http://localhost:5173"]
        # Split by comma and strip whitespace
        origins = [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]
        # If "*" is in the list, return ["*"] for allow all
        if "*" in origins:
            return ["*"]
        return origins if origins else ["http://localhost:3000", "http://localhost:5173"]
    
    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    class Config:
        env_file = [".env", "../.env"]  # Look in backend/ first, then parent directory
        case_sensitive = True


settings = Settings()

