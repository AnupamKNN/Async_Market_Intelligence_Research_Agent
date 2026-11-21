"""Resolve product retrieval limits from research questions."""

from __future__ import annotations

import re

DEFAULT_PRODUCT_LIMIT = 10
DEFAULT_MAX_PRODUCT_LIMIT = 10_000
MIN_PRODUCT_LIMIT = 1

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
}

_NUMBER_PATTERN = (
    r"(?:\d+|"
    r"one|two|three|four|five|six|seven|eight|nine|"
    r"ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|"
    r"twenty(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?|"
    r"thirty(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?|"
    r"forty(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?|"
    r"fifty)"
)

_PRODUCT_PATTERNS = [
    re.compile(
        rf"\b(?:top|best[- ]selling|highest[- ]selling|most popular)"
        rf"\s+(?P<count>{_NUMBER_PATTERN})"
        rf"(?:\s+(?:best[- ]selling|highest[- ]selling|popular))?"
        rf"\s+(?:of\s+the\s+)?(?:products?|items?|skus?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?P<count>{_NUMBER_PATTERN})"
        rf"\s+(?:(?:best[- ]selling|highest[- ]selling|popular)\s+)?"
        rf"(?:products?|items?|skus?)\b",
        re.IGNORECASE,
    ),
]


def _parse_count(value: str) -> int | None:
    """Parse numeric and English number expressions."""

    normalized = value.lower().replace("-", " ").strip()

    if normalized.isdigit():
        return int(normalized)

    parts = normalized.split()

    if len(parts) == 1:
        return _NUMBER_WORDS.get(parts[0])

    if len(parts) == 2:
        tens = _NUMBER_WORDS.get(parts[0])
        units = _NUMBER_WORDS.get(parts[1])

        if tens in {20, 30, 40} and units is not None and 1 <= units <= 9:
            return tens + units

    return None


def resolve_product_limit(
    question: str,
    explicit_limit: int | None = None,
    *,
    max_limit: int = DEFAULT_MAX_PRODUCT_LIMIT,
) -> int:
    """
    Resolve the number of records to retrieve.

    Precedence:
    1. Explicit API limit.
    2. Quantity expressed in the research question.
    3. Default product limit.

    Never silently truncate an explicitly requested quantity.
    """

    if max_limit < MIN_PRODUCT_LIMIT:
        raise ValueError("max_limit must be at least 1.")

    if explicit_limit is not None:
        if not MIN_PRODUCT_LIMIT <= explicit_limit <= max_limit:
            raise ValueError(
                f"product_limit must be between "
                f"{MIN_PRODUCT_LIMIT} and {max_limit}."
            )

        return explicit_limit

    for pattern in _PRODUCT_PATTERNS:
        match = pattern.search(question)

        if match:
            count = _parse_count(match.group("count"))

            if count is not None:
                if count > max_limit:
                    raise ValueError(
                        f"Requested result count {count} exceeds "
                        f"the configured maximum of {max_limit}."
                    )

                return max(MIN_PRODUCT_LIMIT, count)

    return DEFAULT_PRODUCT_LIMIT