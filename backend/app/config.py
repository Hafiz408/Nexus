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

    # Mistral (required for Phase 5+ embedding and LLM)
    mistral_api_key: str = ""
    # Keep for backward compat with tests / RAGAS
    openai_api_key: str = ""

    # LangSmith (optional tracing — Phase 9+)
    langchain_api_key: str = ""
    langchain_tracing_v2: bool = False
    langchain_project: str = "nexus-v1"
    model_name: str = "mistral-small-latest"


@lru_cache
def get_settings() -> Settings:
    return Settings()
