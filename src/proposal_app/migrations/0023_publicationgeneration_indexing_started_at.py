"""Track each Managed KB ingestion attempt's reconciliation deadline."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("proposal_app", "0022_publicationartifact_index_state_length")]

    operations = [
        migrations.AddField(
            model_name="publicationgeneration",
            name="indexing_started_at",
            field=models.DateTimeField(null=True),
        ),
    ]
