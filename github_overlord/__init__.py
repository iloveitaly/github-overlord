import os

import click
import funcy_pipe as fp
from github import Github
from github.Notification import Notification

import github_overlord.patch as _

from .dependabot import dependabot
from .release_checker import check_repo_for_release
from .stale_commenter import inspect_repo_for_stale_prs
from .utils import extract_repo_reference_from_github_url, log
from .version import __version__


@click.group()
@click.version_option(version=__version__)
def cli():
    """
    GitHub Overlord is a tool to help manage annoying tasks across your GitHub repositories. Some of this could be done
    by GitHub Actions, but this eliminates the need to carefully configure GH actions for each repo.
    """



@click.command()
@click.option(
    "--token",
    help="GitHub token, can also be set via GITHUB_TOKEN",
    default=os.getenv("GITHUB_TOKEN"),
)
# TODO move this into the parent command
@click.option("--dry-run", is_flag=True, help="Run script without merging PRs")
@click.option("--repo", help="Only process a single repository")
def keep_alive_prs(token, dry_run, repo):
    """
    Detect when a bot is about to close a PR for no good reason and make a comment to keep it alive
    """

    assert token, "GitHub token is required"
    # TODO should assert on openai setup

    log.info("checking for stale PRs")

    github = Github(token)
    user = github.get_user()
    login = user.login

    repo = extract_repo_reference_from_github_url(repo)

    if repo:
        inspect_repo_for_stale_prs(dry_run, login, github.get_repo(repo))
        return

    def transform_forked_repos(repo):
        return repo.parent if repo.fork else repo

    # TODO this isn't perfect because you may be a contributor :/
    (
        user.get_repos(type="public")
        | fp.map(transform_forked_repos)
        | fp.filter(lambda repo: repo.owner.login != login)
        | fp.map(fp.partial(inspect_repo_for_stale_prs, dry_run, login))
        | fp.to_list()
    )

    log.info("stale PR check complete")


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
    help="Don't limit notifications to unread",
    default=False,
)
def notifications(token, dry_run, all_notifications):
    """
    Look at notifications and mark them as read if they are:

    * Dependabot notifications
    * Releases on repos I own
    * Closed (merged, closed) pull requests on repos I own
    * Closed pull requests that I authored

    Helpful if you work across a lot of repos and want to keep your notifications clean.
    """

    github = Github(token)
    user = github.get_user()
    login = user.login

    # all includes read notifications AND done notifications :/
    # there is no way to determine if a notification is marked as done
    notifications = list(user.get_notifications(all=all_notifications))

    # TODO fix funcy_pipe here
    released_on_owned_repos = (
        notifications
        | fp.filter(
            lambda n: n.subject.type == "Release" and n.repository.owner.login == login
            # TODO I think there is a way to convert the instance method to a standard method so it could be mapped
            #      patchy had some code for this
        )
        | fp.lmap(Notification.mark_as_done)
    )

    log.info("marked releases as done", count=len(released_on_owned_repos))

    def is_dependabot_notification(notification: Notification) -> bool:
        return notification.get_pull_request().user.login == "dependabot[bot]"

    def is_pull_request(notification: Notification) -> bool:
        return notification.subject.type == "PullRequest"

    def is_pull_request_open(notification: Notification) -> bool:
        return notification.get_pull_request().state == "open"

    # TODO github digest has some logic to detect bots, maybev we can use that
    pull_requests_by_dependabot = (
        notifications
        | fp.filter(is_pull_request)
        | fp.filter(is_dependabot_notification)
        | fp.lmap(Notification.mark_as_done)
    )

    log.info("marked dependabot PRs as done", count=len(pull_requests_by_dependabot))

    # Closed (merged, closed) pull requests that I authored
    owned_closed_pull_requests = (
        notifications
        # PRs that I did not author may still be interesting
        | fp.where_attr(reason="author")
        | fp.filter(is_pull_request)
        | fp.filter(fp.complement(is_pull_request_open))
        | fp.lmap(Notification.mark_as_done)
    )

    log.info("marked owned closed PRs as done", count=len(owned_closed_pull_requests))


@click.command(name="generate-releases")
@click.option("--dry-run", is_flag=True, help="Run script without creating releases")
@click.option(
    "--topic",
    help="Only process repos with this topic (can also be set via RELEASE_CHECKER_TOPIC)",
    default=os.getenv("RELEASE_CHECKER_TOPIC"),
)
@click.option(
    "--repo",
    help="Only process a single repository (can also be set via RELEASE_CHECKER_REPO)",
    default=os.getenv("RELEASE_CHECKER_REPO"),
)
def generate_releases(dry_run, topic, repo):
    """
    Check repositories for release readiness using LLM analysis and create releases when appropriate
    """

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise click.ClickException(
            click.style("GITHUB_TOKEN environment variable is required", fg="red")
        )

    if not os.getenv("GOOGLE_API_KEY"):
        raise click.ClickException(
            click.style(
                "GOOGLE_API_KEY environment variable is required to use generate-releases",
                fg="red",
            )
        )

    log.info("checking repositories for release readiness")

    repo = extract_repo_reference_from_github_url(repo)

    if repo:
        g = Github(token)
        result = check_repo_for_release(g.get_repo(repo), dry_run)
        if result["created"]:
            log.info("release check complete - created 1 release", dry_run=dry_run)
        elif result["failed"]:
            log.info("release check complete - failed to create release", dry_run=dry_run)
        else:
            log.info("release check complete - no release needed", dry_run=dry_run)
        return

    # Topic is required when not specifying a single repo
    if not topic:
        raise click.UsageError(
            "Topic is required when not specifying a single repository (use --topic or set RELEASE_CHECKER_TOPIC)"
        )

    g = Github(token)
    user = g.get_user()

    log.info("filtering by topic", topic=topic)

    # Get all public repos owned by user with the specified topic
    repos = user.get_repos(type="public") | fp.filter(
        lambda r: r.owner.login == user.login and not r.fork and topic in r.get_topics()
    )

    def _check_repo_with_log(r):
        log.info("checking repo for release", repo=r.full_name, dry_run=dry_run)
        return check_repo_for_release(r, dry_run=dry_run)

    # Process each repo and collect results
    results = (
        repos
        | fp.map(_check_repo_with_log)
        | fp.to_list()
    )

    # Check if any repos were found
    if not results:
        log.warning("no repositories found with topic", topic=topic)
        return

    # Calculate statistics
    total_checked = sum(1 for r in results if r["checked"])
    total_skipped = sum(1 for r in results if r["skipped"])
    total_created = sum(1 for r in results if r["created"])
    total_failed = sum(1 for r in results if r["failed"])

    # Log summary
    if dry_run:
        log.info(
            "release check complete",
            dry_run=True,
            checked=total_checked,
            would_create=total_created,
            skipped=total_skipped,
            errors=total_failed,
        )
    else:
        log.info(
            "release check complete",
            checked=total_checked,
            created=total_created,
            skipped=total_skipped,
            failed=total_failed,
        )


cli.add_command(dependabot)
cli.add_command(keep_alive_prs)
cli.add_command(notifications)
cli.add_command(generate_releases)

if __name__ == "__main__":
    cli()
