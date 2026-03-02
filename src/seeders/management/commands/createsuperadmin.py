"""
Management command: createsuperadmin

Creates the platform superadmin user. Supports both interactive prompts
and environment variables for automated (Docker/CI) deployments.

Environment variables:
  SUPERADMIN_EMAIL     — required
  SUPERADMIN_PASSWORD  — required
  SUPERADMIN_FULL_NAME — optional (default: "Super Admin")

Usage:
  # Interactive
  python manage.py createsuperadmin

  # Automated (Docker entrypoint)
  SUPERADMIN_EMAIL=admin@example.com SUPERADMIN_PASSWORD=secret \
    python manage.py createsuperadmin --no-input
"""

import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from src.apps.users.models import User
from src.config.env import env


class Command(BaseCommand):
    help = "Create the platform superadmin user."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-input",
            action="store_true",
            dest="no_input",
            help="Read credentials from environment variables instead of prompts.",
        )
        parser.add_argument(
            "--email",
            type=str,
            help="Superadmin email (overrides env var).",
        )
        parser.add_argument(
            "--password",
            type=str,
            help="Superadmin password (overrides env var).",
        )
        parser.add_argument(
            "--full-name",
            type=str,
            help="Superadmin full name (overrides env var).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        no_input = options["no_input"]

        # Resolve credentials: CLI args > env vars > interactive prompts
        email = options.get("email") or getattr(env, "SUPERADMIN_EMAIL", "").strip()
        password = options.get("password") or getattr(env, "SUPERADMIN_PASSWORD", "").strip()
        full_name = options.get("full_name") or getattr(env, "SUPERADMIN_FULL_NAME", "").strip()

        if no_input:
            # Automated mode — require email and password from env or args
            if not email:
                raise CommandError(
                    "SUPERADMIN_EMAIL environment variable is required with --no-input."
                )
            if not password:
                raise CommandError(
                    "SUPERADMIN_PASSWORD environment variable is required with --no-input."
                )
            if not full_name:
                full_name = "Super Admin"
        else:
            # Interactive mode — prompt for missing values
            if not email:
                email = input("Email: ").strip()
            if not email:
                raise CommandError("Email is required.")

            if not full_name:
                full_name = input("Full name [Super Admin]: ").strip() or "Super Admin"

            if not password:
                import getpass
                password = getpass.getpass("Password: ")
                password_confirm = getpass.getpass("Confirm password: ")
                if password != password_confirm:
                    raise CommandError("Passwords do not match.")

            if not password:
                raise CommandError("Password is required.")

        # Normalize
        email = email.lower().strip()

        # Check for existing user
        existing = User.objects.filter(email=email).first()
        if existing:
            if existing.is_superadmin:
                self.stdout.write(
                    self.style.WARNING(f"Superadmin '{email}' already exists. Skipping.")
                )
                return

            # Promote existing user to superadmin
            existing.is_superadmin = True
            existing.is_active = True
            if not existing.account_activated_at:
                from django.utils import timezone
                existing.account_activated_at = timezone.now()
            existing.save(update_fields=[
                "is_superadmin", "is_active", "account_activated_at", "updated_at",
            ])
            self.stdout.write(
                self.style.SUCCESS(f"Existing user '{email}' promoted to superadmin.")
            )
            return

        # Create new superadmin
        user = User(
            email=email,
            full_name=full_name,
            is_superadmin=True,
            is_active=True,
            activation_method="manual",
        )
        user.set_password(password)

        from django.utils import timezone
        user.account_activated_at = timezone.now()
        user.save()

        self.stdout.write(
            self.style.SUCCESS(f"Superadmin '{email}' created successfully.")
        )