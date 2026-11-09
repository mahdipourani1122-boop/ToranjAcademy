from django.core.management.base import BaseCommand
from dashboards.attendance_service import finalize_expired_sessions


class Command(BaseCommand):
    help = 'Finalize expired attendance sessions automatically'

    def handle(self, *args, **options):
        count = finalize_expired_sessions()
        self.stdout.write(self.style.SUCCESS(f'Finalized {count} expired attendance session(s).'))
