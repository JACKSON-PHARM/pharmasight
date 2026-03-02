"""
Database connection and session management
"""
from sqlalchemy import create_engine, pool
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings

_db_url = settings.database_connection_string
# Transaction mode (port 6543 / pgbouncer) does not support prepared statements
_use_pooler = ":6543" in _db_url or "pgbouncer=true" in _db_url.lower()
_connect_args = {
    "connect_timeout": 10,
    "options": "-c statement_timeout=120000",
}
if _use_pooler:
    _connect_args["prepare_threshold"] = None

# Create engine with connection pooling and timeout
engine = create_engine(
    _db_url,
    poolclass=pool.QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,  # Verify connections before using
    pool_recycle=3600,  # Recycle connections after 1 hour
    connect_args=_connect_args,
    echo=settings.DEBUG,
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db():
    """
    Dependency for FastAPI to get database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

