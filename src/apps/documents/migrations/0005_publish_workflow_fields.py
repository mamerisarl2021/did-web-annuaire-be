import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0004_diddocument_last_reminded_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="diddocument",
            name="publish_last_error",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Dernière erreur de publication externe (Registrar ou disque).",
            ),
        ),
        migrations.AddField(
            model_name="diddocument",
            name="pending_version",
            field=models.ForeignKey(
                blank=True,
                help_text="Version en cours de publication, non encore promue.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="documents.diddocumentversion",
            ),
        ),
        migrations.AlterField(
            model_name="diddocument",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "Draft"),
                    ("PENDING_REVIEW", "Pending Review"),
                    ("APPROVED", "Approved"),
                    ("REJECTED", "Rejected"),
                    ("SIGNED", "Signed"),
                    ("PUBLISHING", "Publishing"),
                    ("PUBLISH_FAILED", "Publish Failed"),
                    ("PUBLISHED", "Published"),
                    ("DEACTIVATED", "Deactivated"),
                ],
                default="DRAFT",
                max_length=20,
            ),
        ),
    ]
