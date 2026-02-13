from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # points to project root


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env.local",
        extra="ignore"
    )

    POSTGRES_DB_URL: str | None = None

    # PhonePe constants
    PHONEPE_BASE_URL: str
    # PRODUCTION_BASE_URL: str
    MERCHANT_ID: str
    SALT_KEY: str
    SALT_KEY_INDEX: str
    STORE_ID: str
    TERMINAL_ID: str
    TRANSACTION_ENDPOINT: str
    QR_INIT_ENDPOINT: str
    X_PROVIDER_ID: str
    PHONEPE_CALLBACK_URL: str
    EDC_ENDPOINT: str

    # Cash Payment PIN
    CASH_PAYMENT_PIN: str = "1234"

    # # Rista credentials
    # PI_KEY: str
    # SECRET_KEY: str
    # BRANCH_CODE: str
    # RISTA_BASE_URL: str

    APP_NAME: str = "KTR KIOSK"
    DEBUG_MODE: bool = False

    REDIS_HOST: str

    PETPOOJA_ACCESS_TOKEN: str
    PETPOOJA_API_SECRET: str
    PETPOOJA_API_KEY: str
    PETPOOJA_RESTAURANT_ID: str
    PETPOOJA_FETCH_MENU_URL: str
    PETPOOJA_CREATE_ORDER_URL: str
    PETPOOJA_CALLBACK_URL: str

    PINELABS_EDC_BASE_URL: str
    PINELABS_EDC_MERCHANT_ID: str
    PINELABS_EDC_CLIENT_ID: str
    PINELABS_EDC_API_SECRET: str
    PINELABS_STORE_ID: str
    PINELABS_EDC_SECURITY_TOKEN: str
    PINELABS_EDC_USER_ID: str


settings = Settings()
