"""Provider auth catalog for Ghost Chimera.

This module adapts the useful OpenClaw provider-auth idea into a Ghost-native
shape: every provider exposes declarative auth choices, but runtime activation
stays modular and explicit. API keys remain write-only. OAuth entries are
advertised only as capabilities when a provider has a plausible connector path;
the catalog does not pretend a ChatGPT subscription is the same thing as an
OpenAI API key.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

AuthMethod = Literal["api_key", "oauth", "token", "local", "custom"]


@dataclass(frozen=True)
class ProviderAuthChoice:
    """One selectable auth method for a provider."""

    method: AuthMethod
    label: str
    status: str
    description: str
    setup_hint: str = ""
    supports_runtime_activation: bool = True
    requires_secret: bool = True
    scopes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderAuthSpec:
    """Provider metadata used by Config, discovery, and auth vault surfaces."""

    id: str
    name: str
    description: str
    models: list[str]
    api_key_env: str = ""
    model_env: str = ""
    base_url_env: str = ""
    default_base_url: str = ""
    base_url_required: bool = False
    api_key_label: str = ""
    auth_choices: list[ProviderAuthChoice] = field(default_factory=list)
    capability_badges: list[str] = field(default_factory=list)
    docs_url: str = ""

    @property
    def requires_api_key(self) -> bool:
        return bool(self.api_key_env)

    def to_console_option(self) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "models": self.models,
            "requires_api_key": self.requires_api_key,
            "base_url_required": self.base_url_required,
            "api_key_label": self.api_key_label,
            "default_base_url": self.default_base_url,
            "auth_methods": [choice.to_dict() for choice in self.auth_choices],
            "oauth_supported": any(choice.method == "oauth" for choice in self.auth_choices),
            "capability_badges": self.capability_badges,
            "docs_url": self.docs_url,
            "setup_url": provider_auth_setup_url(self.id),
        }
        return {key: value for key, value in payload.items() if value not in ("", [], None)}


API_KEY = ProviderAuthChoice(
    method="api_key",
    label="API key",
    status="ready",
    description="Use a provider-issued API key stored locally as a write-only secret.",
    setup_hint="Paste the key once in Config. Ghost Chimera will never echo it back.",
)

LOCAL = ProviderAuthChoice(
    method="local",
    label="Local server",
    status="ready",
    description="No hosted provider credential is required. The local runtime must already be running.",
    setup_hint="Start the local server and select the model tag.",
    requires_secret=False,
)

OPENAI_CODEX_OAUTH = ProviderAuthChoice(
    method="oauth",
    label="ChatGPT/Codex OAuth",
    status="codex_cli_bridge",
    description=(
        "Use the official local Codex CLI OAuth session as a Ghost model bridge without "
        "reading or copying Codex token files."
    ),
    setup_hint=(
        "Click Connect to check Codex login status. If needed, run the official Codex login flow, "
        "then activate the Codex CLI bridge."
    ),
    supports_runtime_activation=True,
    scopes=["codex", "chatgpt-subscription"],
)

ANTHROPIC_CLI_OAUTH = ProviderAuthChoice(
    method="oauth",
    label="Claude CLI / subscription auth",
    status="connector_required",
    description="OpenClaw supports this through provider-specific CLI auth reuse; Ghost keeps it modular.",
    setup_hint="Use Anthropic API key unless a local external auth connector is installed.",
    supports_runtime_activation=False,
    scopes=["claude-cli"],
)

GENERIC_OAUTH_CONNECTOR = ProviderAuthChoice(
    method="oauth",
    label="Provider OAuth connector",
    status="provider_specific",
    description="Available only when the provider publishes an OAuth flow for model inference.",
    setup_hint="Install or implement an ExternalAuthProvider connector for this provider.",
    supports_runtime_activation=False,
)

OPENROUTER_PKCE_OAUTH = ProviderAuthChoice(
    method="oauth",
    label="OpenRouter OAuth PKCE",
    status="ready",
    description=(
        "Redirect to OpenRouter, then exchange the authorization code for a user-controlled API key."
    ),
    setup_hint="Click Connect to open the OpenRouter authorization page.",
    supports_runtime_activation=True,
    scopes=["openrouter-api-key"],
)

HUGGINGFACE_DEVICE_OAUTH = ProviderAuthChoice(
    method="oauth",
    label="Hugging Face device OAuth",
    status="client_id_required",
    description=(
        "Use Hugging Face's official device-code OAuth flow for Inference Providers when an OAuth client ID is configured."
    ),
    setup_hint="Set HUGGINGFACE_OAUTH_CLIENT_ID, then click Connect to get a browser code.",
    supports_runtime_activation=True,
    scopes=["openid", "profile", "inference-api"],
)

GOOGLE_ADC_OAUTH = ProviderAuthChoice(
    method="oauth",
    label="Google OAuth / ADC",
    status="adc_setup",
    description=(
        "Launch Google's official application-default credentials flow. Runtime activation needs Gemini ADC support."
    ),
    setup_hint="Click Connect to launch gcloud auth application-default login if gcloud is installed.",
    supports_runtime_activation=False,
    requires_secret=False,
    scopes=["cloud-platform", "generative-language"],
)


_SPECS: dict[str, ProviderAuthSpec] = {
    "openai": ProviderAuthSpec(
        id="openai",
        name="OpenAI",
        description="Hosted OpenAI API models.",
        models=["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"],
        api_key_env="OPENAI_API_KEY",
        model_env="OPENAI_MODEL",
        base_url_env="OPENAI_BASE_URL",
        api_key_label="OpenAI API key",
        auth_choices=[API_KEY, OPENAI_CODEX_OAUTH],
        capability_badges=["reasoning", "vision", "tool-calling"],
        docs_url="https://platform.openai.com/docs",
    ),
    "codex_cli": ProviderAuthSpec(
        id="codex_cli",
        name="Codex CLI OAuth Bridge",
        description="Local bridge to an already-authenticated Codex CLI ChatGPT/Codex session.",
        models=["gpt-5.4-mini", "gpt-5.4", "gpt-5.3-codex", "gpt-5.2"],
        model_env="CODEX_MODEL",
        auth_choices=[OPENAI_CODEX_OAUTH],
        capability_badges=["oauth", "chatgpt-subscription", "local-bridge"],
        docs_url="https://developers.openai.com/codex/",
    ),
    "anthropic": ProviderAuthSpec(
        id="anthropic",
        name="Anthropic",
        description="Claude models through Anthropic.",
        models=["claude-3-5-haiku-20241022", "claude-sonnet-4-6", "claude-opus-4-6"],
        api_key_env="ANTHROPIC_API_KEY",
        model_env="ANTHROPIC_MODEL",
        api_key_label="Anthropic API key",
        auth_choices=[API_KEY, ANTHROPIC_CLI_OAUTH],
        capability_badges=["reasoning", "long-context", "tool-calling"],
        docs_url="https://docs.anthropic.com/",
    ),
    "gemini": ProviderAuthSpec(
        id="gemini",
        name="Google Gemini",
        description="Gemini models through Google AI Studio or Gemini API.",
        models=["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-exp"],
        api_key_env="GOOGLE_API_KEY",
        model_env="GEMINI_MODEL",
        api_key_label="Google/Gemini API key",
        auth_choices=[API_KEY, GOOGLE_ADC_OAUTH],
        capability_badges=["vision", "long-context", "multimodal"],
        docs_url="https://ai.google.dev/",
    ),
    "openrouter": ProviderAuthSpec(
        id="openrouter",
        name="OpenRouter",
        description="Many hosted models behind one OpenRouter API key.",
        models=["openai/gpt-4o-mini", "anthropic/claude-3-5-haiku", "google/gemini-flash-1.5"],
        api_key_env="OPENROUTER_API_KEY",
        model_env="OPENROUTER_MODEL",
        default_base_url="https://openrouter.ai/api/v1",
        api_key_label="OpenRouter API key",
        auth_choices=[API_KEY, OPENROUTER_PKCE_OAUTH],
        capability_badges=["model-router", "discovery", "fallbacks"],
        docs_url="https://openrouter.ai/docs",
    ),
    "vultr": ProviderAuthSpec(
        id="vultr",
        name="Vultr Serverless Inference",
        description="OpenAI-compatible Vultr serverless inference.",
        models=["", "llama-3.1-70b", "mixtral-8x7b"],
        api_key_env="VULTR_INFERENCE_API_KEY",
        model_env="VULTR_INFERENCE_MODEL",
        base_url_env="VULTR_INFERENCE_BASE_URL",
        default_base_url="https://api.vultrinference.com/v1/chat/completions",
        base_url_required=True,
        api_key_label="Vultr inference API key",
        auth_choices=[API_KEY],
        capability_badges=["serverless", "open-weight"],
    ),
    "ollama": ProviderAuthSpec(
        id="ollama",
        name="Ollama",
        description="Local Ollama models running on this machine.",
        models=["llama3.2", "mistral", "qwen2.5:7b", "deepseek-r1:7b"],
        model_env="OLLAMA_MODEL",
        base_url_env="OLLAMA_BASE_URL",
        default_base_url="http://localhost:11434",
        auth_choices=[LOCAL],
        capability_badges=["local/private", "no-key", "open-weight"],
        docs_url="https://ollama.com/",
    ),
    "lmstudio": ProviderAuthSpec(
        id="lmstudio",
        name="LM Studio",
        description="Local LM Studio OpenAI-compatible server.",
        models=["lmstudio-community/Meta-Llama-3.1-8B-Instruct-GGUF", "any"],
        model_env="LMSTUDIO_MODEL",
        base_url_env="LMSTUDIO_BASE_URL",
        default_base_url="http://localhost:1234",
        auth_choices=[LOCAL],
        capability_badges=["local/private", "no-key", "open-weight"],
        docs_url="https://lmstudio.ai/",
    ),
    "minimind": ProviderAuthSpec(
        id="minimind",
        name="Local MiniMind",
        description="Local-first MiniMind profile without a hosted API key.",
        models=["tiny", "balanced", "stronger"],
        model_env="MINIMIND_MODEL_PROFILE",
        auth_choices=[LOCAL],
        capability_badges=["local/private", "personal-rag", "no-key"],
    ),
    "llamacpp": ProviderAuthSpec(
        id="llamacpp",
        name="llama.cpp",
        description="Local GGUF runtime through llama-cpp-python.",
        models=["local"],
        model_env="LLAMACPP_MODEL_PATH",
        auth_choices=[LOCAL],
        capability_badges=["local/private", "gguf", "no-key"],
    ),
    "custom": ProviderAuthSpec(
        id="custom",
        name="Custom OpenAI-Compatible",
        description="Any OpenAI-compatible endpoint not listed yet.",
        models=[""],
        api_key_env="OPENAI_API_KEY",
        model_env="CUSTOM_MODEL",
        base_url_env="OPENAI_BASE_URL",
        base_url_required=True,
        api_key_label="Endpoint API key",
        auth_choices=[API_KEY, GENERIC_OAUTH_CONNECTOR],
        capability_badges=["bring-your-own-endpoint"],
    ),
}


def _add_openai_compatible(
    provider_id: str,
    *,
    name: str,
    description: str,
    models: list[str],
    api_key_env: str,
    model_env: str,
    default_base_url: str = "",
    badges: list[str] | None = None,
    docs_url: str = "",
) -> None:
    _SPECS[provider_id] = ProviderAuthSpec(
        id=provider_id,
        name=name,
        description=description,
        models=models,
        api_key_env=api_key_env,
        model_env=model_env,
        default_base_url=default_base_url,
        api_key_label=f"{name} API key",
        auth_choices=[API_KEY],
        capability_badges=badges or ["openai-compatible"],
        docs_url=docs_url,
    )


_add_openai_compatible("groq", name="Groq", description="Low-latency hosted LPU inference.", models=["llama-3.3-70b-versatile", "llama-3.1-8b-instant"], api_key_env="GROQ_API_KEY", model_env="GROQ_MODEL", badges=["fast", "open-weight"])
_add_openai_compatible("xai", name="xAI", description="Grok model family through xAI.", models=["grok-3-mini", "grok-3"], api_key_env="XAI_API_KEY", model_env="XAI_MODEL", badges=["reasoning"])
_add_openai_compatible("mistral", name="Mistral AI", description="Mistral hosted models.", models=["mistral-small-latest", "mistral-large-latest", "codestral-latest"], api_key_env="MISTRAL_API_KEY", model_env="MISTRAL_MODEL", badges=["open-weight", "code"])
_add_openai_compatible("deepseek", name="DeepSeek", description="DeepSeek chat and reasoning models.", models=["deepseek-chat", "deepseek-reasoner"], api_key_env="DEEPSEEK_API_KEY", model_env="DEEPSEEK_MODEL", badges=["reasoning", "low-cost"])
_add_openai_compatible("together", name="Together AI", description="Hosted open-weight model inference.", models=["meta-llama/Llama-3-70b-chat-hf", "Qwen/Qwen2.5-72B-Instruct-Turbo"], api_key_env="TOGETHER_API_KEY", model_env="TOGETHER_MODEL", badges=["open-weight"])
_add_openai_compatible("cohere", name="Cohere", description="Command family models through Cohere.", models=["command-r-plus", "command-r"], api_key_env="COHERE_API_KEY", model_env="COHERE_MODEL", badges=["enterprise", "rag"])
_add_openai_compatible("perplexity", name="Perplexity", description="Search-augmented Sonar models.", models=["llama-3.1-sonar-small-128k-online", "llama-3.1-sonar-large-128k-online"], api_key_env="PERPLEXITY_API_KEY", model_env="PERPLEXITY_MODEL", badges=["web", "research"])
_add_openai_compatible("fireworks", name="Fireworks AI", description="Fast open-weight model inference.", models=["accounts/fireworks/models/llama-v3p1-70b-instruct", "accounts/fireworks/models/deepseek-r1"], api_key_env="FIREWORKS_API_KEY", model_env="FIREWORKS_MODEL", badges=["fast", "open-weight"])
_add_openai_compatible("cerebras", name="Cerebras", description="Ultra-fast inference on Cerebras Cloud.", models=["llama3.1-70b", "llama3.1-8b"], api_key_env="CEREBRAS_API_KEY", model_env="CEREBRAS_MODEL", badges=["fast"])
_add_openai_compatible("ai21", name="AI21 Labs", description="Jamba model family.", models=["jamba-1.5-mini", "jamba-1.5-large"], api_key_env="AI21_API_KEY", model_env="AI21_MODEL", badges=["enterprise"])
_SPECS["huggingface"] = ProviderAuthSpec(
    id="huggingface",
    name="Hugging Face",
    description="Hugging Face Inference API for compatible open models.",
    models=["meta-llama/Llama-3.3-70B-Instruct", "Qwen/Qwen2.5-72B-Instruct"],
    api_key_env="HF_TOKEN",
    model_env="HUGGINGFACE_MODEL",
    default_base_url="https://api-inference.huggingface.co/v1/chat/completions",
    api_key_label="Hugging Face token",
    auth_choices=[API_KEY, HUGGINGFACE_DEVICE_OAUTH],
    capability_badges=["open-weight", "model-hub"],
    docs_url="https://huggingface.co/docs/hub/oauth",
)
_add_openai_compatible("nvidia", name="NVIDIA NIM", description="NVIDIA hosted NIM inference.", models=["meta/llama-3.1-70b-instruct", "nvidia/llama-3.1-nemotron-70b-instruct"], api_key_env="NVIDIA_API_KEY", model_env="NVIDIA_MODEL", badges=["gpu", "open-weight"])
_add_openai_compatible("moonshot", name="Moonshot Kimi", description="Moonshot Kimi long-context models.", models=["moonshot-v1-8k", "moonshot-v1-128k"], api_key_env="MOONSHOT_API_KEY", model_env="MOONSHOT_MODEL", badges=["long-context"])
_add_openai_compatible("deepinfra", name="DeepInfra", description="Affordable hosted open-weight inference.", models=["meta-llama/Meta-Llama-3.1-70B-Instruct", "deepseek-ai/DeepSeek-R1"], api_key_env="DEEPINFRA_API_KEY", model_env="DEEPINFRA_MODEL", badges=["open-weight", "low-cost"])
_add_openai_compatible("qwen", name="Alibaba Qwen", description="Qwen models through DashScope.", models=["qwen-turbo", "qwen-max", "qwen2.5-72b-instruct"], api_key_env="DASHSCOPE_API_KEY", model_env="QWEN_MODEL", badges=["reasoning", "long-context"])
_add_openai_compatible("volcengine", name="Volcengine Doubao", description="ByteDance Doubao / ARK models.", models=["doubao-pro-4k", "doubao-pro-32k"], api_key_env="ARK_API_KEY", model_env="VOLCENGINE_MODEL", badges=["enterprise"])
_add_openai_compatible("stepfun", name="StepFun", description="Step model family.", models=["step-1-8k", "step-1-200k"], api_key_env="STEPFUN_API_KEY", model_env="STEPFUN_MODEL", badges=["long-context"])
_add_openai_compatible("glm", name="ZhipuAI GLM", description="GLM-4 model family.", models=["glm-4-flash", "glm-4", "glm-4-long"], api_key_env="ZHIPUAI_API_KEY", model_env="GLM_MODEL", badges=["long-context"])
_add_openai_compatible("venice", name="Venice AI", description="Privacy-oriented open-weight inference.", models=["llama-3.3-70b", "deepseek-r1-671b"], api_key_env="VENICE_API_KEY", model_env="VENICE_MODEL", badges=["private", "open-weight"])


_PROVIDER_SETUP_URLS: dict[str, str] = {
    "ai21": "https://studio.ai21.com/account/api-key",
    "anthropic": "https://console.anthropic.com/settings/keys",
    "cerebras": "https://cloud.cerebras.ai/platform",
    "codex_cli": "https://developers.openai.com/codex/",
    "cohere": "https://dashboard.cohere.com/api-keys",
    "custom": "https://platform.openai.com/docs/api-reference",
    "deepinfra": "https://deepinfra.com/dash/api_keys",
    "deepseek": "https://platform.deepseek.com/api_keys",
    "fireworks": "https://fireworks.ai/api-keys",
    "gemini": "https://ai.google.dev/gemini-api/docs/oauth",
    "glm": "https://bigmodel.cn/usercenter/proj-mgmt/apikeys",
    "groq": "https://console.groq.com/keys",
    "huggingface": "https://huggingface.co/settings/tokens",
    "llamacpp": "https://github.com/abetlen/llama-cpp-python",
    "lmstudio": "https://lmstudio.ai/docs/app/api/endpoints/openai",
    "minimind": "https://github.com/jingyaogong/minimind",
    "mistral": "https://console.mistral.ai/api-keys",
    "moonshot": "https://platform.moonshot.ai/console/api-keys",
    "nvidia": "https://build.nvidia.com/api-keys",
    "ollama": "https://ollama.com/download",
    "openai": "https://platform.openai.com/api-keys",
    "openrouter": "https://openrouter.ai/settings/keys",
    "perplexity": "https://www.perplexity.ai/settings/api",
    "qwen": "https://bailian.console.aliyun.com/?tab=model#/api-key",
    "stepfun": "https://platform.stepfun.com/account/api-key",
    "together": "https://api.together.ai/settings/api-keys",
    "venice": "https://venice.ai/settings/api",
    "volcengine": "https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey",
    "vultr": "https://my.vultr.com/settings/#settingsapi",
    "xai": "https://console.x.ai/",
}


def provider_auth_setup_url(provider_id: str) -> str:
    """Return the safest official setup URL for a provider."""

    return _PROVIDER_SETUP_URLS.get(provider_id.strip().lower(), "")


def get_provider_auth_spec(provider_id: str) -> ProviderAuthSpec | None:
    return _SPECS.get(provider_id.strip().lower())


def list_provider_auth_specs(include_custom: bool = True) -> list[ProviderAuthSpec]:
    specs = list(_SPECS.values())
    if not include_custom:
        specs = [spec for spec in specs if spec.id != "custom"]
    return sorted(specs, key=lambda spec: (spec.id in {"custom"}, spec.name.lower()))


def list_provider_options() -> list[dict[str, Any]]:
    return [spec.to_console_option() for spec in list_provider_auth_specs()]


def provider_env_keys() -> set[str]:
    keys = {"GHOSTCHIMERA_MODEL_PROVIDER"}
    for spec in _SPECS.values():
        keys.update(key for key in (spec.api_key_env, spec.model_env, spec.base_url_env) if key)
    return keys


def config_to_provider_env(model: dict[str, Any]) -> dict[str, str]:
    provider = str(model.get("provider") or "").strip().lower()
    spec = get_provider_auth_spec(provider)
    if not spec:
        return {}
    env = {"GHOSTCHIMERA_MODEL_PROVIDER": "minimind" if provider == "local" else provider}
    api_key = str(model.get("api_key") or "").strip()
    model_id = str(model.get("model") or "").strip()
    base_url = str(model.get("base_url") or "").strip()
    if spec.api_key_env and api_key:
        env[spec.api_key_env] = api_key
    if spec.model_env and model_id:
        env[spec.model_env] = model_id
    if spec.base_url_env and base_url:
        env[spec.base_url_env] = base_url
    if provider == "openrouter":
        env.setdefault("OPENAI_BASE_URL", spec.default_base_url)
    if provider == "minimind" and not model_id:
        env["MINIMIND_MODEL_PROFILE"] = "tiny"
    if provider == "codex_cli" and model_id:
        env["CODEX_MODEL"] = model_id
    return {key: value for key, value in env.items() if value}


def provider_auth_summary(config: dict[str, Any]) -> dict[str, Any]:
    model = config.get("model", {}) if isinstance(config.get("model"), dict) else {}
    saved_auth = config.get("provider_auth", {}) if isinstance(config.get("provider_auth"), dict) else {}
    active_provider = str(model.get("provider") or "").strip().lower()
    providers: list[dict[str, Any]] = []
    for spec in list_provider_auth_specs():
        record = saved_auth.get(spec.id, {}) if isinstance(saved_auth.get(spec.id, {}), dict) else {}
        is_active = spec.id == active_provider
        api_key_configured = bool(record.get("api_key")) or (is_active and bool(model.get("api_key")))
        oauth_configured = (
            bool(record.get("oauth_token"))
            or bool(record.get("oauth_connector"))
            or (is_active and bool(model.get("oauth_token")))
            or (spec.id == "openai" and active_provider == "codex_cli")
        )
        providers.append(
            {
                **spec.to_console_option(),
                "active": is_active,
                "api_key_configured": api_key_configured,
                "oauth_configured": oauth_configured,
                "selected_model": str((model if is_active else record).get("model") or ""),
                "selected_base_url": str((model if is_active else record).get("base_url") or ""),
                "configured_methods": [
                    method
                    for method, configured in (
                        ("api_key", api_key_configured),
                        ("oauth", oauth_configured),
                        ("local", any(choice.method == "local" for choice in spec.auth_choices)),
                    )
                    if configured
                ],
            }
        )
    return {
        "ok": True,
        "providers": providers,
        "active_provider": active_provider,
        "policy": {
            "secrets_are_write_only": True,
            "oauth_is_connector_based": True,
            "chatgpt_subscription_is_not_api_key": True,
        },
    }


__all__ = [
    "ProviderAuthChoice",
    "ProviderAuthSpec",
    "config_to_provider_env",
    "get_provider_auth_spec",
    "list_provider_auth_specs",
    "list_provider_options",
    "provider_auth_summary",
    "provider_auth_setup_url",
    "provider_env_keys",
]
