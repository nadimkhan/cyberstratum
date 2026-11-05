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
    mythril_queue_name: str = Field(default="mythril", alias="MYTHRIL_QUEUE_NAME")
    correspondence_queue_name: str = Field(
        default="correspondence", alias="CORRESPONDENCE_QUEUE_NAME"
    )

    # --- Mythril (manual, on-demand) -------------------------------------
    # Mythril runs out of process, outside this application's Python
    # environment, and only when a human asks for it. It is deliberately on
    # its own queue with its own generous budget: a default scan must never
    # inherit Mythril's runtime cost.
    mythril_bin: str = Field(default="myth", alias="MYTHRIL_BIN")
    mythril_timeout_seconds: int = Field(default=300, alias="MYTHRIL_TIMEOUT_SECONDS")
    mythril_solver_timeout_ms: int = Field(default=60000, alias="MYTHRIL_SOLVER_TIMEOUT_MS")

    # --- Source/bytecode correspondence (manual, on-demand) --------------
    # The proof recompiles a contract's verified source and compares the
    # result with the deployed runtime. That is a compiler run, so it gets
    # its own queue and its own budget rather than delaying a scan.
    correspondence_timeout_seconds: int = Field(default=900, alias="CORRESPONDENCE_TIMEOUT_SECONDS")
    correspondence_compile_timeout_seconds: int = Field(
        default=600, alias="CORRESPONDENCE_COMPILE_TIMEOUT_SECONDS"
    )
    correspondence_http_timeout_seconds: int = Field(
        default=60, alias="CORRESPONDENCE_HTTP_TIMEOUT_SECONDS"
    )

    # --- Auth ------------------------------------------------------------
    auth_secret: str = Field(default="dev-only-change-me", alias="AUTH_SECRET")
    api_key: str = Field(default="dev-api-key-change-me", alias="API_KEY")  # noqa: S105
    api_key_header: str = Field(default="X-API-Key", alias="API_KEY_HEADER")
    access_token_ttl_minutes: int = Field(default=60 * 8, alias="ACCESS_TOKEN_TTL_MINUTES")
    refresh_token_ttl_days: int = Field(default=30, alias="REFRESH_TOKEN_TTL_DAYS")

    # --- Human identity: Google OAuth (ADR-0020) -------------------------
    # Humans sign in with Google; machine clients keep using API keys. The
    # client secret is a credential: it is deployment configuration, never
    # committed, and never exposed to the browser.
    google_client_id: str = Field(default="", alias="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(default="", alias="GOOGLE_CLIENT_SECRET")  # noqa: S105
    google_auth_endpoint: str = Field(
        default="https://accounts.google.com/o/oauth2/v2/auth", alias="GOOGLE_AUTH_ENDPOINT"
    )
    google_token_endpoint: str = Field(
        default="https://oauth2.googleapis.com/token", alias="GOOGLE_TOKEN_ENDPOINT"
    )
    google_tokeninfo_endpoint: str = Field(
        default="https://oauth2.googleapis.com/tokeninfo", alias="GOOGLE_TOKENINFO_ENDPOINT"
    )
    #: How long a session token stays valid. The session token is signed and
    #: stateless; this is the bound on its lifetime.
    session_ttl_minutes: int = Field(default=60 * 8, alias="SESSION_TTL_MINUTES")
    #: How long an in-flight OAuth ``state`` record may be redeemed.
    auth_state_ttl_seconds: int = Field(default=600, alias="AUTH_STATE_TTL_SECONDS")
    #: How long a one-time sign-in ticket may be redeemed.
    auth_ticket_ttl_seconds: int = Field(default=300, alias="AUTH_TICKET_TTL_SECONDS")
    #: Name of the cookie the frontend stores the session token in. It is
    #: ``HttpOnly`` on the frontend side, so the browser cannot read it.
    session_cookie_name: str = Field(default="cs_session", alias="SESSION_COOKIE_NAME")

    # --- Object storage --------------------------------------------------
    object_storage_driver: str = Field(default="local", alias="OBJECT_STORAGE_DRIVER")
    object_storage_root: Path = Field(
        default=REPO_ROOT / "var" / "artifacts", alias="OBJECT_STORAGE_ROOT"
    )
    signed_url_ttl_seconds: int = Field(default=300, alias="SIGNED_URL_TTL_SECONDS")

    @field_validator("object_storage_root")
    @classmethod
    def _resolve_storage_root(cls, value: Path) -> Path:
        """Resolve a relative artifact root against the repository root.

        The API, the scan worker and the deep-analysis workers do not all
        run from the same working directory. A relative root therefore
        points at a different directory for each of them: the pipeline
        writes artifacts into one place and the workers look for them in
        another, and every artifact lookup then fails as if the file had
        never been stored. Resolving the path once, against the repository
        root, makes every process agree on where the artifacts live.
        """
        if value.is_absolute():
            return value
        return (REPO_ROOT / value).resolve()

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
            "frontier",
            "homestead",
            "tangerine_whistle",
            "spurious_dragon",
            "byzantium",
            "constantinople",
            "petersburg",
            "istanbul",
            "berlin",
            "london",
            "paris",
            "shanghai",
            "cancun",
            "prague",
            "osaka",
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
