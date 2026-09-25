from django.db import migrations, models
import django.db.models.deletion
import uuid
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("proposal_app", "0016_one_current_curation_plan")]

    operations = [
        migrations.AddField(
            model_name="curationplan",
            name="config_fingerprint",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="decisionevent",
            name="review_seconds",
            field=models.PositiveIntegerField(null=True),
        ),
        migrations.CreateModel(
            name="ClassificationResult",
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
                ("fingerprint", models.CharField(max_length=64)),
                ("state", models.CharField(max_length=30)),
                ("predictions", models.JSONField(default=dict)),
                ("error", models.CharField(blank=True, max_length=100)),
                ("model_revision", models.CharField(max_length=100)),
                ("prompt_revision", models.CharField(max_length=100)),
                ("schema_revision", models.CharField(max_length=100)),
                ("policy_revision", models.CharField(max_length=100)),
                ("usage", models.JSONField(default=dict)),
                (
                    "extraction_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="proposal_app.extractionrun"
                    ),
                ),
                (
                    "family",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="proposal_app.versionfamily"
                    ),
                ),
                (
                    "job",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT, to="proposal_app.job"
                    ),
                ),
                (
                    "unit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="proposal_app.extractedunit"
                    ),
                ),
                (
                    "version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="proposal_app.sourceversion"
                    ),
                ),
            ],
        ),
    ]
