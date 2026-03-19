"""Model factory — provider-agnostic embedding and LLM clients.

Adding a new provider:
  1. Subclass EmbeddingClient and implement embed() + dimensions.
  2. Register in _EMBEDDING_CLIENTS.
  3. Add an LLM case to get_llm().
  4. Add <provider>_api_key to Settings (config.py).
  5. Set EMBEDDING_PROVIDER=<name> and LLM_PROVIDER=<name> in .env.

Switching providers requires a full re-index because embedding dimensions
differ between providers (e.g. mistral-embed=1024, text-embedding-3-small=1536).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


# ---------------------------------------------------------------------------
# Embedding interface
# ---------------------------------------------------------------------------

class EmbeddingClient(ABC):
    """Common interface for all embedding providers."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text, preserving input order."""
        ...

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Dimensionality of the embedding vectors this client produces."""
        ...


# ---------------------------------------------------------------------------
# Concrete implementations
# ---------------------------------------------------------------------------

class MistralEmbeddingClient(EmbeddingClient):
    """Mistral AI — mistral-embed (1024 dimensions)."""

    def __init__(self, api_key: str) -> None:
        from mistralai.client import Mistral
        self._client = Mistral(api_key=api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model="mistral-embed", inputs=texts)
        return [item.embedding for item in response.data]

    @property
    def dimensions(self) -> int:
        return 1024


class OpenAIEmbeddingClient(EmbeddingClient):
    """OpenAI — text-embedding-3-small (1536 dimensions)."""

    def __init__(self, api_key: str) -> None:
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(
            model="text-embedding-3-small", input=texts
        )
        return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]

    @property
    def dimensions(self) -> int:
        return 1536


# Registry — add new providers here
_EMBEDDING_CLIENTS: dict[str, type[EmbeddingClient]] = {
    "mistral": MistralEmbeddingClient,
    "openai": OpenAIEmbeddingClient,
}


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------

def get_embedding_client() -> EmbeddingClient:
    """Instantiate and return the configured embedding client.

    Reads EMBEDDING_PROVIDER from settings. The matching <provider>_api_key
    field is resolved dynamically so no code change is needed when adding
    a provider that follows the naming convention.
    """
    from app.config import get_settings
    settings = get_settings()
    provider = settings.embedding_provider.lower()
    cls = _EMBEDDING_CLIENTS.get(provider)
    if cls is None:
        raise ValueError(
            f"Unknown embedding_provider '{provider}'. "
            f"Supported: {sorted(_EMBEDDING_CLIENTS)}"
        )
    api_key = getattr(settings, f"{provider}_api_key", "")
    return cls(api_key)


def get_llm():
    """Return a LangChain BaseChatModel for the configured LLM provider.

    All provider-specific imports are deferred so that importing this module
    does not fail if a provider's package is not installed.
    """
    from app.config import get_settings
    settings = get_settings()
    provider = settings.llm_provider.lower()
    api_key = getattr(settings, f"{provider}_api_key", "")

    if provider == "mistral":
        from langchain_mistralai import ChatMistralAI
        return ChatMistralAI(model=settings.model_name, temperature=0, api_key=api_key)
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=settings.model_name, temperature=0, api_key=api_key)

    raise ValueError(
        f"Unknown llm_provider '{provider}'. Supported: mistral, openai"
    )
