"""Delete email-pending users older than UNVERIFIED_SIGNUP_EXPIRE_HOURS (no HTTP session)."""
from django.core.management.base import BaseCommand

from apps.users.pending_cleanup import purge_expired_unverified_users


class Command(BaseCommand):
    help = 'Remove unverified inactive accounts past the configured expiry (cron-friendly).'

    def handle(self, *args, **options):
        n = purge_expired_unverified_users(request=None)
        self.stdout.write(self.style.SUCCESS(f'Removed {n} expired unverified signup(s).'))
