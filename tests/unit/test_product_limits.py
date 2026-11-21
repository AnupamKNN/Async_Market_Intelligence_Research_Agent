import pytest

from market_intelligence.services.product_limits import (
    DEFAULT_MAX_PRODUCT_LIMIT,
    DEFAULT_PRODUCT_LIMIT,
    resolve_product_limit,
)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Analyze retail sales trends.", 10),
        ("Identify top 5 products.", 5),
        ("Identify top 10 products.", 10),
        ("Identify the top ten products.", 10),
        ("Show the top twenty products by sales.", 20),
        ("Find the top twenty-five products.", 25),
        ("Show 15 products.", 15),
        ("Identify 7 best-selling products.", 7),
        ("Find the top 50 products.", 50),
        ("Find the top 100 products.", 100),
        ("Find the top 200 products.", 200),
        ("Find the top 500 products.", 500),
        ("Find the top 1000 products.", 1000),
        ("Identify top 100 products.", 100),
        ("Identify top 200 products.", 200),
        ("Identify top 500 products.", 500),
        ("Identify 7 best-selling products.", 7),
        ("Find 200 best-selling products.", 200),
    ],
)
def test_resolves_product_limit_from_question(question, expected):
    assert resolve_product_limit(question) == expected


@pytest.mark.parametrize(
    ("question", "explicit_limit", "expected"),
    [
        ("Find the top 10 products.", 5, 5),
        ("Find the top 5 products.", 20, 20),
        ("Analyze retail performance.", 30, 30),
    ],
)
def test_explicit_limit_takes_precedence(
    question,
    explicit_limit,
    expected,
):
    assert resolve_product_limit(question, explicit_limit) == expected


@pytest.mark.parametrize(
    "limit",
    [0, 10001, -1],
)
def test_rejects_invalid_explicit_limit(limit):
    with pytest.raises(ValueError):
        resolve_product_limit(
            "Find the top 10 products.",
            explicit_limit=limit,
        )


def test_default_product_limit_is_ten():
    assert DEFAULT_PRODUCT_LIMIT == 10


def test_default_maximum_product_limit():
    assert DEFAULT_MAX_PRODUCT_LIMIT == 10_000


def test_rejects_quantity_above_configured_maximum():
    with pytest.raises(ValueError, match="configured maximum"):
        resolve_product_limit(
            "Find the top 20000 products.",
            max_limit=10000,
        )


def test_accepts_large_quantity_when_configured():
    assert (
        resolve_product_limit(
            "Find the top 20000 products.",
            max_limit=25000,
        )
        == 20000
    )

def test_uses_configured_maximum():
    assert resolve_product_limit(
        "Find the top 200 products.",
        max_limit=250,
    ) == 200