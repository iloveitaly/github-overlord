import json

from github.IssueComment import IssueComment
from openai import OpenAI


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
