"""Permit current plan-approved factual evidence without changing extracted history."""

from django.db import migrations

CURATED_FACTUAL = """(
          u.support_kind = 'factual'
          OR EXISTS (
            SELECT 1 FROM proposal_app_curationplan cp
            JOIN proposal_app_decision d ON d.id = a.decision_event_id
            WHERE cp.family_id = d.family_id
              AND cp.version_id = u.version_id
              AND cp.extraction_run_id = u.extraction_run_id
              AND cp.state = 'current'
              AND cp.config_fingerprint <> ''
              AND cp.eligible_units ? u.id::text
          )
        )"""

LEGACY_FACTUAL = "u.support_kind = 'factual'"

REFERENCE_GUARD = f"""
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
        AND a.eligible AND g.state = 'active' AND {CURATED_FACTUAL}) THEN
      RAISE EXCEPTION 'Pinned evidence must be active, factual, and owned in one collection'
        USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
"""

RESTORE_REFERENCE_GUARD = REFERENCE_GUARD.replace(CURATED_FACTUAL, LEGACY_FACTUAL)


class Migration(migrations.Migration):
    dependencies = [("proposal_app", "0017_classificationresult")]

    operations = [migrations.RunSQL(REFERENCE_GUARD, reverse_sql=RESTORE_REFERENCE_GUARD)]
