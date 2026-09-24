from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("proposal_app", "0014_evaluationcall")]

    operations = [
        migrations.AddField(
            model_name="curationplan", name="pending_units", field=models.JSONField(default=list)
        ),
        migrations.AddField(
            model_name="curationplan",
            name="metadata_only_units",
            field=models.JSONField(default=list),
        ),
    ]
