from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    kumo_api_key: str = ""
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "INFO"

    cache_graph_ttl: int = 300
    cache_templates_ttl: int = 3600
    cache_predict_ttl: int = 120

    predict_max_entity_ids: int = 1000
    predict_max_query_length: int = 2000
    predict_min_query_length: int = 8

    auto_load_dataset: str = "online_shopping"

    dataframe_downcast: bool = True

    cache_disk_enabled: bool = True
    cache_cleanup_interval: int = 300

    cors_origins: str = "*"

    rate_limit_enabled: bool = True
    rate_limit_max_requests: int = 60
    rate_limit_window_seconds: int = 60


settings = Settings()

__all__ = ["settings", "Settings"]
