from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """
    Environment: shared infrastructure and PhonePe *API* endpoints only.
    Per-store secrets (Petpooja, PhonePe merchant/salt/terminals, PineLabs) live in PostgreSQL.
    """

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env.local",
        extra="ignore",
    )

    # Database
    POSTGRES_DB_URL: str | None = None

    # Redis (full URL for redis.from_url)
    REDIS_HOST: str
    # Per-process pool cap. Every open KDS websocket / TMS SSE stream pins one connection
    # for its pub/sub subscription, so size this above (concurrent screens + request load).
    # Keep (this × number of app instances) below the Valkey server's maxclients.
    REDIS_MAX_CONNECTIONS: int = 200
    # Seconds a request waits for a free pooled connection before failing.
    REDIS_POOL_TIMEOUT: int = 5

    # PhonePe HTTP client — same base paths for all stores; merchant/salt/terminal IDs are in DB
    PHONEPE_BASE_URL: str
    PHONEPE_CALLBACK_URL: str
    PHONEPE_QR_INIT_ENDPOINT: str
    PHONEPE_TRANSACTION_ENDPOINT: str

    APP_NAME: str = "KTR KIOSK"
    DEBUG_MODE: bool = False


settings = Settings()
