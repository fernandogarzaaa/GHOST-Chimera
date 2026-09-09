-- Ghost Chimera: unified token management (PostgreSQL).
-- Mirrors ghostchimera/connectors/auth_engine.py AuthStore (SQLite).
-- Apply: psql $DATABASE_URL -f migrations/0001_integration_auth_tokens.sql

CREATE TABLE IF NOT EXISTS integration_auth_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id VARCHAR(255) NOT NULL,       -- ID of the user/agent/tenant
    provider VARCHAR(50) NOT NULL,         -- e.g., 'google', 'slack', 'zendesk'
    access_token TEXT NOT NULL,            -- Encrypted string (Fernet/AES-256)
    refresh_token TEXT NOT NULL,           -- Encrypted string (Fernet/AES-256)
    expires_at TIMESTAMP WITH TIMEZONE NOT NULL,
    scopes TEXT[],                         -- Array of authorized scopes
    created_at TIMESTAMP WITH TIMEZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIMEZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(entity_id, provider)
);

-- Operational status beyond the base contract: the engine marks rows
-- NEEDS_REAUTH on invalid_grant instead of deleting them, so dashboards
-- can prompt reconnect without losing the entity/provider mapping.
ALTER TABLE integration_auth_tokens
    ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE';

CREATE INDEX IF NOT EXISTS idx_auth_tokens_entity ON integration_auth_tokens(entity_id);
CREATE INDEX IF NOT EXISTS idx_auth_tokens_expiry ON integration_auth_tokens(expires_at);
