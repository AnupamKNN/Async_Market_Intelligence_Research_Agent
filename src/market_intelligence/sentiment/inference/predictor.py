# Imports and model loading

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import joblib


class SentimentPredictor:
    """Load and manage the trained sentiment classification model."""

    def __init__(self, artifact_path: str | Path) -> None:
        self.artifact_path = Path(artifact_path).expanduser()

        if not self.artifact_path.is_file():
            raise FileNotFoundError(f"Sentiment model artifact not found: {self.artifact_path}")

        # Load the saved model bundle

        bundle: Any = joblib.load(self.artifact_path)

        # Validate the structure of the loaded artifact.
        if not isinstance(bundle, dict):
            raise TypeError("Invalid model artifact: expected a dictionary.")

        required_keys = {"model", "vectorizer", "label_mapping"}
        missing_keys = required_keys.difference(bundle.keys())

        if missing_keys:
            raise ValueError(f"Invalid model artifact. Missing keys: {missing_keys}")

        # Store the components for reuse during inference.
        self.model = bundle["model"]
        self.vectorizer = bundle["vectorizer"]
        self.label_mapping = bundle["label_mapping"]

    # Input validation
    @staticmethod
    def _validate_text(text: str) -> str:
        """Validate and normalize a single text input."""

        if not isinstance(text, str):
            raise TypeError(f"Expected text input as str, received {type(text).__name__}.")

        text = text.strip()

        if not text:
            raise ValueError("Text input cannot be empty.")

        return text

    # Core prediction logic
    def _predict_validated(self, texts: list[str]) -> list[dict[str, Any]]:
        """Generate predictions for a list of already-validated texts."""

        # Convert input text into TF-IDF feature vectors.
        features = self.vectorizer.transform(texts)

        # Generate predicted class IDs
        predicted_ids = self.model.predict(features)

        # Generate probabilities for each class.
        probabilities = self.model.predict_proba(features)

        # Identify the column corresponding to the positive class (ID 1).
        class_ids = [int(class_id) for class_id in self.model.classes_]

        if len(class_ids) != 2 or 0 not in class_ids or 1 not in class_ids:
            raise ValueError(f"Expected binary classes [0, 1], received {class_ids}.")

        positive_class_index = class_ids.index(1)

        results = []

        for predicted_id, probability in zip(predicted_ids, probabilities, strict=True):
            label_id = int(predicted_id)
            positive_probability = float(probability[positive_class_index])

            results.append(
                {
                    "label_id": label_id,
                    "label": self.label_mapping[label_id],
                    "positive_probability": positive_probability,
                    "negative_probability": 1.0 - positive_probability,
                }
            )

        return results

    # Public prediction methods
    def predict(self, text: str) -> dict[str, Any]:
        """Predict sentiment for a single text."""

        validated_text = self._validate_text(text)

        return self._predict_validated([validated_text])[0]

    def predict_batch(self, texts: Sequence[str]) -> list[dict[str, Any]]:
        """Predict sentiment for multiple texts in one batch."""

        if isinstance(texts, str) or not isinstance(texts, Sequence):
            raise TypeError("Expected a sequence of text inputs.")

        validated_texts = [self._validate_text(text) for text in texts]

        if not validated_texts:
            return []

        return self._predict_validated(validated_texts)
