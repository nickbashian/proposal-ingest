"""Protect immutable history and validate references that span multiple tables."""

from django.db import migrations

SQL = """
CREATE FUNCTION proposal_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Immutable application history cannot be changed' USING ERRCODE = '23514';
END $$;

CREATE FUNCTION proposal_reference_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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

CREATE FUNCTION proposal_parent_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE field text;
BEGIN
  FOREACH field IN ARRAY TG_ARGV LOOP
    IF (to_jsonb(OLD) -> field) IS DISTINCT FROM (to_jsonb(NEW) -> field) THEN
      RAISE EXCEPTION 'Identity and ownership cannot be reassigned' USING ERRCODE = '23514';
    END IF;
  END LOOP;
  RETURN NEW;
END $$;
"""

IMMUTABLE = [
    "decisionevent",
    "auditrecord",
    "sourceversion",
    "extractedunit",
    "evidencepacket",
    "draftrevision",
    "draftexport",
    "legacyimport",
    "jobresult",
]
PARENTS = {
    "sourceitem": ["collection_id", "connector", "tenant", "site", "drive", "item"],
    "proposal": ["collection_id"],
    "versionfamily": ["proposal_id"],
    "proposalmembership": ["source_id", "family_id"],
    "decision": ["family_id", "scope", "field", "kind"],
    "publicationgeneration": ["proposal_id", "revision"],
    "publicationartifact": ["generation_id", "unit_id", "decision_event_id", "blob_id"],
    "draftsession": ["collection_id", "owner_id"],
    "job": ["collection_id", "creator_id", "key", "kind", "payload"],
}
for table in IMMUTABLE:
    SQL += f"CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON proposal_app_{table} FOR EACH ROW EXECUTE FUNCTION proposal_immutable();\n"
for table in ["draftrevision", "proposalmembership", "publicationartifact"]:
    SQL += f"CREATE TRIGGER references_valid BEFORE INSERT OR UPDATE ON proposal_app_{table} FOR EACH ROW EXECUTE FUNCTION proposal_reference_guard();\n"
for table, fields in PARENTS.items():
    arguments = ", ".join(f"'{field}'" for field in fields)
    SQL += f"CREATE TRIGGER parents_immutable BEFORE UPDATE ON proposal_app_{table} FOR EACH ROW EXECUTE FUNCTION proposal_parent_guard({arguments});\n"


class Migration(migrations.Migration):
    dependencies = [("proposal_app", "0001_initial")]
    # Deliberately irreversible: use the documented backup/restore procedure.
    operations = [migrations.RunSQL(SQL)]
