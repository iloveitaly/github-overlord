"""Test github-overlord."""

import github_overlord


def test_import() -> None:
    """Test that the package can be imported."""
    assert isinstance(github_overlord.__name__, str)


def test_version() -> None:
    """Test that the version is available."""
    assert isinstance(github_overlord.__version__, str)


def test_patch_hashes() -> None:
    """Test that patched functions match the expected SHA256 hashes."""
    from github_overlord.patch import hash_function_code

    def sample_func():
        return 42

    assert isinstance(hash_function_code(sample_func), str)
    assert len(hash_function_code(sample_func)) == 64


def test_url_keyed_caching() -> None:
    """Test that patched methods cache results across instances using stdlib lru_cache."""
    from unittest.mock import MagicMock

    from github.Notification import Notification
    from github.PullRequest import PullRequest

    from github_overlord.patch import clear_cache

    clear_cache()

    requester = MagicMock()
    requester.base_url = "https://api.github.com"
    requester.is_lazy = False
    requester.is_not_lazy = True
    requester.requestJsonAndCheck.return_value = (
        {},
        {
            "url": "https://api.github.com/repos/owner/repo/pulls/42",
            "issue_url": "https://api.github.com/repos/owner/repo/issues/42",
        },
    )

    # Test Notification.get_pull_request cached across distinct instances with same URL
    n1 = Notification(
        requester,
        {},
        {
            "url": "https://api.github.com/notifications/threads/1",
            "subject": {"url": "https://api.github.com/repos/owner/repo/pulls/42"},
        },
        True,
    )
    n2 = Notification(
        requester,
        {},
        {
            "url": "https://api.github.com/notifications/threads/1",
            "subject": {"url": "https://api.github.com/repos/owner/repo/pulls/42"},
        },
        True,
    )

    pr1 = n1.get_pull_request()
    pr2 = n2.get_pull_request()
    assert pr1 is pr2
    assert Notification.get_pull_request.cache_info().hits == 1

    # Test PullRequest.get_reviews cached across distinct instances with same URL
    pr_inst1 = PullRequest(
        requester,
        {},
        {
            "url": "https://api.github.com/repos/owner/repo/pulls/42",
            "issue_url": "https://api.github.com/repos/owner/repo/issues/42",
        },
        True,
    )
    pr_inst2 = PullRequest(
        requester,
        {},
        {
            "url": "https://api.github.com/repos/owner/repo/pulls/42",
            "issue_url": "https://api.github.com/repos/owner/repo/issues/42",
        },
        True,
    )

    revs1 = pr_inst1.get_reviews()
    revs2 = pr_inst2.get_reviews()
    assert revs1 is revs2
    assert PullRequest.get_reviews.cache_info().hits == 1

    # Test PullRequest.as_issue cached across distinct instances with same URL
    iss1 = pr_inst1.as_issue()
    iss2 = pr_inst2.as_issue()
    assert iss1 is iss2
    assert PullRequest.as_issue.cache_info().hits == 1

    # Test clear_cache clears all lru_cache stats and entries
    clear_cache()
    assert Notification.get_pull_request.cache_info().currsize == 0
    assert PullRequest.get_reviews.cache_info().currsize == 0
    assert PullRequest.as_issue.cache_info().currsize == 0


def test_generate_releases_max_releases_option() -> None:
    """Test that max-releases option exists on generate_releases command with default 1."""
    from click.testing import CliRunner

    from github_overlord import generate_releases

    runner = CliRunner()
    result = runner.invoke(generate_releases, ["--help"])
    assert result.exit_code == 0
    assert "--max-releases" in result.output
    assert "-m" in result.output
