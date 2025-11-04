from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # points to project root

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        extra="ignore"
    )

    POSTGRES_DB_URL: str | None = None

    # PhonePe constants
    UAT_BASE_URL: str
    PRODUCTION_BASE_URL: str
    MERCHANT_ID: str
    SALT_KEY: str
    SALT_KEY_INDEX: str
    STORE_ID: str
    TERMINAL_ID: str
    TRANSACTION_ENDPOINT: str
    QR_INIT_ENDPOINT: str
    X_PROVIDER_ID: str

    APP_NAME: str = "API App"
    DEBUG_MODE: bool = False


settings = Settings()
