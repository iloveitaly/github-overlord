from github import Github
from github.GithubException import GithubException
from github.Issue import Issue
from github.IssueComment import IssueComment
from github.PullRequest import PullRequest
from pydantic import BaseModel, Field

from github_overlord.ai import get_agent
from github_overlord.utils import log


class StalePRsResult(BaseModel):
    inspected: int = 0
    kept_alive: int = 0
    skipped: int = 0
    failed: int = 0

    def __init__(
        self,
        checked: int | None = None,
        commented: int | None = None,
        **data,
    ):
        if checked is not None and "inspected" not in data:
            data["inspected"] = checked
        if commented is not None and "kept_alive" not in data:
            data["kept_alive"] = commented
        super().__init__(**data)

    @property
    def checked(self) -> int:
        return self.inspected

    @property
    def commented(self) -> int:
        return self.kept_alive


def inspect_stale_prs(
    github: Github,
    login: str,
    dry_run: bool,
    repo: str | None = None,
) -> StalePRsResult:
    if repo:
        query = f"is:pr is:open author:{login} repo:{repo} draft:false"
        log.info("searching for stale PRs in repo", repo=repo)
    else:
        query = f"is:pr is:open author:{login} -user:{login} draft:false"
        log.info("searching for open external PRs", author=login)

    try:
        issues = list(github.search_issues(query))
    except GithubException as e:
        log.error(
            "failed to search for pull requests",
            error=str(e),
            status=e.status if hasattr(e, "status") else None,
        )
        return StalePRsResult(failed=1)

    log.info("found open PRs to inspect", count=len(issues))

    inspected = 0
    kept_alive = 0
    skipped = 0
    failed = 0

    for issue in issues:
        inspected += 1
        result = check_for_stale_comments(dry_run, issue, login=login)
        if result is True:
            kept_alive += 1
        elif result is False:
            skipped += 1
        else:
            failed += 1

    return StalePRsResult(
        inspected=inspected,
        kept_alive=kept_alive,
        skipped=skipped,
        failed=failed,
    )


def check_for_stale_comments(
    dry_run: bool,
    pr: Issue | PullRequest,
    login: str | None = None,
) -> bool | None:
    """
    Look at PRs which you have written:

    1. There are bots out there which will close the PR if there are is no activity, even if there is no activity from
       the maintainer. This will keep the PR open by adding a comment.
    2. PRs that are not merged, been open for at least 30 days, with no comments from the maintainer.

    """

    log.debug("checking for stale comments", url=pr.html_url)

    try:
        issue: Issue = pr.as_issue() if isinstance(pr, PullRequest) else pr
    except GithubException as e:
        log.warning(
            "failed to get issue for PR",
            url=pr.html_url,
            error=str(e),
            status=e.status if hasattr(e, "status") else None,
        )
        return None

    if getattr(issue, "comments", None) == 0:
        log.debug("PR has no comments", url=pr.html_url)
        return False

    try:
        comments = list(issue.get_comments())
    except GithubException as e:
        log.warning(
            "failed to fetch comments for PR",
            url=pr.html_url,
            error=str(e),
            status=e.status if hasattr(e, "status") else None,
        )
        return None

    if len(comments) == 0:
        return False

    if not login:
        user_obj = getattr(pr, "user", None)
        login = getattr(user_obj, "login", None)

    pr_title = getattr(pr, "title", None) or getattr(issue, "title", None)

    # Walk backwards through comments
    for comment in reversed(comments):
        author = getattr(getattr(comment, "user", None), "login", None)

        if login and author == login:
            log.debug("already replied to PR after bot comment", url=pr.html_url)
            return False

        # TODO this will need to be changed
        if author == "github-actions[bot]":
            is_stale, comment_text = is_stale_comment(comment, pr_title=pr_title)

            if not is_stale or not comment_text:
                log.debug("comment does not indicate stale state", url=pr.html_url)
                return False

            if dry_run:
                log.info(
                    "comment indicates stale state, would comment",
                    url=pr.html_url,
                    comment=comment_text,
                )
                return True

            log.info(
                "comment indicates stale state, commenting",
                url=pr.html_url,
                comment=comment_text,
            )
            try:
                issue.create_comment(comment_text)
            except GithubException as e:
                log.error(
                    "failed to create comment on stale PR",
                    url=pr.html_url,
                    error=str(e),
                    status=e.status if hasattr(e, "status") else None,
                )
                return None

            return True

    return False


class StaleCommentDecision(BaseModel):
    stale: bool = Field(
        description="Whether this comment indicates that the pull request will be closed if there is no activity"
    )
    comment: str | None = Field(
        default=None,
        description=(
            "Friendly reminder comment to keep the PR open, adjusting wording slightly. "
            "Do not ask for an update or mention that the pull request will be closed. "
            "Only populated if stale is true."
        ),
    )


def is_stale_comment(
    comment: IssueComment, pr_title: str | None = None
) -> tuple[bool, str | None]:
    """
    Check if the comment indicates that the PR will be automatically closed if there is no activity
    """

    prompt = """A GitHub pull request comment will be included with the author name and the pull request title. Determine if this comment indicates that if there is no activity (more commits, comments, etc) the pull request will be closed.

If the comment indicates that the pull request will be closed:
- Set stale to True.
- Set comment to a friendly reminder, adjusting the wording slightly and keeping it naturally relevant to the pull request.
- Keep the comment concise and polite.

If the comment does not indicate that the pull request will be closed:
- Set stale to False.
- Set comment to None.

Do not:
* Ask for an update. This sounds demanding.
* Mention that the pull request will be closed.
"""
    title_line = f"Pull Request Title: {pr_title}\n\n" if pr_title else ""
    comment_markdown = f"""{title_line}Author: {comment.user.login}

{comment.body}
"""

    try:
        agent = get_agent(output_type=StaleCommentDecision, system_prompt=prompt)
        result = agent.run_sync(comment_markdown)
        output: StaleCommentDecision = result.output
        return (output.stale, output.comment)
    except Exception as e:  # noqa: BLE001
        log.error("llm api call failed for stale comment check", error=str(e))
        return (False, None)
