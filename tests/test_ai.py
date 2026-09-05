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


def test_inspect_repo_for_stale_prs_handles_github_exception():
    from github.GithubException import UnknownObjectException

    from github_overlord.stale_commenter import inspect_repo_for_stale_prs

    mock_repo = MagicMock()
    mock_repo.full_name = "Codeinwp/Nivo-Slider-jQuery"
    mock_repo.get_pulls.side_effect = UnknownObjectException(
        status=404, data={"message": "Not Found"}
    )

    result = inspect_repo_for_stale_prs(
        dry_run=True, login="iloveitaly", repo=mock_repo
    )
    assert result == []


def test_check_for_stale_comments_handles_github_exception():
    from github.GithubException import GithubException
    from github.PullRequest import PullRequest

    from github_overlord.stale_commenter import check_for_stale_comments

    mock_pr = MagicMock(spec=PullRequest)
    mock_pr.html_url = "https://github.com/org/repo/pull/1"
    mock_pr.as_issue.side_effect = GithubException(
        status=404, data={"message": "Not Found"}
    )

    # Should not raise exception and return None
    result = check_for_stale_comments(dry_run=True, pr=mock_pr)
    assert result is None


def test_check_for_stale_comments_skips_zero_comments():
    from github_overlord.stale_commenter import check_for_stale_comments

    mock_pr = MagicMock()
    mock_pr.comments = 0
    mock_pr.as_issue.return_value = mock_pr

    result = check_for_stale_comments(dry_run=True, pr=mock_pr)
    assert result is False
    mock_pr.get_comments.assert_not_called()


def test_inspect_stale_prs_search_query_without_repo():
    from github_overlord.stale_commenter import inspect_stale_prs

    mock_github = MagicMock()
    mock_issue = MagicMock()
    mock_issue.comments = 0
    mock_github.search_issues.return_value = [mock_issue]

    result = inspect_stale_prs(
        github=mock_github, login="testuser", dry_run=True, repo=None
    )
    mock_github.search_issues.assert_called_once_with(
        "is:pr is:open author:testuser -user:testuser"
    )
    assert result.checked == 1
    assert result.inspected == 1
    assert result.kept_alive == 0
    assert result.skipped == 1
    assert result.failed == 0


def test_inspect_stale_prs_search_query_with_repo():
    from github_overlord.stale_commenter import inspect_stale_prs

    mock_github = MagicMock()
    mock_github.search_issues.return_value = []

    result = inspect_stale_prs(
        github=mock_github, login="testuser", dry_run=True, repo="owner/repo"
    )
    mock_github.search_issues.assert_called_once_with(
        "is:pr is:open author:testuser repo:owner/repo"
    )
    assert result.checked == 0
    assert result.inspected == 0
    assert result.kept_alive == 0
    assert result.skipped == 0
    assert result.failed == 0


def test_inspect_stale_prs_handles_github_exception():
    from github.GithubException import GithubException

    from github_overlord.stale_commenter import inspect_stale_prs

    mock_github = MagicMock()
    mock_github.search_issues.side_effect = GithubException(
        status=403, data={"message": "rate limited"}
    )

    result = inspect_stale_prs(
        github=mock_github, login="testuser", dry_run=True, repo=None
    )
    assert result.checked == 0
    assert result.inspected == 0
    assert result.kept_alive == 0
    assert result.failed == 1


def test_inspect_stale_prs_counts_kept_alive():
    from github_overlord.stale_commenter import inspect_stale_prs

    mock_github = MagicMock()
    mock_issue = MagicMock()
    mock_issue.comments = 1
    mock_comment = MagicMock()
    mock_comment.user.login = "github-actions[bot]"
    mock_comment.body = "Stale PR"
    mock_issue.get_comments.return_value = [mock_comment]

    mock_github.search_issues.return_value = [mock_issue]

    with patch(
        "github_overlord.stale_commenter.is_stale_comment",
        return_value=(True, "Keep alive comment"),
    ):
        result = inspect_stale_prs(
            github=mock_github, login="testuser", dry_run=True, repo=None
        )

    assert result.inspected == 1
    assert result.kept_alive == 1
    assert result.skipped == 0
    assert result.failed == 0


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
