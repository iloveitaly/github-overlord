from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from github.GithubException import GithubException
from github.Notification import Notification

from github_overlord.notifications import (
    clean_notifications,
    is_notification_older_than,
    is_pull_request,
    is_pull_request_approved_by_user_and_merged,
    is_pull_request_closed_by_user,
    is_pull_request_merged_by_user,
    is_self_authored_pr_without_activity,
)


def _make_notification(
    reason: str = "author",
    subject_type: str = "PullRequest",
    latest_comment_url: str | None = None,
    pr_user_login: str = "testuser",
    comments: int = 0,
    review_comments: int = 0,
    reviews: list | None = None,
    merged: bool = False,
    merged_by_login: str | None = None,
    state: str = "open",
    closed_by_login: str | None = None,
    updated_at: datetime | None = None,
) -> Notification:
    notification = MagicMock(spec=Notification)
    notification.reason = reason
    notification.updated_at = (
        updated_at if updated_at is not None else datetime.now(UTC)
    )

    subject = MagicMock()
    subject.type = subject_type
    subject.latest_comment_url = latest_comment_url
    notification.subject = subject

    pr = MagicMock()
    pr_user = MagicMock()
    pr_user.login = pr_user_login
    pr.user = pr_user
    pr.comments = comments
    pr.review_comments = review_comments
    pr.get_reviews.return_value = reviews or []
    pr.merged = merged
    pr.state = state
    if merged_by_login is not None:
        merged_by = MagicMock()
        merged_by.login = merged_by_login
        pr.merged_by = merged_by
    else:
        pr.merged_by = None

    issue = MagicMock()
    if closed_by_login is not None:
        closed_by = MagicMock()
        closed_by.login = closed_by_login
        issue.closed_by = closed_by
    else:
        issue.closed_by = None
    pr.as_issue.return_value = issue

    notification.get_pull_request.return_value = pr
    return notification


def test_is_pull_request() -> None:
    pr_notification = _make_notification(subject_type="PullRequest")
    issue_notification = _make_notification(subject_type="Issue")

    assert is_pull_request(pr_notification) is True
    assert is_pull_request(issue_notification) is False


def test_is_self_authored_pr_without_activity_matches() -> None:
    notification = _make_notification(
        reason="author",
        subject_type="PullRequest",
        latest_comment_url=None,
        pr_user_login="myuser",
        comments=0,
        review_comments=0,
        reviews=[],
    )
    assert is_self_authored_pr_without_activity(notification, "myuser") is True


def test_is_self_authored_pr_without_activity_ignores_non_author_reason() -> None:
    notification = _make_notification(
        reason="subscribed",
        latest_comment_url=None,
        pr_user_login="myuser",
    )
    assert is_self_authored_pr_without_activity(notification, "myuser") is False


def test_is_self_authored_pr_without_activity_ignores_non_pr() -> None:
    notification = _make_notification(
        reason="author",
        subject_type="Issue",
        latest_comment_url=None,
        pr_user_login="myuser",
    )
    assert is_self_authored_pr_without_activity(notification, "myuser") is False


def test_is_self_authored_pr_without_activity_ignores_when_comment_exists() -> None:
    notification = _make_notification(
        reason="author",
        latest_comment_url="https://api.github.com/repos/owner/repo/issues/comments/123",
        pr_user_login="myuser",
    )
    assert is_self_authored_pr_without_activity(notification, "myuser") is False


def test_is_self_authored_pr_without_activity_ignores_different_author() -> None:
    notification = _make_notification(
        reason="author",
        latest_comment_url=None,
        pr_user_login="otheruser",
    )
    assert is_self_authored_pr_without_activity(notification, "myuser") is False


def test_is_self_authored_pr_without_activity_ignores_when_pr_has_comments() -> None:
    notification = _make_notification(
        reason="author",
        latest_comment_url=None,
        pr_user_login="myuser",
        comments=2,
    )
    assert is_self_authored_pr_without_activity(notification, "myuser") is False


def test_is_self_authored_pr_without_activity_ignores_when_pr_has_review_comments() -> (
    None
):
    notification = _make_notification(
        reason="author",
        latest_comment_url=None,
        pr_user_login="myuser",
        review_comments=1,
    )
    assert is_self_authored_pr_without_activity(notification, "myuser") is False


def test_is_self_authored_pr_without_activity_ignores_when_external_review_exists() -> (
    None
):
    reviewer = MagicMock()
    reviewer.user.login = "teammate"
    review = MagicMock()
    review.user = reviewer.user

    notification = _make_notification(
        reason="author",
        latest_comment_url=None,
        pr_user_login="myuser",
        reviews=[review],
    )
    assert is_self_authored_pr_without_activity(notification, "myuser") is False


def test_is_pull_request_merged_by_user_matches() -> None:
    notification = _make_notification(
        reason="subscribed",
        subject_type="PullRequest",
        merged=True,
        merged_by_login="dynamic_user",
    )
    assert is_pull_request_merged_by_user(notification, "dynamic_user") is True


def test_is_pull_request_merged_by_user_ignores_different_merger() -> None:
    notification = _make_notification(
        reason="subscribed",
        subject_type="PullRequest",
        merged=True,
        merged_by_login="someoneelse",
    )
    assert is_pull_request_merged_by_user(notification, "dynamic_user") is False


def test_is_pull_request_merged_by_user_ignores_unmerged() -> None:
    notification = _make_notification(
        reason="subscribed",
        subject_type="PullRequest",
        merged=False,
        merged_by_login=None,
    )
    assert is_pull_request_merged_by_user(notification, "dynamic_user") is False


def test_is_pull_request_merged_by_user_ignores_non_pr() -> None:
    notification = _make_notification(
        reason="subscribed",
        subject_type="Issue",
        merged=True,
        merged_by_login="dynamic_user",
    )
    assert is_pull_request_merged_by_user(notification, "dynamic_user") is False


def test_is_pull_request_merged_by_user_handles_none_merged_by() -> None:
    notification = _make_notification(
        reason="subscribed",
        subject_type="PullRequest",
        merged=True,
        merged_by_login=None,
    )
    assert is_pull_request_merged_by_user(notification, "dynamic_user") is False


def _make_review(user_login: str, state: str) -> MagicMock:
    review = MagicMock()
    review.user.login = user_login
    review.state = state
    return review


def test_is_pull_request_approved_by_user_and_merged_matches() -> None:
    notification = _make_notification(
        reason="subscribed",
        subject_type="PullRequest",
        merged=True,
        reviews=[_make_review("reviewer", "APPROVED")],
    )
    assert is_pull_request_approved_by_user_and_merged(notification, "reviewer") is True


def test_is_pull_request_approved_by_user_and_merged_unmerged() -> None:
    notification = _make_notification(
        reason="subscribed",
        subject_type="PullRequest",
        merged=False,
        reviews=[_make_review("reviewer", "APPROVED")],
    )
    assert (
        is_pull_request_approved_by_user_and_merged(notification, "reviewer") is False
    )


def test_is_pull_request_approved_by_user_and_merged_no_reviews() -> None:
    notification = _make_notification(
        reason="subscribed",
        subject_type="PullRequest",
        merged=True,
        reviews=[],
    )
    assert (
        is_pull_request_approved_by_user_and_merged(notification, "reviewer") is False
    )


def test_is_pull_request_approved_by_user_and_merged_different_user() -> None:
    notification = _make_notification(
        reason="subscribed",
        subject_type="PullRequest",
        merged=True,
        reviews=[_make_review("someoneelse", "APPROVED")],
    )
    assert (
        is_pull_request_approved_by_user_and_merged(notification, "reviewer") is False
    )


def test_is_pull_request_approved_by_user_and_merged_only_commented() -> None:
    notification = _make_notification(
        reason="subscribed",
        subject_type="PullRequest",
        merged=True,
        reviews=[_make_review("reviewer", "COMMENTED")],
    )
    assert (
        is_pull_request_approved_by_user_and_merged(notification, "reviewer") is False
    )


def test_is_pull_request_approved_by_user_and_merged_subsequent_changes_requested() -> (
    None
):
    notification = _make_notification(
        reason="subscribed",
        subject_type="PullRequest",
        merged=True,
        reviews=[
            _make_review("reviewer", "APPROVED"),
            _make_review("reviewer", "CHANGES_REQUESTED"),
        ],
    )
    assert (
        is_pull_request_approved_by_user_and_merged(notification, "reviewer") is False
    )


def test_is_pull_request_approved_by_user_and_merged_subsequent_approval_overrides_changes_requested() -> (
    None
):
    notification = _make_notification(
        reason="subscribed",
        subject_type="PullRequest",
        merged=True,
        reviews=[
            _make_review("reviewer", "CHANGES_REQUESTED"),
            _make_review("reviewer", "APPROVED"),
        ],
    )
    assert is_pull_request_approved_by_user_and_merged(notification, "reviewer") is True


def test_is_pull_request_approved_by_user_and_merged_subsequent_comment_preserves_approval() -> (
    None
):
    notification = _make_notification(
        reason="subscribed",
        subject_type="PullRequest",
        merged=True,
        reviews=[
            _make_review("reviewer", "APPROVED"),
            _make_review("reviewer", "COMMENTED"),
        ],
    )
    assert is_pull_request_approved_by_user_and_merged(notification, "reviewer") is True


def test_is_pull_request_approved_by_user_and_merged_dismissed() -> None:
    notification = _make_notification(
        reason="subscribed",
        subject_type="PullRequest",
        merged=True,
        reviews=[
            _make_review("reviewer", "APPROVED"),
            _make_review("reviewer", "DISMISSED"),
        ],
    )
    assert (
        is_pull_request_approved_by_user_and_merged(notification, "reviewer") is False
    )


def test_is_pull_request_approved_by_user_and_merged_ignores_non_pr() -> None:
    notification = _make_notification(
        reason="subscribed",
        subject_type="Issue",
        merged=True,
        reviews=[_make_review("reviewer", "APPROVED")],
    )
    assert (
        is_pull_request_approved_by_user_and_merged(notification, "reviewer") is False
    )


def test_is_pull_request_closed_by_user_unmerged_matches() -> None:
    notification = _make_notification(
        reason="subscribed",
        subject_type="PullRequest",
        state="closed",
        merged=False,
        closed_by_login="closer",
    )
    assert is_pull_request_closed_by_user(notification, "closer") is True


def test_is_pull_request_closed_by_user_unmerged_different_closer() -> None:
    notification = _make_notification(
        reason="subscribed",
        subject_type="PullRequest",
        state="closed",
        merged=False,
        closed_by_login="other",
    )
    assert is_pull_request_closed_by_user(notification, "closer") is False


def test_is_pull_request_closed_by_user_merged_matches() -> None:
    notification = _make_notification(
        reason="subscribed",
        subject_type="PullRequest",
        state="closed",
        merged=True,
        merged_by_login="closer",
    )
    assert is_pull_request_closed_by_user(notification, "closer") is True


def test_is_pull_request_closed_by_user_merged_different_merger() -> None:
    notification = _make_notification(
        reason="subscribed",
        subject_type="PullRequest",
        state="closed",
        merged=True,
        merged_by_login="other",
    )
    assert is_pull_request_closed_by_user(notification, "closer") is False


def test_is_pull_request_closed_by_user_open_ignores() -> None:
    notification = _make_notification(
        reason="subscribed",
        subject_type="PullRequest",
        state="open",
        merged=False,
        closed_by_login="closer",
    )
    assert is_pull_request_closed_by_user(notification, "closer") is False


def test_is_pull_request_closed_by_user_unmerged_none_closed_by() -> None:
    notification = _make_notification(
        reason="subscribed",
        subject_type="PullRequest",
        state="closed",
        merged=False,
        closed_by_login=None,
    )
    assert is_pull_request_closed_by_user(notification, "closer") is False


def test_is_pull_request_closed_by_user_ignores_non_pr() -> None:
    notification = _make_notification(
        reason="subscribed",
        subject_type="Issue",
        state="closed",
        merged=False,
        closed_by_login="closer",
    )
    assert is_pull_request_closed_by_user(notification, "closer") is False


def test_is_notification_older_than_matches_when_over_60_days() -> None:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    old_time = now - timedelta(days=61)
    notification = _make_notification(updated_at=old_time)
    assert is_notification_older_than(notification, now=now) is True


def test_is_notification_older_than_ignores_when_under_60_days() -> None:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    recent_time = now - timedelta(days=30)
    notification = _make_notification(updated_at=recent_time)
    assert is_notification_older_than(notification, now=now) is False


def test_is_notification_older_than_handles_naive_datetime() -> None:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    naive_old_time = (now - timedelta(days=61)).replace(tzinfo=None)
    notification = _make_notification(updated_at=naive_old_time)
    assert is_notification_older_than(notification, now=now) is True


def test_is_notification_older_than_custom_max_age() -> None:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    time_10_days_ago = now - timedelta(days=10)
    notification = _make_notification(updated_at=time_10_days_ago)
    assert (
        is_notification_older_than(notification, max_age=timedelta(days=7), now=now)
        is True
    )
    assert (
        is_notification_older_than(notification, max_age=timedelta(days=14), now=now)
        is False
    )


class _FakeRepo:
    def __init__(
        self,
        full_name: str = "testuser/testrepo",
        owner_login: str = "testuser",
        permissions: object | None = None,
        permissions_error: Exception | None = None,
    ):
        self.full_name = full_name
        self.raw_data = {"full_name": full_name}
        self.owner = MagicMock(login=owner_login)
        self._permissions = permissions
        self._permissions_error = permissions_error

    @property
    def permissions(self):
        if self._permissions_error:
            raise self._permissions_error
        return self._permissions


def _make_release_notification(
    repo_full_name: str = "testuser/testrepo",
    repo_owner_login: str = "testuser",
    permissions_push: bool | None = None,
    permissions_exception: Exception | None = None,
    subject_type: str = "Release",
    repository_none: bool = False,
) -> Notification:
    notification = MagicMock(spec=Notification)
    subject = MagicMock()
    subject.type = subject_type
    notification.subject = subject

    if repository_none:
        notification.repository = None
        return notification

    perms = None
    if permissions_push is not None:
        perms = MagicMock()
        perms.push = permissions_push

    notification.repository = _FakeRepo(
        full_name=repo_full_name,
        owner_login=repo_owner_login,
        permissions=perms,
        permissions_error=permissions_exception,
    )
    return notification


def test_clean_notifications_handles_github_exception_on_release() -> None:
    forbidden_notification = _make_release_notification(
        repo_full_name="railwayapp/railpack",
        repo_owner_login="railwayapp",
        permissions_exception=GithubException(
            403,
            "`railwayapp` forbids access via a personal access token (classic).",
        ),
    )
    forbidden_notification.reason = "subscribed"
    forbidden_notification.updated_at = datetime.now(UTC)

    owned_notification = _make_release_notification(
        repo_full_name="myuser/myproject",
        repo_owner_login="myuser",
        permissions_push=True,
    )
    owned_notification.reason = "subscribed"
    owned_notification.updated_at = datetime.now(UTC)

    mock_user = MagicMock()
    mock_user.login = "myuser"
    mock_user.get_notifications.return_value = [
        forbidden_notification,
        owned_notification,
    ]

    with (
        patch("github_overlord.notifications.Github") as mock_github_class,
        patch("github_overlord.notifications.log.error") as mock_log_error,
        patch.object(Notification, "mark_as_done") as mock_mark_done,
    ):
        mock_github = MagicMock()
        mock_github.get_user.return_value = mock_user
        mock_github_class.return_value = mock_github

        clean_notifications(token="dummy-token", dry_run=False)

    mock_log_error.assert_called_once()
    assert mock_log_error.call_args[1]["repo"] == "railwayapp/railpack"

    mock_mark_done.assert_called_once_with(owned_notification)


def test_clean_notifications_skips_uncontrolled_release() -> None:
    uncontrolled_notification = _make_release_notification(
        repo_full_name="otherorg/otherrepo",
        repo_owner_login="otherorg",
        permissions_push=False,
    )
    uncontrolled_notification.reason = "subscribed"
    uncontrolled_notification.updated_at = datetime.now(UTC)

    mock_user = MagicMock()
    mock_user.login = "myuser"
    mock_user.get_notifications.return_value = [uncontrolled_notification]

    with (
        patch("github_overlord.notifications.Github") as mock_github_class,
        patch("github_overlord.notifications.log.error") as mock_log_error,
        patch.object(Notification, "mark_as_done") as mock_mark_done,
    ):
        mock_github = MagicMock()
        mock_github.get_user.return_value = mock_user
        mock_github_class.return_value = mock_github

        clean_notifications(token="dummy-token", dry_run=False)

    mock_log_error.assert_not_called()
    mock_mark_done.assert_not_called()


def test_clean_notifications_marks_owner_release_when_permissions_none() -> None:
    owned_notification = _make_release_notification(
        repo_full_name="myuser/myproject",
        repo_owner_login="myuser",
        permissions_push=None,
    )
    owned_notification.reason = "subscribed"
    owned_notification.updated_at = datetime.now(UTC)

    mock_user = MagicMock()
    mock_user.login = "myuser"
    mock_user.get_notifications.return_value = [owned_notification]

    with (
        patch("github_overlord.notifications.Github") as mock_github_class,
        patch.object(Notification, "mark_as_done") as mock_mark_done,
    ):
        mock_github = MagicMock()
        mock_github.get_user.return_value = mock_user
        mock_github_class.return_value = mock_github

        clean_notifications(token="dummy-token", dry_run=False)

    mock_mark_done.assert_called_once_with(owned_notification)
