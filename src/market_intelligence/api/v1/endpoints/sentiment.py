from fastapi import APIRouter, HTTPException, Request, status

from market_intelligence.schemas.sentiment import (
    SentimentPredictionRequest,
    SentimentPredictionResponse,
)

router = APIRouter(
    prefix="/sentiment",
    tags=["Sentiment Analysis"],
)


@router.post(
    "/predict",
    response_model=SentimentPredictionResponse,
    status_code=status.HTTP_200_OK,
)
def predict_sentiment(
    payload: SentimentPredictionRequest,
    request: Request,
) -> SentimentPredictionResponse:
    """Predict the sentiment of a text review."""
    predictor = getattr(request.app.state, "sentiment_predictor", None)

    if predictor is None:
        raise HTTPException(
            tatus_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sentiment prediction service is unavailable.",
        )

    result = predictor.predict(payload.text)

    return SentimentPredictionResponse(**result)
