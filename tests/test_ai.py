"""Tests for AI model configuration and resolution."""

import os
from unittest.mock import MagicMock, patch

from github_overlord.ai import (
    DEFAULT_MODEL_NAME,
    get_agent,
    get_expected_ai_key_var,
    get_model_name,
    is_ai_key_configured,
    normalize_model_name,
    update_env_variables,
)
from github_overlord.stale_commenter import is_stale_comment


def test_default_model_name():
    assert DEFAULT_MODEL_NAME == "google:gemini-3.8-flash"


def test_normalize_model_name():
    assert normalize_model_name("gemini-3.8-flash") == "google:gemini-3.8-flash"
    assert normalize_model_name("google:gemini-3.8-flash") == "google:gemini-3.8-flash"
    assert normalize_model_name("gpt-4o") == "openai:gpt-4o"
    assert normalize_model_name("openai:gpt-4o") == "openai:gpt-4o"
    assert normalize_model_name("claude-3-5-sonnet") == "anthropic:claude-3-5-sonnet"


def test_universal_ai_key_mapping():
    test_cases = [
        ("openai:gpt-4o", "OPENAI_API_KEY"),
        ("anthropic:claude-3-5-sonnet", "ANTHROPIC_API_KEY"),
        ("gemini-3.8-flash", "GOOGLE_API_KEY"),
        ("google:gemini-3.8-flash", "GOOGLE_API_KEY"),
        ("azure:gpt-4", "AZURE_OPENAI_API_KEY"),
        ("groq:llama3", "GROQ_API_KEY"),
    ]

    for model, target_var in test_cases:
        with patch.dict(
            os.environ,
            {"GITHUB_OVERLORD_AI_KEY": "test-key-123", "GITHUB_OVERLORD_MODEL": model},
            clear=True,
        ):
            update_env_variables()
            assert os.environ.get(target_var) == "test-key-123", (
                f"Failed for model {model}"
            )


def test_ai_key_precedence():
    # Direct provider key should take precedence over universal GITHUB_OVERLORD_AI_KEY
    with patch.dict(
        os.environ,
        {
            "GITHUB_OVERLORD_AI_KEY": "universal-key",
            "GOOGLE_API_KEY": "specific-key",
            "GITHUB_OVERLORD_MODEL": "gemini-3.8-flash",
        },
        clear=True,
    ):
        update_env_variables()
        assert os.environ.get("GOOGLE_API_KEY") == "specific-key"


def test_overload_alias_support():
    # GITHUB_OVERLOAD_ (common typo) is supported as an alias
    with patch.dict(
        os.environ,
        {
            "GITHUB_OVERLOAD_AI_KEY": "overload-key",
            "GITHUB_OVERLOAD_MODEL": "gemini-3.8-flash",
        },
        clear=True,
    ):
        update_env_variables()
        assert os.environ.get("GOOGLE_API_KEY") == "overload-key"
        assert get_model_name() == "google:gemini-3.8-flash"


def test_is_ai_key_configured():
    with patch.dict(os.environ, {}, clear=True):
        assert not is_ai_key_configured()

    with patch.dict(os.environ, {"GOOGLE_API_KEY": "key"}, clear=True):
        assert is_ai_key_configured()
        assert get_expected_ai_key_var() == "GOOGLE_API_KEY"

    with patch.dict(
        os.environ,
        {"GITHUB_OVERLORD_AI_KEY": "key", "GITHUB_OVERLORD_MODEL": "openai:gpt-4o"},
        clear=True,
    ):
        assert is_ai_key_configured()
        assert get_expected_ai_key_var() == "OPENAI_API_KEY"


def test_get_agent():
    with patch.dict(
        os.environ,
        {"GITHUB_OVERLORD_MODEL": "gemini-3.8-flash", "GOOGLE_API_KEY": "dummy"},
        clear=True,
    ):
        agent = get_agent()
        assert get_model_name() == "google:gemini-3.8-flash"
        assert agent is not None


def test_is_stale_comment():
    mock_comment = MagicMock()
    mock_comment.user.login = "github-actions[bot]"
    mock_comment.body = "Marked as stale. Will be closed in 7 days."

    with patch("github_overlord.stale_commenter.get_agent") as mock_get_agent:
        mock_agent_instance = MagicMock()
        mock_output = MagicMock()
        mock_output.stale = True
        mock_output.comment = "Friendly reminder!"
        mock_result = MagicMock(output=mock_output)
        mock_agent_instance.run_sync.return_value = mock_result
        mock_get_agent.return_value = mock_agent_instance

        is_stale, comment = is_stale_comment(mock_comment)
        assert is_stale is True
        assert comment == "Friendly reminder!"
