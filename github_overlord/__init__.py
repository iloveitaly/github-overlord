import os
import re
import time

import click
import funcy_pipe as fp
from github import Github
from github.GithubObject import NotSet
from github.PullRequest import PullRequest

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


def is_eligible_for_merge(pr: PullRequest):
    resolve_async_status(pr, "mergeable")

    if not pr.mergeable:
        return False

    if pr.user.login != "dependabot[bot]":
        return False

    last_commit = pr.get_commits().reversed[0]
    combined_status = last_commit.get_combined_status()
    status = combined_status.state

    # status is different than CI runs!
    if len(combined_status.statuses) > 0 and status != "success":
        return False

    # checks are the CI runs
    all_checks_successful = (
        last_commit.get_check_runs() | fp.pluck_attr("conclusion") | fp.all("success")
    )

    if not all_checks_successful:
        return False

    return True


def process_repo(repo, dry_run):
    log.debug("checking repository", repo=repo.full_name)

    if repo.fork:
        log.debug("skipping forked repo")
        return

    pulls = repo.get_pulls(state="open")

    if pulls.totalCount == 0:
        log.debug("no open prs, skipping")
        return

    merged_pr_count = 0

    for pr in pulls:
        if is_eligible_for_merge(pr):
            merge_pr(pr, dry_run)

            merged_pr_count += 1
        else:
            log.debug("skipping PR", url=pr.html_url)

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

    if repo:
        # convert 'https://github.com/iloveitaly/todoist-digest/pulls' to 'iloveitaly/todoist-digest'
        if "github.com" in repo:
            match = re.search(r"github\.com/([^/]+)/([^/]+)", repo)

            if match:
                repo = f"{match.group(1)}/{match.group(2)}"

    main(token, dry_run, repo)


cli.add_command(dependabot)

if __name__ == "__main__":
    cli()
