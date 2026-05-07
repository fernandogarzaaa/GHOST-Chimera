# Multi-Provider Auth and Credential Pool

## Architecture

The credential pool lives in `ghostchimera/chimera_pilot/credential_pool.py` and the `AuthProfile` data type in `ghostchimera/model_layer/auth_profiles.py`.

### CredentialPool

The `CredentialPool` manages API keys, tokens, and service credentials across multiple providers (OpenAI, Anthropic, etc.). It:

- Stores credentials in memory (not on disk) — secrets never touch persistent storage
- Loads credentials from environment variables at initialization via `initialize_from_env()`
- Tracks quota usage per key (`quota_used`, `quota_limit`) and availability (`enabled`, `expires_at`)
- Provides `get_credential(provider)` to retrieve a specific provider's active `CredentialEntry`
- Provides `get_provider_instance(provider)` to construct a ready-to-use `BaseProvider` with auth injected
- Supports key rotation via `rotate_credential(provider, new_api_key)`
- Records per-provider health metrics via `record_request(provider, success)`
- Selects the best available provider via `select_best_provider(exclude=...)`

### AuthProfile

`AuthProfile` is a frozen dataclass in `ghostchimera/model_layer/auth_profiles.py` that represents a single provider's configuration:

- `provider`: Provider name (e.g. `"openai"`, `"anthropic"`)
- `auth_kind`: `"api_key"` or `"oauth"`
- `api_key`: The provider API key
- `oauth_token`: OAuth bearer token (for OAuth providers)
- `model`: Model selector (e.g. `"gpt-4o"`, `"claude-3-5-haiku"`)
- `base_url`: Override URL for the provider endpoint
- `expires_at`: Optional key expiration (Unix timestamp)

The pool builds `AuthProfile` instances from `CredentialEntry` objects inside `get_provider_instance()` and passes them to provider constructors at initialization time (OpenClaw-style auth injection).

### CredentialEntry

`CredentialEntry` is the pool's internal per-provider record:

- `provider`, `api_key`, `api_secret`, `oauth_token`, `model`, `base_url`
- `quota_limit` (0 = unlimited), `quota_used`
- `last_rotated`, `expires_at`, `enabled`
- Properties: `is_expired`, `is_available`, `usage_pct()`

### Key Rotation and Quota Tracking

Key rotation is triggered by:

1. Explicit `rotate_credential(provider, new_api_key)` calls (e.g. when a key is compromised)
2. OAuth token refresh via `refresh_credential(provider)` — delegates to a registered `ExternalAuthProvider`
3. Automatic OAuth refresh when a stored token is expired and an `ExternalAuthProvider` is registered

Quota is tracked via `record_request(provider, success)` which increments `quota_used` and updates per-provider `ProviderHealth` statistics (`request_count`, `success_count`, `failure_count`).

### ExternalAuthProvider Integration

Call `register_auth_provider(provider_id, auth_provider)` to register an
`ExternalAuthProvider` instance. The pool will call `auth_provider.refresh(oauth_credential)`
automatically when the stored credential is expired.

## Key Files

| File | Purpose |
|------|---------|
| `ghostchimera/chimera_pilot/credential_pool.py` | CredentialPool, CredentialEntry, ProviderHealth |
| `ghostchimera/model_layer/auth_profiles.py` | AuthProfile, OAuthCredential, ExternalAuthProvider |
| `ghostchimera/model_layer/providers.py` | Provider classes that consume AuthProfile |
