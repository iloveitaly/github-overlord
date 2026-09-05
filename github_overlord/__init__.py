import os

import click
import funcy_pipe as fp
from github import Github

import github_overlord.patch  # noqa: F401

from .ai import get_expected_ai_key_var, is_ai_key_configured
from .dependabot import dependabot
from .notifications import notifications
from .release_checker import check_repo_for_release
from .stale_commenter import inspect_stale_prs
from .utils import extract_repo_reference_from_github_url, log
from .version import __version__


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
def generate_releases(dry_run, topic, repo):
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

    if repo:
        g = Github(token)
        result = check_repo_for_release(g.get_repo(repo), dry_run)
        if result["created"]:
            log.info("release check complete - created 1 release", dry_run=dry_run)
        elif result["failed"]:
            log.info(
                "release check complete - failed to create release", dry_run=dry_run
            )
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
    results = repos | fp.map(_check_repo_with_log) | fp.to_list()

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
