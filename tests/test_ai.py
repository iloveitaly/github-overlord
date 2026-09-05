"""Tests for AI model configuration and resolution."""

import os
from unittest.mock import MagicMock, patch

from github_overlord.ai import (
    DEFAULT_MODEL_NAME,
    get_agent,
    normalize_model_name,
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


def test_get_agent_universal_key_mapping():
    with patch.dict(
        os.environ,
        {
            "GITHUB_OVERLORD_AI_KEY": "test-key",
            "GITHUB_OVERLORD_MODEL": "gemini-3.8-flash",
        },
        clear=True,
    ):
        agent = get_agent()
        assert os.environ.get("GOOGLE_API_KEY") == "test-key"
        assert agent is not None


def test_get_agent_key_precedence():
    with patch.dict(
        os.environ,
        {
            "GITHUB_OVERLORD_AI_KEY": "generic-key",
            "GOOGLE_API_KEY": "specific-key",
            "GITHUB_OVERLORD_MODEL": "gemini-3.8-flash",
        },
        clear=True,
    ):
        agent = get_agent()
        assert os.environ.get("GOOGLE_API_KEY") == "specific-key"
        assert agent is not None


def test_get_agent_overload_alias():
    with patch.dict(
        os.environ,
        {
            "GITHUB_OVERLOAD_AI_KEY": "overload-key",
            "GITHUB_OVERLOAD_MODEL": "gemini-3.8-flash",
        },
        clear=True,
    ):
        agent = get_agent()
        assert os.environ.get("GOOGLE_API_KEY") == "overload-key"
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
