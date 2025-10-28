from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


    MONGO_DB_URL: str
    POSTGRES_DB_URL: str | None = None


    APP_NAME: str = "API App"
    DEBUG_MODE: bool = False

settings = Settings()