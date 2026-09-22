"""The scheduler logs an org token-lifetime 403 and runs the next command."""

from unittest.mock import MagicMock, patch

from github.GithubException import GithubException

TOKEN_POLICY_MESSAGE = (
    "The 'CodingZeal' organization forbids access via a fine-grained personal access "
    "tokens if the token's lifetime is greater than 366 days."
)


def test_job_continues_after_token_policy_error():
    from main import job

    failed = MagicMock()
    failed.name = "keep-alive-prs"
    failed.side_effect = GithubException(403, {"message": TOKEN_POLICY_MESSAGE})

    later = MagicMock()
    later.name = "notifications"

    with patch("main.cli") as mock_cli:
        mock_cli.commands.values.return_value = [failed, later]
        job()

    later.assert_called_once_with()


def test_job_reraises_other_forbidden_errors():
    from main import job

    failed = MagicMock()
    failed.name = "keep-alive-prs"
    failed.side_effect = GithubException(
        403, {"message": "Resource not accessible by integration"}
    )

    later = MagicMock()
    later.name = "notifications"

    with patch("main.cli") as mock_cli:
        mock_cli.commands.values.return_value = [failed, later]
        try:
            job()
        except GithubException as error:
            assert error.status == 403
        else:
            raise AssertionError("expected GithubException")

    later.assert_not_called()
