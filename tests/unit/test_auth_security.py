from market_intelligence.services.auth_security import (
    generate_token,
    hash_password,
    hash_token,
    verify_password,
    verify_token,
)


def test_password_hash_verification():
    password = "Correct-Horse-Battery-42"

    stored_hash = hash_password(password)

    assert stored_hash != password
    assert verify_password(password, stored_hash)
    assert not verify_password("incorrect-password", stored_hash)


def test_token_generation():
    first = generate_token()
    second = generate_token()

    assert first != second
    assert len(first) > 32


def test_token_hashing_and_verification():
    token = generate_token()
    digest = hash_token(token)

    assert digest != token
    assert verify_token(token, digest)
    assert not verify_token("different-token", digest)
