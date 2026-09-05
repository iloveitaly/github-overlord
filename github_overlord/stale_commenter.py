import funcy_pipe as fp
from github.IssueComment import IssueComment
from github.PullRequest import PullRequest
from github.Repository import Repository
from pydantic import BaseModel, Field

from github_overlord.ai import get_agent, run_agent_sync
from github_overlord.utils import log


def inspect_repo_for_stale_prs(dry_run: bool, login: str, repo: Repository):
    log.debug("inspecting repo for stale PRs", repo=repo.full_name)

    return (
        # there is not a way to filter by the user which created the PR! This take a long time on repos with many PRs
        repo.get_pulls(state="open")
        # make sure the auth token user is the author of the PR
        | fp.filter(lambda pr: pr.user.login == login)
        | fp.map(fp.partial(check_for_stale_comments, dry_run))
        | fp.to_list()
    )


def check_for_stale_comments(dry_run: bool, pr: PullRequest):
    """
    Look at PRs which you have written:

    1. There are bots out there which will close the PR if there are is no activity, even if there is no activity from
       the maintainer. This will keep the PR open by adding a comment.
    2. PRs that are not merged, been open for at least 30 days, with no comments from the maintainer.

    """

    log.debug("checking for stale comments", url=pr.html_url)

    # PR comments are comments on the cod3
    issue = pr.as_issue()
    comments = list(issue.get_comments())

    if len(comments) == 0:
        return

    last_comment = comments[-1]

    # TODO this will need to be changed
    if last_comment.user.login != "github-actions[bot]":
        log.debug("Last comment is not from github-actions[bot]", url=pr.html_url)
        return

    is_stale, comment = is_stale_comment(last_comment)

    if not is_stale or not comment:
        log.debug("comment does not indicate stale state", url=pr.html_url)
        return

    log.info(
        "comment indicates stale state, commenting", url=pr.html_url, comment=comment
    )

    if not dry_run:
        pr.create_issue_comment(comment)


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


def is_stale_comment(comment: IssueComment) -> tuple[bool, str | None]:
    """
    Check if the comment indicates that the PR will be automatically closed if there is no activity
    """

    prompt = """A GitHub pull request comment will be included with the author name. Determine if this comment indicates that if there is no activity (more commits, comments, etc) the pull request will be closed.

If the comment indicates that the pull request will be closed:
- Set stale to True.
- Set comment to a friendly reminder (e.g. "Friendly reminder on this pull request! Let me know what else may need to be done here."), adjusting the wording slightly.

If the comment does not indicate that the pull request will be closed:
- Set stale to False.
- Set comment to None.

Do not:
* Ask for an update. This sounds demanding.
* Mention that the pull request will be closed.
"""
    comment_markdown = f"""Author: {comment.user.login}

{comment.body}
"""

    try:
        agent = get_agent(output_type=StaleCommentDecision, system_prompt=prompt)
        result = run_agent_sync(agent, comment_markdown)
        output: StaleCommentDecision = result.output
        return (output.stale, output.comment)
    except Exception as e:  # noqa: BLE001
        log.error("llm api call failed for stale comment check", error=str(e))
        return (False, None)
