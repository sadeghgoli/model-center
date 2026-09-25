from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./modelcenter.db"
    redis_url: str = ""
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 30
    ai_platform_secret: str = ""
    public_base_url: str = "http://localhost:8090"
    default_admin_email: str = ""
    default_admin_password: str = ""
    cors_origins: str = "http://localhost:3010"
    request_timeout_seconds: float = 60
    max_body_bytes: int = 1_048_576
    app_env: str = "development"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("postgresql+asyncpg", "postgresql+psycopg").replace(
            "sqlite+aiosqlite", "sqlite"
        )


def get_settings() -> Settings:
    return Settings()
