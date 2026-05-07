# Multi-Provider Auth and Credential Pool

## Architecture

The credential pool lives in `ghostchimera/chimera_pilot/credential_pool.py` and the `AuthProfile` data type in `ghostchimera/model_layer/auth_profiles.py`.

### CredentialPool

The `CredentialPool` manages API keys, tokens, and service credentials across multiple providers (OpenAI, Anthropic, etc.). It:

- Stores credentials in memory (not on disk) — secrets never touch persistent storage
- Validates keys at construction time (checks format, checks reachability)
- Tracks quota usage per key (calls remaining, rate limits)
- Provides `get_creds(provider)` to retrieve a specific provider's active credential
- Supports key rotation via `rotate_key(provider, new_key)`

### AuthProfile

`AuthProfile` is a frozen dataclass that represents a single provider's configuration:

- `api_key`: The provider API key
- `model`: Model selector (e.g. "gpt-3.5-turbo", "claude-3-5-haiku")
- `base_url`: Override URL for the provider endpoint
- `quota_limit`: Optional request limit
- `expires_at`: Optional key expiration

The pool builds `AuthProfile` instances from `CredentialEntry` objects and passes them to provider constructors at initialization time.

### Key Rotation and Quota Tracking

Key rotation is triggered by:

1. Explicit `rotate_key()` calls (e.g. when a key is compromised)
2. Automatic rotation when quota is exhausted (`quota_limit` reached)
3. Expiration (`expires_at` reached)

The pool tracks `calls_made`, `quota_remaining`, and `reset_at` per key, and raises `CredentialError` when all keys are exhausted.

## Key Files

| File | Purpose |
|------|---------|
| `ghostchimera/chimera_pilot/credential_pool.py` | CredentialPool, credential management |
| `ghostchimera/model_layer/auth_profiles.py` | AuthProfile data class |
| `ghostchimera/model_layer/providers.py` | Provider classes that consume AuthProfile |
