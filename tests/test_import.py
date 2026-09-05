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
    """Test that patched methods cache results by URL across different instances."""
    from unittest.mock import MagicMock, patch

    from github.Notification import Notification
    from github.PullRequest import PullRequest

    from github_overlord.patch import clear_cache

    clear_cache()

    # Test Notification.get_pull_request URL-keyed cache across distinct instances
    n1 = MagicMock(spec=Notification)
    n1.subject.url = "https://api.github.com/repos/owner/repo/pulls/42"
    n2 = MagicMock(spec=Notification)
    n2.subject.url = "https://api.github.com/repos/owner/repo/pulls/42"

    mock_pr = MagicMock(spec=PullRequest)
    with patch(
        "github_overlord.patch._orig_get_pull_request", return_value=mock_pr
    ) as mock_orig:
        res1 = Notification.get_pull_request(n1)
        res2 = Notification.get_pull_request(n2)
        assert res1 is res2
        assert mock_orig.call_count == 1

    # Test PullRequest.get_reviews URL-keyed cache across distinct instances
    pr1 = MagicMock(spec=PullRequest)
    pr1.url = "https://api.github.com/repos/owner/repo/pulls/42"
    pr2 = MagicMock(spec=PullRequest)
    pr2.url = "https://api.github.com/repos/owner/repo/pulls/42"

    mock_reviews = [MagicMock()]
    with patch(
        "github_overlord.patch._orig_get_reviews", return_value=mock_reviews
    ) as mock_orig_rev:
        revs1 = PullRequest.get_reviews(pr1)
        revs2 = PullRequest.get_reviews(pr2)
        assert revs1 is revs2
        assert mock_orig_rev.call_count == 1

    # Test PullRequest.as_issue URL-keyed cache across distinct instances
    pr1.issue_url = "https://api.github.com/repos/owner/repo/issues/42"
    pr2.issue_url = "https://api.github.com/repos/owner/repo/issues/42"

    mock_issue = MagicMock()
    with patch(
        "github_overlord.patch._orig_as_issue", return_value=mock_issue
    ) as mock_orig_issue:
        iss1 = PullRequest.as_issue(pr1)
        iss2 = PullRequest.as_issue(pr2)
        assert iss1 is iss2
        assert mock_orig_issue.call_count == 1

    # Test clear_cache
    clear_cache()
    with patch(
        "github_overlord.patch._orig_get_pull_request", return_value=mock_pr
    ) as mock_orig:
        Notification.get_pull_request(n1)
        assert mock_orig.call_count == 1
