from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("emails", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="email",
            name="last_error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="email",
            name="metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="email",
            name="task_name",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
    ]
