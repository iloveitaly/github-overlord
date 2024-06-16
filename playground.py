#!/usr/bin/env ipython -i

import os
import re

from github import Github

token = os.getenv("GITHUB_TOKEN")
g = Github(token)


# seems terrible
def get_pr_from_url(github, url):
    # Extract the owner, repo, and PR number from the URL
    match = re.match(r"https://github.com/(.+)/(.+)/pull/(\d+)", url)
    if match is None:
        raise ValueError("Invalid URL")

    owner, repo, pr_number = match.groups()

    # Get the PR
    pr = github.get_repo(f"{owner}/{repo}").get_pull(int(pr_number))

    return pr


example_pr = "https://github.com/iloveitaly/funcy-pipe/pull/13"
pr = g.get_repo("iloveitaly/funcy-pipe").get_pull(13)

"https://api.github.com/repos/iloveitaly/asdf-devcontainer/pulls/13"
example_pr = "https://github.com/iloveitaly/todoist-scheduler/pull/92"
pr = get_pr_from_url(g, example_pr)
