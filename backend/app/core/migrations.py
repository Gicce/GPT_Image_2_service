from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def ensure_compat_schema(conn: AsyncConnection) -> None:
    statements = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS account_type VARCHAR(16) DEFAULT 'normal'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS balance_usd NUMERIC(10, 6) DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS api_token_id VARCHAR(36)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_expires_at TIMESTAMPTZ",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()",
        "ALTER TABLE token_inventory ADD COLUMN IF NOT EXISTS \"group\" VARCHAR(32) DEFAULT 'image' NOT NULL",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS trade_no VARCHAR(64)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS package_usd INTEGER DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS \"group\" VARCHAR(128)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS amount_usd NUMERIC(10, 2)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS amount_cny NUMERIC(10, 2) DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS exchange_rate NUMERIC(10, 4) DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS items_json TEXT",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_type VARCHAR(16)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS status VARCHAR(16) DEFAULT 'pending'",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS out_refund_no VARCHAR(64)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS token_id VARCHAR(36)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS allocated_at TIMESTAMPTZ",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS refunded_at TIMESTAMPTZ",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS refund_requested_at TIMESTAMPTZ",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS status_before_refund VARCHAR(16)",
        "ALTER TABLE ai_models ADD COLUMN IF NOT EXISTS provider VARCHAR(32) DEFAULT 'OpenAI'",
        "ALTER TABLE ai_models ADD COLUMN IF NOT EXISTS billing_type VARCHAR(16)",
        "ALTER TABLE ai_models ADD COLUMN IF NOT EXISTS \"group\" VARCHAR(32)",
        "ALTER TABLE ai_models ADD COLUMN IF NOT EXISTS price_input VARCHAR(32)",
        "ALTER TABLE ai_models ADD COLUMN IF NOT EXISTS price_output VARCHAR(32)",
        "ALTER TABLE ai_models ADD COLUMN IF NOT EXISTS price_cached VARCHAR(32)",
        "ALTER TABLE ai_models ADD COLUMN IF NOT EXISTS price_per_call VARCHAR(32)",
        "ALTER TABLE ai_models ADD COLUMN IF NOT EXISTS price_per_image VARCHAR(32)",
        "ALTER TABLE ai_models ADD COLUMN IF NOT EXISTS price_input_per_m VARCHAR(32)",
        "ALTER TABLE ai_models ADD COLUMN IF NOT EXISTS price_output_per_m VARCHAR(32)",
        "ALTER TABLE ai_models ADD COLUMN IF NOT EXISTS price_cached_per_m VARCHAR(32)",
        "ALTER TABLE ai_models ADD COLUMN IF NOT EXISTS context_window INTEGER DEFAULT 32768",
        "ALTER TABLE ai_models ADD COLUMN IF NOT EXISTS supports_tools BOOLEAN DEFAULT FALSE",
        "ALTER TABLE ai_models ADD COLUMN IF NOT EXISTS supports_vision BOOLEAN DEFAULT FALSE",
    ]
    for statement in statements:
        await conn.execute(text(statement))
