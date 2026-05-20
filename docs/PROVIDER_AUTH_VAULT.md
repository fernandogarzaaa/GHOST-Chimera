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

## ChatGPT Subscription And OpenAI API

The OpenAI API key path is the production-safe OpenAI path today. A ChatGPT
subscription is not stored as an OpenAI API key. Ghost Chimera can model a
future OpenAI Codex/ChatGPT OAuth connector through `ExternalAuthProvider`, but
the dashboard does not scrape browser sessions, cookies, or local ChatGPT data.

## Dashboard Flow

1. Open `http://127.0.0.1:8766/`.
2. Go to **Config**.
3. Pick a provider and model.
4. For hosted providers, paste the provider key once.
5. Click **Save Provider Auth** or **Save Config**.
6. Use **Discover Models** to review compatible models before switching.

Secrets are write-only. API responses and model cards return configured/not
configured status, not raw credentials.

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
