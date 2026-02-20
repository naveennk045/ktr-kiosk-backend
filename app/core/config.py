from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent 

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env.local",
        extra="ignore"
    )

#  Database credentials
    POSTGRES_DB_URL: str | None = None
    REDIS_HOST: str


#  PhonePe credentials
    PHONEPE_BASE_URL: str
    PHONEPE_CALLBACK_URL: str

    MERCHANT_ID: str
    SALT_KEY: str
    SALT_KEY_INDEX: str
    STORE_ID: str
    TERMINAL_ID: str
    TRANSACTION_ENDPOINT: str
    QR_INIT_ENDPOINT: str
    X_PROVIDER_ID: str
    EDC_ENDPOINT: str

#  Rista credentials
    RISTA_PI_KEY: str
    RISTA_SECRET_KEY: str
    RISTA_BRANCH_CODE: str
    RISTA_BASE_URL: str

#  Petpooja credentials
    PETPOOJA_ACCESS_TOKEN: str
    PETPOOJA_API_SECRET: str
    PETPOOJA_API_KEY: str
    PETPOOJA_RESTAURANT_ID: str
    PETPOOJA_FETCH_MENU_URL: str
    PETPOOJA_CREATE_ORDER_URL: str
    PETPOOJA_CALLBACK_URL: str

#  PineLabs EDC credentials
    PINELABS_EDC_BASE_URL: str
    PINELABS_EDC_MERCHANT_ID: str
    PINELABS_EDC_CLIENT_ID: str
    PINELABS_STORE_ID: str
    PINELABS_EDC_SECURITY_TOKEN: str
    PINELABS_EDC_USER_ID: str


#  Cash Payment PIN
    CASH_PAYMENT_PIN: str = "1234"


    APP_NAME: str = "KTR KIOSK"
    DEBUG_MODE: bool = False

settings = Settings()
