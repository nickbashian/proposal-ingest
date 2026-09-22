from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("proposal_app", "0003_job_resume_state")]
    operations = [
        migrations.RunSQL(
            "CREATE TRIGGER immutable BEFORE DELETE ON proposal_app_proposalmembership "
            "FOR EACH ROW EXECUTE FUNCTION proposal_immutable();"
        )
    ]
