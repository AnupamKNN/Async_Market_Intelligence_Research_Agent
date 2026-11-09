from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SentimentPredictionRequest(BaseModel):
    """Request body for sentiment prediction."""

    text: str = Field(min_length=1, max_length=10_000)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        """Reject whitespace-only input and normalize surrounding whitespace."""

        value = value.strip()

        if not value:
            raise ValueError("Text cannot be empty or whitespace-only.")

        return value


class SentimentPredictionResponse(BaseModel):
    """Structured response from sentiment prediction."""

    label_id: Literal[0, 1]
    label: Literal["negative", "positive"]
    positive_probability: float = Field(ge=0, le=1)
    negative_probability: float = Field(ge=0, le=1)
