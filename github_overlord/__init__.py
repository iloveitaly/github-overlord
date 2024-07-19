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

from github_overlord.stale_commenter import (
    check_for_stale_comments,
    inspect_repo_for_stale_prs,
    is_stale_comment,
)
from github_overlord.utils import log

AUTOMATIC_MERGE_MESSAGE = "Automatically merged with GitHub overlord"


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


def main(token, dry_run, repo):
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

    main(token, dry_run, repo)


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


def notifications(token, dry_run):
    """
    Look at notifications and mark them as read if they are dependabot notifications
    """

    g = Github(token)
    user = g.get_user()
    notifications = user.get_notifications()

    def handle_notification(notification: Notification):
        pass

    # for notification in notifications:
    #     print(f"Notification: {notification.subject['title']}, Reason: {notification.reason}")
    #     if not read_only:
    #         notification.mark_as_read()


cli.add_command(dependabot)
cli.add_command(keep_alive_prs)

if __name__ == "__main__":
    cli()
