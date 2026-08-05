from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCTOR_", env_file=".env", extra="ignore")

    database_path: str = "./datarepo-doctor.db"
    schedules_enabled: bool = True
