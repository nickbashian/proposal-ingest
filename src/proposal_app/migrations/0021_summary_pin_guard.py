"""Allow a mapped curated summary to be pinned without exposing its source units."""

import importlib

from django.db import migrations

previous = importlib.import_module("proposal_app.migrations.0018_curated_evidence_pin_guard")

SUMMARY_FACTUAL = f"""({previous.CURATED_FACTUAL} OR (
    a.kind = 'summary' AND EXISTS (
      SELECT 1 FROM proposal_app_curationplan cp
      JOIN LATERAL jsonb_array_elements(cp.derived_summaries) summary ON true
      JOIN proposal_app_decisionevent e ON e.id = a.decision_event_id
      JOIN proposal_app_decision d ON d.id = e.decision_id
      WHERE cp.family_id = d.family_id
        AND cp.version_id = u.version_id
        AND cp.extraction_run_id = u.extraction_run_id
        AND cp.state = 'current'
        AND cp.config_fingerprint <> ''
        AND summary->>'decision_event_id' = a.decision_event_id::text
        AND summary->'source_units' = a.source_unit_ids
        AND summary->'source_units' ? u.id::text
    )
  ))"""

if previous.REFERENCE_GUARD.count(previous.CURATED_FACTUAL) != 1:
    raise RuntimeError("0018 reference guard changed; summary guard cannot be applied")


class Migration(migrations.Migration):
    dependencies = [("proposal_app", "0020_publicationgeneration_deletion_job_id_and_more")]

    operations = [
        migrations.RunSQL(
            previous.REFERENCE_GUARD.replace(previous.CURATED_FACTUAL, SUMMARY_FACTUAL),
            reverse_sql=previous.REFERENCE_GUARD,
        )
    ]
