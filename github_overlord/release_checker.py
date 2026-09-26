"""
Logic for analyzing repository commits and determining if a new release should be created.

Uses LLM analysis to evaluate the significance of changes since the last release,
calculates semantic version bumps, and generates formatted release notes.
"""

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from github import GithubException
from github.Repository import Repository
from pydantic import BaseModel, Field

from github_overlord.ai import (
    get_agent,
    get_expected_ai_key_var,
    is_ai_key_configured,
)
from github_overlord.config import JINJA_ENV
from github_overlord.utils import log

# Release notes include this line. It is how a later run recognizes its own releases.
GENERATED_BY_MARKER = "**Generated-by**: https://github.com/iloveitaly/github-overlord"


def _parse_duration_to_timedelta(value: str) -> timedelta:
    """Parse a simple duration string into a timedelta.

    Supported formats (case-insensitive):
    - "2w", "14d", "48h", "30m", "10s"
    - "week(s)", "day(s)", "hour(s)", "minute(s)", "second(s)"
    - If unit is omitted, days are assumed (e.g. "14" -> 14 days)
    """

    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("empty duration")

    match = re.fullmatch(r"(\d+)\s*([a-z]*)", normalized)
    if not match:
        raise ValueError(f"invalid duration: {value!r}")

    amount = int(match.group(1))
    unit = match.group(2) or "d"

    if unit in {"w", "week", "weeks"}:
        return timedelta(weeks=amount)
    if unit in {"d", "day", "days"}:
        return timedelta(days=amount)
    if unit in {"h", "hr", "hrs", "hour", "hours"}:
        return timedelta(hours=amount)
    if unit in {"m", "min", "mins", "minute", "minutes"}:
        return timedelta(minutes=amount)
    if unit in {"s", "sec", "secs", "second", "seconds"}:
        return timedelta(seconds=amount)

    raise ValueError(f"unsupported duration unit: {unit!r}")


def _get_configured_gap(
    env_var: str,
    default: str,
    *,
    invalid_event: str,
    negative_event: str,
) -> timedelta:
    raw = os.getenv(env_var, default)
    try:
        gap = _parse_duration_to_timedelta(raw)
    except ValueError:
        log.warning(invalid_event, value=raw, default=default)
        gap = _parse_duration_to_timedelta(default)

    if gap.total_seconds() < 0:
        log.warning(negative_event, value=raw, default=default)
        return _parse_duration_to_timedelta(default)

    return gap


def _get_min_release_gap() -> timedelta:
    return _get_configured_gap(
        "RELEASE_CHECKER_MIN_GAP",
        "2w",
        invalid_event="invalid release_checker_min_gap; falling back to default",
        negative_event="negative release_checker_min_gap; falling back to default",
    )


def get_global_min_release_gap() -> timedelta:
    """Minimum time between auto-generated releases across the selected repos.

    Defaults to one week. ``0`` disables the limit.
    """

    return _get_configured_gap(
        "RELEASE_CHECKER_GLOBAL_MIN_GAP",
        "1w",
        invalid_event="invalid release_checker_global_min_gap; falling back to default",
        negative_event="negative release_checker_global_min_gap; falling back to default",
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_generated_release(release: object) -> bool:
    body = getattr(release, "body", None) or ""
    if not isinstance(body, str):
        return False
    return GENERATED_BY_MARKER in body


def _published_at(release: object) -> datetime | None:
    published = getattr(release, "published_at", None)
    if not isinstance(published, datetime):
        return None
    return _as_utc(published)


@dataclass(frozen=True)
class GeneratedRelease:
    """An auto-generated GitHub release, identified by its release notes."""

    repo_full_name: str
    tag_name: str
    published_at: datetime


def latest_generated_release_since(
    repos: Iterable[Repository], since: datetime
) -> GeneratedRelease | None:
    """Return the newest auto-generated release published after ``since``.

    GitHub lists releases by ``created_at``, and that field is the tagged
    commit's timestamp, not when the release was published. A release published
    today for an older commit can sort behind a newer commit, so this compares
    ``published_at`` across the full list. Manual releases are ignored.
    """

    since = _as_utc(since)
    latest: GeneratedRelease | None = None

    for repo in repos:
        try:
            for release in repo.get_releases():
                published_at = _published_at(release)
                if published_at is None or published_at <= since:
                    continue
                if latest is not None and published_at <= latest.published_at:
                    continue
                if not _is_generated_release(release):
                    continue
                latest = GeneratedRelease(
                    repo_full_name=repo.full_name,
                    tag_name=release.tag_name,
                    published_at=published_at,
                )
        except GithubException as error:
            log.error(
                "failed to list releases while checking global gap",
                repo=getattr(repo, "full_name", None),
                error=str(error),
            )
            raise

    return latest


def release_creation_blocked_by_global_gap(
    repos: Iterable[Repository],
    *,
    now: datetime | None = None,
    gap: timedelta | None = None,
) -> bool:
    """Return whether an auto-generated release is still inside the global gap.

    A gap of zero disables the check. The clock is the newest published
    auto-generated release among ``repos``.
    """

    gap = get_global_min_release_gap() if gap is None else gap
    if gap.total_seconds() <= 0:
        return False

    now = _as_utc(now or datetime.now(UTC))
    latest = latest_generated_release_since(repos, now - gap)
    if latest is None:
        return False

    time_since = now - latest.published_at
    log.info(
        "skipping release check due to global minimum gap",
        last_release=latest.tag_name,
        last_release_repo=latest.repo_full_name,
        time_since_release_seconds=int(time_since.total_seconds()),
        min_gap_seconds=int(gap.total_seconds()),
    )
    return True


def should_stop_for_global_gap(
    gap: timedelta, max_releases: int, created_count: int
) -> bool:
    """Return whether this run should stop after creating an auto-generated release.

    A positive global gap allows one new auto-generated release per interval.
    ``max_releases`` still caps a run on its own when the global gap is disabled.
    """

    if gap.total_seconds() <= 0 or created_count < 1:
        return False
    # max_releases <= 0 means unlimited for the run; the global gap is the cap.
    if max_releases <= 0:
        return True
    return created_count < max_releases


class ReleaseAnalysis(BaseModel):
    """Structured output from LLM analysis of commits."""

    should_release: str = Field(description="yes, no, or maybe")
    confidence: int = Field(ge=0, le=100, description="Confidence level 0-100")
    reasoning: str = Field(description="Brief explanation in 1-2 sentences")
    suggested_version_bump: str = Field(description="major, minor, or patch")
    release_notes: str = Field(description="Full markdown changelog for the release")


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

    now = datetime.now(UTC)

    # Get the last release
    releases = list(repo.get_releases())

    if releases:
        last_release = releases[0]
        baseline_date = last_release.created_at
        baseline_tag = last_release.tag_name
        log.debug("found last release", tag=baseline_tag, date=baseline_date)

        min_gap = _get_min_release_gap()
        time_since_release = now - baseline_date
        if time_since_release < min_gap:
            log.info(
                "skipping release check due to minimum gap",
                last_release=baseline_tag,
                time_since_release_seconds=int(time_since_release.total_seconds()),
                min_gap_seconds=int(min_gap.total_seconds()),
            )
            return ReleaseDecision(
                should_create=False, suggested_version="", release_notes=""
            )
    else:
        # No releases yet, use repo creation date
        baseline_date = repo.created_at
        baseline_tag = None
        log.debug("no releases found, using repo creation date", date=baseline_date)

    # Get commits since baseline (limit to 50)
    try:
        all_commits = list(
            repo.get_commits(since=baseline_date, sha=repo.default_branch)
        )
    except GithubException as e:
        log.error(
            "failed to get commits",
            error=str(e),
            code=e.status if hasattr(e, "status") else None,
        )
        return ReleaseDecision(
            should_create=False, suggested_version="", release_notes=""
        )

    # limit number of commits to analyze
    commits = all_commits[:100]

    if not commits:
        log.info("no commits since last release", last_release=baseline_tag or "none")
        return ReleaseDecision(
            should_create=False, suggested_version="", release_notes=""
        )

    log.info("analyzing commits", count=len(commits), total_available=len(all_commits))

    # Format commits for LLM
    commit_summary = format_commits_for_llm(commits)

    # Calculate days since last release
    days_since_release = (now - baseline_date).days

    # Call LLM to analyze
    analysis = analyze_commits_with_llm(
        repo=repo,
        commit_summary=commit_summary,
        commit_count=len(commits),
        days_since_release=days_since_release,
        last_tag=baseline_tag,
    )

    if not analysis:
        log.error("llm analysis failed")
        return ReleaseDecision(
            should_create=False, suggested_version="", release_notes=""
        )

    should_release = analysis.should_release.lower() in ["yes", "maybe"]

    if should_release:
        suggested_version = calculate_next_version(
            baseline_tag, analysis.suggested_version_bump
        )
        release_notes = generate_release_notes(
            repo, baseline_tag, suggested_version, analysis
        )

        log.info(
            "llm recommends release",
            decision=analysis.should_release,
            confidence=analysis.confidence,
            version=suggested_version,
            bump=analysis.suggested_version_bump,
            reasoning=analysis.reasoning,
        )

        return ReleaseDecision(
            should_create=True,
            suggested_version=suggested_version,
            release_notes=release_notes,
        )

    log.info(
        "llm does not recommend release",
        decision=analysis.should_release,
        confidence=analysis.confidence,
        reasoning=analysis.reasoning,
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


def analyze_commits_with_llm(
    repo: Repository,
    commit_summary: str,
    commit_count: int,
    days_since_release: int,
    last_tag: str | None,
) -> ReleaseAnalysis | None:
    """Use LLM via Pydantic AI to analyze commits and determine if a release should be created."""

    if not is_ai_key_configured():
        expected_var = get_expected_ai_key_var()
        log.error(
            f"{expected_var} environment variable is not set; skipping llm analysis"
        )
        return None

    template = JINJA_ENV.get_template("release_analysis_prompt.j2")

    last_release_info = (
        f"Last release: {last_tag} ({days_since_release} days ago)"
        if last_tag
        else f"No previous releases (repo is {days_since_release} days old)"
    )

    prompt = template.render(
        repo_name=repo.full_name,
        last_release_info=last_release_info,
        commit_count=commit_count,
        commit_summary=commit_summary,
    )

    try:
        agent = get_agent(output_type=ReleaseAnalysis)
        result = agent.run_sync(prompt)
        return result.output

    except Exception as e:  # noqa: BLE001
        log.error("llm api call failed", error=str(e))
        return None


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


def generate_release_notes(
    repo: Repository,
    baseline_tag: str | None,
    new_tag: str,
    analysis: ReleaseAnalysis,
) -> str:
    """Generate release notes from LLM analysis and add changelog link."""

    # Get the markdown changelog from LLM
    llm_changelog = analysis.release_notes.strip()

    # Build the full release notes
    notes_parts = []

    if llm_changelog:
        notes_parts.append(llm_changelog)
        notes_parts.append("")  # Empty line before separator

    # Add horizontal line and Full Changelog link
    notes_parts.append("---")
    notes_parts.append("")

    if baseline_tag:
        # Compare from last tag to new tag
        changelog_url = (
            f"https://github.com/{repo.full_name}/compare/{baseline_tag}...{new_tag}"
        )
    else:
        # No previous release, link to all commits up to this tag
        changelog_url = f"https://github.com/{repo.full_name}/commits/{new_tag}"

    notes_parts.append(f"**Full Changelog**: {changelog_url}")
    notes_parts.append(GENERATED_BY_MARKER)

    return "\n".join(notes_parts)


def create_release(repo: Repository, tag: str, notes: str, dry_run: bool) -> bool:
    """Create a new GitHub release."""

    if dry_run:
        log.info(
            "would create release",
            dry_run=True,
            repo=repo.full_name,
            tag=tag,
            notes_preview=notes,
        )
        return True

    try:
        repo.create_git_release(
            tag=tag,
            name=tag,
            message=notes,
            draft=False,
            prerelease=False,
            target_commitish=repo.default_branch,
        )

        log.info("created release", repo=repo.full_name, tag=tag)
        return True

    except GithubException as e:
        log.error("failed to create release", repo=repo.full_name, error=str(e))
        return False


def check_repo_for_release(repo: Repository, dry_run: bool) -> dict:
    """
    Check a single repository and create a release if recommended.

    The cross-repo ``RELEASE_CHECKER_GLOBAL_MIN_GAP`` is enforced by the
    generate-releases command before this function is called.

    Returns:
        dict with keys: checked, skipped, created, failed
    """

    result = {"checked": False, "skipped": False, "created": False, "failed": False}

    # log.context is dynamic attribute monkey patched in utils.py
    with log.context(repo=repo.full_name):  # type: ignore
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
        except Exception:  # noqa: BLE001, S110
            pass  # If we can't determine size, continue anyway

        result["checked"] = True

        try:
            decision = should_create_release(repo)

            if decision.should_create:
                success = create_release(
                    repo, decision.suggested_version, decision.release_notes, dry_run
                )
                if success:
                    result["created"] = True
                else:
                    result["failed"] = True
            else:
                log.debug("no release needed")
        except GithubException as e:
            log.error(
                "github api error",
                error=str(e),
                status=e.status if hasattr(e, "status") else None,
            )
            result["failed"] = True
        except Exception as e:  # noqa: BLE001
            log.error(
                "unexpected error checking repository",
                error=str(e),
                error_type=type(e).__name__,
            )
            result["failed"] = True

    return result
