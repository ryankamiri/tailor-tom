"""Google OAuth + JWT authentication routes.

Flow:
  1. Frontend redirects user to  GET /auth/google
  2. Backend redirects to Google consent screen
  3. Google redirects back to  GET /auth/google/callback?code=...&state=...
  4. Backend exchanges code for tokens, upserts user, issues JWT + refresh token
  5. Backend redirects to FRONTEND_URL with tokens in URL fragment

Refresh:
  POST /auth/refresh  — exchange a refresh token for a new access token

Profile:
  GET /auth/me  — returns the current user's profile (protected)
"""

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from api.cache import (
    get_user_profile_cache,
    set_user_profile_cache,
    invalidate_user_profile_cache,
)
from api.database import get_db
from api.db_models import User
from api.deps import CurrentUserIdentity, get_current_user, require_admin
from api.storage import get_redis_client
from tailor_tom.config import settings
from tailor_tom.constants import (
    DAILY_JOB_LIMIT,
    USER_SETTINGS_MAX_BULLET_LINES_MAX,
    USER_SETTINGS_MAX_BULLET_LINES_MIN,
    USER_SETTINGS_MAX_ITERATIONS_MAX,
    USER_SETTINGS_MAX_ITERATIONS_MIN,
    USER_SETTINGS_TARGET_PAGES_MAX,
    USER_SETTINGS_TARGET_PAGES_MIN,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

REFRESH_TOKEN_PREFIX = "refresh:"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_redirect_uri(request: Request) -> str:
    """Build the absolute callback URL from the current request."""
    # Use X-Forwarded-Proto if behind a reverse proxy
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", request.url.netloc)
    return f"{scheme}://{host}/auth/google/callback"


def _create_access_token(user_id: str, is_admin: bool = False) -> str:
    """Create a short-lived JWT access token (identity only; no DB needed to validate)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "is_admin": is_admin,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_expiration_minutes),
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _create_refresh_token(user_id: str) -> str:
    """Create a long-lived refresh token and store it in Redis.

    The token itself is a random hex string. We store a hash of it in Redis
    keyed by ``refresh:<hash>`` with the user_id as the value, and a TTL
    matching the configured refresh expiration.
    """
    token = secrets.token_hex(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    ttl_seconds = settings.jwt_refresh_expiration_days * 24 * 60 * 60
    redis = get_redis_client()
    redis.setex(
        f"{REFRESH_TOKEN_PREFIX}{token_hash}",
        ttl_seconds,
        user_id,
    )
    return token


def _validate_refresh_token(token: str) -> str | None:
    """Validate a refresh token against Redis.

    Returns the user_id if valid, None otherwise.
    """
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    redis = get_redis_client()
    user_id = redis.get(f"{REFRESH_TOKEN_PREFIX}{token_hash}")
    return user_id  # str or None


def _revoke_refresh_token(token: str) -> None:
    """Delete a refresh token from Redis."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    redis = get_redis_client()
    redis.delete(f"{REFRESH_TOKEN_PREFIX}{token_hash}")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/google")
async def google_login(request: Request):
    """Redirect the browser to Google's OAuth consent screen."""
    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth is not configured (GOOGLE_CLIENT_ID is missing)",
        )

    # Generate a random state param for CSRF protection
    state = secrets.token_urlsafe(32)

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": _build_redirect_uri(request),
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "state": state,
        "prompt": "consent",
    }
    url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    return RedirectResponse(url)


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str,
    state: str | None = None,
    db: Session = Depends(get_db),
):
    """Handle Google's OAuth callback.

    Exchanges the authorization code for tokens, extracts user info,
    upserts the user, issues JWT + refresh token, and redirects to the
    frontend with the tokens in the URL fragment.
    """
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth is not configured",
        )

    redirect_uri = _build_redirect_uri(request)

    # ---- Exchange code for tokens ----
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    if token_resp.status_code != 200:
        logger.error("Google token exchange failed: %s", token_resp.text)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to exchange authorization code with Google",
        )

    token_data = token_resp.json()
    id_token_raw = token_data.get("id_token")
    access_token_google = token_data.get("access_token")

    if not id_token_raw and not access_token_google:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No id_token or access_token received from Google",
        )

    # ---- Extract user info ----
    # Prefer decoding the id_token (no extra network call).
    # We skip signature verification here because we just received this token
    # directly from Google over HTTPS.
    user_info: dict = {}
    if id_token_raw:
        try:
            user_info = jwt.decode(
                id_token_raw,
                options={"verify_signature": False},
                algorithms=["RS256"],
            )
        except Exception:
            logger.warning("Could not decode id_token, falling back to userinfo endpoint")

    # Fallback: call the userinfo endpoint
    if not user_info.get("sub"):
        async with httpx.AsyncClient() as client:
            userinfo_resp = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token_google}"},
            )
        if userinfo_resp.status_code == 200:
            user_info = userinfo_resp.json()

    google_id = user_info.get("sub")
    if not google_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not determine Google user ID",
        )

    email = user_info.get("email", "")
    name = user_info.get("name")
    first_name = user_info.get("given_name")
    last_name = user_info.get("family_name")
    avatar_url = user_info.get("picture")

    # ---- Upsert user ----
    user = db.query(User).filter(User.google_id == google_id).first()
    if user:
        # Update mutable fields on every login
        user.email = email
        user.name = name
        user.first_name = first_name or user.first_name
        user.last_name = last_name or user.last_name
        user.avatar_url = avatar_url or user.avatar_url
    else:
        user = User(
            id=uuid.uuid4(),
            email=email,
            name=name,
            google_id=google_id,
            first_name=first_name,
            last_name=last_name,
            avatar_url=avatar_url,
        )
        db.add(user)

    db.commit()
    db.refresh(user)

    # ---- Issue our own tokens ----
    user_id_str = str(user.id)
    access_token = _create_access_token(user_id_str, is_admin=user.is_admin)
    refresh_token = _create_refresh_token(user_id_str)

    # ---- Redirect to frontend with tokens in URL fragment ----
    fragment = urlencode({
        "access_token": access_token,
        "refresh_token": refresh_token,
    })
    redirect_url = f"{settings.frontend_url}/auth/callback#{fragment}"
    return RedirectResponse(redirect_url)


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/refresh")
async def refresh_access_token(body: RefreshRequest, db: Session = Depends(get_db)):
    """Exchange a valid refresh token for a new access token.

    The old refresh token remains valid until it expires or is revoked.
    """
    user_id = _validate_refresh_token(body.refresh_token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Verify user still exists
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        _revoke_refresh_token(body.refresh_token)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )

    new_access_token = _create_access_token(str(user.id), is_admin=user.is_admin)
    return {"access_token": new_access_token, "token_type": "bearer"}


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


def _user_to_dict(user: User) -> dict:
    """Serialize a User row to the profile dict (only fields the frontend uses)."""
    today_utc = datetime.now(timezone.utc).date()
    daily_completions_today = (
        user.daily_completions_count
        if (
            user.daily_completions_date is not None
            and user.daily_completions_date == today_utc
        )
        else 0
    )
    total_used = daily_completions_today + user.active_jobs_count
    daily_limit_remaining = max(0, DAILY_JOB_LIMIT - total_used)
    return {
        "email": user.email,
        "name": user.name,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "avatar_url": user.avatar_url,
        "is_admin": user.is_admin,
        "resume_latex": user.resume_latex,
        "max_iterations": user.max_iterations,
        "target_pages": user.target_pages,
        "max_bullet_lines": user.max_bullet_lines,
        "daily_job_limit": DAILY_JOB_LIMIT,
        "daily_completions_today": daily_completions_today,
        "active_jobs_count": user.active_jobs_count,
        "daily_limit_remaining": daily_limit_remaining,
    }


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    """Return the authenticated user's profile (cache-aside)."""
    cached = get_user_profile_cache(str(current_user.id))
    if cached is not None:
        return cached
    profile = _user_to_dict(current_user)
    set_user_profile_cache(str(current_user.id), profile)
    return profile


class UpdateMeRequest(BaseModel):
    """Partial update for the authenticated user's editable fields."""
    resume_latex: str | None = None
    max_iterations: int | None = None
    target_pages: int | None = None
    max_bullet_lines: int | None = None


@router.patch("/me")
async def update_me(
    body: UpdateMeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the authenticated user's editable fields (partial update).

    Only provided (non-None) fields are written.  Returns the full
    updated profile in the same shape as ``GET /auth/me``.
    """
    if body.resume_latex is not None:
        current_user.resume_latex = body.resume_latex
    if body.max_iterations is not None:
        if not USER_SETTINGS_MAX_ITERATIONS_MIN <= body.max_iterations <= USER_SETTINGS_MAX_ITERATIONS_MAX:
            raise HTTPException(
                status_code=400,
                detail=f"max_iterations must be between {USER_SETTINGS_MAX_ITERATIONS_MIN} and {USER_SETTINGS_MAX_ITERATIONS_MAX}",
            )
        current_user.max_iterations = body.max_iterations
    if body.target_pages is not None:
        if not USER_SETTINGS_TARGET_PAGES_MIN <= body.target_pages <= USER_SETTINGS_TARGET_PAGES_MAX:
            raise HTTPException(
                status_code=400,
                detail=f"target_pages must be between {USER_SETTINGS_TARGET_PAGES_MIN} and {USER_SETTINGS_TARGET_PAGES_MAX}",
            )
        current_user.target_pages = body.target_pages
    if body.max_bullet_lines is not None:
        if not USER_SETTINGS_MAX_BULLET_LINES_MIN <= body.max_bullet_lines <= USER_SETTINGS_MAX_BULLET_LINES_MAX:
            raise HTTPException(
                status_code=400,
                detail=f"max_bullet_lines must be between {USER_SETTINGS_MAX_BULLET_LINES_MIN} and {USER_SETTINGS_MAX_BULLET_LINES_MAX}",
            )
        current_user.max_bullet_lines = body.max_bullet_lines

    db.commit()
    db.refresh(current_user)
    invalidate_user_profile_cache(str(current_user.id))
    return _user_to_dict(current_user)


@router.post("/me/reset-daily-count")
async def reset_my_daily_count(
    identity: CurrentUserIdentity = Depends(require_admin),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reset the authenticated admin's daily job completions count to 0 for today (UTC). Admin only."""
    today_utc = datetime.now(timezone.utc).date()
    current_user.daily_completions_date = today_utc
    current_user.daily_completions_count = 0
    db.commit()
    db.refresh(current_user)
    invalidate_user_profile_cache(str(current_user.id))
    return _user_to_dict(current_user)
