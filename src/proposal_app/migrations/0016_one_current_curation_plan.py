from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("proposal_app", "0015_curationplan_unit_dispositions"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="curationplan",
            constraint=models.UniqueConstraint(
                fields=("family", "version"),
                condition=Q(state="current"),
                name="one_current_curation_plan",
            ),
        ),
    ]
