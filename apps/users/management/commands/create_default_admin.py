"""
Create default admin user if no superuser exists.
Used at container startup (Docker/Render) so the system has a known admin.
Credentials: username=admin, email=admin@kyc.local, password from env DEFAULT_ADMIN_PASSWORD or 'admin123'.
"""
import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = 'Create default admin user (admin / admin@kyc.local) if no superuser exists.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--noinput', '--no-input',
            action='store_true',
            help='Use env DEFAULT_ADMIN_PASSWORD or default password; do not prompt.',
        )

    def handle(self, *args, **options):
        User = get_user_model()
        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write(self.style.SUCCESS('Superuser already exists; skipping.'))
            return
        username = os.environ.get('DEFAULT_ADMIN_USERNAME', 'admin')
        email = os.environ.get('DEFAULT_ADMIN_EMAIL', 'admin@kyc.local')
        password = os.environ.get('DEFAULT_ADMIN_PASSWORD', 'admin123')
        User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f'Default admin created: {username} / {email}'))
