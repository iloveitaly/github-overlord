"""Monkey patches to third party libraries to ensure correct behavior and performance."""

import functools
import hashlib
import inspect

from github.Notification import Notification
from github.PullRequest import PullRequest


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

# Note on functools.lru_cache with PyGithub methods:
# Normally, using functools.lru_cache on instance methods causes memory leaks and fails
# across different instances because standard Python objects hash by id(self).
# However, PyGithub objects inherit from CompletableGithubObject, which implements __hash__
# and __eq__ based on the REST API URL (self._url.value).
# Consequently, functools.lru_cache(maxsize=1024) safely deduplicates calls across different
# instances representing the same GitHub resource while bounding memory consumption.

# Verify PyGithub's get_pull_request implementation has not changed before memoizing
assert (
    hash_function_code(Notification.get_pull_request)
    == "da4147db60ce0743f0e7dea20ababffe9b6408a7806b2b97ff895c73c4e36f80"
)
Notification.get_pull_request = functools.lru_cache(maxsize=1024)(
    Notification.get_pull_request
)  # type: ignore[assignment]

# Verify PyGithub's get_reviews implementation has not changed before memoizing
assert (
    hash_function_code(PullRequest.get_reviews)
    == "341cb10e8bcf74800aa0f125ee14b6a7de501c1d3e1813e9b150cdc8fcee60b1"
)
PullRequest.get_reviews = functools.lru_cache(maxsize=1024)(PullRequest.get_reviews)  # type: ignore[assignment]

# Verify PyGithub's as_issue implementation has not changed before memoizing
assert (
    hash_function_code(PullRequest.as_issue)
    == "59f1e51010a5f009af813b88787f03e54e4cec225244c4f46438d3a1e4fbd704"
)
PullRequest.as_issue = functools.lru_cache(maxsize=1024)(PullRequest.as_issue)  # type: ignore[assignment]


def clear_cache() -> None:
    """Clear all monkey-patch caches."""
    Notification.get_pull_request.cache_clear()  # type: ignore[attr-defined]
    PullRequest.get_reviews.cache_clear()  # type: ignore[attr-defined]
    PullRequest.as_issue.cache_clear()  # type: ignore[attr-defined]
