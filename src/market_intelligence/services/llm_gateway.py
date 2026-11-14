"""Centralized LangChain LLM gateway through Portkey."""

from typing import Literal

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
) -> ChatOpenAI:
    """Create a LangChain chat model routed through Portkey."""

    headers = {"x-portkey-provider": provider}

    if provider == "ollama":
        api_key = "ollama"
        headers["x-portkey-custom-host"] = settings.ollama_base_url.rstrip("/")

    elif provider == "groq":
        if settings.groq_api_key is None:
            raise ValueError("GROQ_API_KEY is not configured.")

        api_key = settings.groq_api_key.get_secret_value()

        if not api_key.strip():
            raise ValueError("GROQ_API_KEY is empty.")

    elif provider == "openai":
        if settings.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is not configured.")

        api_key = settings.openai_api_key.get_secret_value()

        if not api_key.strip():
            raise ValueError("OPENAI_API_KEY is empty.")

    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")

    if max_completion_tokens is not None and max_completion_tokens < 1:
        raise ValueError("max_completion_tokens must be positive.")

    return ChatOpenAI(
        model=model,
        base_url=settings.portkey_base_url,
        api_key=api_key,
        temperature=temperature,
        default_headers=headers,
        max_completion_tokens=max_completion_tokens,
    )
