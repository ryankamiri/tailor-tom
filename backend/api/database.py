"""Database engine, session factory, and FastAPI dependency.

Uses sync SQLAlchemy (compatible with both FastAPI and Celery workers).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
from typing import Generator

from tailor_tom.config import settings


# ---------------------------------------------------------------------------
# Base class for all ORM models
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """Declarative base shared by every SQLAlchemy model."""
    pass


# ---------------------------------------------------------------------------
# Engine & session factory
# ---------------------------------------------------------------------------

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,       # verify connections before checkout
    pool_size=5,              # default pool size
    max_overflow=10,          # extra connections beyond pool_size
    echo=False,               # set True for SQL debug logging
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session and close it when the request finishes.

    Usage in a route::

        @router.get("/example")
        def example(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
