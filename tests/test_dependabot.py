"""Tests for dependabot PR merging and summary reporting."""

from unittest.mock import MagicMock, patch

from github_overlord.dependabot import (
    RepoDependabotResult,
    merge_dependabot_prs,
    process_repo,
)


def test_repo_dependabot_result_defaults():
    result = RepoDependabotResult()
    assert result.checked == 0
    assert result.merged == 0
    assert result.failed == 0


def test_process_repo_skips_forked_repo():
    mock_repo = MagicMock()
    mock_repo.fork = True
    mock_repo.full_name = "testuser/forked-repo"

    result = process_repo(mock_repo, dry_run=True)
    assert result.checked == 0
    assert result.merged == 0
    assert result.failed == 0
    mock_repo.get_pulls.assert_not_called()


def test_process_repo_no_open_prs():
    mock_repo = MagicMock()
    mock_repo.fork = False
    mock_repo.full_name = "testuser/repo"
    mock_pulls = MagicMock()
    mock_pulls.totalCount = 0
    mock_repo.get_pulls.return_value = mock_pulls

    result = process_repo(mock_repo, dry_run=False)
    assert result.checked == 0
    assert result.merged == 0
    assert result.failed == 0


def test_process_repo_merges_eligible_prs():
    mock_repo = MagicMock()
    mock_repo.fork = False
    mock_repo.full_name = "testuser/repo"

    pr1 = MagicMock()
    pr1.html_url = "https://github.com/testuser/repo/pull/1"
    pr2 = MagicMock()
    pr2.html_url = "https://github.com/testuser/repo/pull/2"

    mock_pulls = MagicMock()
    mock_pulls.totalCount = 2
    mock_pulls.__iter__.return_value = [pr1, pr2]
    mock_repo.get_pulls.return_value = mock_pulls

    with (
        patch(
            "github_overlord.dependabot.is_eligible_for_merge",
            side_effect=[True, False],
        ),
        patch("github_overlord.dependabot.merge_pr", return_value=True),
    ):
        result = process_repo(mock_repo, dry_run=False)
        assert result.checked == 2
        assert result.merged == 1
        assert result.failed == 0


def test_process_repo_handles_merge_failure():
    mock_repo = MagicMock()
    mock_repo.fork = False
    mock_repo.full_name = "testuser/repo"

    pr = MagicMock()
    pr.html_url = "https://github.com/testuser/repo/pull/1"

    mock_pulls = MagicMock()
    mock_pulls.totalCount = 1
    mock_pulls.__iter__.return_value = [pr]
    mock_repo.get_pulls.return_value = mock_pulls

    with (
        patch("github_overlord.dependabot.is_eligible_for_merge", return_value=True),
        patch("github_overlord.dependabot.merge_pr", return_value=False),
    ):
        result = process_repo(mock_repo, dry_run=False)
        assert result.checked == 1
        assert result.merged == 0
        assert result.failed == 1


def test_merge_dependabot_prs_single_repo():
    with patch("github_overlord.dependabot.Github") as mock_github_class:
        mock_gh = MagicMock()
        mock_github_class.return_value = mock_gh
        mock_repo = MagicMock()
        mock_repo.fork = False
        mock_repo.full_name = "testuser/repo"
        mock_gh.get_repo.return_value = mock_repo

        expected_result = RepoDependabotResult(checked=3, merged=2, failed=1)
        with patch(
            "github_overlord.dependabot.process_repo", return_value=expected_result
        ):
            result = merge_dependabot_prs(
                "fake-token", dry_run=False, repo="testuser/repo"
            )
            assert result.checked == 3
            assert result.merged == 2
            assert result.failed == 1


def test_merge_dependabot_prs_all_repos_dry_run():
    with patch("github_overlord.dependabot.Github") as mock_github_class:
        mock_gh = MagicMock()
        mock_github_class.return_value = mock_gh
        mock_user = MagicMock()
        mock_user.login = "testuser"
        mock_gh.get_user.return_value = mock_user

        repo1 = MagicMock()
        repo1.owner.login = "testuser"
        repo2 = MagicMock()
        repo2.owner.login = "testuser"
        mock_user.get_repos.return_value = [repo1, repo2]

        r1 = RepoDependabotResult(checked=2, merged=1, failed=0)
        r2 = RepoDependabotResult(checked=3, merged=2, failed=0)
        with patch("github_overlord.dependabot.process_repo", side_effect=[r1, r2]):
            result = merge_dependabot_prs("fake-token", dry_run=True, repo=None)
            assert result.checked == 5
            assert result.merged == 3
            assert result.failed == 0
