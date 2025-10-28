from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


    DB_URL: str


    APP_NAME: str = "API App"
    DEBUG_MODE: bool = False

settings = Settings()