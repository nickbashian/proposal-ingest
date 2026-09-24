import django.db.models.deletion
import django.utils.timezone
import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("proposal_app", "0013_classificationfact_entity_key")]

    operations = [
        migrations.CreateModel(
            name="EvaluationCall",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now, editable=False),
                ),
                ("route", models.CharField(max_length=30)),
                ("case", models.CharField(max_length=200)),
                ("state", models.CharField(default="reserved", max_length=30)),
                ("reserved_usd", models.DecimalField(decimal_places=6, max_digits=12)),
                ("model_revision", models.CharField(blank=True, max_length=100)),
                ("error", models.CharField(blank=True, max_length=100)),
                ("input_tokens", models.PositiveIntegerField(default=0)),
                ("output_tokens", models.PositiveIntegerField(default=0)),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="proposal_app.evaluationrun"
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("run", "route", "case"), name="evaluation_call_identity"
                    )
                ]
            },
        ),
    ]
