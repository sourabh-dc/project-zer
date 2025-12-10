from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = Field(..., env="DATABASE_URL")
    CONNECTION_POOL_SIZE: int = Field(default=20, env="CONNECTION_POOL_SIZE")
    MAX_OVERFLOW: int = Field(default=10, env="MAX_OVERFLOW")
    POOL_TIMEOUT: int = Field(default=30, env="POOL_TIMEOUT")
    SERVICE_NAME: str = Field(default="ZeroQue Internal API", env="SERVICE_NAME")
    SERVICE_VERSION: str = Field(default="0.1.0", env="SERVICE_VERSION")

    class Config:
        case_sensitive = False


SETTINGS = Settings()
SERVICE_NAME = SETTINGS.SERVICE_NAME
SERVICE_VERSION = SETTINGS.SERVICE_VERSION

__all__ = ["SETTINGS", "SERVICE_NAME", "SERVICE_VERSION"]

