"""Tests for AI model configuration and resolution."""

import os
from unittest.mock import MagicMock, patch

from github_overlord.ai import (
    DEFAULT_MODEL,
    get_agent,
    get_expected_ai_key_var,
    is_ai_key_configured,
    normalize_model_name,
    resolve_model_name,
)
from github_overlord.release_checker import ReleaseAnalysis, should_create_release
from github_overlord.stale_commenter import is_stale_comment


def test_default_model():
    assert DEFAULT_MODEL == "google:gemini-3.8-flash"


def test_normalize_model_name():
    assert normalize_model_name("gemini-3.8-flash") == "google:gemini-3.8-flash"
    assert normalize_model_name("google:gemini-3.8-flash") == "google:gemini-3.8-flash"
    assert normalize_model_name("gpt-4o") == "openai:gpt-4o"
    assert normalize_model_name("openai:gpt-4o") == "openai:gpt-4o"
    assert normalize_model_name("claude-3-5-sonnet") == "anthropic:claude-3-5-sonnet"
    assert normalize_model_name("ollama/llama3") == "ollama/llama3"


def test_resolve_model_name():
    assert resolve_model_name("claude-3-5-sonnet") == "anthropic:claude-3-5-sonnet"
    with patch.dict(os.environ, {}, clear=True):
        assert resolve_model_name() == DEFAULT_MODEL

    with patch.dict(os.environ, {"GITHUB_OVERLORD_MODEL": "gpt-4o"}, clear=True):
        assert resolve_model_name() == "openai:gpt-4o"


def test_get_expected_ai_key_var():
    assert get_expected_ai_key_var("gemini-3.8-flash") == "GOOGLE_API_KEY"
    assert get_expected_ai_key_var("openai:gpt-4o") == "OPENAI_API_KEY"
    assert get_expected_ai_key_var("anthropic:claude-3-5-sonnet") == "ANTHROPIC_API_KEY"


def test_is_ai_key_configured():
    with patch.dict(os.environ, {}, clear=True):
        assert is_ai_key_configured() is False

    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}, clear=True):
        assert is_ai_key_configured() is True
        assert is_ai_key_configured("openai:gpt-4o") is False

    with patch.dict(os.environ, {"GITHUB_OVERLORD_AI_KEY": "generic-key"}, clear=True):
        assert is_ai_key_configured() is True
        assert is_ai_key_configured("openai:gpt-4o") is True


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


def test_should_create_release():
    mock_repo = MagicMock()
    mock_repo.get_releases.return_value = []
    mock_commit = MagicMock()
    mock_commit.commit.message = "feat: add cool feature"
    mock_commit.commit.author.name = "dev"
    mock_commit.commit.author.date = MagicMock()
    mock_commit.commit.author.date.strftime.return_value = "2026-09-01"
    mock_repo.get_commits.return_value = [mock_commit]
    mock_repo.default_branch = "main"
    mock_repo.full_name = "org/repo"

    analysis = ReleaseAnalysis(
        should_release="yes",
        confidence=95,
        reasoning="Significant feature added.",
        suggested_version_bump="minor",
        release_notes="## Features\n- Added cool feature",
    )

    with patch(
        "github_overlord.release_checker.analyze_commits_with_llm",
        return_value=analysis,
    ):
        decision = should_create_release(mock_repo)
        assert decision.should_create is True
        assert decision.suggested_version == "v1.0.0"
        assert "## Features" in decision.release_notes
        assert "**Full Changelog**" in decision.release_notes
