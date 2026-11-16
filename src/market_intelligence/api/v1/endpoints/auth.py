"""Email/password authentication API endpoints."""

import asyncio
from uuid import uuid4

import asyncpg
from fastapi import APIRouter, HTTPException, Request, Response, status
from redis.exceptions import RedisError

from market_intelligence.core.config import Settings
from market_intelligence.db.repositories.auth import (
    create_email_user,
    create_user_session,
    get_active_session,
    get_user_by_email,
    revoke_user_session,
    update_session_csrf,
)
from market_intelligence.schemas.auth import (
    AuthMessageResponse,
    AuthResponse,
    AuthUserResponse,
    LoginRequest,
    RegisterRequest,
)
from market_intelligence.services.auth_security import (
    DUMMY_PASSWORD_HASH,
    generate_token,
    hash_password,
    hash_token,
    verify_password,
    verify_token,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])

SESSION_COOKIE = "mi_session"
CSRF_COOKIE = "mi_csrf"
CSRF_HEADER = "X-CSRF-Token"


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _pool(request: Request) -> asyncpg.Pool:
    return request.app.state.db_pool


def _user_response(row: asyncpg.Record) -> AuthUserResponse:
    return AuthUserResponse(
        id=row["id"] if "id" in row else row["user_id"],
        email=row["email"],
        display_name=row["display_name"],
        email_verified=row["email_verified_at"] is not None,
        created_at=(row["created_at"] if "created_at" in row else row["user_created_at"]),
    )


def _set_auth_cookies(
    response: Response,
    settings: Settings,
    session_token: str,
    csrf_token: str,
) -> None:
    max_age = settings.auth_session_ttl_hours * 3600

    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_token,
        max_age=max_age,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )

    response.set_cookie(
        key=CSRF_COOKIE,
        value=csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_auth_cookies(response: Response, settings: Settings) -> None:
    for cookie in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(
            key=cookie,
            path="/",
            secure=settings.auth_cookie_secure,
            httponly=(cookie == SESSION_COOKIE),
            samesite="lax",
        )


async def _rate_limit(
    request: Request,
    scope: str,
    identity: str,
    limit: int,
    window_seconds: int,
) -> str:
    """Apply a Redis-backed fixed-window rate limit."""

    key = f"auth:rate:{scope}:{hash_token(identity)}"

    try:
        redis = request.app.state.redis
        count = await redis.incr(key)

        if count == 1:
            await redis.expire(key, window_seconds)

    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable.",
        ) from exc

    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please try again later.",
            headers={"Retry-After": str(window_seconds)},
        )

    return key


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _issue_session(
    request: Request,
    response: Response,
    user: asyncpg.Record,
) -> str:
    """Create a session and issue its cookies."""

    settings = _settings(request)
    session_token = generate_token()
    csrf_token = generate_token()

    await create_user_session(
        pool=_pool(request),
        session_id=uuid4(),
        user_id=user["id"],
        token_hash=hash_token(session_token),
        csrf_token_hash=hash_token(csrf_token),
        ttl_hours=settings.auth_session_ttl_hours,
    )

    _set_auth_cookies(
        response,
        settings,
        session_token,
        csrf_token,
    )

    return csrf_token


async def _require_session(request: Request) -> asyncpg.Record:
    token = request.cookies.get(SESSION_COOKIE)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    session = await get_active_session(
        _pool(request),
        hash_token(token),
    )

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid.",
        )

    return session


def _validate_csrf(request: Request, session: asyncpg.Record) -> None:
    cookie_token = request.cookies.get(CSRF_COOKIE)
    header_token = request.headers.get(CSRF_HEADER)

    if (
        not cookie_token
        or not header_token
        or cookie_token != header_token
        or not verify_token(cookie_token, session["csrf_token_hash"])
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed.",
        )


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
) -> AuthResponse:
    """Register an email/password account."""

    email = str(payload.email).strip().lower()
    ip = _client_ip(request)

    await _rate_limit(
        request,
        scope="register",
        identity=ip,
        limit=5,
        window_seconds=3600,
    )

    display_name = (
        payload.display_name.strip()
        if payload.display_name and payload.display_name.strip()
        else email.split("@", maxsplit=1)[0]
    )

    password_digest = await asyncio.to_thread(
        hash_password,
        payload.password,
    )

    try:
        user = await create_email_user(
            pool=_pool(request),
            user_id=uuid4(),
            email=email,
            display_name=display_name,
            password_hash=password_digest,
        )

    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from exc

    csrf_token = await _issue_session(request, response, user)

    return AuthResponse(
        user=_user_response(user),
        csrf_token=csrf_token,
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
) -> AuthResponse:
    """Authenticate an existing email/password account."""

    email = str(payload.email).strip().lower()
    ip = _client_ip(request)

    rate_key = await _rate_limit(
        request,
        scope="login",
        identity=f"{ip}:{email}",
        limit=10,
        window_seconds=900,
    )

    user = await get_user_by_email(_pool(request), email)

    candidate_hash = (
        user["password_hash"] if user is not None and user["password_hash"] else DUMMY_PASSWORD_HASH
    )

    valid_password = await asyncio.to_thread(
        verify_password,
        payload.password,
        candidate_hash,
    )

    if user is None or not user["is_active"] or not user["password_hash"] or not valid_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    try:
        await request.app.state.redis.delete(rate_key)
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable.",
        ) from exc

    csrf_token = await _issue_session(request, response, user)

    return AuthResponse(
        user=_user_response(user),
        csrf_token=csrf_token,
    )


@router.get("/me", response_model=AuthResponse)
async def get_current_user(
    request: Request,
    response: Response,
) -> AuthResponse:
    """Return the authenticated user and refresh the CSRF token if needed."""

    session = await _require_session(request)

    csrf_token = request.cookies.get(CSRF_COOKIE)

    if not csrf_token or not verify_token(csrf_token, session["csrf_token_hash"]):
        csrf_token = generate_token()

        await update_session_csrf(
            _pool(request),
            session["session_id"],
            hash_token(csrf_token),
        )

        settings = _settings(request)

        response.set_cookie(
            key=CSRF_COOKIE,
            value=csrf_token,
            max_age=settings.auth_session_ttl_hours * 3600,
            httponly=False,
            secure=settings.auth_cookie_secure,
            samesite="lax",
            path="/",
        )

    return AuthResponse(
        user=_user_response(session),
        csrf_token=csrf_token,
    )


@router.post("/logout", response_model=AuthMessageResponse)
async def logout(
    request: Request,
    response: Response,
) -> AuthMessageResponse:
    """Revoke the current session and clear authentication cookies."""

    session = await _require_session(request)
    _validate_csrf(request, session)

    await revoke_user_session(
        _pool(request),
        session["session_id"],
    )

    _clear_auth_cookies(response, _settings(request))

    return AuthMessageResponse(message="Successfully signed out.")
