from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCTOR_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./datarepo-doctor.db"
    schedules_enabled: bool = True
