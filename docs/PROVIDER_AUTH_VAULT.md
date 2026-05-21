# Provider Auth Vault

Ghost Chimera keeps model-provider access modular. The dashboard can connect
hosted providers with write-only secrets, show OAuth-capable connector slots,
and activate local providers such as Ollama without requiring users to edit
`.env` files.

## What Is Supported

- **API keys and tokens:** OpenAI, Anthropic, Gemini, OpenRouter, Vultr, Groq,
  xAI, Mistral, DeepSeek, Together, Cohere, Perplexity, Fireworks, Cerebras,
  AI21, Hugging Face, NVIDIA NIM, Moonshot/Kimi, DeepInfra, Qwen, Volcengine,
  StepFun, GLM, Venice, and custom OpenAI-compatible endpoints.
- **Local providers:** Ollama, LM Studio, MiniMind, and llama.cpp do not require
  hosted API credentials. The local server or runtime still needs to be
  installed and running.
- **OAuth connector slots:** Ghost Chimera exposes OpenClaw-style OAuth metadata
  where a provider has a plausible external-auth path. These slots are modular
  and do not make OAuth mandatory.
- **Codex CLI OAuth bridge:** OpenAI ChatGPT/Codex OAuth can be activated
  through the official local `codex` CLI session. Ghost Chimera checks
  `codex login status` and delegates model turns through `codex exec`; it does
  not read `~/.codex/auth.json` or copy refresh tokens into Ghost state.
- **OpenRouter OAuth PKCE:** Ghost can redirect to OpenRouter's official PKCE
  flow and exchange the callback code for a user-controlled OpenRouter API key.
  The returned key is stored write-only and can activate the `openrouter`
  provider.
- **Hugging Face device OAuth:** If `HUGGINGFACE_OAUTH_CLIENT_ID` is configured
  for a public Hugging Face OAuth app, Ghost can launch the official device-code
  flow and poll it into a write-only `HF_TOKEN`.
- **Google OAuth / ADC:** Ghost can launch `gcloud auth application-default
  login` for Google/Gemini setup. Runtime activation still requires Gemini ADC
  provider support; the current built-in Gemini provider continues to support
  API-key auth.

## ChatGPT Subscription And OpenAI API

The OpenAI API key path remains the production API path. A ChatGPT subscription
is not stored as an OpenAI API key. For users who already use Codex with
ChatGPT login, Ghost Chimera can use the **Codex CLI OAuth Bridge**:

1. Install and log into the official Codex CLI:
   `codex login --device-auth`
2. Verify it:
   `codex login status`
3. In Ghost Console, choose **OpenAI** and **ChatGPT/Codex OAuth**.
4. Click **Connect**. If the CLI is not logged in, Ghost launches the official
   Codex device-login flow in a separate local process; complete the browser or
   device prompt and click **Connect** again.
5. If the CLI reports logged in, save it as active.

When activated, the dashboard writes `codex_cli` as the active provider and
routes through Codex's own OAuth-managed runtime. The dashboard still does not
scrape browser sessions, cookies, or local ChatGPT data.

The default bridge model is `gpt-5.4-mini` for latency. You can choose a
different Codex-supported model such as `gpt-5.4`, `gpt-5.3-codex`, or
`gpt-5.2` in the dashboard model field.

## Dashboard Flow

1. Open `http://127.0.0.1:8766/`.
2. Go to **Config**.
3. Pick a provider and model.
4. For hosted providers, paste the provider key once.
5. Click **Save Provider Auth** or **Save Config**.
6. Use **Discover Models** to review compatible models before switching.

Secrets are write-only. API responses and model cards return configured/not
configured status, not raw credentials.

## Provider OAuth Matrix

| Provider | Ghost behavior | Runtime activation |
| --- | --- | --- |
| OpenAI / Codex | Launches or verifies official `codex login --device-auth`; routes through `codex_cli`. | Yes, through local Codex CLI bridge. |
| OpenRouter | Opens official PKCE authorization and stores the returned user-controlled API key write-only. | Yes, as `openrouter`. |
| Hugging Face | Starts official device-code OAuth when `HUGGINGFACE_OAUTH_CLIENT_ID` is set, then polls for an access token. | Yes, as `huggingface` after polling succeeds. |
| Google Gemini | Launches official gcloud ADC login. | Not yet; current Gemini runtime still uses API key. |
| Anthropic | API key remains the supported runtime path. | No third-party consumer OAuth reuse is enabled. |

Ghost intentionally does not scrape browser sessions, cookies, CLI credential
files, or hidden OAuth token stores for any provider.

## Email OAuth For Personal MiniMind

Ghost Console also supports read-only email OAuth for Personal MiniMind. Non-technical
users can configure the required OAuth client IDs from **Config -> Email OAuth For
MiniMind**; editing `.env` is optional.

| Provider | Required app setting | Scope posture |
| --- | --- | --- |
| Gmail | `GMAIL_OAUTH_CLIENT_ID` or `GOOGLE_OAUTH_CLIENT_ID` | `gmail.readonly` only |
| Outlook | `OUTLOOK_OAUTH_CLIENT_ID` or `MS_GRAPH_CLIENT_ID` | `Mail.Read`, `User.Read`, `offline_access` |

The flow is device-code based:

1. Add the Gmail or Outlook OAuth client ID in the Config tab and click
   **Save Config**.
2. Open the MiniMind tab, choose Gmail or Outlook, and click **Start OAuth**.
3. Complete the provider browser/device prompt.
4. Click **Poll** to store the resulting token locally.

Tokens are stored under the local Ghost state directory and never returned in
Console API responses. Saved client IDs are written to the local dashboard config
and `.env` compatibility file; token values remain write-only.

Email crawling remains consent-gated. Personal MiniMind must have admin consent
and email-crawl consent enabled before `/api/console/email/oauth/crawl` can
ingest messages into memory or generate dataset records.

## Ollama

Ollama is built in as a first-class local provider.

1. Install Ollama.
2. Pull a model, for example `ollama pull llama3.2`.
3. Start the server if needed: `ollama serve`.
4. In Ghost Console, choose **Ollama**, set model `llama3.2`, and save.

Default base URL: `http://localhost:11434`

## Extension Point

Provider OAuth connectors should implement the existing
`ghostchimera.model_layer.auth_profiles.ExternalAuthProvider` contract and
register with the credential pool. This keeps OpenClaw-style auth modular:
users who prefer API keys or local models can opt out entirely.

The `codex_cli` bridge is intentionally separate from direct OpenAI API access.
It is useful for local operator workflows, but it is not a substitute for an
organization-managed OpenAI API key in production deployments.
