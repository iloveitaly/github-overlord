import os
import logging
import click
from github import Github

# Configure logging
logging.basicConfig(level=logging.INFO)


def merge_pr(pr, dry_run):
    if dry_run:
        logging.info(f"Would merge PR: {pr.html_url}")
    else:
        pr.create_issue_comment(
            "This PR was automatically merged with dependabot-overlord"
        )
        pr.merge(merge_method="squash")
        logging.info(f"Merged PR: {pr.html_url}")


def is_eligible_for_merge(pr_title):
    return "patch" in pr_title.lower() or "github actions" in pr_title.lower()


def main(token, dry_run):
    g = Github(token)

    user = g.get_user()
    for repo in user.get_repos(type="public"):
        if repo.owner.login == user.login:
            logging.info(f"Checking repository: {repo.full_name}")
            pulls = repo.get_pulls(state="open")
            for pr in pulls:
                if pr.user.login == "dependabot[bot]" and is_eligible_for_merge(
                    pr.title
                ):
                    commit = pr.get_commits().reversed[0]
                    status = commit.get_combined_status().state
                    if status == "success":
                        merge_pr(pr, dry_run)
                    else:
                        logging.info(
                            f"Skipping PR (checks not successful): {pr.html_url}"
                        )
                else:
                    logging.info(f"Skipping PR (not eligible): {pr.html_url}")


@click.command()
@click.option("--dry-run", is_flag=True, help="Run script without making changes")
def cli(dry_run):
    token = os.getenv("GITHUB_TOKEN")
    main(token, dry_run)


if __name__ == "__main__":
    cli()
