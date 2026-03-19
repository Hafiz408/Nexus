from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # PostgreSQL
    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    # Provider selection (model-agnostic factory)
    embedding_provider: str = "mistral"   # mistral | openai
    llm_provider: str = "mistral"         # mistral | openai

    # API keys — add <provider>_api_key for each provider
    mistral_api_key: str = ""
    openai_api_key: str = ""

    # LLM model name (interpreted by the active llm_provider)
    model_name: str = "mistral-small-latest"

    # LangSmith (optional tracing — Phase 9+)
    langchain_api_key: str = ""
    langchain_tracing_v2: bool = False
    langchain_project: str = "nexus-v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
