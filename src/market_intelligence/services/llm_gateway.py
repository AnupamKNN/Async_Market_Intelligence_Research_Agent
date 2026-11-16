"""Centralized provider-specific LangChain LLM gateway."""

from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from market_intelligence.core.config import Settings

Provider = Literal["ollama", "groq", "openai"]


def create_chat_model(
    settings: Settings,
    *,
    provider: Provider,
    model: str,
    temperature: float = 0.0,
    max_completion_tokens: int | None = None,
) -> BaseChatModel:
    """Create a provider-specific LangChain chat model."""

    if max_completion_tokens is not None and max_completion_tokens < 1:
        raise ValueError("max_completion_tokens must be positive.")

    if temperature < 0:
        raise ValueError("temperature cannot be negative.")

    # Ollama: direct local connection.
    if provider == "ollama":
        return ChatOllama(
            model=model,
            base_url=settings.ollama_base_url.rstrip("/"),
            temperature=temperature,
            num_predict=max_completion_tokens,
        )

    # Groq: direct Groq API connection.
    if provider == "groq":
        if settings.groq_api_key is None:
            raise ValueError("GROQ_API_KEY is not configured.")

        api_key = settings.groq_api_key.get_secret_value()

        if not api_key.strip():
            raise ValueError("GROQ_API_KEY is empty.")

        return ChatGroq(
            model=model,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_completion_tokens,
        )

    # OpenAI: direct OpenAI API connection.
    if provider == "openai":
        if settings.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is not configured.")

        api_key = settings.openai_api_key.get_secret_value()

        if not api_key.strip():
            raise ValueError("OPENAI_API_KEY is empty.")

        return ChatOpenAI(
            model=model,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_completion_tokens,
        )

    raise ValueError(f"Unsupported LLM provider: {provider}")
