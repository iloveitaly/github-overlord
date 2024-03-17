import os
import logging
from github import Github

# Configure logging
logging.basicConfig(level=logging.INFO)

def merge_pr(pr):
    pr.create_issue_comment("This PR was automatically merged with dependabot-overlord")
    pr.merge(merge_method='squash')
    logging.info(f"Merged PR: {pr.html_url}")

def is_eligible_for_merge(pr_title):
    return 'patch' in pr_title.lower() or 'github actions' in pr_title.lower()

def main():
    token = os.getenv('GITHUB_TOKEN')
    g = Github(token)

    for repo in g.get_user().get_repos(type='public'):
        logging.info(f"Checking repository: {repo.full_name}")
        pulls = repo.get_pulls(state='open')
        for pr in pulls:
            if pr.user.login == "dependabot[bot]" and is_eligible_for_merge(pr.title):
                commit = pr.get_commits().reversed[0]
                status = commit.get_combined_status().state
                if status == 'success':
                    merge_pr(pr)
                else:
                    logging.info(f"Skipping PR (checks not successful): {pr.html_url}")
            else:
                logging.info(f"Skipping PR (not eligible): {pr.html_url}")

if __name__ == "__main__":
    main()
