import os
import re
import time
from collections.abc import Awaitable
from types import NoneType
from typing import Protocol, TypedDict

import click
import funcy_pipe as fp
import yaml
from github import Github
from github.GithubException import GithubException
from github.GithubObject import NotSet
from github.PullRequest import PullRequest

from .utils import extract_repo_reference_from_github_url, log

AUTOMATIC_MERGE_MESSAGE = "Automatically merged with [github-overlord](https://github.com/iloveitaly/github-overlord)"


class DependencyAlert(TypedDict):
    alertState: str
    ghsaId: str
    cvss: float


class UpdatedDependency(DependencyAlert, total=False):
    dependencyName: str
    dependencyType: str
    updateType: str
    directory: str
    packageEcosystem: str
    targetBranch: str
    prevVersion: str
    newVersion: str
    compatScore: float
    maintainerChanges: bool
    dependencyGroup: str


class AlertLookup(Protocol):
    def __call__(
        self, dependencyName: str, dependencyVersion: str, directory: str
    ) -> Awaitable[DependencyAlert]: ...


class ScoreLookup(Protocol):
    def __call__(
        self, dependencyName: str, previousVersion: str, newVersion: str, ecosystem: str
    ) -> Awaitable[float]: ...


async def parse(
    commitMessage: str,
    body: str,
    branchName: str,
    mainBranch: str,
    lookup: AlertLookup | None = None,
    getScore: ScoreLookup | None = None,
) -> list[UpdatedDependency]:
    bump_re = r"^Bumps .* from (?P<from>v?\d[^ ]*) to (?P<to>v?\d[^ ]*)\.$"
    update_re = (
        r"^Update .* requirement from \S*? ?(?P<from>v?\d\S*) to \S*? ?(?P<to>v?\d\S*)$"
    )
    yaml_re = r"-{3}\n(?P<dependencies>[\S|\s]*?)\n\.{3}\n"
    group_re = r"dependency-group:\s(?P<name>\S*)"

    bump_match = re.search(bump_re, commitMessage, re.MULTILINE)
    update_match = re.search(update_re, commitMessage, re.MULTILINE)
    yaml_match = re.search(yaml_re, commitMessage, re.MULTILINE)
    group_match = re.search(group_re, commitMessage, re.MULTILINE)

    new_maintainer = bool(re.search(r"Maintainer changes", body, re.MULTILINE))
    lookup_fn = (
        lookup
        if lookup
        else (lambda *args: _empty_dependency_alert())
    )
    score_fn = getScore if getScore else (lambda *args: 0)

    if not yaml_match or not branchName.startswith("dependabot"):
        return []

    data = yaml.safe_load(yaml_match.group("dependencies"))
    delim = branchName[10]
    chunks = branchName.split(delim)
    prev = (
        bump_match.group("from")
        if bump_match
        else (update_match.group("from") if update_match else "")
    )
    next = (
        bump_match.group("to")
        if bump_match
        else (update_match.group("to") if update_match else "")
    )
    dependency_group = group_match.group("name") if group_match else ""

    if "updated-dependencies" not in data:
        return []

    async def create_dependency(dependency: dict[str, str], index: int):
        dirname = f"/{'/'.join(chunks[2:-1 * (1 + dependency['dependency-name'].count('/'))]) or ''}"
        last_version = prev if index == 0 else ""
        next_version = next if index == 0 else ""
        update_type = dependency.get(
            "update-type", calculate_update_type(last_version, next_version)
        )
        return UpdatedDependency(
            dependencyName=dependency["dependency-name"],
            dependencyType=dependency["dependency-type"],
            updateType=update_type,
            directory=dirname,
            packageEcosystem=chunks[1],
            targetBranch=mainBranch,
            prevVersion=last_version,
            newVersion=next_version,
            compatScore=await score_fn(
                dependency["dependency-name"],
                last_version,
                next_version,
                chunks[1],
            ),
            maintainerChanges=new_maintainer,
            dependencyGroup=dependency_group,
            **await lookup_fn(dependency["dependency-name"], last_version, dirname),
        )

    return [
        await create_dependency(dependency, index)
        for index, dependency in enumerate(data["updated-dependencies"])
    ]


def _empty_dependency_alert() -> DependencyAlert:
    return {"alertState": "", "ghsaId": "", "cvss": 0}


def calculate_update_type(last_version: str, next_version: str) -> str:
    if not last_version or not next_version or last_version == next_version:
        return ""

    last_parts = last_version.lstrip("v").split(".")
    next_parts = next_version.lstrip("v").split(".")

    if last_parts[0] != next_parts[0]:
        return "version-update:semver-major"

    if len(last_parts) < 2 or len(next_parts) < 2 or last_parts[1] != next_parts[1]:
        return "version-update:semver-minor"

    return "version-update:semver-patch"


def merge_pr(pr: PullRequest, dry_run: bool) -> bool:
    if dry_run:
        log.info("would merge PR", pr=pr.html_url)
        return True

    try:
        pr.merge(merge_method="squash")
    except GithubException as error:
        log.error(
            "failed to merge PR",
            pr=pr.html_url,
            status=error.status,
            error=error.data.get("message", str(error)),
        )
        return False

    try:
        pr.create_issue_comment(AUTOMATIC_MERGE_MESSAGE)
    except GithubException as error:
        log.error(
            "failed to comment on merged PR",
            pr=pr.html_url,
            status=error.status,
            error=error.data.get("message", str(error)),
        )

    log.info("merged PR", pr=pr.html_url)
    return True


def resolve_async_status(github_object, key: str) -> None:
    """
    https://github.com/PyGithub/PyGithub/issues/1979
    """

    count_limit = 10

    while getattr(github_object, key) is None:
        time.sleep(1)

        setattr(github_object, f"_{key}", NotSet)
        github_object._CompletableGithubObject__completed = False

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


def is_eligible_for_merge(pr: PullRequest) -> bool:
    resolve_async_status(pr, "mergeable")

    if pr.state == "closed":
        log.debug("PR is closed", url=pr.html_url)
        return False

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

    if len(combined_status.statuses) > 0 and status != "success":
        log.debug("PR has failed status", url=pr.html_url, status=status)
        return False

    all_checks_successful = (
        last_commit.get_check_runs()
        | fp.pluck_attr("conclusion")
        | fp.all({"success", "skipped"})
    )

    if not all_checks_successful:
        log.debug("PR has failed checks", url=pr.html_url)
        return False

    return True


def process_repo(repo, dry_run: bool) -> None:
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
                if merge_pr(pr, dry_run):
                    merged_pr_count += 1
                continue

            log.debug("skipping PR", url=pr.html_url)

        if merged_pr_count == 0:
            log.debug("no PRs were merged")
            return

        log.info("merged prs", count=merged_pr_count)


def merge_dependabot_prs(token: str, dry_run: bool, repo: str | None) -> None:
    assert token, "GitHub token is required"

    github = Github(token)
    user = github.get_user()

    if repo:
        process_repo(github.get_repo(repo), dry_run)
        return

    (
        user.get_repos(type="public")
        | fp.filter(lambda current_repo: current_repo.owner.login == user.login)
        | fp.map(fp.rpartial(process_repo, dry_run))
        | fp.to_list()
    )

    log.info("dependabot pr check complete")


@click.command()
@click.option(
    "--token",
    help="GitHub token, can also be set via GITHUB_TOKEN",
    default=os.getenv("GITHUB_TOKEN"),
)
@click.option("--dry-run", is_flag=True, help="Run script without merging PRs")
@click.option("--repo", help="Only process a single repository")
def dependabot(token: str, dry_run: bool, repo: str | None) -> None:
    """
    Automatically merge dependabot PRs in public repos that have passed CI checks
    """

    log.info("merging dependabot PRs")

    repo = extract_repo_reference_from_github_url(repo)

    merge_dependabot_prs(token, dry_run, repo)