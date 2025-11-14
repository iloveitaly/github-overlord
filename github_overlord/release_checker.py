import os
from datetime import datetime, timezone

import funcy_pipe as fp
from github import GithubException
from github.Repository import Repository
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from github_overlord.utils import log


class ReleaseAnalysis(BaseModel):
    """Structured output from LLM analysis of commits."""

    should_release: str = Field(description="yes, no, or maybe")
    confidence: int = Field(ge=0, le=100, description="Confidence level 0-100")
    reasoning: str = Field(description="Brief explanation in 1-2 sentences")
    suggested_version_bump: str = Field(description="major, minor, or patch")
    key_changes: list[str] = Field(description="List of key changes (2-5 items)")


def should_create_release(repo: Repository) -> tuple[bool, str, str]:
    """
    Analyze commits since last release and determine if a new release should be created.

    Returns:
        Tuple of (should_create, suggested_version, release_notes)
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
        return False, "", ""

    # Limit to last 50 commits
    commits = all_commits[:50]

    if not commits:
        log.info("no commits since last release", last_release=baseline_tag or "none")
        return False, "", ""

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
        return False, "", ""

    should_release = analysis.get("should_release", "no") in ["yes", "maybe"]

    if should_release:
        suggested_version = calculate_next_version(baseline_tag, analysis.get("suggested_version_bump", "patch"))
        release_notes = generate_release_notes(repo, commits, analysis)

        log.info(
            "✓ LLM recommends release",
            decision=analysis.get("should_release"),
            confidence=analysis.get("confidence", 0),
            version=suggested_version,
            bump=analysis.get("suggested_version_bump", "patch"),
            reasoning=analysis.get("reasoning", "")
        )

        return True, suggested_version, release_notes

    log.info(
        "○ LLM does not recommend release",
        decision=analysis.get("should_release", "no"),
        confidence=analysis.get("confidence", 0),
        reasoning=analysis.get("reasoning", "")
    )
    return False, "", ""


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

    system_prompt = """
You are analyzing commits for an open-source project to determine if a new release should be created.

Consider these factors:
- Number of commits (more commits = more likely to release, but even 1-2 significant commits may warrant a release)
- Type of changes (features, bug fixes, refactoring, docs, tests, dependencies)
- Impact of changes (major features vs minor tweaks)
- Time since last release (longer time = more likely, but not the only factor)
- For template/starter projects: any meaningful updates warrant a release

Guidelines:
- "yes" = clear value in creating a release (new features, important fixes, meaningful updates)
- "no" = minimal changes (typos, minor docs, CI tweaks only)
- "maybe" = borderline case (some value but not urgent)
- For dependency updates: patch bump
- For bug fixes: patch bump
- For new features: minor bump
- For breaking changes: major bump
"""

    last_release_info = f"Last release: {last_tag} ({days_since_release} days ago)" if last_tag else f"No previous releases (repo is {days_since_release} days old)"

    user_content = f"""
Repository: {repo.full_name}
{last_release_info}
Number of commits: {commit_count}

Commits:
{commit_summary}
"""

    try:
        # Create agent with structured output
        # Using latest stable Gemini Flash model
        agent = Agent(
            'google-gla:gemini-2.0-flash',
            result_type=ReleaseAnalysis,
            system_prompt=system_prompt
        )

        result = agent.run_sync(user_content)

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


def generate_release_notes(repo: Repository, commits, analysis: dict) -> str:
    """Generate release notes based on commits and LLM analysis."""

    key_changes = analysis.get("key_changes", [])
    reasoning = analysis.get("reasoning", "")

    notes_lines = [
        "## What's Changed",
        "",
        reasoning,
        ""
    ]

    if key_changes:
        notes_lines.append("### Key Changes")
        for change in key_changes:
            notes_lines.append(f"- {change}")
        notes_lines.append("")

    # Add commit count
    notes_lines.append(f"**{len(commits)} commits** in this release")
    notes_lines.append("")

    # Add compare link (will be updated after release is created)
    notes_lines.append("*This release was automatically generated by [github-overlord](https://github.com/iloveitaly/github-overlord)*")

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

        log.info("✓ created release", repo=repo.full_name, tag=tag)
        return True

    except GithubException as e:
        log.error("✗ failed to create release", repo=repo.full_name, error=str(e))
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
            should_release, version, notes = should_create_release(repo)

            if should_release:
                success = create_release(repo, version, notes, dry_run)
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
