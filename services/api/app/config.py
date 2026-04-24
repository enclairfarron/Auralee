from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # GCP
    gcp_project: str = Field(default="auralee-api-server", alias="GCP_PROJECT")
    gcp_region: str = Field(default="us-east1", alias="GCP_REGION")
    raw_bucket: str = Field(default="auralee-api-server-raw", alias="RAW_BUCKET")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Secrets (mounted as env by Cloud Run via --set-secrets)
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    wsj_cookie: str = Field(default="", alias="WSJ_COOKIE")
    admin_token: str = Field(default="", alias="ADMIN_TOKEN")

    # Prompt versioning
    prompt_version: str = Field(default="v1", alias="PROMPT_VERSION")

    # Models
    extraction_model: str = "gemini-2.5-flash"
    judge_model: str = "gemini-2.5-pro"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
