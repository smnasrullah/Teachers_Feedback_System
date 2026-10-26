from django.core.management.base import BaseCommand

from apps.notifications.services import schedule


class Command(BaseCommand):
    help = (
        "Run the scheduled notification jobs once: round reminders, queued head-of-department "
        "reminders and result notices. Celery beat runs them on a timer; this is for hand runs "
        "and cron."
    )

    def handle(self, *args, **options):
        counts = {
            "round reminders": schedule.send_round_reminders(),
            "queued reminders": schedule.process_reminder_requests(),
            "result notices": schedule.announce_results(),
        }
        for label, count in counts.items():
            self.stdout.write(f"{label}: {count}")
