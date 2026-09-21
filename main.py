import os

from apscheduler.schedulers.background import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from github.GithubException import GithubException

from github_overlord import cli
from github_overlord.utils import (
    github_error_message,
    is_fine_grained_token_lifetime_forbidden,
    log,
)


def handle_click_exit(func):
    def wrapper(*args, **kwargs):
        try:
            func(*args, **kwargs)
        except SystemExit as e:
            if e.code != 0:
                raise

    return wrapper


def job():
    for command in list(cli.commands.values()):
        log.info("running command", command=command.name)
        try:
            handle_click_exit(command)()
        except GithubException as error:
            if not is_fine_grained_token_lifetime_forbidden(error):
                raise

            log.error(
                "command stopped by github token policy, continuing",
                command=command.name,
                error=github_error_message(error),
                status=error.status,
            )


def cron():
    schedule = os.environ.get("SCHEDULE", "0 6 * * *")
    print(f"Running on schedule: {schedule}")

    scheduler = BlockingScheduler()
    scheduler.add_job(job, CronTrigger.from_crontab(schedule))
    scheduler.start()


if __name__ == "__main__":
    cron()
