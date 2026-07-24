import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0004_alter_membership_has_audit_access_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="membership",
            name="invitation_expires_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Date d'expiration du lien d'activation ou d'invitation.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="membership",
            name="invitation_token",
            field=models.UUIDField(
                blank=True,
                db_index=True,
                default=uuid.uuid4,
                null=True,
                unique=True,
            ),
        ),
    ]
