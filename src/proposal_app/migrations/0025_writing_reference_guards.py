"""Keep private writing references inside their owning session and collection."""

from django.db import migrations

SQL = """
CREATE FUNCTION proposal_writing_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME = 'proposal_app_draftgeneration' THEN
    IF NOT EXISTS (SELECT 1 FROM proposal_app_evidencepacket p
      WHERE p.id = NEW.packet_id AND p.session_id = NEW.session_id) OR
      (NEW.result_revision_id IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM proposal_app_draftrevision r WHERE r.id = NEW.result_revision_id
         AND r.session_id = NEW.session_id AND r.packet_id = NEW.packet_id)) THEN
      RAISE EXCEPTION 'Generation evidence and result must belong to its session' USING ERRCODE = '23514';
    END IF;
  ELSIF TG_TABLE_NAME = 'proposal_app_voicepin' THEN
    IF NOT EXISTS (SELECT 1 FROM proposal_app_draftsession s
      JOIN proposal_app_curationplan cp ON cp.id = NEW.plan_id
      JOIN proposal_app_versionfamily f ON f.id = cp.family_id
      JOIN proposal_app_proposal p ON p.id = f.proposal_id
      JOIN proposal_app_extractedunit u ON u.id = NEW.unit_id
      WHERE s.id = NEW.session_id AND s.collection_id = p.collection_id
        AND cp.version_id = u.version_id AND cp.extraction_run_id = u.extraction_run_id
        AND cp.voice_units ? u.id::text AND cp.state = 'current') THEN
      RAISE EXCEPTION 'Voice pin must refer to an approved plan in its collection' USING ERRCODE = '23514';
    END IF;
  ELSIF TG_TABLE_NAME = 'proposal_app_evidenceexclusion' THEN
    IF NOT EXISTS (SELECT 1 FROM proposal_app_draftsession s
      JOIN proposal_app_sourceitem i ON i.id = NEW.source_id
      WHERE s.id = NEW.session_id AND s.collection_id = i.collection_id) THEN
      RAISE EXCEPTION 'Source exclusion must remain in its collection' USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER writing_references BEFORE INSERT OR UPDATE ON proposal_app_draftgeneration
FOR EACH ROW EXECUTE FUNCTION proposal_writing_guard();
CREATE TRIGGER writing_references BEFORE INSERT OR UPDATE ON proposal_app_voicepin
FOR EACH ROW EXECUTE FUNCTION proposal_writing_guard();
CREATE TRIGGER writing_references BEFORE INSERT OR UPDATE ON proposal_app_evidenceexclusion
FOR EACH ROW EXECUTE FUNCTION proposal_writing_guard();
CREATE TRIGGER parents_immutable BEFORE UPDATE ON proposal_app_draftgeneration
FOR EACH ROW EXECUTE FUNCTION proposal_parent_guard('session_id', 'packet_id', 'expected_revision');
CREATE TRIGGER parents_immutable BEFORE UPDATE ON proposal_app_voicepin
FOR EACH ROW EXECUTE FUNCTION proposal_parent_guard('session_id', 'unit_id', 'plan_id');
CREATE TRIGGER parents_immutable BEFORE UPDATE ON proposal_app_evidenceexclusion
FOR EACH ROW EXECUTE FUNCTION proposal_parent_guard('session_id', 'source_id');
"""


class Migration(migrations.Migration):
    dependencies = [
        ("proposal_app", "0024_draftrevision_checks_draftrevision_reuse_state_and_more")
    ]
    operations = [migrations.RunSQL(SQL)]
