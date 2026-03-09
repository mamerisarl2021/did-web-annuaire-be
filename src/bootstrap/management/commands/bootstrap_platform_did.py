"""
Management command: bootstrap_platform_did

Creates the platform's own DID document at:
  did:web:<PLATFORM_DOMAIN>

This DID is used as the "issuer" in Verifiable Credentials issued
by the platform when DID documents are published.

The document is written to:
  /app/data/dids/.well-known/did.json

Which nginx serves at:
  GET /.well-known/did.json

Configuration via Django settings:
  PLATFORM_DOMAIN       — e.g., "annuairedid-be.qcdigitalhub.com"
  PLATFORM_DID_KEY_TYPE — optional, default "Ed25519" (for the platform signing key)

Usage:
  python manage.py bootstrap_platform_did
  python manage.py bootstrap_platform_did --force  # overwrite existing
"""

import datetime
import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create the platform root DID document (did:web:<domain>)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite the existing platform DID document.",
        )
        parser.add_argument(
            "--dids-path",
            type=str,
            default="/app/data/dids",
            help="Base path for DID document storage (default: /app/data/dids).",
        )

    def handle(self, *args, **options):
        domain = getattr(settings, "PLATFORM_DOMAIN", "")
        if not domain:
            raise CommandError(
                "PLATFORM_DOMAIN is not set in Django settings. "
                "Cannot create platform DID."
            )

        dids_path = options["dids_path"]
        force = options["force"]

        # Platform root DID: did:web:<domain>
        # Resolves to: GET /.well-known/did.json
        # File path: <dids_path>/.well-known/did.json
        encoded_domain = domain.replace(":", "%3A")
        did_uri = f"did:web:{encoded_domain}"

        output_dir = os.path.join(dids_path, ".well-known")
        output_file = os.path.join(output_dir, "did.json")

        if os.path.exists(output_file) and not force:
            self.stdout.write(
                self.style.WARNING(
                    f"Platform DID document already exists at {output_file}. "
                    f"Use --force to overwrite."
                )
            )
            # Print the current document
            with open(output_file, "r") as f:
                self.stdout.write(f.read())
            return

        # Build the platform DID document
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        did_document = {
            "@context": [
                "https://www.w3.org/ns/did/v1",
                "https://w3id.org/security/suites/jws-2020/v1",
            ],
            "id": did_uri,
            "controller": did_uri,
            "verificationMethod": [],
            "authentication": [],
            "assertionMethod": [],
            "service": [
                {
                    "id": f"{did_uri}#directory",
                    "type": "DIDDirectory",
                    "serviceEndpoint": f"https://{domain}",
                    "description": "AnnuaireDID — DID Web Directory Service",
                },
                {
                    "id": f"{did_uri}#resolver",
                    "type": "DIDResolver",
                    "serviceEndpoint": f"https://{domain}/resolver/1.0/identifiers/",
                    "description": "Universal Resolver endpoint",
                },
                {
                    "id": f"{did_uri}#registrar",
                    "type": "DIDRegistrar",
                    "serviceEndpoint": f"https://{domain}/registrar/1.0/",
                    "description": "Universal Registrar endpoint (authorized use only)",
                },
            ],
            "created": now,
            "updated": now,
        }

        # Write to disk
        os.makedirs(output_dir, exist_ok=True)

        with open(output_file, "w") as f:
            json.dump(did_document, f, indent=2)

        self.stdout.write(
            self.style.SUCCESS(
                f"Platform DID document created:\n"
                f"  DID URI:  {did_uri}\n"
                f"  File:     {output_file}\n"
                f"  Resolves: https://{domain}/.well-known/did.json\n"
            )
        )

        # Print the document
        self.stdout.write(json.dumps(did_document, indent=2))

        self.stdout.write(
            self.style.NOTICE(
                "\nNote: The platform DID currently has no verificationMethod.\n"
                "To add a platform signing key:\n"
                "  1. Generate or import a key pair\n"
                "  2. Add the public key JWK to the verificationMethod array\n"
                "  3. Reference it in authentication and assertionMethod\n"
                "  4. Re-run this command with --force\n"
                "For now, VCs issued by this platform reference the DID URI\n"
                "as issuer without a cryptographic proof.\n"
            )
        )