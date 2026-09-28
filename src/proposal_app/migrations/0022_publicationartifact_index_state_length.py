from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("proposal_app", "0021_summary_pin_guard")]

    operations = [
        migrations.AlterField(
            model_name="publicationartifact",
            name="index_state",
            field=models.CharField(default="pending", max_length=40),
        )
    ]
