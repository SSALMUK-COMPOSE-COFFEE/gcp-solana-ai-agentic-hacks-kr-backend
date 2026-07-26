from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_version: str = "0.1.0"

    database_url: str = "postgresql+asyncpg://app:app@localhost:5432/chongdae"

    chain_svc_url: str = "http://localhost:8081"
    chain_enabled: bool = False

    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl: int = 60 * 60
    refresh_token_ttl: int = 60 * 60 * 24 * 14

    service_token: str = "dev-service-token"

    usdc_mint: str = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"

    nonce_ttl: int = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
