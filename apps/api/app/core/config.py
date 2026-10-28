"""Application configuration.

All configuration comes from environment variables (12-factor). Values are validated
at startup so a misconfigured deployment fails fast rather than at first request.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    """Runtime configuration for the API process."""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application -----------------------------------------------------
    app_env: str = Field(default="local", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    api_host: str = Field(default="127.0.0.1", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    api_base_url: str = Field(default="http://127.0.0.1:8000", alias="API_BASE_URL")
    web_base_url: str = Field(default="http://localhost:3000", alias="WEB_BASE_URL")
    # Additional browser origins allowed to call the API. The frontend is
    # deployed to Netlify, which gives every site a distinct
    # `https://<site>.netlify.app` origin, and preview deploys add more.
    # Keeping these separate from WEB_BASE_URL lets a local development
    # origin stay allowed while production origins are added on the VPS.
    cors_extra_origins: str = Field(default="", alias="CORS_EXTRA_ORIGINS")

    # --- Database --------------------------------------------------------
    database_url: str = Field(
        default="postgresql+psycopg://cyberstratum_app:CHANGE_ME@127.0.0.1:5433/cyberstratum",
        alias="DATABASE_URL",
    )
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    db_echo: bool = Field(default=False, alias="DB_ECHO")
    test_database_url: str = Field(default="", alias="TEST_DATABASE_URL")

    # --- Queue -----------------------------------------------------------
    redis_url: str = Field(default="redis://127.0.0.1:6379", alias="REDIS_URL")
    queue_backend: str = Field(default="rq", alias="QUEUE_BACKEND")
    queue_prefix: str = Field(default="cyberstratum", alias="QUEUE_PREFIX")
    scan_queue_name: str = Field(default="scans", alias="SCAN_QUEUE_NAME")
    discovery_queue_name: str = Field(default="discovery", alias="DISCOVERY_QUEUE_NAME")
    sandbox_queue_name: str = Field(default="sandbox", alias="SANDBOX_QUEUE_NAME")

    # --- Auth ------------------------------------------------------------
    auth_secret: str = Field(default="dev-only-change-me", alias="AUTH_SECRET")
    api_key: str = Field(default="dev-api-key-change-me", alias="API_KEY")  # noqa: S105
    api_key_header: str = Field(default="X-API-Key", alias="API_KEY_HEADER")
    access_token_ttl_minutes: int = Field(default=60 * 8, alias="ACCESS_TOKEN_TTL_MINUTES")
    refresh_token_ttl_days: int = Field(default=30, alias="REFRESH_TOKEN_TTL_DAYS")

    # --- Object storage --------------------------------------------------
    object_storage_driver: str = Field(default="local", alias="OBJECT_STORAGE_DRIVER")
    object_storage_root: Path = Field(
        default=REPO_ROOT / "var" / "artifacts", alias="OBJECT_STORAGE_ROOT"
    )
    signed_url_ttl_seconds: int = Field(default=300, alias="SIGNED_URL_TTL_SECONDS")

    # --- EVM / chain -----------------------------------------------------
    evm_chain_id: int = Field(default=1, alias="EVM_CHAIN_ID")
    evm_rpc_url: str = Field(default="", alias="EVM_RPC_URL")
    evm_rpc_provider: str = Field(default="public", alias="EVM_RPC_PROVIDER")
    explorer_api_base_url: str = Field(default="", alias="EXPLORER_API_BASE_URL")
    explorer_api_key: str = Field(default="", alias="EXPLORER_API_KEY")
    default_evm_fork: str = Field(default="prague", alias="DEFAULT_EVM_FORK")

    # --- Scan pipeline ---------------------------------------------------
    enable_experimental_ml: bool = Field(default=False, alias="ENABLE_EXPERIMENTAL_ML")
    ml_model_version: str = Field(default="", alias="ML_MODEL_VERSION")
    ml_model_artifact_uri: str = Field(default="", alias="ML_MODEL_ARTIFACT_URI")
    scan_max_bytecode_bytes: int = Field(default=2_000_000, alias="SCAN_MAX_BYTECODE_BYTES")
    scan_job_timeout_seconds: int = Field(default=300, alias="SCAN_JOB_TIMEOUT_SECONDS")
    scan_max_retries: int = Field(default=3, alias="SCAN_MAX_RETRIES")

    # --- Source engine -------------------------------------------------
    # Slither is AGPL-3.0. It is never installed into this project's
    # environment, never imported and never vendored: it is run as an
    # unmodified external executable (ADR-0013). An empty value means the
    # executable is looked up on PATH instead.
    slither_bin: str = Field(default="", alias="SLITHER_BIN")
    solc_artifacts_dir: str = Field(default="", alias="SOLC_ARTIFACTS_DIR")

    # --- Sandbox (disabled by default) ------------------------------------
    sandbox_enabled: bool = Field(default=False, alias="SANDBOX_ENABLED")
    sandbox_max_memory_mb: int = Field(default=512, alias="SANDBOX_MAX_MEMORY_MB")
    sandbox_max_cpu_seconds: int = Field(default=30, alias="SANDBOX_MAX_CPU_SECONDS")
    sandbox_max_wall_seconds: int = Field(default=120, alias="SANDBOX_MAX_WALL_SECONDS")

    # --- Observability ---------------------------------------------------
    error_tracking_dsn: str = Field(default="", alias="ERROR_TRACKING_DSN")
    otel_exporter_otlp_endpoint: str = Field(default="", alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    email_provider: str = Field(default="disabled", alias="EMAIL_PROVIDER")

    @field_validator("queue_backend")
    @classmethod
    def _validate_queue_backend(cls, v: str) -> str:
        allowed = {"rq", "celery"}
        if v.lower() not in allowed:
            raise ValueError(f"QUEUE_BACKEND must be one of {sorted(allowed)}, got {v!r}")
        return v.lower()

    @field_validator("default_evm_fork")
    @classmethod
    def _validate_fork(cls, v: str) -> str:
        allowed = {
            "frontier", "homestead", "tangerine_whistle", "spurious_dragon",
            "byzantium", "constantinople", "petersburg", "istanbul", "berlin",
            "london", "paris", "shanghai", "cancun", "prague", "osaka",
        }
        if v.lower() not in allowed:
            raise ValueError(f"DEFAULT_EVM_FORK must be one of {sorted(allowed)}, got {v!r}")
        return v.lower()

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def cors_origins(self) -> list[str]:
        """Every browser origin allowed to call the API.

        `WEB_BASE_URL` is the primary origin. `CORS_EXTRA_ORIGINS` carries any
        additional ones as a comma-separated list, which is how the Netlify
        deploy origin and its preview-deploy origins are added on the VPS.
        """
        origins: list[str] = []
        for candidate in (self.web_base_url, self.cors_extra_origins):
            for origin in candidate.split(","):
                trimmed = origin.strip().rstrip("/")
                if trimmed and trimmed not in origins:
                    origins.append(trimmed)
        return origins


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings singleton."""
    return Settings()
