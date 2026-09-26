"""Shared configuration using pydantic-settings."""

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _is_placeholder_secret(value: str | None) -> bool:
    """True for empty values and the example/placeholder strings shipped in
    .env.example (change-me, your-..., example, ...-here, dev-secret)."""
    if not value:
        return True
    lowered = value.lower()
    return any(
        marker in lowered
        for marker in ("change-me", "change_me", "your-", "example", "dev-secret")
    ) or lowered.endswith("-here")


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
    # Sized against Postgres default max_connections=100: 4 gunicorn workers
    # + events service + 2 ARQ workers each open their own pool. The old
    # 20+10 per process could demand 120+ connections and 500 under load.
    db_pool_size: int = Field(default=8, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=4, alias="DB_MAX_OVERFLOW")

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
    internal_api_key: str | None = Field(default=None, alias="INTERNAL_API_KEY")

    # Settlement
    # Multibank settlement is in operational timezone (Asia/Jakarta).
    app_timezone: str = Field(default="Asia/Jakarta", alias="APP_TIMEZONE")
    # Settlement SFTP delivery (Multibank v1.3 §I)
    settlement_sftp_host: str = Field(default="", alias="SETTLEMENT_SFTP_HOST")
    settlement_sftp_port: int = Field(default=22, alias="SETTLEMENT_SFTP_PORT")
    settlement_sftp_username: str = Field(default="", alias="SETTLEMENT_SFTP_USERNAME")
    settlement_sftp_key_path: str = Field(default="", alias="SETTLEMENT_SFTP_KEY_PATH")
    settlement_sftp_known_hosts: str = Field(
        default="", alias="SETTLEMENT_SFTP_KNOWN_HOSTS"
    )
    """Path to SSH known_hosts file. Empty string disables host-key checking
    (NOT recommended in production — leaves you open to MITM)."""
    settlement_sftp_remote_dir: str = Field(
        default="/incoming", alias="SETTLEMENT_SFTP_REMOTE_DIR"
    )
    settlement_sftp_response_dir: str = Field(
        default="/incoming", alias="SETTLEMENT_SFTP_RESPONSE_DIR"
    )
    settlement_sftp_connect_timeout: int = Field(
        default=30, alias="SETTLEMENT_SFTP_CONNECT_TIMEOUT"
    )

    # Telegram
    telegram_bot_token: str | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str | None = Field(default=None, alias="TELEGRAM_CHAT_ID")

    # ── ANPR (Automatic Number Plate Recognition) ─────────────────────
    anpr_enabled: bool = Field(default=False, alias="ANPR_ENABLED")
    anpr_model: str = Field(default="paddleocr", alias="ANPR_MODEL")
    anpr_confidence_threshold: float = Field(
        default=0.8, alias="ANPR_CONFIDENCE_THRESHOLD"
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

    # ── Mock hardware (local dev / hardware test) ─────────────────────
    mock_hardware: bool = Field(default=False, alias="MOCK_HARDWARE")
    mock_hardware_dir: str = Field(
        default="/tmp/parking-mock", alias="MOCK_HARDWARE_DIR"
    )

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="json", alias="LOG_FORMAT")

    # Setup wizard
    setup_token_path: str = Field(
        default="/etc/parking/setup-token", alias="SETUP_TOKEN_PATH"
    )
    enroll_token_path: str = Field(
        default="/etc/parking/enroll-token", alias="ENROLL_TOKEN_PATH"
    )
    setup_session_ttl_seconds: int = Field(
        default=3600, alias="SETUP_SESSION_TTL_SECONDS"
    )
    parking_install_root: str = Field(
        default="/opt/parking-system-v2", alias="PARKING_INSTALL_ROOT"
    )

    @model_validator(mode="after")
    def _validate_production_settings(self) -> "Settings":
        """Ensure critical settings are configured in production."""
        if self.app_env == "production":
            if not self.internal_api_key:
                raise ValueError(
                    "INTERNAL_API_KEY must be set in production — "
                    "booth bridge endpoints will be unprotected without it"
                )
            # Reject placeholders, not just literals: the shipped .env values
            # ("change-me-in-production-...") passed the old check and would
            # have signed every session token in production.
            if _is_placeholder_secret(self.jwt_secret):
                raise ValueError("JWT_SECRET must be changed from default in production")
            if _is_placeholder_secret(self.internal_api_key):
                raise ValueError(
                    "INTERNAL_API_KEY must be changed from the .env.example "
                    "placeholder in production"
                )
            if self.db_password in ("parking_secret", "") or _is_placeholder_secret(
                self.db_password
            ):
                raise ValueError("DB_PASSWORD must be changed from default in production")
            # If settlement SFTP is configured, require host-key verification —
            # an empty known_hosts disables it and leaves the money path open to MITM.
            if self.settlement_sftp_host and not self.settlement_sftp_known_hosts:
                raise ValueError(
                    "SETTLEMENT_SFTP_KNOWN_HOSTS must be set in production when "
                    "SETTLEMENT_SFTP_HOST is configured — empty disables host-key "
                    "verification (MITM risk)"
                )
            # Debug mode leaks tracebacks and exposes /api/docs — never in prod.
            self.debug = False
        return self

    @property
    def database_url(self) -> str:
        """Build async PostgreSQL connection URL."""
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
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
