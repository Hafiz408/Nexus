from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Provider selection — seeds runtime defaults on startup
    llm_provider: str = "mistral"
    embedding_provider: str = "mistral"

    # API keys — one per role; share the same value if LLM and embedding use the same provider
    llm_provider_api_key: str = ""
    embedding_provider_api_key: str = ""

    # LangSmith (optional tracing)
    langchain_api_key: str = ""
    langchain_tracing_v2: bool = False
    langchain_project: str = "nexus-v4"

    # Agent tuning knobs (all optional, safe defaults)
    github_token: str = ""
    max_critic_loops: int = 2
    critic_threshold: float = 0.7
    debugger_max_hops: int = 4
    reviewer_context_hops: int = 1


@lru_cache
def get_settings() -> Settings:
    return Settings()
