from celery import shared_task

from apps.notifications.services import schedule


@shared_task(name="notifications.send_round_reminders", ignore_result=True)
def send_round_reminders() -> None:
    schedule.send_round_reminders()


@shared_task(name="notifications.process_reminder_requests", ignore_result=True)
def process_reminder_requests() -> None:
    schedule.process_reminder_requests()


@shared_task(name="notifications.announce_results", ignore_result=True)
def announce_results() -> None:
    schedule.announce_results()
