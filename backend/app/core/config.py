from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://cyimage:cyimage123@postgres:5432/cyimage"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # JWT
    SECRET_KEY: str = "change-this-secret-key-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Admin
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin123"

    # 树杰支付
    SHUJIE_PID: int = 1752
    SHUJIE_MD5_KEY: str = "cA1DdJ1ODA2xoU0QEPD5pdE1C513D0V1"
    SHUJIE_API_BASE: str = "https://www.shujiepay.com/api/pay"
    SHUJIE_NOTIFY_URL: str = "http://150.158.124.224/api/pay/notify"
    SHUJIE_RETURN_URL: str = "http://150.158.124.224/api/pay/return"

    # Server
    SERVER_BASE_URL: str = "http://150.158.124.224"

    # Exchange rate API (free tier)
    EXCHANGE_RATE_API: str = "https://open.er-api.com/v6/latest/USD"

    class Config:
        env_file = ".env"


settings = Settings()
