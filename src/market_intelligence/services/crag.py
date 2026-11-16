from collections.abc import Mapping
from typing import Any

MAX_CRAG_RETRIES = 2


def assess_crag_quality(
    quality: Mapping[str, Any],
    *,
    include_external: bool,
    include_news: bool,
    planned_news_query: str | None,
    attempts: int,
) -> dict[str, Any]:
    """Decide whether retrieved external evidence needs corrective retrieval."""

    if not include_external:
        return {
            "status": "skipped",
            "should_retry": False,
            "reason": "External research was not requested.",
        }

    if int(quality.get("comparison_candidates", 0) or 0) > 0:
        return {
            "status": "sufficient",
            "should_retry": False,
            "reason": "Date-aligned comparison evidence is available.",
        }

    # Contextual evidence can still be useful even when it cannot
    # be compared directly with the dataset's historical window.
    assessments = quality.get("records", [])

    has_usable_context = any(
        isinstance(item, Mapping)
        and item.get("citation_valid")
        and (item.get("topical_relevance") or {}).get("status") == "matched"
        and (item.get("geographic_relevance") or {}).get("status") in {"matched", "not_requested"}
        for item in assessments
    )

    if has_usable_context:
        return {
            "status": "context_only",
            "should_retry": False,
            "reason": (
                "Relevant, citation-valid external context is available, "
                "but no date-aligned comparison candidate was found."
            ),
        }

    reason = (
        "No citation-valid, topically relevant, geographically acceptable "
        "external evidence was found."
    )

    if attempts >= MAX_CRAG_RETRIES:
        return {
            "status": "retry_exhausted",
            "should_retry": False,
            "reason": f"{reason} Maximum corrective retrieval attempts reached.",
        }

    if not include_news or not planned_news_query:
        return {
            "status": "insufficient",
            "should_retry": False,
            "reason": (
                f"{reason} No configured news retrieval query is available "
                "for corrective retrieval."
            ),
        }

    return {
        "status": "retry_required",
        "should_retry": True,
        "reason": reason,
    }


def build_corrective_news_query(
    *,
    question: str,
    original_query: str | None,
    target_geography: str | None,
    attempt: int,
    reason: str,
) -> str:
    """Broaden the news query while preserving its original research intent."""

    base = (original_query or question).strip()
    geography = (target_geography or "").strip()[:40]

    reason_lower = reason.lower()

    if attempt >= 2:
        focus = "sector outlook business conditions"
    elif "geograph" in reason_lower:
        focus = "regional market developments"
    elif "topic" in reason_lower:
        focus = "industry trends sector developments"
    else:
        focus = "industry trends market developments"

    fixed_parts = [part for part in (geography, focus) if part]
    fixed_text = " ".join(fixed_parts)

    available_base_length = 200 - len(fixed_text)
    if base and fixed_text:
        available_base_length -= 1

    base = base[: max(0, available_base_length)].strip()

    return " ".join(part for part in (base, fixed_text) if part)[:200]
