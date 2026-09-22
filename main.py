import os

from apscheduler.schedulers.background import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from github.GithubException import GithubException

from github_overlord import cli
from github_overlord.utils import log

_TOKEN_LIFETIME_FORBIDDEN = "forbids access via a fine-grained personal access token"


def handle_click_exit(func):
    def wrapper(*args, **kwargs):
        try:
            func(*args, **kwargs)
        except SystemExit as e:
            if e.code != 0:
                raise

    return wrapper


def _token_lifetime_forbidden_message(error: GithubException) -> str | None:
    if error.status != 403:
        return None

    data = error.data
    message = data.get("message") if isinstance(data, dict) else error.message
    if not isinstance(message, str):
        return None

    if _TOKEN_LIFETIME_FORBIDDEN not in message.lower():
        return None

    return message


def job():
    for command in list(cli.commands.values()):
        log.info("running command", command=command.name)
        try:
            handle_click_exit(command)()
        except GithubException as error:
            message = _token_lifetime_forbidden_message(error)
            if message is None:
                raise

            log.error(
                "command stopped by github token policy, continuing",
                command=command.name,
                error=message,
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
