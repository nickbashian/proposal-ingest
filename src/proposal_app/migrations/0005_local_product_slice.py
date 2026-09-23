import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import django.utils.timezone

REFERENCE_GUARD = """
CREATE OR REPLACE FUNCTION proposal_reference_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME = 'proposal_app_draftrevision' THEN
    IF NOT EXISTS (SELECT 1 FROM proposal_app_evidencepacket p
                   WHERE p.id = NEW.packet_id AND p.session_id = NEW.session_id) THEN
      RAISE EXCEPTION 'Packet and revision must belong to the same session' USING ERRCODE = '23514';
    END IF;
  ELSIF TG_TABLE_NAME = 'proposal_app_proposalmembership' THEN
    IF NOT EXISTS (SELECT 1 FROM proposal_app_sourceitem s
                   JOIN proposal_app_versionfamily f ON f.id = NEW.family_id
                   JOIN proposal_app_proposal p ON p.id = f.proposal_id
                   WHERE s.id = NEW.source_id AND s.collection_id = p.collection_id) THEN
      RAISE EXCEPTION 'Membership must remain in its collection' USING ERRCODE = '23514';
    END IF;
  ELSIF TG_TABLE_NAME = 'proposal_app_publicationartifact' THEN
    IF NOT EXISTS (SELECT 1 FROM proposal_app_publicationgeneration g
      JOIN proposal_app_decisionevent e ON e.id = NEW.decision_event_id
      JOIN proposal_app_decision d ON d.id = e.decision_id
      JOIN proposal_app_versionfamily f ON f.id = d.family_id
      JOIN proposal_app_extractedunit u ON u.id = NEW.unit_id
      JOIN proposal_app_sourceversion v ON v.id = u.version_id
      JOIN proposal_app_proposalmembership membership
        ON membership.source_id = v.source_id AND membership.family_id = f.id
      WHERE g.id = NEW.generation_id AND g.proposal_id = f.proposal_id) THEN
      RAISE EXCEPTION 'Artifact provenance must belong to its proposal' USING ERRCODE = '23514';
    END IF;
  ELSIF TG_TABLE_NAME = 'proposal_app_evidencepin' THEN
    IF NOT EXISTS (SELECT 1 FROM proposal_app_draftsession s
      JOIN proposal_app_publicationartifact a ON a.id = NEW.artifact_id
      JOIN proposal_app_publicationgeneration g ON g.id = a.generation_id
      JOIN proposal_app_proposal p ON p.id = g.proposal_id
      JOIN proposal_app_extractedunit u ON u.id = a.unit_id
      WHERE s.id = NEW.session_id AND s.collection_id = p.collection_id
        AND s.owner_id = NEW.actor_id AND s.deleted_at IS NULL
        AND a.eligible AND g.state = 'active' AND u.support_kind = 'factual') THEN
      RAISE EXCEPTION 'Pinned evidence must be active, factual, and owned in one collection'
        USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
"""

RESTORE_REFERENCE_GUARD = """
DROP TRIGGER IF EXISTS references_valid ON proposal_app_evidencepin;
DROP TRIGGER IF EXISTS parents_immutable ON proposal_app_evidencepin;
CREATE OR REPLACE FUNCTION proposal_reference_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME = 'proposal_app_draftrevision' THEN
    IF NOT EXISTS (SELECT 1 FROM proposal_app_evidencepacket p
                   WHERE p.id = NEW.packet_id AND p.session_id = NEW.session_id) THEN
      RAISE EXCEPTION 'Packet and revision must belong to the same session' USING ERRCODE = '23514';
    END IF;
  ELSIF TG_TABLE_NAME = 'proposal_app_proposalmembership' THEN
    IF NOT EXISTS (SELECT 1 FROM proposal_app_sourceitem s
                   JOIN proposal_app_versionfamily f ON f.id = NEW.family_id
                   JOIN proposal_app_proposal p ON p.id = f.proposal_id
                   WHERE s.id = NEW.source_id AND s.collection_id = p.collection_id) THEN
      RAISE EXCEPTION 'Membership must remain in its collection' USING ERRCODE = '23514';
    END IF;
  ELSIF TG_TABLE_NAME = 'proposal_app_publicationartifact' THEN
    IF NOT EXISTS (SELECT 1 FROM proposal_app_publicationgeneration g
      JOIN proposal_app_decisionevent e ON e.id = NEW.decision_event_id
      JOIN proposal_app_decision d ON d.id = e.decision_id
      JOIN proposal_app_versionfamily f ON f.id = d.family_id
      JOIN proposal_app_extractedunit u ON u.id = NEW.unit_id
      JOIN proposal_app_sourceversion v ON v.id = u.version_id
      JOIN proposal_app_proposalmembership membership
        ON membership.source_id = v.source_id AND membership.family_id = f.id
      WHERE g.id = NEW.generation_id AND g.proposal_id = f.proposal_id) THEN
      RAISE EXCEPTION 'Artifact provenance must belong to its proposal' USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [("proposal_app", "0004_membership_history")]

    operations = [
        migrations.AddField(
            model_name="sourceitem",
            name="disposition",
            field=models.CharField(default="awaiting_decision", max_length=30),
        ),
        migrations.AddField(
            model_name="sourceitem",
            name="disposition_reason",
            field=models.CharField(blank=True, max_length=300),
        ),
        migrations.AddField(
            model_name="extractedunit",
            name="support_kind",
            field=models.CharField(default="factual", max_length=30),
        ),
        migrations.CreateModel(
            name="EvidencePin",
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
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL
                    ),
                ),
                (
                    "artifact",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="proposal_app.publicationartifact",
                    ),
                ),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="proposal_app.draftsession",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="evidencepin",
            constraint=models.UniqueConstraint(
                fields=("session", "artifact"), name="session_artifact_pin"
            ),
        ),
        migrations.AddConstraint(
            model_name="publicationartifact",
            constraint=models.UniqueConstraint(
                fields=("generation", "unit"), name="generation_unit_artifact"
            ),
        ),
        migrations.RunSQL(
            REFERENCE_GUARD
            + "CREATE TRIGGER references_valid BEFORE INSERT OR UPDATE ON proposal_app_evidencepin "
            "FOR EACH ROW EXECUTE FUNCTION proposal_reference_guard();\n"
            "CREATE TRIGGER parents_immutable BEFORE UPDATE ON proposal_app_evidencepin "
            "FOR EACH ROW EXECUTE FUNCTION proposal_parent_guard('session_id', 'artifact_id', 'actor_id');",
            reverse_sql=RESTORE_REFERENCE_GUARD,
        ),
    ]
