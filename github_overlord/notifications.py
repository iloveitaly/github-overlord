"""Notification management and cleanup for github-overlord."""

import os
from datetime import UTC, datetime, timedelta

import click
import funcy_pipe as fp
from github import Github
from github.Notification import Notification

import github_overlord.patch  # noqa: F401

from .utils import log


def is_pull_request(notification: Notification) -> bool:
    """Check if the notification subject is a Pull Request."""
    return notification.subject.type == "PullRequest"


def is_self_authored_pr_without_activity(
    notification: Notification, login: str
) -> bool:
    """Filter notifications for self-authored PR creations that have no external activity.

    Case: When the user opens a new PR, GitHub automatically posts an inbox notification
    informing them that their own PR was created (reason="author"). If no one has commented
    or reviewed yet, this notification is redundant noise because the author already knows
    they just opened the PR. If an external user comments or submits a review, the
    notification is retained.
    """
    if notification.reason != "author":
        return False

    if not is_pull_request(notification):
        return False

    # If latest_comment_url is populated, someone has commented on the thread
    if getattr(notification.subject, "latest_comment_url", None) is not None:
        return False

    pr = notification.get_pull_request()
    if not pr.user or pr.user.login != login:
        return False

    if pr.comments > 0 or pr.review_comments > 0:
        return False

    external_reviews = [r for r in pr.get_reviews() if r.user and r.user.login != login]
    return not external_reviews


def is_pull_request_merged_by_user(notification: Notification, login: str) -> bool:
    """Filter notifications for pull requests that were merged by the authenticated user.

    Case: When the user merges a PR (either their own or someone else's), GitHub sends
    or retains notifications on the PR thread (e.g. from prior review requests, subscriptions,
    mentions, or the merge event itself). Because the user was the one who performed the merge,
    their involvement with this PR is complete and the notification is obsolete.
    """
    if not is_pull_request(notification):
        return False

    pr = notification.get_pull_request()
    return bool(pr.merged and pr.merged_by and pr.merged_by.login == login)


def is_pull_request_approved_by_user_and_merged(
    notification: Notification, login: str
) -> bool:
    """Filter notifications for merged pull requests that were approved by the authenticated user.

    Case: When the user reviews and approves a PR (e.g. from a teammate, contributor,
    or bot), and that PR is subsequently merged by someone else, GitHub retains a notification
    in the inbox announcing the merge. Since the user already reviewed and approved the changes,
    and the PR has reached its terminal merged state, no further action or attention is required
    from the reviewer.
    """
    if not is_pull_request(notification):
        return False

    pr = notification.get_pull_request()
    if not pr.merged:
        return False

    # Check reviews from this user in chronological order.
    # A user has approved the PR if their latest decision review (APPROVED, CHANGES_REQUESTED, DISMISSED) is APPROVED.
    decision_states = {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}
    user_decision_reviews = [
        r
        for r in pr.get_reviews()
        if r.user
        and r.user.login == login
        and (r.state or "").upper() in decision_states
    ]
    if not user_decision_reviews:
        return False

    return (user_decision_reviews[-1].state or "").upper() == "APPROVED"


def is_pull_request_closed_by_user(notification: Notification, login: str) -> bool:
    """Filter notifications for pull requests that were closed by the authenticated user.

    Case: When the user closes a pull request (either closing an unmerged PR such as an
    unwanted, stale, or duplicate contribution, or closing their own PR), GitHub retains
    notifications on the PR thread. Because the user was the actor who closed the pull request,
    their involvement is finished and the notification is obsolete.
    """
    if not is_pull_request(notification):
        return False

    pr = notification.get_pull_request()
    if pr.state != "closed":
        return False

    if pr.merged:
        return bool(pr.merged_by and pr.merged_by.login == login)

    issue = pr.as_issue()
    return bool(issue.closed_by and issue.closed_by.login == login)


DEFAULT_MAX_NOTIFICATION_AGE = timedelta(days=60)


def is_notification_older_than(
    notification: Notification,
    max_age: timedelta = DEFAULT_MAX_NOTIFICATION_AGE,
    now: datetime | None = None,
) -> bool:
    """Check if a notification's updated_at timestamp is older than max_age (defaults to 60 days / 2 months).

    Case: Notifications that have had no activity for more than 2 months are considered
    stale and can safely be marked as done to keep the inbox uncluttered.
    """
    reference_time = now or datetime.now(UTC)
    cutoff = reference_time - max_age
    updated_at = notification.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return updated_at < cutoff


def clean_notifications(
    token: str | None,
    dry_run: bool = False,
    all_notifications: bool = False,
) -> None:
    """Scan and mark notifications as done based on age, authorship, and repository status."""
    github = Github(token)
    user = github.get_user()
    login = user.login

    # GitHub exposes unread vs all, but not done vs not-done.
    # To catch read-but-not-done release and PR notifications, scan all threads.
    # AuthenticatedUser at runtime has get_notifications; PyGithub stubs type user as NamedUser | AuthenticatedUser
    notifications_list = list(user.get_notifications(all=True))  # type: ignore
    now = datetime.now(UTC)

    def is_older_than_two_months(notification: Notification) -> bool:
        return is_notification_older_than(
            notification, max_age=timedelta(days=60), now=now
        )

    if dry_run:
        log.info("running notifications cleanup in dry-run mode")

    mark_done = (lambda _n: None) if dry_run else Notification.mark_as_done

    # Case: Notifications older than 2 months (60 days)
    # Stale notifications with no recent activity are cleaned up.
    old_notifications = (
        notifications_list | fp.filter(is_older_than_two_months) | fp.lmap(mark_done)
    )

    log.info("marked old notifications (>2mo) as done", count=len(old_notifications))

    def is_release_on_controlled_repo(notification: Notification) -> bool:
        if notification.subject.type != "Release":
            return False

        permissions = notification.repository.permissions

        # permissions is available in the notifications API response when authenticated;
        # fall back to owner check if the field is absent
        if permissions is None:
            return notification.repository.owner.login == login

        return permissions.push

    # TODO fix funcy_pipe here
    released_on_controlled_repos = (
        notifications_list
        | fp.filter(is_release_on_controlled_repo)
        # TODO I think there is a way to convert the instance method to a standard method so it could be mapped
        #      patchy had some code for this
        | fp.lmap(mark_done)
    )

    log.info("marked releases as done", count=len(released_on_controlled_repos))

    def is_bot_authored_pull_request(notification: Notification) -> bool:
        pull_request = notification.get_pull_request()
        author = pull_request.user

        return author.type == "Bot" or author.login.endswith("[bot]")

    def is_release_please_pull_request(notification: Notification) -> bool:
        pull_request = notification.get_pull_request()
        body = pull_request.body or ""

        return (
            "This PR was generated with [Release Please]" in body
            or pull_request.head.ref.startswith("release-please--branches--")
        )

    def is_pull_request_open(notification: Notification) -> bool:
        return notification.get_pull_request().state == "open"

    # TODO github digest has some logic to detect bots, maybev we can use that
    bot_authored_pull_requests = (
        notifications_list
        | fp.filter(is_pull_request)
        | fp.filter(is_bot_authored_pull_request)
        | fp.lmap(mark_done)
    )

    log.info("marked bot-authored PRs as done", count=len(bot_authored_pull_requests))

    release_please_pull_requests = (
        notifications_list
        | fp.filter(is_pull_request)
        | fp.filter(is_release_please_pull_request)
        | fp.lmap(mark_done)
    )

    log.info(
        "marked release-please PRs as done",
        count=len(release_please_pull_requests),
    )

    # Closed (merged, closed) pull requests that I authored
    owned_closed_pull_requests = (
        notifications_list
        # PRs that I did not author may still be interesting
        # funcy_pipe provides where_attr dynamically at runtime
        | fp.where_attr(reason="author")  # type: ignore
        | fp.filter(is_pull_request)
        | fp.filter(fp.complement(is_pull_request_open))
        | fp.lmap(mark_done)
    )

    log.info("marked owned closed PRs as done", count=len(owned_closed_pull_requests))

    # Case: Self-authored PR creation notifications without external activity
    # GitHub notifies authors upon opening a PR (reason="author"). Clear if no reviews/comments.
    self_authored_inactive_prs = (
        notifications_list
        | fp.filter(lambda n: is_self_authored_pr_without_activity(n, login))
        | fp.lmap(mark_done)
    )

    log.info(
        "marked self-authored PR creation notifications as done",
        count=len(self_authored_inactive_prs),
    )

    # Case: Pull requests merged by the authenticated user
    # If the user performed the merge, their action is completed.
    user_merged_pull_requests = (
        notifications_list
        | fp.filter(is_pull_request)
        | fp.filter(lambda n: is_pull_request_merged_by_user(n, login))
        | fp.lmap(mark_done)
    )

    log.info(
        "marked user-merged PRs as done",
        count=len(user_merged_pull_requests),
    )

    # Case: Pull requests closed (unmerged) by the authenticated user
    # If the user closed the PR without merging, their action is completed.
    # Merged PRs are already handled by user_merged_pull_requests.
    user_closed_pull_requests = (
        notifications_list
        | fp.filter(is_pull_request)
        | fp.filter(lambda n: not n.get_pull_request().merged)
        | fp.filter(lambda n: is_pull_request_closed_by_user(n, login))
        | fp.lmap(mark_done)
    )

    log.info(
        "marked user-closed PRs as done",
        count=len(user_closed_pull_requests),
    )

    # Case: Pull requests approved by the authenticated user and subsequently merged
    # If the user approved the PR and it was merged (by someone else), reviewer action is complete.
    # We skip PRs merged by the user to avoid redundant review checks and ensure distinct counts.
    user_approved_and_merged_prs = (
        notifications_list
        | fp.filter(is_pull_request)
        | fp.filter(lambda n: not is_pull_request_merged_by_user(n, login))
        | fp.filter(lambda n: is_pull_request_approved_by_user_and_merged(n, login))
        | fp.lmap(mark_done)
    )

    log.info(
        "marked user-approved and merged PRs as done",
        count=len(user_approved_and_merged_prs),
    )


@click.command()
@click.option(
    "--token",
    help="GitHub token, can also be set via GITHUB_TOKEN",
    default=os.getenv("GITHUB_TOKEN"),
)
# TODO move this into the parent command
@click.option(
    "--dry-run",
    is_flag=True,
    help="Run script without marking notification as complete",
)
@click.option(
    "--all-notifications",
    is_flag=True,
    help="Deprecated: cleanup always scans all notifications",
    default=False,
)
def notifications(token, dry_run, all_notifications):
    """
    Look at notifications and mark them as read if they are:

    * Older than two months
    * Bot-authored pull request notifications
    * Releases on repos I control (own or have push access to)
    * Closed (merged, closed) pull requests on repos I own
    * Closed pull requests that I authored
    * Self-authored pull request creation notifications without external activity
    * Pull requests merged by me
    * Pull requests closed by me
    * Pull requests approved by me that are now merged

    Helpful if you work across a lot of repos and want to keep your notifications clean.
    """
    clean_notifications(
        token=token, dry_run=dry_run, all_notifications=all_notifications
    )
