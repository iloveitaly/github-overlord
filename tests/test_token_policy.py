"""Token-lifetime 403s are logged and skipped instead of aborting a run."""

from unittest.mock import MagicMock, patch

from github.GithubException import GithubException

from github_overlord.utils import is_fine_grained_token_lifetime_forbidden

TOKEN_POLICY_MESSAGE = (
    "The 'CodingZeal' organization forbids access via a fine-grained personal access "
    "tokens if the token's lifetime is greater than 366 days. Please adjust your "
    "token's lifetime at the following URL: "
    "https://github.com/settings/personal-access-tokens/11080270"
)


def token_policy_error() -> GithubException:
    return GithubException(403, {"message": TOKEN_POLICY_MESSAGE})


def test_detects_fine_grained_token_lifetime_forbidden():
    assert is_fine_grained_token_lifetime_forbidden(token_policy_error()) is True


def test_detects_token_policy_from_exception_message():
    error = GithubException(403, None, message=TOKEN_POLICY_MESSAGE)
    assert is_fine_grained_token_lifetime_forbidden(error) is True


def test_ignores_other_forbidden_errors():
    other = GithubException(403, {"message": "Resource not accessible by integration"})
    rate_limit = GithubException(403, {"message": "API rate limit exceeded"})
    missing = GithubException(404, {"message": "Not Found"})

    assert is_fine_grained_token_lifetime_forbidden(other) is False
    assert is_fine_grained_token_lifetime_forbidden(rate_limit) is False
    assert is_fine_grained_token_lifetime_forbidden(missing) is False
    assert is_fine_grained_token_lifetime_forbidden(RuntimeError("nope")) is False


def test_inspect_stale_prs_skips_forbidden_pr_and_continues():
    from github_overlord.stale_commenter import inspect_stale_prs

    blocked = MagicMock()
    blocked.html_url = "https://github.com/CodingZeal/hash_diff/pull/1"
    blocked.comments = 2
    blocked.get_comments.side_effect = token_policy_error()

    remaining = MagicMock()
    remaining.html_url = "https://github.com/other/repo/pull/2"
    remaining.comments = 0

    github = MagicMock()
    github.search_issues.return_value = [blocked, remaining]

    result = inspect_stale_prs(github=github, login="iloveitaly", dry_run=True)

    assert result.inspected == 2
    assert result.failed == 1
    assert result.skipped == 1
    assert result.kept_alive == 0


def test_inspect_stale_prs_skips_when_pull_request_url_is_forbidden():
    from github_overlord.stale_commenter import inspect_stale_prs

    class ForbiddenPullRequest:
        @property
        def html_url(self):
            raise token_policy_error()

    blocked = ForbiddenPullRequest()
    remaining = MagicMock()
    remaining.html_url = "https://github.com/other/repo/pull/2"
    remaining.comments = 0

    github = MagicMock()
    github.search_issues.return_value = [blocked, remaining]

    result = inspect_stale_prs(github=github, login="iloveitaly", dry_run=True)

    assert result.inspected == 2
    assert result.failed == 1
    assert result.skipped == 1


def test_process_repo_skips_forbidden_repo():
    from github_overlord.dependabot import process_repo

    repo = MagicMock()
    repo.fork = False
    repo.full_name = "CodingZeal/hash_diff"
    repo.get_pulls.side_effect = token_policy_error()

    result = process_repo(repo, dry_run=False)

    assert result.checked == 0
    assert result.merged == 0
    assert result.failed == 1


def test_process_repo_reraises_other_github_errors():
    from github_overlord.dependabot import process_repo

    repo = MagicMock()
    repo.fork = False
    repo.full_name = "iloveitaly/activemodel"
    repo.get_pulls.side_effect = GithubException(500, {"message": "Server Error"})

    try:
        process_repo(repo, dry_run=False)
    except GithubException as error:
        assert error.status == 500
    else:
        raise AssertionError("expected GithubException")


def test_job_continues_after_token_policy_error():
    from main import job

    failed = MagicMock()
    failed.name = "keep-alive-prs"
    failed.side_effect = token_policy_error()

    later = MagicMock()
    later.name = "notifications"

    with patch("main.cli") as mock_cli:
        mock_cli.commands.values.return_value = [failed, later]
        job()

    later.assert_called_once_with()


def test_job_reraises_other_github_errors():
    from main import job

    failed = MagicMock()
    failed.name = "keep-alive-prs"
    failed.side_effect = GithubException(500, {"message": "Server Error"})

    later = MagicMock()
    later.name = "notifications"

    with patch("main.cli") as mock_cli:
        mock_cli.commands.values.return_value = [failed, later]
        try:
            job()
        except GithubException as error:
            assert error.status == 500
        else:
            raise AssertionError("expected GithubException")

    later.assert_not_called()
