"""
Policy Engine Configuration
Environment-based settings for the Policy Engine service
"""
import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Database
    DATABASE_URL: str = "postgresql://zeroque:zeroque_dev_password@localhost:5432/zeroque_dev"
    
    # Redis (for caching policies)
    REDIS_URL: str = "redis://localhost:6379/1"  # Use DB 1 for policy engine
    
    # Service
    SERVICE_NAME: str = "policy-engine"
    SERVICE_VERSION: str = "1.0.0"
    PORT: int = 8004
    LOG_LEVEL: str = "INFO"
    
    # CORS
    ALLOW_ORIGINS: str = "*"
    
    # Database Pool
    CONNECTION_POOL_SIZE: int = 10
    MAX_OVERFLOW: int = 5
    POOL_TIMEOUT: int = 30
    POOL_RECYCLE: int = 3600
    
    # Cache settings
    POLICY_CACHE_TTL_SECONDS: int = 300  # 5 minutes
    DECISION_LOG_RETENTION_DAYS: int = 90  # 3 months
    
    # JWT Settings (for auth)
    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_JWKS_URL: str = ""
    JWT_AUDIENCE: str = ""
    JWT_ISSUER: str = ""
    JWT_EXPIRY_MINUTES: int = 60
    JWT_CACHE_SECONDS: int = 3600
    
    # Feature flags
    ENABLE_DECISION_LOGGING: bool = True
    ENABLE_METRICS: bool = True
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


SETTINGS = get_settings()
