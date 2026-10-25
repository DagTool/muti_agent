from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./agentforge.db"
    kafka_bootstrap_servers: str = "localhost:9092"
    api_key: str = ""
    workspace_id: str = "local-dev"
    web_origin: str = "http://127.0.0.1:5173"
    agent_mode: str = "mock"
    openai_model: str = "gpt-6.1-sol"
    artifact_root: str = ".agentforge/projects"

    model_config = SettingsConfigDict(env_prefix="AGENTFORGE_", env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
