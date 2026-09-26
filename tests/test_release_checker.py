"""Tests for release gap enforcement."""

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from github import GithubException

from github_overlord import generate_releases
from github_overlord.release_checker import (
    GENERATED_BY_MARKER,
    get_global_min_release_gap,
    latest_generated_release_since,
    release_creation_blocked_by_global_gap,
    should_stop_for_global_gap,
)

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
WEEK = timedelta(weeks=1)
CREATED = {"checked": True, "skipped": False, "created": True, "failed": False}
NOT_CREATED = {"checked": True, "skipped": False, "created": False, "failed": False}


def _release(
    tag: str, published_at: datetime, body: str, created_at: datetime | None = None
):
    release = MagicMock()
    release.tag_name = tag
    release.published_at = published_at
    release.created_at = created_at or published_at
    release.body = body
    return release


def _repo(name: str, releases: list) -> MagicMock:
    repo = MagicMock()
    repo.full_name = name
    repo.get_releases.return_value = releases
    return repo


def _generated(tag: str, published_at: datetime, created_at: datetime | None = None):
    return _release(tag, published_at, f"notes\n{GENERATED_BY_MARKER}\n", created_at)


def test_global_min_gap_configuration():
    with patch.dict(os.environ, {"RELEASE_CHECKER_GLOBAL_MIN_GAP": "3d"}):
        assert get_global_min_release_gap() == timedelta(days=3)

    with patch.dict(os.environ, {"RELEASE_CHECKER_GLOBAL_MIN_GAP": "0"}):
        assert get_global_min_release_gap() == timedelta(0)

    with patch.dict(os.environ, {"RELEASE_CHECKER_GLOBAL_MIN_GAP": "nope"}):
        assert get_global_min_release_gap() == WEEK

    env = {
        key: value
        for key, value in os.environ.items()
        if key != "RELEASE_CHECKER_GLOBAL_MIN_GAP"
    }
    with patch.dict(os.environ, env, clear=True):
        assert get_global_min_release_gap() == WEEK


def test_latest_generated_release_uses_publish_time_not_commit_time():
    """A freshly published release of an old commit blocks; an old publish does not."""

    old_commit_published_now = _repo(
        "owner/old-commit",
        [
            _release(
                "v2.0.0",
                published_at=NOW - timedelta(hours=1),
                body="shipped by hand",
                created_at=NOW - timedelta(hours=1),
            ),
            _generated(
                "v1.0.0",
                published_at=NOW - timedelta(hours=2),
                created_at=NOW - timedelta(days=400),
            ),
        ],
    )
    recent_commit_published_long_ago = _repo(
        "owner/old-publish",
        [
            _generated(
                "v9.0.0",
                published_at=NOW - timedelta(days=30),
                created_at=NOW - timedelta(minutes=5),
            )
        ],
    )

    latest = latest_generated_release_since(
        [recent_commit_published_long_ago, old_commit_published_now],
        since=NOW - WEEK,
    )

    assert latest is not None
    assert latest.repo_full_name == "owner/old-commit"
    assert latest.tag_name == "v1.0.0"
    assert release_creation_blocked_by_global_gap(
        [recent_commit_published_long_ago, old_commit_published_now],
        now=NOW,
        gap=WEEK,
    )


def test_release_published_exactly_at_the_gap_boundary_does_not_block():
    repo = _repo("owner/repo", [_generated("v1.0.0", NOW - WEEK)])

    assert latest_generated_release_since([repo], since=NOW - WEEK) is None
    assert not release_creation_blocked_by_global_gap([repo], now=NOW, gap=WEEK)


def test_zero_global_gap_does_not_read_releases():
    repo = _repo("owner/repo", [_generated("v1.0.0", NOW)])
    repo.get_releases.side_effect = AssertionError("should not list releases")

    assert not release_creation_blocked_by_global_gap([repo], now=NOW, gap=timedelta(0))


def test_should_stop_for_global_gap_allows_one_release_per_interval():
    assert should_stop_for_global_gap(WEEK, max_releases=5, created_count=1)
    assert should_stop_for_global_gap(WEEK, max_releases=0, created_count=1)
    assert not should_stop_for_global_gap(WEEK, max_releases=1, created_count=1)
    assert not should_stop_for_global_gap(timedelta(0), max_releases=5, created_count=1)
    assert not should_stop_for_global_gap(WEEK, max_releases=5, created_count=0)


def _run_generate_releases(repos, *, topic, repo, max_releases, gap, check_result):
    with (
        patch.dict(
            os.environ,
            {
                "GITHUB_TOKEN": "test-token",
                "GITHUB_OVERLORD_AI_KEY": "test-key",
                "RELEASE_CHECKER_GLOBAL_MIN_GAP": gap,
            },
        ),
        patch("github_overlord.Github") as github_cls,
        patch(
            "github_overlord.check_repo_for_release", side_effect=check_result
        ) as check,
    ):
        github = github_cls.return_value
        github.get_repo.return_value = repos[0]
        github.get_user.return_value.login = "tester"
        github.search_repositories.return_value = repos
        generate_releases.callback(False, topic, repo, max_releases)
        return check


def test_generate_releases_skips_work_when_a_generated_release_is_inside_the_gap():
    repos = [
        _repo("owner/quiet", []),
        _repo(
            "owner/recent",
            [_generated("v1.2.3", datetime.now(UTC) - timedelta(hours=1))],
        ),
    ]

    check = _run_generate_releases(
        repos,
        topic="auto-release",
        repo=None,
        max_releases=5,
        gap="1w",
        check_result=lambda *args, **kwargs: CREATED,
    )

    check.assert_not_called()


def test_generate_releases_stops_after_one_create_while_global_gap_is_active():
    repos = [_repo("owner/a", []), _repo("owner/b", []), _repo("owner/c", [])]
    results = iter([NOT_CREATED, CREATED, CREATED])

    check = _run_generate_releases(
        repos,
        topic="auto-release",
        repo=None,
        max_releases=5,
        gap="1w",
        check_result=lambda *args, **kwargs: next(results),
    )

    assert check.call_count == 2
    assert check.call_args_list[0].args[0].full_name == "owner/a"
    assert check.call_args_list[1].args[0].full_name == "owner/b"


def test_generate_releases_keeps_max_releases_when_global_gap_is_disabled():
    repos = [_repo("owner/a", []), _repo("owner/b", []), _repo("owner/c", [])]

    check = _run_generate_releases(
        repos,
        topic="auto-release",
        repo=None,
        max_releases=1,
        gap="0",
        check_result=lambda *args, **kwargs: CREATED,
    )

    assert check.call_count == 1
    repos[0].get_releases.assert_not_called()


def test_generate_releases_single_repo_respects_global_gap():
    recent = _repo(
        "owner/repo",
        [_generated("v1.2.3", datetime.now(UTC) - timedelta(hours=1))],
    )
    blocked = _run_generate_releases(
        [recent],
        topic=None,
        repo="owner/repo",
        max_releases=1,
        gap="1w",
        check_result=lambda *args, **kwargs: CREATED,
    )
    blocked.assert_not_called()

    quiet = _repo("owner/repo", [])
    allowed = _run_generate_releases(
        [quiet],
        topic=None,
        repo="owner/repo",
        max_releases=1,
        gap="1w",
        check_result=lambda *args, **kwargs: NOT_CREATED,
    )
    allowed.assert_called_once()


def test_generate_releases_fails_closed_when_release_history_cannot_be_read():
    repo = _repo("owner/repo", [])
    repo.get_releases.side_effect = GithubException(
        502, {"message": "unavailable"}, None
    )

    check = _run_generate_releases(
        [repo],
        topic=None,
        repo="owner/repo",
        max_releases=1,
        gap="1w",
        check_result=lambda *args, **kwargs: CREATED,
    )

    check.assert_not_called()
