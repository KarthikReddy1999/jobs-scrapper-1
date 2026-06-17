from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("jobright", "0002_jobrightscraperstate_worker_pid"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobrightjob",
            name="description",
            field=models.TextField(blank=True, default=""),
        ),
    ]
