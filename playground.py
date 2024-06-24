#!/usr/bin/env ipython -i

import os
import re

from github import Github

github_token = os.getenv("GITHUB_TOKEN")
github = Github(github_token)
user = github.get_user()


# seems terrible
def get_pr_from_url(url):
    # Extract the owner, repo, and PR number from the URL
    match = re.match(r"https://github.com/(.+)/(.+)/pull/(\d+)", url)
    if match is None:
        raise ValueError("Invalid URL")

    owner, repo, pr_number = match.groups()

    # Get the PR
    pr = github.get_repo(f"{owner}/{repo}").get_pull(int(pr_number))

    return pr


example_pr = "https://github.com/iloveitaly/funcy-pipe/pull/13"
stale_pr = "https://github.com/railwayapp/nixpacks/pull/1115"

# pr = g.get_repo("iloveitaly/funcy-pipe").get_pull(13)
pr = get_pr_from_url(stale_pr)
