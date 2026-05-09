"""Shared FastAPI dependencies for authentication and authorization."""

import logging
from typing import Optional
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from api.database import get_db
from api.db_models import User
from tailor_tom.config import settings

logger = logging.getLogger(__name__)

# OAuth2 scheme — extracts the token from the Authorization: Bearer <token> header.
# tokenUrl is a placeholder; the actual login flow is redirect-based (Google OAuth).
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/google", auto_error=True)
optional_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/google", auto_error=False)


# ---------------------------------------------------------------------------
# Identity (JWT-only, no DB) — use for ownership checks and admin gate
# ---------------------------------------------------------------------------

class CurrentUserIdentity:
    """Minimal auth result from JWT; no DB read. Use when route only needs user_id / is_admin."""

    def __init__(self, user_id: UUID, is_admin: bool):
        self.user_id = user_id
        self.is_admin = is_admin


def get_current_user_identity(token: str = Depends(oauth2_scheme)) -> CurrentUserIdentity:
    """Validate JWT and return user_id + is_admin. No DB read.
    Note: is_admin is from token claims; revoking admin in DB does not take effect until token expiry."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
        )
        user_id_raw: Optional[str] = payload.get("sub")
        if not user_id_raw:
            raise credentials_exception
        user_id = UUID(user_id_raw)
        is_admin = bool(payload.get("is_admin", False))
        return CurrentUserIdentity(user_id=user_id, is_admin=is_admin)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise credentials_exception
    except (ValueError, TypeError):
        raise credentials_exception


def get_optional_current_user_identity(
    token: Optional[str] = Depends(optional_oauth2_scheme),
) -> Optional[CurrentUserIdentity]:
    """Best-effort JWT identity for public routes that can attach user context."""
    if not token:
        return None
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
        )
        user_id_raw: Optional[str] = payload.get("sub")
        if not user_id_raw:
            return None
        return CurrentUserIdentity(
            user_id=UUID(user_id_raw),
            is_admin=bool(payload.get("is_admin", False)),
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Full user (DB read) — use only when route needs profile, limits, resume, etc.
# ---------------------------------------------------------------------------

def get_current_user(
    identity: CurrentUserIdentity = Depends(get_current_user_identity),
    db: Session = Depends(get_db),
) -> User:
    """Load the full User row from DB. Use when the route needs profile, limits, or resume."""
    user = db.query(User).filter(User.id == identity.user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_optional_current_user(
    identity: Optional[CurrentUserIdentity] = Depends(get_optional_current_user_identity),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Best-effort full user lookup for public routes. Invalid/missing auth returns None."""
    if identity is None:
        return None
    return db.query(User).filter(User.id == identity.user_id).first()


# ---------------------------------------------------------------------------
# require_admin — JWT-only admin check; no DB read
# ---------------------------------------------------------------------------

def require_admin(
    identity: CurrentUserIdentity = Depends(get_current_user_identity),
) -> CurrentUserIdentity:
    """Return identity only if is_admin is True; otherwise 403. No DB read.
    Admin status is JWT-claim based; use get_current_user and check user.is_admin for DB-authoritative check."""
    if not identity.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return identity
