from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    app_version: str = "0.1.0"

    database_url: str

    chain_svc_url: str = "http://localhost:8081"
    chain_enabled: bool = False
    chain_svc_timeout: float = 60.0

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_ttl: int = 60 * 60
    refresh_token_ttl: int = 60 * 60 * 24 * 14

    service_token: str

    usdc_mint: str = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"

    nonce_ttl: int = 300

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
