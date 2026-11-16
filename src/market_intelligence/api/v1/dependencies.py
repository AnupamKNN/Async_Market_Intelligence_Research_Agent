import asyncpg
from fastapi import HTTPException, Request, status

from market_intelligence.db.repositories.auth import get_active_session
from market_intelligence.services.auth_security import hash_token, verify_token

SESSION_COOKIE = "mi_session"
CSRF_COOKIE = "mi_csrf"
CSRF_HEADER = "X-CSRF-Token"


async def get_authenticated_session(request: Request) -> asyncpg.Record:
    """Return the active authenticated session or reject the request."""

    token = request.cookies.get(SESSION_COOKIE)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    session = await get_active_session(
        request.app.state.db_pool,
        hash_token(token),
    )

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid.",
        )

    return session


def validate_csrf(request: Request, session: asyncpg.Record) -> None:
    """Validate the double-submit CSRF token against the session hash."""

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
