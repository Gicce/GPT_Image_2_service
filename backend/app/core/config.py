from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Environment
    APP_ENV: str = "production"  # "production" or "development"

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

    # CORS 白名单（逗号分隔，留空则放开以兼容 Tauri 客户端多变 origin）
    CORS_ORIGINS: str = ""

    # 微信支付
    WECHAT_MCHID: str = ""
    WECHAT_APPID: str = ""
    WECHAT_APIV3_KEY: str = ""
    WECHAT_CERT_SERIAL_NO: str = ""
    WECHAT_PRIVATE_KEY_PATH: str = "/app/certs/apiclient_key.pem"
    WECHAT_NOTIFY_URL: str = ""
    WECHAT_REFUND_NOTIFY_URL: str = ""
    WECHAT_PUBLIC_KEY_PATH: str = ""
    WECHAT_PUBLIC_KEY_ID: str = ""

    # Server
    SERVER_BASE_URL: str = "https://www.zjcypc.com"
    SKILL_SAMPLE_DIR: str = "./data/skill_samples"
    SKILL_SAMPLE_MAX_BYTES: int = 10 * 1024 * 1024

    # SMTP / Email
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_NAME: str = "CyImagePro"
    SMTP_USE_SSL: bool = True

    # Payment limits
    PAYMENT_MIN_TOTAL_USD: float = 1.0
    PAYMENT_MAX_TOTAL_USD: float = 1000.0
    PAYMENT_MIN_PER_ITEM_USD: float = 0.01

    # Image2 billing
    TRIAL_CREDIT_USD: float = 1.0        # 注册/补领试用额度（USD）
    RESERVATION_TTL_HOURS: int = 2       # 预占超时自动释放（小时）

    # Exchange rate API (free tier)
    EXCHANGE_RATE_API: str = "https://open.er-api.com/v6/latest/USD"

    # PackyAPI runtime token（V4：仅保留 Image2 单一上游 Token，存服务端）
    PACKYAPI_MASTER_TOKEN: str = ""      # legacy 兜底
    PACKYAPI_IMAGE_MASTER_TOKEN: str = ""
    PACKYAPI_IMAGE_BASE_URL: str = "https://www.packyapi.com"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
