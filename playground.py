#!/usr/bin/env ipython -i

import os
from github import Github

token = os.getenv("GITHUB_TOKEN")
g = Github(token)

example_pr = "https://github.com/iloveitaly/funcy-pipe/pull/13"
pr = g.get_repo("iloveitaly/funcy-pipe").get_pull(13)
"https://api.github.com/repos/iloveitaly/asdf-devcontainer/pulls/13"
