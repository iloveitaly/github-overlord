"""Monkey patches to third party libraries to ensure correct behavior and performance."""

import hashlib
import inspect

from github.Issue import Issue
from github.Notification import Notification
from github.PullRequest import PullRequest
from github.PullRequestReview import PullRequestReview

_PULL_REQUEST_CACHE: dict[str, PullRequest] = {}
_REVIEWS_CACHE: dict[str, list[PullRequestReview]] = {}
_ISSUE_CACHE: dict[str, Issue] = {}


def clear_cache() -> None:
    """Clear all monkey-patch caches."""
    _PULL_REQUEST_CACHE.clear()
    _REVIEWS_CACHE.clear()
    _ISSUE_CACHE.clear()


def hash_function_code(func) -> str:
    """Get SHA256 of a function's source code to easily assert that it hasn't changed."""
    source = inspect.getsource(func)
    return hashlib.sha256(source.encode()).hexdigest()


# Verify PyGithub's mark_as_done implementation has not changed
assert (
    hash_function_code(Notification.mark_as_done)
    == "afccbc5627a2d6d546403613e4a13e1c045da2f7fada6fefadcb146bfee27dfe"
)


def mark_as_done(self) -> None:
    """
    :calls: `PATCH /notifications/threads/{id} <https://docs.github.com/en/rest/activity/notifications?apiVersion=2022-11-28#mark-a-thread-as-done>`_
    """
    _headers, _data = self._requester.requestJsonAndCheck(
        "DELETE",
        self.url,
    )


Notification.mark_as_done = mark_as_done

# Verify PyGithub's get_pull_request implementation has not changed before memoizing
assert (
    hash_function_code(Notification.get_pull_request)
    == "da4147db60ce0743f0e7dea20ababffe9b6408a7806b2b97ff895c73c4e36f80"
)

_orig_get_pull_request = Notification.get_pull_request


def get_pull_request(self) -> PullRequest:
    """Memoize get_pull_request by subject URL to avoid redundant GitHub API calls.

    PyGithub's default implementation makes a fresh HTTP GET request each time
    get_pull_request() is called. Because notification cleanup executes multiple
    filter passes over the same notifications, caching by PR URL avoids
    redundant network round-trips and prevents rate limit exhaustion across instances.
    """
    url = getattr(getattr(self, "subject", None), "url", None)
    if url:
        if url not in _PULL_REQUEST_CACHE:
            _PULL_REQUEST_CACHE[url] = _orig_get_pull_request(self)
        return _PULL_REQUEST_CACHE[url]

    if not hasattr(self, "_cached_pull_request"):
        self._cached_pull_request = _orig_get_pull_request(self)
    return self._cached_pull_request


Notification.get_pull_request = get_pull_request  # type: ignore[assignment]

# Verify PyGithub's get_reviews implementation has not changed before memoizing
assert (
    hash_function_code(PullRequest.get_reviews)
    == "341cb10e8bcf74800aa0f125ee14b6a7de501c1d3e1813e9b150cdc8fcee60b1"
)

_orig_get_reviews = PullRequest.get_reviews


def get_reviews(self) -> list[PullRequestReview]:
    """Memoize get_reviews by PR URL to avoid redundant GitHub API calls.

    PyGithub's get_reviews() creates a new PaginatedList each time it is called,
    refetching all reviews from GitHub on every iteration. Caching the review list
    by PR URL prevents redundant API calls across filter passes and different instances.
    """
    url = getattr(self, "url", None)
    if url:
        if url not in _REVIEWS_CACHE:
            _REVIEWS_CACHE[url] = list(_orig_get_reviews(self))
        return _REVIEWS_CACHE[url]

    if not hasattr(self, "_cached_reviews"):
        self._cached_reviews = list(_orig_get_reviews(self))
    return self._cached_reviews


PullRequest.get_reviews = get_reviews  # type: ignore[assignment]

# Verify PyGithub's as_issue implementation has not changed before memoizing
assert (
    hash_function_code(PullRequest.as_issue)
    == "59f1e51010a5f009af813b88787f03e54e4cec225244c4f46438d3a1e4fbd704"
)

_orig_as_issue = PullRequest.as_issue


def as_issue(self) -> Issue:
    """Memoize as_issue by issue URL to avoid redundant GitHub API calls.

    PyGithub's as_issue() creates a new Issue instance on each call, requiring
    a separate HTTP GET request when accessing attributes like closed_by. Caching
    by issue URL avoids redundant Issue completions across filter passes.
    """
    url = getattr(self, "issue_url", None)
    if url:
        if url not in _ISSUE_CACHE:
            _ISSUE_CACHE[url] = _orig_as_issue(self)
        return _ISSUE_CACHE[url]

    if not hasattr(self, "_cached_issue"):
        self._cached_issue = _orig_as_issue(self)
    return self._cached_issue


PullRequest.as_issue = as_issue  # type: ignore[assignment]
