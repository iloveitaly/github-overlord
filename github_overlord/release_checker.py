import os
from datetime import datetime, timezone

import funcy_pipe as fp
from github import GithubException
from github.Repository import Repository
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from github_overlord.config import JINJA_ENV
from github_overlord.utils import log


class ReleaseAnalysis(BaseModel):
    """Structured output from LLM analysis of commits."""

    should_release: str = Field(description="yes, no, or maybe")
    confidence: int = Field(ge=0, le=100, description="Confidence level 0-100")
    reasoning: str = Field(description="Brief explanation in 1-2 sentences")
    suggested_version_bump: str = Field(description="major, minor, or patch")
    key_changes: list[str] = Field(description="List of key changes (2-5 items)")


class ReleaseDecision(BaseModel):
    """Decision about whether to create a release."""

    should_create: bool
    suggested_version: str
    release_notes: str


def should_create_release(repo: Repository) -> ReleaseDecision:
    """
    Analyze commits since last release and determine if a new release should be created.

    Returns:
        ReleaseDecision with should_create, suggested_version, and release_notes
    """

    # Get the last release
    releases = list(repo.get_releases())

    if releases:
        last_release = releases[0]
        baseline_date = last_release.created_at
        baseline_tag = last_release.tag_name
        log.debug("found last release", tag=baseline_tag, date=baseline_date)
    else:
        # No releases yet, use repo creation date
        baseline_date = repo.created_at
        baseline_tag = None
        log.debug("no releases found, using repo creation date", date=baseline_date)

    # Get commits since baseline (limit to 50)
    try:
        all_commits = list(repo.get_commits(since=baseline_date, sha=repo.default_branch))
    except GithubException as e:
        log.error("failed to get commits", error=str(e), code=e.status if hasattr(e, 'status') else None)
        return ReleaseDecision(should_create=False, suggested_version="", release_notes="")

    # Limit to last 50 commits
    commits = all_commits[:50]

    if not commits:
        log.info("no commits since last release", last_release=baseline_tag or "none")
        return ReleaseDecision(should_create=False, suggested_version="", release_notes="")

    log.info("analyzing commits", count=len(commits), total_available=len(all_commits))

    # Format commits for LLM
    commit_summary = format_commits_for_llm(commits)

    # Calculate days since last release
    days_since_release = (datetime.now(timezone.utc) - baseline_date).days

    # Call LLM to analyze
    analysis = analyze_commits_with_llm(
        repo=repo,
        commit_summary=commit_summary,
        commit_count=len(commits),
        days_since_release=days_since_release,
        last_tag=baseline_tag
    )

    if not analysis:
        log.error("LLM analysis failed")
        return ReleaseDecision(should_create=False, suggested_version="", release_notes="")

    should_release = analysis.get("should_release", "no") in ["yes", "maybe"]

    if should_release:
        suggested_version = calculate_next_version(baseline_tag, analysis.get("suggested_version_bump", "patch"))
        release_notes = generate_release_notes(repo, baseline_tag, suggested_version, analysis)

        log.info(
            "LLM recommends release",
            decision=analysis.get("should_release"),
            confidence=analysis.get("confidence", 0),
            version=suggested_version,
            bump=analysis.get("suggested_version_bump", "patch"),
            reasoning=analysis.get("reasoning", "")
        )

        return ReleaseDecision(
            should_create=True,
            suggested_version=suggested_version,
            release_notes=release_notes
        )

    log.info(
        "LLM does not recommend release",
        decision=analysis.get("should_release", "no"),
        confidence=analysis.get("confidence", 0),
        reasoning=analysis.get("reasoning", "")
    )
    return ReleaseDecision(should_create=False, suggested_version="", release_notes="")


def format_commits_for_llm(commits) -> str:
    """Format commits into a readable summary for LLM analysis."""

    commit_lines = []

    for commit in commits[:50]:  # Limit to avoid token limits
        # Get first line of commit message
        message_lines = commit.commit.message.strip().split("\n")
        first_line = message_lines[0][:100]  # Limit length

        author = commit.commit.author.name
        date = commit.commit.author.date.strftime("%Y-%m-%d")

        commit_lines.append(f"- [{date}] {first_line} (@{author})")

    return "\n".join(commit_lines)


def analyze_commits_with_llm(repo: Repository, commit_summary: str, commit_count: int, days_since_release: int, last_tag: str | None) -> dict:
    """Use Gemini via Pydantic AI to analyze commits and determine if a release should be created."""

    template = JINJA_ENV.get_template("release_analysis_prompt.j2")

    last_release_info = f"Last release: {last_tag} ({days_since_release} days ago)" if last_tag else f"No previous releases (repo is {days_since_release} days old)"

    prompt = template.render(
        repo_name=repo.full_name,
        last_release_info=last_release_info,
        commit_count=commit_count,
        commit_summary=commit_summary
    )

    try:
        # Create agent with structured output
        # Using gemini-flash which points to latest flash model
        agent = Agent(
            'google-gla:gemini-flash',
            result_type=ReleaseAnalysis,
        )

        result = agent.run_sync(prompt)

        # Convert Pydantic model to dict for compatibility
        return result.data.model_dump()

    except Exception as e:
        log.error("LLM API call failed", error=str(e))
        return {}


def calculate_next_version(current_tag: str | None, bump_type: str) -> str:
    """Calculate the next semantic version based on the current tag and bump type."""

    if not current_tag:
        # No previous releases, start with v1.0.0
        return "v1.0.0"

    # Remove 'v' prefix if present
    version_str = current_tag.lstrip("v")

    try:
        parts = version_str.split(".")
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        # Can't parse version, default to v1.0.0
        log.warning("could not parse version", current_tag=current_tag)
        return "v1.0.0"

    if bump_type == "major":
        major += 1
        minor = 0
        patch = 0
    elif bump_type == "minor":
        minor += 1
        patch = 0
    else:  # patch
        patch += 1

    return f"v{major}.{minor}.{patch}"


def generate_release_notes(repo: Repository, baseline_tag: str | None, new_tag: str, analysis: dict) -> str:
    """Generate release notes from LLM analysis and add changelog link."""

    key_changes = analysis.get("key_changes", [])

    notes_lines = []

    # Add key changes from LLM
    if key_changes:
        for change in key_changes:
            notes_lines.append(f"- {change}")
        notes_lines.append("")

    # Add horizontal line and Full Changelog link
    notes_lines.append("---")
    notes_lines.append("")

    if baseline_tag:
        # Compare from last tag to new tag
        changelog_url = f"https://github.com/{repo.full_name}/compare/{baseline_tag}...{new_tag}"
    else:
        # No previous release, link to all commits up to this tag
        changelog_url = f"https://github.com/{repo.full_name}/commits/{new_tag}"

    notes_lines.append(f"**Full Changelog**: {changelog_url}")

    return "\n".join(notes_lines)


def create_release(repo: Repository, tag: str, notes: str, dry_run: bool) -> bool:
    """Create a new GitHub release."""

    if dry_run:
        log.info(
            "DRY RUN: would create release",
            repo=repo.full_name,
            tag=tag,
            notes_preview=notes[:200] + "..." if len(notes) > 200 else notes
        )
        return True

    try:
        repo.create_git_release(
            tag=tag,
            name=tag,
            message=notes,
            draft=False,
            prerelease=False,
            target_commitish=repo.default_branch
        )

        log.info("created release", repo=repo.full_name, tag=tag)
        return True

    except GithubException as e:
        log.error("failed to create release", repo=repo.full_name, error=str(e))
        return False


def check_repo_for_release(repo: Repository, dry_run: bool) -> dict:
    """
    Check a single repository and create a release if recommended.

    Returns:
        dict with keys: checked, skipped, created, failed
    """

    result = {
        "checked": False,
        "skipped": False,
        "created": False,
        "failed": False
    }

    with log.context(repo=repo.full_name):
        log.debug("checking repository for release")

        # Skip archived repos
        if repo.archived:
            log.debug("skipping archived repo")
            result["skipped"] = True
            return result

        # Skip empty repos
        try:
            if repo.size == 0:
                log.debug("skipping empty repo")
                result["skipped"] = True
                return result
        except Exception:
            pass  # If we can't determine size, continue anyway

        result["checked"] = True

        try:
            decision = should_create_release(repo)

            if decision.should_create:
                success = create_release(repo, decision.suggested_version, decision.release_notes, dry_run)
                if success:
                    result["created"] = True
                else:
                    result["failed"] = True
            else:
                log.debug("no release needed")
        except GithubException as e:
            log.error("GitHub API error", error=str(e), status=e.status if hasattr(e, 'status') else None)
            result["failed"] = True
        except Exception as e:
            log.error("unexpected error checking repository", error=str(e), error_type=type(e).__name__)
            result["failed"] = True

    return result
