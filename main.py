import os

from apscheduler.schedulers.background import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from github_overlord import cli


def handle_click_exit(func):
    def wrapper(*args, **kwargs):
        try:
            func(*args, **kwargs)
        except SystemExit as e:
            if e.code != 0:
                raise

    return wrapper


from github_overlord.utils import log


def job():
    for command in list(cli.commands.values()):
        log.info("running command", command=command.name)
        handle_click_exit(command)()


def cron():
    schedule = os.environ.get("SCHEDULE", "0 6 * * *")
    print(f"Running on schedule: {schedule}")

    scheduler = BlockingScheduler()
    scheduler.add_job(job, CronTrigger.from_crontab(schedule))
    scheduler.start()


if __name__ == "__main__":
    cron()
