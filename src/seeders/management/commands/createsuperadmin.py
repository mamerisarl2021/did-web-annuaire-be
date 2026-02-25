"""
Create a platform superadmin.

Usage:
    python src/manage.py createsuperadmin

Interactive prompts for email, full_name, and password.
Sets is_active=True, is_staff=True, is_superadmin=True so the user
can log into both Django admin and the API immediately.
"""

import getpass

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from src.apps.users.models import User


class Command(BaseCommand):
    help = "Create a platform superadmin user."

    def add_arguments(self, parser):
        parser.add_argument("--email", type=str, help="Superadmin email")
        parser.add_argument("--full-name", type=str, help="Full name")
        parser.add_argument("--password", type=str, help="Password (prompted if omitted)")
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Use --email, --full-name, and --password without prompts.",
        )

    def handle(self, *args, **options):
        email = options.get("email")
        full_name = options.get("full_name")
        password = options.get("password")
        no_input = options.get("no_input", False)

        if not no_input:
            if not email:
                email = input("Email: ").strip()
            if not full_name:
                full_name = input("Full name: ").strip()
            if not password:
                password = getpass.getpass("Password: ")
                password2 = getpass.getpass("Password (again): ")
                if password != password2:
                    raise CommandError("Passwords do not match.")

        if not email:
            raise CommandError("Email is required.")
        if not full_name:
            raise CommandError("Full name is required.")
        if not password:
            raise CommandError("Password is required.")

        try:
            user = User.objects.create_superuser(
                email=email,
                password=password,
                full_name=full_name,
            )
        except IntegrityError:
            raise CommandError(f"A user with email '{email}' already exists.")

        self.stdout.write(
            self.style.SUCCESS(
                f"Superadmin created: {user.email} (id={user.id})"
            )
        )