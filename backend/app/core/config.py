from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://cyimage:cyimage123@postgres:5432/cyimage"
    REDIS_URL: str = "redis://redis:6379/0"

    SECRET_KEY: str = "change-this-secret-key-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin123"

    WECHAT_MCHID: str = ""
    WECHAT_APPID: str = ""
    WECHAT_APIV3_KEY: str = ""
    WECHAT_CERT_SERIAL_NO: str = ""
    WECHAT_PRIVATE_KEY_PATH: str = "/app/certs/apiclient_key.pem"
    WECHAT_NOTIFY_URL: str = ""
    WECHAT_REFUND_NOTIFY_URL: str = ""
    WECHAT_PUBLIC_KEY_PATH: str = ""
    WECHAT_PUBLIC_KEY_ID: str = ""

    SERVER_BASE_URL: str = "https://www.zjcypc.com"

    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_NAME: str = "CyImagePro"
    SMTP_USE_SSL: bool = True

    PAYMENT_MIN_TOTAL_USD: float = 0.01
    PAYMENT_MAX_TOTAL_USD: float = 1000.0
    PAYMENT_MIN_PER_ITEM_USD: float = 0.01

    EXCHANGE_RATE_API: str = "https://open.er-api.com/v6/latest/USD"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
