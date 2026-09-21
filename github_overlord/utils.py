"""
This file should be imported first in any application entrypoint.
"""

import logging
import re
import typing as t
from pathlib import Path

import structlog
from decouple import config
from github.GithubException import GithubException

root: Path

# must type manually, unfortunately :/
# https://www.structlog.org/en/21.3.0/types.html
log: structlog.stdlib.BoundLogger = structlog.get_logger()


def configure_logger():
    # context manager to auto-clear context
    log.context = structlog.contextvars.bound_contextvars  # type: ignore
    # set thread-local context
    log.local = structlog.contextvars.bind_contextvars  # type: ignore
    # clear thread-local context
    log.clear = structlog.contextvars.clear_contextvars  # type: ignore

    logger_factory = structlog.PrintLoggerFactory()

    # allow user to specify a log in case they want to do something meaningful with the stdout
    if python_log_path := config("PYTHON_LOG_PATH", default=None):
        python_log = open(  # noqa: SIM115
            python_log_path, "a", encoding="utf-8"
        )  # pylint: disable=consider-using-with
        logger_factory = structlog.PrintLoggerFactory(file=python_log)

    log_level = t.cast(str, config("LOG_LEVEL", default="INFO", cast=str))
    level = getattr(logging, log_level.upper())

    # TODO logging.root.manager.loggerDict
    # we need this option to be set for other non-structlog loggers
    logging.basicConfig(level=level)

    # TODO look into further customized format
    # https://cs.github.com/GeoscienceAustralia/digitalearthau/blob/4cf486eb2a93d7de23f86ce6de0c3af549fe42a9/digitalearthau/uiutil.py#L45

    structlog.configure(
        context_class=dict,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=logger_factory,
        cache_logger_on_first_use=True,
    )


def setup():
    if hasattr(setup, "complete") and setup.complete:  # type: ignore # function attribute caching
        return

    global root, log

    root = Path(__file__).parent.parent

    log = structlog.get_logger()
    configure_logger()

    log.debug("application setup")

    # local state in a method is strange, but it works :/
    setup.complete = True  # type: ignore # function attribute caching


def extract_repo_reference_from_github_url(url: str | None) -> str | None:
    if url is None:
        return None

    if "github.com" not in url:
        return url

    match = re.search(r"github\.com/([^/]+)/([^/]+)", url)
    if match is None:
        return url

    return f"{match.group(1)}/{match.group(2)}"


_TOKEN_LIFETIME_FORBIDDEN = "forbids access via a fine-grained personal access token"


def github_error_message(error: GithubException) -> str:
    data = error.data
    if isinstance(data, dict):
        message = data.get("message")
        if isinstance(message, str) and message:
            return message

    if error.message:
        return error.message

    return str(error)


def is_fine_grained_token_lifetime_forbidden(error: BaseException) -> bool:
    """GitHub orgs can reject fine-grained tokens whose lifetime is over 366 days."""

    if not isinstance(error, GithubException) or error.status != 403:
        return False

    return _TOKEN_LIFETIME_FORBIDDEN in github_error_message(error).lower()


def log_token_policy_skip(
    error: GithubException,
    url: str | None = None,
    repo: str | None = None,
    command: str | None = None,
) -> bool:
    """Log the org token-lifetime 403 and report that the caller should continue."""

    if not is_fine_grained_token_lifetime_forbidden(error):
        return False

    context = {
        key: value
        for key, value in {"url": url, "repo": repo, "command": command}.items()
        if value is not None
    }

    log.error(
        "skipping github resource forbidden by token policy",
        error=github_error_message(error),
        status=error.status,
        **context,
    )
    return True


# side effects are bad, but it's fun to do bad things
setup()
