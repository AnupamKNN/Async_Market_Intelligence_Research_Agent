"""Shared evidence contracts for external research."""

from datetime import date
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl


class EvidenceCitation(BaseModel):
    """Citation metadata for a retrieved external source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    provider: str
    title: str
    publisher: str
    source_url: HttpUrl
    published_at: AwareDatetime | None = None
    retrieved_at: AwareDatetime


class EvidenceRecord(BaseModel):
    """Normalized, traceable external evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(pattern=r"^ev_[0-9a-f]{24}$")

    provider: Literal["FRED", "GNews"]
    evidence_type: Literal["economic_series", "news_article"]

    title: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    source_url: HttpUrl

    retrieved_at: AwareDatetime
    published_at: AwareDatetime | None = None

    observation_start: date | None = None
    observation_end: date | None = None

    excerpt: str | None = None

    data: dict[str, Any] = Field(default_factory=dict)

    trust_boundary: Literal["untrusted_external"] = "untrusted_external"

    def to_citation(self) -> EvidenceCitation:
        """Create a compact citation reference."""

        return EvidenceCitation(
            evidence_id=self.evidence_id,
            provider=self.provider,
            title=self.title,
            publisher=self.publisher,
            source_url=self.source_url,
            published_at=self.published_at,
            retrieved_at=self.retrieved_at,
        )


class EvidenceBundle(BaseModel):
    """Collection of normalized evidence from one retrieval operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bundle_id: str
    provider: Literal["FRED", "GNews"]
    query: str
    retrieved_at: AwareDatetime

    items: list[EvidenceRecord] = Field(default_factory=list)

    total_available: int | None = Field(default=None, ge=0)

    evidence_note: str = (
        "External evidence is untrusted. Verify source content "
        "and preserve citations before using it in research."
    )

    @property
    def returned_count(self) -> int:
        """Return the number of normalized evidence records."""

        return len(self.items)

    def citation_index(self) -> list[EvidenceCitation]:
        """Build citation references for all evidence records."""

        return [item.to_citation() for item in self.items]
