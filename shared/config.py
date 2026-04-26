"""Shared configuration using pydantic-settings."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = Field(default="E-Parking v2", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    debug: bool = Field(default=False, alias="DEBUG")

    # Database (direct PostgreSQL)
    db_host: str = Field(default="localhost", alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_name: str = Field(default="parking", alias="DB_NAME")
    db_user: str = Field(default="parking", alias="DB_USER")
    db_password: str = Field(default="parking_secret", alias="DB_PASSWORD")
    db_pool_size: int = Field(default=20, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")

    # pgBouncer
    pgbouncer_host: str = Field(default="localhost", alias="PGBOUNCER_HOST")
    pgbouncer_port: int = Field(default=6432, alias="PGBOUNCER_PORT")
    pgbouncer_pool_mode: str = Field(default="transaction", alias="PGBOUNCER_POOL_MODE")

    # Redis
    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_db: int = Field(default=0, alias="REDIS_DB")
    redis_password: str | None = Field(default=None, alias="REDIS_PASSWORD")

    # JWT
    jwt_secret: str = Field(default="dev-secret", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_access_token_expire_minutes: int = Field(
        default=30, alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES"
    )
    jwt_refresh_token_expire_days: int = Field(
        default=7, alias="JWT_REFRESH_TOKEN_EXPIRE_DAYS"
    )

    # Security
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000", alias="CORS_ORIGINS"
    )

    # Hardware defaults
    default_emoney_minimum_balance: int = Field(
        default=10000, alias="DEFAULT_EMONEY_MINIMUM_BALANCE"
    )
    default_payment_timeout_seconds: int = Field(
        default=120, alias="DEFAULT_PAYMENT_TIMEOUT_SECONDS"
    )
    default_print_decision_timeout_seconds: int = Field(
        default=10, alias="DEFAULT_PRINT_DECISION_TIMEOUT_SECONDS"
    )
    default_gate_close_duration_ms: int = Field(
        default=5000, alias="DEFAULT_GATE_CLOSE_DURATION_MS"
    )

    # Settlement
    settlement_schedule: str = Field(default="0 2 * * *", alias="SETTLEMENT_SCHEDULE")
    settlement_auto_upload: bool = Field(default=False, alias="SETTLEMENT_AUTO_UPLOAD")

    # Telegram
    telegram_bot_token: str | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")

    # ── ANPR (Automatic Number Plate Recognition) ─────────────────────
    anpr_enabled: bool = Field(default=False, alias="ANPR_ENABLED")
    anpr_model: str = Field(default="paddleocr", alias="ANPR_MODEL")
    anpr_confidence_threshold: float = Field(
        default=0.8, alias="ANPR_CONFIDENCE_THRESHOLD"
    )

    # ── Plate Detection (YOLO model for cropping plate region) ────────
    plate_detection_model: str = Field(
        default="license_plate_detector", alias="PLATE_DETECTION_MODEL"
    )

    # ── Vehicle Detection ─────────────────────────────────────────────
    vehicle_detection_enabled: bool = Field(
        default=False, alias="VEHICLE_DETECTION_ENABLED"
    )
    vehicle_detection_model: str = Field(
        default="yolov8n", alias="VEHICLE_DETECTION_MODEL"
    )
    vehicle_detection_confidence_threshold: float = Field(
        default=0.7, alias="VEHICLE_DETECTION_CONFIDENCE_THRESHOLD"
    )

    # ── Printer Paper Counter ─────────────────────────────────────────
    printer_paper_counter_enabled: bool = Field(
        default=False, alias="PRINTER_PAPER_COUNTER_ENABLED"
    )
    printer_paper_warning_threshold: int = Field(
        default=50, alias="PRINTER_PAPER_WARNING_THRESHOLD"
    )
    printer_paper_critical_threshold: int = Field(
        default=10, alias="PRINTER_PAPER_CRITICAL_THRESHOLD"
    )

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="json", alias="LOG_FORMAT")

    @property
    def database_url(self) -> str:
        """Build async PostgreSQL connection URL."""
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def pgbouncer_url(self) -> str:
        """Build async PostgreSQL connection URL via pgBouncer."""
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.pgbouncer_host}:{self.pgbouncer_port}/{self.db_name}"
        )

    @property
    def redis_url(self) -> str:
        """Build Redis connection URL."""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins string into list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return Settings()
