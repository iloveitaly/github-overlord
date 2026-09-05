"""Notification management and cleanup for github-overlord."""

import os
from datetime import UTC, datetime, timedelta

import click
import funcy_pipe as fp
from github import Github
from github.Notification import Notification

from .utils import log


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
    one_year_ago = datetime.now(UTC) - timedelta(days=365)

    def is_older_than_one_year(notification: Notification) -> bool:
        return notification.updated_at < one_year_ago

    old_notifications = (
        notifications_list
        | fp.filter(is_older_than_one_year)
        | fp.lmap(Notification.mark_as_done)
    )

    log.info("marked old notifications as done", count=len(old_notifications))

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
        | fp.lmap(Notification.mark_as_done)
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

    def is_pull_request(notification: Notification) -> bool:
        return notification.subject.type == "PullRequest"

    def is_pull_request_open(notification: Notification) -> bool:
        return notification.get_pull_request().state == "open"

    # TODO github digest has some logic to detect bots, maybev we can use that
    bot_authored_pull_requests = (
        notifications_list
        | fp.filter(is_pull_request)
        | fp.filter(is_bot_authored_pull_request)
        | fp.lmap(Notification.mark_as_done)
    )

    log.info("marked bot-authored PRs as done", count=len(bot_authored_pull_requests))

    release_please_pull_requests = (
        notifications_list
        | fp.filter(is_pull_request)
        | fp.filter(is_release_please_pull_request)
        | fp.lmap(Notification.mark_as_done)
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
        | fp.lmap(Notification.mark_as_done)
    )

    log.info("marked owned closed PRs as done", count=len(owned_closed_pull_requests))


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

    * Older than one year
    * Bot-authored pull request notifications
    * Releases on repos I control (own or have push access to)
    * Closed (merged, closed) pull requests on repos I own
    * Closed pull requests that I authored

    Helpful if you work across a lot of repos and want to keep your notifications clean.
    """
    clean_notifications(
        token=token, dry_run=dry_run, all_notifications=all_notifications
    )
