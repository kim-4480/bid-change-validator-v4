from functools import lru_cache
from typing import Literal
from urllib.parse import unquote

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .schemas import BusinessType


class Settings(BaseSettings):
    app_name: str = "Bid Change Validator API"
    app_version: str = "0.1.0"
    app_environment: str = "development"
    database_url: str = (
        "postgresql://bidjigi:bidjigi_local_password@localhost:5432/bidjigi"
    )
    migration_database_url: str | None = None
    database_pool_mode: Literal["auto", "queue", "transaction"] = "auto"
    database_pool_size: int = Field(default=2, ge=1, le=50)
    database_max_overflow: int = Field(default=0, ge=0, le=50)
    database_pool_timeout_seconds: int = Field(default=30, ge=1, le=300)
    database_pool_recycle_seconds: int = Field(default=900, ge=30, le=86_400)
    g2b_service_key: str | None = None
    g2b_base_url: str = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"
    g2b_request_timeout_seconds: float = 30.0
    document_storage_backend: str = "LOCAL"
    document_storage_path: str = "data/notice-documents"
    document_download_timeout_seconds: float = 60.0
    document_max_file_size_bytes: int = 100 * 1024 * 1024
    document_s3_bucket: str | None = None
    document_s3_prefix: str = "notice-documents"
    document_s3_endpoint_url: str | None = None
    aws_region: str | None = None
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    notice_poll_interval_seconds: int = Field(default=300, ge=30)
    notice_poll_lookback_minutes: int = Field(default=60, ge=1, le=43_200)
    notice_poll_overlap_minutes: int = Field(default=5, ge=0, le=1_440)
    notice_poll_page_size: int = Field(default=100, ge=1, le=999)
    notice_poll_max_pages: int = Field(default=10, ge=1, le=100)
    notice_poll_business_types: str = "SERVICE,GOODS,CONSTRUCTION,FOREIGN"
    notice_history_backfill_batch_size: int = Field(default=10, ge=1, le=100)
    notice_history_backfill_retry_minutes: int = Field(default=15, ge=1, le=1_440)
    auth_bootstrap_admin_username: str = "admin"
    auth_bootstrap_admin_password: str = "admin"
    auth_session_ttl_hours: int = Field(default=12, ge=1, le=720)
    auth_cookie_secure: bool = False
    auth_required: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def sqlalchemy_database_url(self) -> str:
        return self._as_sqlalchemy_url(self.database_url)

    @property
    def sqlalchemy_migration_database_url(self) -> str:
        return self._as_sqlalchemy_url(self.migration_database_url or self.database_url)

    @staticmethod
    def _as_sqlalchemy_url(value: str) -> str:
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @property
    def decoded_g2b_service_key(self) -> str | None:
        if self.g2b_service_key is None:
            return None
        value = self.g2b_service_key.strip()
        return unquote(value) if value else None

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def notice_poll_business_type_list(self) -> list[BusinessType]:
        values: list[BusinessType] = []
        for raw_value in self.notice_poll_business_types.split(","):
            value = raw_value.strip().upper()
            if value:
                values.append(BusinessType(value))
        if not values:
            raise ValueError("NOTICE_POLL_BUSINESS_TYPES must contain at least one value")
        return list(dict.fromkeys(values))


@lru_cache
def get_settings() -> Settings:
    return Settings()
