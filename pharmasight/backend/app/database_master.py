"""
Master database connection for tenant management.

Stores tenant registry, subscriptions, provisioning metadata only. Never used
for operational queries (users, branches, stock, etc.). See ENV CONFIG LOCK.

Option A: same project as legacy app — set MASTER_DATABASE_URL = DATABASE_URL.
"""
from sqlalchemy import create_engine, pool
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings
import os

# Master database connection. Use MASTER_DATABASE_URL or fall back to app DB (Option A).
MASTER_DATABASE_URL = os.getenv(
    "MASTER_DATABASE_URL",
    settings.database_connection_string  # Default to same database, but we'll use different schema
)

# Create engine with connection pooling
master_engine = create_engine(
    MASTER_DATABASE_URL,
    poolclass=pool.QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=3600,
    connect_args={
        "connect_timeout": 10,
        "options": "-c statement_timeout=120000"
    },
    echo=settings.DEBUG,
)

# Session factory for master database
MasterSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=master_engine)

# Base class for master database models
MasterBase = declarative_base()


def get_master_db():
    """
    Dependency for FastAPI to get master database session
    """
    db = MasterSessionLocal()
    try:
        yield db
    finally:
        db.close()
