"""Model factory — provider-agnostic embedding and LLM clients.

Adding a new provider:
  1. Subclass EmbeddingClient and implement embed() + dimensions.
  2. Register in _EMBEDDING_CLIENTS.
  3. Add an LLM case to get_llm().
  4. Add <provider>_api_key to Settings (config.py) or supply via runtime config.
  5. Set chat_provider / embedding_provider via POST /api/config.

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

    @property
    @abstractmethod
    def max_tokens(self) -> int:
        """Maximum total tokens allowed per API request for this provider/model."""
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

    @property
    def max_tokens(self) -> int:
        return 16_384  # mistral-embed hard cap


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

    @property
    def max_tokens(self) -> int:
        return 8_191  # text-embedding-3-small context length


class OllamaEmbeddingClient(EmbeddingClient):
    """Ollama — local embeddings via langchain-ollama."""

    def __init__(self, model: str, base_url: str) -> None:
        from langchain_ollama import OllamaEmbeddings
        self._client = OllamaEmbeddings(model=model, base_url=base_url)
        self._model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._client.embed_documents(texts)

    @property
    def dimensions(self) -> int:
        # Ollama embedding dimensions vary per model; nomic-embed-text=768
        return 768


class GeminiEmbeddingClient(EmbeddingClient):
    """Google Gemini — embeddings via langchain-google-genai."""

    def __init__(self, api_key: str, model: str) -> None:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        self._client = GoogleGenerativeAIEmbeddings(model=model, google_api_key=api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._client.embed_documents(texts)

    @property
    def dimensions(self) -> int:
        # models/text-embedding-004 = 768
        return 768


# Registry — add new providers here
_EMBEDDING_CLIENTS: dict[str, type[EmbeddingClient]] = {
    "mistral": MistralEmbeddingClient,
    "openai": OpenAIEmbeddingClient,
    "ollama": OllamaEmbeddingClient,
    "gemini": GeminiEmbeddingClient,
}


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------

def get_embedding_client() -> EmbeddingClient:
    """Instantiate and return the configured embedding client.

    Prefers runtime config (POST /api/config) over static .env settings.
    """
    from app.core.runtime_config import get_runtime_config
    cfg = get_runtime_config()
    provider = cfg.embedding_provider.lower()

    if provider == "ollama":
        model = cfg.embedding_model or "nomic-embed-text"
        return OllamaEmbeddingClient(model=model, base_url=cfg.ollama_base_url)

    if provider == "gemini":
        api_key = cfg.api_keys.get("gemini", "")
        model = cfg.embedding_model or "models/text-embedding-004"
        return GeminiEmbeddingClient(api_key=api_key, model=model)

    if provider == "openai":
        api_key = cfg.api_keys.get("openai", "")
        if not api_key:
            from app.config import get_settings
            api_key = get_settings().embedding_provider_api_key
        return OpenAIEmbeddingClient(api_key=api_key)

    if provider == "mistral":
        api_key = cfg.api_keys.get("mistral", "")
        if not api_key:
            from app.config import get_settings
            api_key = get_settings().embedding_provider_api_key
        return MistralEmbeddingClient(api_key=api_key)

    raise ValueError(
        f"Unknown embedding_provider '{provider}'. "
        f"Supported: {sorted(_EMBEDDING_CLIENTS)}"
    )


def get_llm():
    """Return a LangChain BaseChatModel for the configured LLM provider.

    Prefers runtime config (POST /api/config) over static .env settings.
    All provider-specific imports are deferred so that importing this module
    does not fail if a provider's package is not installed.
    """
    from app.core.runtime_config import get_runtime_config
    cfg = get_runtime_config()
    provider = cfg.chat_provider.lower()
    model = cfg.chat_model

    if provider == "mistral":
        from langchain_mistralai import ChatMistralAI
        api_key = cfg.api_keys.get("mistral", "")
        if not api_key:
            from app.config import get_settings
            api_key = get_settings().llm_provider_api_key
        return ChatMistralAI(model=model, temperature=0, api_key=api_key)

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        api_key = cfg.api_keys.get("openai", "")
        if not api_key:
            from app.config import get_settings
            api_key = get_settings().llm_provider_api_key
        return ChatOpenAI(model=model, temperature=0, api_key=api_key)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        api_key = cfg.api_keys.get("anthropic", "")
        return ChatAnthropic(model=model, temperature=0, api_key=api_key)

    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=model, temperature=0, base_url=cfg.ollama_base_url)

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        api_key = cfg.api_keys.get("gemini", "")
        return ChatGoogleGenerativeAI(model=model, temperature=0, google_api_key=api_key)

    raise ValueError(
        f"Unknown chat_provider '{provider}'. Supported: mistral, openai, anthropic, ollama, gemini"
    )
