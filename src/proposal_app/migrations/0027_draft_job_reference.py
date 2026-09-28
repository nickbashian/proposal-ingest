"""Private provider jobs cannot be attached to another user's writing attempt."""

from django.db import migrations

SQL = """
CREATE FUNCTION proposal_draft_job_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.provider_job_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM proposal_app_job j JOIN proposal_app_draftsession s ON s.id = NEW.session_id
    WHERE j.id = NEW.provider_job_id AND j.creator_id = s.owner_id
      AND j.collection_id = s.collection_id AND j.kind = 'draft-generation'
      AND j.payload->>'generation_id' = NEW.id::text
      AND j.payload->>'packet_id' = NEW.packet_id::text
  ) THEN
    RAISE EXCEPTION 'Provider job must belong to its writing attempt' USING ERRCODE = '23514';
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.provider_job_id IS NOT NULL AND
      NEW.provider_job_id IS DISTINCT FROM OLD.provider_job_id THEN
    RAISE EXCEPTION 'Provider job cannot be reassigned' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER provider_job_valid BEFORE INSERT OR UPDATE ON proposal_app_draftgeneration
FOR EACH ROW EXECUTE FUNCTION proposal_draft_job_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("proposal_app", "0026_draftgeneration_provider_job")]
    operations = [migrations.RunSQL(SQL)]
