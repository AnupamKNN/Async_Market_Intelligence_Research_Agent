"""Password hashing and authentication token utilities."""

import hashlib
import secrets

from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()

# Used to reduce timing differences for unknown email addresses.
DUMMY_PASSWORD_HASH = password_hash.hash("not-a-real-user-password")


def hash_password(password: str) -> str:
    """Hash a password using the recommended Argon2id configuration."""
    return password_hash.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against its stored password hash."""
    try:
        return password_hash.verify(password, stored_hash)
    except Exception:
        return False


def generate_token() -> str:
    """Generate a cryptographically secure opaque token."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Return the SHA-256 digest of a token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token(token: str, stored_hash: str) -> bool:
    """Constant-time comparison of a token against its stored digest."""
    return secrets.compare_digest(hash_token(token), stored_hash)
