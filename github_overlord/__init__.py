import os

import click
from github import Github, GithubException

import github_overlord.patch  # noqa: F401

from .ai import get_expected_ai_key_var, is_ai_key_configured
from .dependabot import dependabot
from .notifications import notifications
from .release_checker import (
    check_repo_for_release,
    get_global_min_release_gap,
    release_creation_blocked_by_global_gap,
    should_stop_for_global_gap,
)
from .stale_commenter import inspect_stale_prs
from .utils import extract_repo_reference_from_github_url, log
from .version import __version__


def _log_release_run_summary(
    dry_run: bool, *, checked: int, created: int, skipped: int, failed: int
) -> None:
    if dry_run:
        log.info(
            "release check complete",
            dry_run=True,
            checked=checked,
            would_create=created,
            skipped=skipped,
            errors=failed,
        )
        return

    log.info(
        "release check complete",
        checked=checked,
        created=created,
        skipped=skipped,
        failed=failed,
    )


def _ensure_ai_key_configured(command_action: str) -> None:
    if not is_ai_key_configured():
        expected_var = get_expected_ai_key_var()
        raise click.ClickException(
            click.style(
                f"{expected_var} (or GITHUB_OVERLORD_AI_KEY) environment variable is required to {command_action}",
                fg="red",
            )
        )


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
@click.option("--dry-run", is_flag=True, help="Run script without creating comments")
@click.option("--repo", help="Only process a single repository")
def keep_alive_prs(token, dry_run, repo):
    """
    Detect when a bot is about to close a PR for no good reason and make a comment to keep it alive
    """

    if not token:
        raise click.ClickException(
            click.style("GITHUB_TOKEN environment variable is required", fg="red")
        )

    _ensure_ai_key_configured("run keep-alive-prs")

    log.info("checking for stale PRs")

    github = Github(token)
    user = github.get_user()
    login = user.login

    repo = extract_repo_reference_from_github_url(repo)

    result = inspect_stale_prs(github, login, dry_run, repo)
    if dry_run:
        log.info(
            "stale PR check complete",
            dry_run=True,
            prs_inspected=result.inspected,
            would_keep_alive=result.kept_alive,
            skipped=result.skipped,
            failed=result.failed,
        )
        return

    log.info(
        "stale PR check complete",
        prs_inspected=result.inspected,
        kept_alive=result.kept_alive,
        skipped=result.skipped,
        failed=result.failed,
    )


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
@click.option(
    "--max-releases",
    "-m",
    type=int,
    default=lambda: int(os.getenv("RELEASE_CHECKER_MAX_RELEASES", "1")),
    show_default="1",
    help="Maximum number of releases to create in a single run (0 for unlimited)",
)
def generate_releases(dry_run, topic, repo, max_releases):
    """
    Check repositories for release readiness using LLM analysis and create releases when appropriate
    """

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise click.ClickException(
            click.style("GITHUB_TOKEN environment variable is required", fg="red")
        )

    _ensure_ai_key_configured("use generate-releases")

    log.info("checking repositories for release readiness")

    repo = extract_repo_reference_from_github_url(repo)

    # Topic is required when not specifying a single repo
    if not repo and not topic:
        raise click.UsageError(
            "Topic is required when not specifying a single repository (use --topic or set RELEASE_CHECKER_TOPIC)"
        )

    g = Github(token)
    if repo:
        candidates = [g.get_repo(repo)]
    else:
        user = g.get_user()
        log.info("filtering by topic", topic=topic)
        # Public repos owned by the user with the specified topic.
        candidates = list(
            g.search_repositories(
                f"user:{user.login} topic:{topic} fork:false is:public",
                sort="updated",
                order="desc",
            )
        )
        if not candidates:
            log.warning("no repositories found with topic", topic=topic)
            return

    global_gap = get_global_min_release_gap()
    try:
        blocked = release_creation_blocked_by_global_gap(candidates, gap=global_gap)
    except GithubException:
        log.error(
            "skipping release creation because global gap state could not be read"
        )
        return

    if blocked:
        if repo:
            log.info("release check complete - no release needed", dry_run=dry_run)
        else:
            _log_release_run_summary(dry_run, checked=0, created=0, skipped=0, failed=0)
        return

    if repo:
        result = check_repo_for_release(candidates[0], dry_run)
        if result["created"]:
            log.info("release check complete - created 1 release", dry_run=dry_run)
        elif result["failed"]:
            log.info(
                "release check complete - failed to create release", dry_run=dry_run
            )
        else:
            log.info("release check complete - no release needed", dry_run=dry_run)
        return

    results = []
    created_count = 0

    for candidate in candidates:
        if max_releases > 0 and created_count >= max_releases:
            log.info(
                "reached max releases limit for this run",
                max_releases=max_releases,
            )
            break

        log.info("checking repo for release", repo=candidate.full_name, dry_run=dry_run)
        result = check_repo_for_release(candidate, dry_run=dry_run)
        results.append(result)
        if result["created"]:
            created_count += 1
            if should_stop_for_global_gap(global_gap, max_releases, created_count):
                log.info(
                    "stopping after one auto-generated release to honor global minimum gap",
                    min_gap_seconds=int(global_gap.total_seconds()),
                )
                break

    total_checked = sum(1 for result in results if result["checked"])
    total_skipped = sum(1 for result in results if result["skipped"])
    total_created = sum(1 for result in results if result["created"])
    total_failed = sum(1 for result in results if result["failed"])
    _log_release_run_summary(
        dry_run,
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
