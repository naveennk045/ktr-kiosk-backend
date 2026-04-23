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

    # PhonePe HTTP client — same base paths for all stores; merchant/salt/terminal IDs are in DB
    PHONEPE_BASE_URL: str
    PHONEPE_CALLBACK_URL: str
    PHONEPE_QR_INIT_ENDPOINT: str
    PHONEPE_TRANSACTION_ENDPOINT: str

    APP_NAME: str = "KTR KIOSK"
    DEBUG_MODE: bool = False


settings = Settings()
