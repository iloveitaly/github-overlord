import os
import re
import time
from types import NoneType

import click
import funcy_pipe as fp
from github import Github
from github.GithubObject import NotSet
from github.Notification import Notification
from github.PullRequest import PullRequest

import github_overlord.patch as _

from .release_checker import check_repo_for_release
from .stale_commenter import inspect_repo_for_stale_prs
from .utils import log

AUTOMATIC_MERGE_MESSAGE = "Automatically merged with [github-overlord](https://github.com/iloveitaly/github-overlord)"


def merge_pr(pr, dry_run):
    if dry_run:
        log.info("would merge PR", pr=pr.html_url)
        return

    pr.create_issue_comment(AUTOMATIC_MERGE_MESSAGE)
    pr.merge(merge_method="squash")

    log.info("merged PR", pr=pr.html_url)


def resolve_async_status(object, key):
    """
    https://github.com/PyGithub/PyGithub/issues/1979
    """

    count_limit = 10

    while getattr(object, key) is None:
        time.sleep(1)

        setattr(object, f"_{key}", NotSet)
        object._CompletableGithubObject__completed = False

        count_limit -= 1
        if count_limit == 0:
            return


def handle_stale_dependabot_pr(pr: PullRequest) -> None:
    """
    Handle a dependabot PR that has been open for at least 30 days and has conflicts
    """

    assert not pr.mergeable
    assert pr.mergeable_state == "dirty"

    if pr.body is None:
        return

    if "Automatic rebases have been disabled on this pull request" in pr.body:
        log.info(
            "PR has disabled automatic rebases, manually commenting", url=pr.html_url
        )

        pr.create_issue_comment("@dependabot rebase")


def is_eligible_for_merge(pr: PullRequest):
    resolve_async_status(pr, "mergeable")

    if pr.state == "closed":
        log.debug("PR is closed", url=pr.html_url)
        return

    if not pr.mergeable:
        log.debug("PR is not mergeable", url=pr.html_url)
        handle_stale_dependabot_pr(pr)
        return False

    if pr.user.login != "dependabot[bot]":
        log.debug("PR is not from dependabot", url=pr.html_url)
        return False

    last_commit = pr.get_commits().reversed[0]
    combined_status = last_commit.get_combined_status()
    status = combined_status.state

    # status is different than CI runs!
    if len(combined_status.statuses) > 0 and status != "success":
        log.debug("PR has failed status", url=pr.html_url, status=status)
        return False

    # checks are the CI runs
    all_checks_successful = (
        last_commit.get_check_runs()
        | fp.pluck_attr("conclusion")
        | fp.all({"success", "skipped"})
    )

    if not all_checks_successful:
        log.debug("PR has failed checks", url=pr.html_url)
        return False

    return True


def process_repo(repo, dry_run):
    with log.context(repo=repo.full_name):
        log.debug("checking repository")

        if repo.fork:
            log.debug("skipping forked repo")
            return

        pulls = repo.get_pulls(state="open")

        if pulls.totalCount == 0 or pulls == NoneType:
            log.debug("no open prs, skipping")
            return

        merged_pr_count = 0

        for pr in pulls:
            if is_eligible_for_merge(pr):
                merge_pr(pr, dry_run)

                merged_pr_count += 1
            else:
                log.debug("skipping PR", url=pr.html_url)

        if merged_pr_count == 0:
            log.debug("no PRs were merged")
        else:
            log.info("merged prs", count=merged_pr_count)


def merge_dependabot_prs(token, dry_run, repo):
    assert token, "GitHub token is required"

    g = Github(token)
    user = g.get_user()

    if repo:
        process_repo(g.get_repo(repo), dry_run)
        return

    # if not, process everything!
    user.get_repos(type="public") | fp.filter(
        lambda repo: repo.owner.login == user.login
    ) | fp.map(fp.rpartial(process_repo, dry_run)) | fp.to_list()

    log.info("dependabot pr check complete")


@click.group()
def cli():
    """
    GitHub Overlord is a tool to help manage annoying tasks across your GitHub repositories. Some of this could be done
    by GitHub Actions, but this eliminates the need to carefully configure GH actions for each repo.
    """

    pass


def extract_repo_reference_from_github_url(url: str | None):
    """
    Extract the owner and repo from a GitHub URL
    """

    if url is None:
        return None

    # convert 'https://github.com/iloveitaly/todoist-digest/pulls' to 'iloveitaly/todoist-digest'
    if "github.com" in url:
        match = re.search(r"github\.com/([^/]+)/([^/]+)", url)

        if match:
            url = f"{match.group(1)}/{match.group(2)}"

    return url


@click.command()
@click.option(
    "--token",
    help="GitHub token, can also be set via GITHUB_TOKEN",
    default=os.getenv("GITHUB_TOKEN"),
)
# TODO move this into the parent command
@click.option("--dry-run", is_flag=True, help="Run script without merging PRs")
@click.option("--repo", help="Only process a single repository")
def dependabot(token, dry_run, repo):
    """
    Automatically merge dependabot PRs in public repos that have passed CI checks
    """

    log.info("merging dependabot PRs")

    repo = extract_repo_reference_from_github_url(repo)

    merge_dependabot_prs(token, dry_run, repo)


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
    user.get_repos(type="public") | fp.map(transform_forked_repos) | fp.filter(
        lambda repo: repo.owner.login != login
    ) | fp.map(fp.partial(inspect_repo_for_stale_prs, dry_run, login)) | fp.to_list()

    log.info("stale PR check complete")


@click.command()
@click.option(
    "--token",
    help="GitHub token, can also be set via GITHUB_TOKEN",
    default=os.getenv("GITHUB_TOKEN"),
)
# TODO move this into the parent command
@click.option("--dry-run", is_flag=True, help="Run script without merging PRs")
@click.option(
    "--only-unread", is_flag=True, help="Only process a single repository", default=True
)
def notifications(token, dry_run, only_unread):
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
    notifications = list(user.get_notifications(all=not only_unread))

    # TODO fix funcy_pipe here
    released_on_owned_repos = (
        notifications
        | fp.filter(
            lambda n: n.subject.type == "Release"
            and n.repository.owner.login == login
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


@click.command()
@click.option(
    "--token",
    help="GitHub token, can also be set via GITHUB_TOKEN",
    default=os.getenv("GITHUB_TOKEN"),
)
@click.option("--dry-run", is_flag=True, help="Run script without creating releases")
@click.option(
    "--topic",
    help="Only process repos with this topic (can also be set via RELEASE_CHECKER_TOPIC)",
    default=os.getenv("RELEASE_CHECKER_TOPIC"),
)
@click.option("--repo", help="Only process a single repository")
def check_releases(token, dry_run, topic, repo):
    """
    Check repositories for release readiness using LLM analysis and create releases when appropriate
    """

    assert token, "GitHub token is required"
    assert os.getenv("GEMINI_API_KEY"), "GEMINI_API_KEY environment variable is required"

    log.info("checking repositories for release readiness")

    g = Github(token)
    user = g.get_user()

    repo = extract_repo_reference_from_github_url(repo)

    if repo:
        check_repo_for_release(g.get_repo(repo), dry_run)
        return

    # Get all public repos owned by user
    repos = user.get_repos(type="public") | fp.filter(
        lambda r: r.owner.login == user.login and not r.fork
    )

    # Filter by topic if specified
    if topic:
        log.info("filtering by topic", topic=topic)
        repos = repos | fp.filter(lambda r: topic in r.get_topics())

    # Process each repo
    repos | fp.map(fp.partial(check_repo_for_release, dry_run=dry_run)) | fp.to_list()

    log.info("release check complete")


cli.add_command(dependabot)
cli.add_command(keep_alive_prs)
cli.add_command(notifications)
cli.add_command(check_releases)

if __name__ == "__main__":
    cli()
