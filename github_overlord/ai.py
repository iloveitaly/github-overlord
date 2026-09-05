"""AI agent configuration for github-overlord."""

import os
from typing import Any

from pydantic_ai import Agent, ModelSettings

DEFAULT_MODEL_NAME = "google:gemini-3.8-flash"
DEFAULT_MODEL = DEFAULT_MODEL_NAME


def normalize_model_name(model_name: str) -> str:
    """Ensure provider prefix is present for shorthand model names."""
    cleaned = model_name.strip()
    if ":" in cleaned or "/" in cleaned:
        return cleaned
    if cleaned.startswith("gemini"):
        return f"google:{cleaned}"
    if cleaned.startswith(("gpt", "o1", "o3")):
        return f"openai:{cleaned}"
    if cleaned.startswith("claude"):
        return f"anthropic:{cleaned}"
    return cleaned


def get_expected_ai_key_var(model: str | None = None) -> str:
    """Return the expected environment variable name for the active model provider."""
    raw_model = (
        model
        or os.getenv("GITHUB_OVERLORD_MODEL")
        or os.getenv("GITHUB_OVERLOAD_MODEL")
        or DEFAULT_MODEL
    )
    selected_model = normalize_model_name(raw_model)
    provider = selected_model.split(":")[0] if ":" in selected_model else "google"
    return (
        "GOOGLE_API_KEY"
        if provider in ("google", "gemini")
        else f"{provider.upper()}_API_KEY"
    )


def is_ai_key_configured() -> bool:
    """Check if an API key is configured for the active model provider."""
    if os.getenv("GITHUB_OVERLORD_AI_KEY") or os.getenv("GITHUB_OVERLOAD_AI_KEY"):
        return True
    return bool(os.getenv(get_expected_ai_key_var()))


def get_agent(
    model: str | None = None,
    output_type: Any = None,
    system_prompt: str | None = None,
) -> Agent[Any, Any]:
    """Create a configured Pydantic AI Agent."""
    raw_model = (
        model
        or os.getenv("GITHUB_OVERLORD_MODEL")
        or os.getenv("GITHUB_OVERLOAD_MODEL")
        or DEFAULT_MODEL
    )
    selected_model = normalize_model_name(raw_model)

    # Map generic GITHUB_OVERLORD_AI_KEY to provider-specific env var if not already set
    if generic_key := os.getenv("GITHUB_OVERLORD_AI_KEY") or os.getenv(
        "GITHUB_OVERLOAD_AI_KEY"
    ):
        target_env = get_expected_ai_key_var(selected_model)
        os.environ.setdefault(target_env, generic_key)

    kwargs: dict[str, Any] = {}
    if output_type is not None:
        kwargs["output_type"] = output_type
    if system_prompt is not None:
        kwargs["system_prompt"] = system_prompt
    if selected_model.startswith("google:"):
        kwargs["model_settings"] = ModelSettings(thinking="low")

    return Agent(selected_model, **kwargs)
