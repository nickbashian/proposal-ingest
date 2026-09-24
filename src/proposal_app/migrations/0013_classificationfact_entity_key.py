from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("proposal_app", "0012_curationplan_voice_units")]

    operations = [
        migrations.AddField(
            model_name="classificationfact",
            name="entity_key",
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
