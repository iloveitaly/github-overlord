import json

import funcy_pipe as fp
from github import Github
from github.IssueComment import IssueComment
from github.PullRequest import PullRequest
from github.Repository import Repository
from openai import OpenAI

from github_overlord.utils import log


def inspect_repo_for_stale_prs(dry_run: bool, login: str, repo: Repository):
    log.debug("inspecting repo for stale PRs", repo=repo.full_name)

    return (
        repo.get_pulls(state="open")
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

    if not is_stale:
        log.debug("comment does not indicate stale state", url=pr.html_url)
        return

    log.info(
        "comment indicates stale state, commenting", url=pr.html_url, comment=comment
    )

    if not dry_run:
        pr.create_issue_comment(comment)


def is_stale_comment(comment: IssueComment):
    """
    Check if the comment indicates that the PR will be automatically closed if there is no activity
    """

    prompt = """
A GitHub pull request comment will be included with the author name. Determine if this comment indicates that if there is no activity
(more commits, comments, etc) the pull request will be closed. If the comment indicates that the pull
request will be closed, respond with a JSON object like:

{
    "stale": "yes",
    "comment": "Friendly reminder on this pull request! Let me know what else may need to be done here."
}

Adjust the comment wording slightly.

If the comment does not indicate that the pull request will be closed, respond with:

{
    "stale": "no",
}

Do not:

* Ask for an update. This sound demanding.
* Mention that the pull request will be closed.
"""
    comment_markdown = """
Author: {comment.user.login}

{comment.body}
"""
    client = OpenAI()

    response = client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": prompt,
            },
            {
                "role": "user",
                "content": comment_markdown,
            },
        ],
        model="gpt-3.5-turbo",
        response_format={"type": "json_object"},
    )

    # TODO got to be a helper for this instead
    message = response.choices[0].message
    response_dict = json.loads(message.content)

    return (response_dict["stale"] == "yes", response_dict.get("comment"))
