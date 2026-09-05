"""AI model configuration and utilities for github-overlord."""

import os
from typing import Any

from pydantic_ai import Agent, ModelSettings
from pydantic_ai.models.google import GoogleModel

DEFAULT_MODEL_NAME = "google:gemini-3.8-flash"

PROVIDER_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "cohere": "CO_API_KEY",
}


def normalize_model_name(model_name: str) -> str:
    """Normalize model string to ensure provider prefix is present for pydantic_ai."""
    model_name = model_name.strip()
    if ":" in model_name:
        return model_name

    if model_name.startswith("gemini"):
        return f"google:{model_name}"
    if model_name.startswith(("gpt", "o1", "o3")):
        return f"openai:{model_name}"
    if model_name.startswith("claude"):
        return f"anthropic:{model_name}"

    return model_name


def map_ai_key(ai_key: str, model_name: str) -> None:
    """
    Map universal GITHUB_OVERLORD_AI_KEY to the provider-specific environment variable.
    Specific keys already present in the environment take precedence.
    """
    provider = model_name.split(":")[0]

    if (target_key := PROVIDER_KEY_MAP.get(provider)) and target_key not in os.environ:
        os.environ[target_key] = ai_key


def update_env_variables() -> None:
    """
    Allow keys specific to GITHUB_OVERLORD (or GITHUB_OVERLOAD typo alias) to be set globally
    so project-specific keys can be used for AI calls.
    """
    prefixes = ("GITHUB_OVERLORD_", "GITHUB_OVERLOAD_")
    for key in list(os.environ.keys()):
        for prefix in prefixes:
            if key.startswith(prefix):
                base_key = key[len(prefix) :]
                if base_key not in ("AI_KEY", "MODEL"):
                    os.environ[base_key] = os.environ[key]

    model_name = get_model_name()

    if ai_key := os.environ.get("GITHUB_OVERLORD_AI_KEY") or os.environ.get(
        "GITHUB_OVERLOAD_AI_KEY"
    ):
        map_ai_key(ai_key, model_name)


def get_model_name() -> str:
    """Get the configured or default model name, normalized for pydantic_ai."""
    raw_model = (
        os.environ.get("GITHUB_OVERLORD_MODEL")
        or os.environ.get("GITHUB_OVERLOAD_MODEL")
        or DEFAULT_MODEL_NAME
    )
    return normalize_model_name(raw_model)


def get_expected_ai_key_var() -> str:
    """Return the expected environment variable name for the active model provider."""
    model = get_model_name()
    provider = model.split(":")[0]
    return PROVIDER_KEY_MAP.get(provider, "AI_KEY")


def is_ai_key_configured() -> bool:
    """Check if the active model provider has an API key configured in the environment."""
    update_env_variables()
    target_var = get_expected_ai_key_var()
    return bool(os.getenv(target_var))


def get_agent(
    model: str | None = None,
    output_type: Any = None,
    system_prompt: str | None = None,
) -> Agent:
    """Create a configured pydantic_ai Agent."""
    update_env_variables()
    resolved_model = normalize_model_name(model) if model else get_model_name()
    kwargs: dict[str, Any] = {}
    if output_type is not None:
        kwargs["output_type"] = output_type
    if system_prompt is not None:
        kwargs["system_prompt"] = system_prompt
    return Agent(resolved_model, **kwargs)


def run_agent_sync(agent: Agent, prompt: str, **kwargs: Any) -> Any:
    """Run agent synchronously with provider-optimized settings."""
    model_settings = kwargs.pop("model_settings", None)
    if model_settings is None and isinstance(agent.model, GoogleModel):
        model_settings = ModelSettings(thinking="low")
    return agent.run_sync(prompt, model_settings=model_settings, **kwargs)
