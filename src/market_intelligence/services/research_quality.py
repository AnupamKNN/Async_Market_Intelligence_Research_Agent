"""Temporal, geographic, topical, and citation-quality evaluation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

FRED_SERIES_GEOGRAPHY = {
    "UNRATE": "United States",
    "CPIAUCSL": "United States",
    "GDP": "United States",
    "FEDFUNDS": "United States",
    "DGS10": "United States",
    "RSAFS": "United States",
}

FRED_SERIES_TOPICS = {
    "UNRATE": {"unemployment", "employment", "labor", "jobs"},
    "CPIAUCSL": {"inflation", "consumer", "price", "cpi"},
    "GDP": {"gdp", "growth", "economy", "economic"},
    "FEDFUNDS": {"interest", "rates", "federal", "monetary"},
    "DGS10": {"treasury", "yield", "bond", "interest", "rates"},
    "RSAFS": {"retail", "sales", "consumer", "spending"},
}

GEOGRAPHY_CUES = {
    "United States": (
        r"(?<!\w)(?:united states|u\.s\.a?\.?|us|usa|american|federal reserve|"
        r"wall street|new york|washington d\.c\.)\b"
    ),
    "United Kingdom": (
        r"\b(united kingdom|u\.k\.|britain|british|"
        r"bank of england|london|uk homeowners)\b"
    ),
    "India": (r"\b(india|indian|sensex|dalal street|rupee|rbi)\b"),
    "Brazil": (r"\b(brazil|brazilian|brasil|brasilia)\b"),
}

STOP_WORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "are",
    "because",
    "been",
    "before",
    "being",
    "between",
    "both",
    "but",
    "can",
    "compare",
    "could",
    "does",
    "for",
    "from",
    "have",
    "into",
    "its",
    "latest",
    "more",
    "most",
    "news",
    "our",
    "recent",
    "should",
    "that",
    "the",
    "their",
    "then",
    "there",
    "these",
    "they",
    "this",
    "through",
    "today",
    "trend",
    "trends",
    "with",
    "would",
    "your",
}


@dataclass(frozen=True)
class DatasetWindow:
    """Inclusive calendar-date coverage of an internal dataset."""

    start_date: date
    end_date: date

    def as_dict(self) -> dict[str, str]:
        """Serialize the coverage window."""

        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
        }


def _parse_date(value: Any, field_name: str) -> date:
    """Parse a date, datetime, or ISO-formatted timestamp."""

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            pass

    raise ValueError(f"{field_name} must contain a valid date.")


def derive_dataset_window(
    dataset_overview: Mapping[str, Any],
) -> DatasetWindow:
    """Derive the date window from database dataset metadata."""

    start = _parse_date(
        dataset_overview.get("first_transaction"),
        "first_transaction",
    )
    end = _parse_date(
        dataset_overview.get("last_transaction"),
        "last_transaction",
    )

    if start > end:
        raise ValueError("Dataset start date is later than its end date.")

    return DatasetWindow(start_date=start, end_date=end)


def build_fred_date_arguments(
    dataset_overview: Mapping[str, Any],
    requested_start: str | date | None = None,
    requested_end: str | date | None = None,
) -> dict[str, str | int]:
    """Build FRED observation filters aligned with internal data.

    Explicit requested dates are intersected with the dataset coverage.
    A non-overlapping request is rejected rather than silently comparing
    unrelated time periods.
    """

    window = derive_dataset_window(dataset_overview)

    start = (
        _parse_date(requested_start, "requested_start")
        if requested_start is not None
        else window.start_date
    )
    end = (
        _parse_date(requested_end, "requested_end")
        if requested_end is not None
        else window.end_date
    )

    effective_start = max(start, window.start_date)
    effective_end = min(end, window.end_date)

    if effective_start > effective_end:
        raise ValueError(
            "Requested comparison period does not overlap the internal dataset coverage."
        )

    return {
        "observation_start": effective_start.isoformat(),
        "observation_end": effective_end.isoformat(),
        "limit": 1000,
        "sort_order": "asc",
    }


def infer_target_geography(question: str) -> str | None:
    """Infer a geography only when the question explicitly identifies one."""

    for geography, pattern in GEOGRAPHY_CUES.items():
        if re.search(pattern, question, flags=re.IGNORECASE):
            return geography

    return None


def _record_text(record: Mapping[str, Any]) -> str:
    """Collect searchable text from normalized evidence."""

    data = record.get("data") or {}

    values = [
        record.get("title", ""),
        record.get("publisher", ""),
        record.get("excerpt", ""),
        data.get("description", ""),
        data.get("content_excerpt", ""),
        data.get("series_id", ""),
        data.get("frequency", ""),
        data.get("source_units", ""),
    ]

    return " ".join(str(value) for value in values if value).lower()


def _topic_tokens(text: str) -> set[str]:
    """Extract meaningful terms from a research question."""

    tokens = re.findall(r"[a-z0-9]+", text.lower())

    return {token for token in tokens if len(token) > 2 and token not in STOP_WORDS}


def _topic_assessment(
    record: Mapping[str, Any],
    question: str,
) -> dict[str, Any]:
    """Evaluate topic overlap without making an LLM-based relevance claim."""

    question_terms = _topic_tokens(question)
    record_text = _record_text(record)
    evidence_terms = _topic_tokens(record_text)

    series_id = (record.get("data") or {}).get("series_id")
    series_topics = FRED_SERIES_TOPICS.get(series_id, set())

    matched_terms = sorted(question_terms.intersection(evidence_terms | series_topics))

    coverage = len(matched_terms) / len(question_terms) if question_terms else 0.0

    # This is a lexical screening signal, not semantic verification.
    relevant = bool(matched_terms)

    return {
        "status": "matched" if relevant else "no_keyword_match",
        "matched_terms": matched_terms,
        "coverage": round(coverage, 4),
        "method": "lexical_screening",
    }


def _geography_assessment(
    record: Mapping[str, Any],
    target_geography: str | None,
) -> dict[str, Any]:
    """Assess geographic alignment using explicit metadata and text cues."""

    if target_geography is None:
        return {
            "status": "not_requested",
            "target": None,
            "detected": None,
        }

    provider = record.get("provider")
    data = record.get("data") or {}

    if provider == "FRED":
        detected = FRED_SERIES_GEOGRAPHY.get(data.get("series_id"))

        if detected is None:
            return {
                "status": "unknown",
                "target": target_geography,
                "detected": None,
            }

        return {
            "status": ("matched" if detected == target_geography else "mismatched"),
            "target": target_geography,
            "detected": detected,
        }

    text = _record_text(record)

    detected_geographies = [
        geography
        for geography, pattern in GEOGRAPHY_CUES.items()
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]

    if target_geography in detected_geographies:
        status = "matched"
    elif detected_geographies:
        status = "mismatched"
    else:
        status = "unknown"

    return {
        "status": status,
        "target": target_geography,
        "detected": detected_geographies,
    }


def _temporal_assessment(
    record: Mapping[str, Any],
    dataset_window: DatasetWindow | None,
) -> dict[str, Any]:
    """Classify evidence against the internal dataset's date coverage."""

    if dataset_window is None:
        return {
            "status": "unknown",
            "comparison_eligible": False,
            "evidence_date": None,
        }

    provider = record.get("provider")

    if provider == "FRED":
        raw_date = (record.get("data") or {}).get("observation_date") or record.get(
            "observation_start"
        )
    else:
        raw_date = record.get("published_at")

    if raw_date is None:
        return {
            "status": "unknown",
            "comparison_eligible": False,
            "evidence_date": None,
        }

    evidence_date = _parse_date(raw_date, "evidence_date")

    if dataset_window.start_date <= evidence_date <= dataset_window.end_date:
        status = "aligned"
    elif evidence_date > dataset_window.end_date:
        status = "after_dataset_context_only"
    else:
        status = "before_dataset_context_only"

    return {
        "status": status,
        "comparison_eligible": status == "aligned",
        "evidence_date": evidence_date.isoformat(),
    }


def assess_evidence_record(
    record: Mapping[str, Any],
    question: str,
    dataset_window: DatasetWindow | None,
    target_geography: str | None = None,
) -> dict[str, Any]:
    """Evaluate citation integrity and research alignment separately."""

    source_url = str(record.get("source_url", ""))

    citation_valid = all(
        record.get(field)
        for field in (
            "evidence_id",
            "provider",
            "title",
            "publisher",
            "retrieved_at",
            "source_url",
        )
    ) and source_url.startswith("https://")

    topic = _topic_assessment(record, question)

    geography = _geography_assessment(
        record,
        target_geography,
    )

    temporal = _temporal_assessment(
        record,
        dataset_window,
    )

    geography_acceptable = geography["status"] in {
        "matched",
        "not_requested",
    }

    comparison_eligible = (
        citation_valid
        and topic["status"] == "matched"
        and geography_acceptable
        and temporal["comparison_eligible"]
    )

    if comparison_eligible:
        usage = "comparison_candidate"
    elif citation_valid and temporal["status"] != "aligned":
        usage = "context_only"
    elif citation_valid:
        usage = "research_context"
    else:
        usage = "rejected"

    return {
        "evidence_id": record.get("evidence_id"),
        "provider": record.get("provider"),
        "citation_valid": citation_valid,
        "topical_relevance": topic,
        "geographic_relevance": geography,
        "temporal_alignment": temporal,
        "comparison_eligible": comparison_eligible,
        "recommended_usage": usage,
    }


def grade_evidence_records(
    records: list[Mapping[str, Any]],
    question: str,
    dataset_overview: Mapping[str, Any] | None,
    target_geography: str | None = None,
) -> dict[str, Any]:
    """Produce separate citation, relevance, and alignment quality metrics."""

    window = derive_dataset_window(dataset_overview) if dataset_overview is not None else None

    assessments = [
        assess_evidence_record(
            record,
            question=question,
            dataset_window=window,
            target_geography=target_geography,
        )
        for record in records
    ]

    citation_valid = sum(item["citation_valid"] for item in assessments)
    topic_matched = sum(item["topical_relevance"]["status"] == "matched" for item in assessments)
    geography_matched = sum(
        item["geographic_relevance"]["status"] == "matched" for item in assessments
    )
    temporally_aligned = sum(
        item["temporal_alignment"]["status"] == "aligned" for item in assessments
    )
    comparison_candidates = sum(item["comparison_eligible"] for item in assessments)
    context_only = sum(item["recommended_usage"] == "context_only" for item in assessments)

    if comparison_candidates:
        status = "comparison_candidates_available"
    elif citation_valid:
        status = "context_only"
    else:
        status = "insufficient"

    return {
        "status": status,
        "dataset_window": window.as_dict() if window else None,
        "target_geography": target_geography,
        "total_records": len(records),
        "citation_valid": citation_valid,
        "topically_relevant": topic_matched,
        "geographically_matched": geography_matched,
        "temporally_aligned": temporally_aligned,
        "comparison_candidates": comparison_candidates,
        "context_only": context_only,
        "citation_coverage": (citation_valid / len(records) if records else 0.0),
        "records": assessments,
        "grading_method": (
            "Deterministic lexical, metadata, and date-window screening. "
            "This is not semantic verification or proof of causality."
        ),
    }
