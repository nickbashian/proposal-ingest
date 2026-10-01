import hashlib
import json

import pytest

from scripts import app_recovery


def test_package_and_validate_backup_hashes_database_and_objects(tmp_path):
    objects = tmp_path / "objects"
    objects.mkdir()
    content = b"fictional proposal evidence"
    key = hashlib.sha256(content).hexdigest()
    (objects / key).write_bytes(content)
    dump = tmp_path / "database.dump"
    dump.write_bytes(b"synthetic custom-format dump")
    bundle = tmp_path / "backup"

    app_recovery.package_dump(dump, objects, bundle)

    dump_path, manifest = app_recovery._validate_bundle(bundle)
    assert dump_path.read_bytes() == b"synthetic custom-format dump"
    assert manifest == [{"key": key, "sha256": key, "size": len(content)}]
    assert (bundle / "manifest.json").is_file()

    (bundle / "database.dump").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="database integrity"):
        app_recovery._validate_bundle(bundle)


def test_validate_backup_fails_closed_on_tampered_object_and_unlisted_file(tmp_path):
    objects = tmp_path / "objects"
    objects.mkdir()
    content = b"fictional"
    key = hashlib.sha256(content).hexdigest()
    (objects / key).write_bytes(content)
    dump = tmp_path / "database.dump"
    dump.write_bytes(b"dump")
    bundle = tmp_path / "backup"
    app_recovery.package_dump(dump, objects, bundle)

    (bundle / "objects" / key).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="object integrity"):
        app_recovery._validate_bundle(bundle)

    (bundle / "objects" / key).write_bytes(content)
    (bundle / "objects" / ("0" * 64)).write_bytes(b"extra")
    with pytest.raises(ValueError, match="does not match"):
        app_recovery._validate_bundle(bundle)


def test_restore_checks_hold_and_integrity_before_target_database(tmp_path, monkeypatch):
    bundle = tmp_path / "backup"
    bundle.mkdir()
    (bundle / "database.dump").write_bytes(b"tampered")
    (bundle / "objects").mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "format": 1,
                "database_dump": {"path": "database.dump", "size": 0, "sha256": "bad"},
                "objects": [],
            }
        ),
        encoding="utf-8",
    )
    target = tmp_path / "restored-objects"

    with pytest.raises(ValueError, match="CLI hold flag"):
        app_recovery.restore(
            "postgresql://user:" + "pass@localhost/db",
            bundle,
            target,
            publication_hold=False,
        )
    monkeypatch.setenv("PROPOSAL_PUBLICATION_HOLD", "true")
    monkeypatch.setattr(
        app_recovery,
        "_database_is_empty",
        lambda _: pytest.fail("database checked before bundle validation"),
    )
    with pytest.raises(ValueError, match="database integrity"):
        app_recovery.restore(
            "postgresql://user:" + "pass@localhost/db",
            bundle,
            target,
            publication_hold=True,
        )
    assert not target.exists()


def test_missing_psql_reports_sanitized_recovery_error(monkeypatch):
    def missing_client(*_args, **_kwargs):
        raise FileNotFoundError("private host path")

    monkeypatch.setattr(app_recovery.subprocess, "run", missing_client)
    with pytest.raises(RuntimeError, match="Required PostgreSQL utility is missing: psql"):
        app_recovery._database_is_empty({})


def test_ssm_env_rendering_rejects_ambiguous_secret_quoting():
    from deploy import render_env_from_ssm

    assert render_env_from_ssm._compose_value("ENTRA_CLIENT_SECRET", "synthetic-token") == (
        "'synthetic-token'"
    )
    assert render_env_from_ssm._compose_value("ENTRA_CLIENT_SECRET", "synthetic'quote") == (
        "'synthetic\\'quote'"
    )
    with pytest.raises(ValueError, match="unsupported quoting"):
        render_env_from_ssm._compose_value("ENTRA_CLIENT_SECRET", "synthetic\\backslash")


def test_restore_passes_connection_secrets_only_through_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("PROPOSAL_PUBLICATION_HOLD", "true")
    objects = tmp_path / "objects"
    objects.mkdir()
    content = b"synthetic evidence"
    key = hashlib.sha256(content).hexdigest()
    (objects / key).write_bytes(content)
    dump = tmp_path / "database.dump"
    dump.write_bytes(b"synthetic database dump")
    bundle = tmp_path / "backup"
    app_recovery.package_dump(dump, objects, bundle)
    target = tmp_path / "restored-objects"
    captured = []
    monkeypatch.setattr(app_recovery, "_database_is_empty", lambda _: True)
    monkeypatch.setattr(
        app_recovery,
        "_run",
        lambda command, *, env, stdout=None: captured.append((command, env)),
    )
    database_url = (
        "postgresql://synthetic-user:" + "p%40ss%3Aword@db.internal:5432/proposals"
        "?sslmode=verify-full&sslrootcert=%2Frun%2Fca.crt"
    )

    app_recovery.restore(database_url, bundle, target, publication_hold=True)

    command, env = captured[0]
    assert "p%40ss%3Aword" not in " ".join(command)
    assert database_url not in " ".join(command)
    assert env["PGPASSWORD"] == "p@ss:word"
    assert env["PGSSLMODE"] == "verify-full"
    assert (target / key).read_bytes() == content
    assert "--single-transaction" in command
    assert command[command.index("--dbname") + 1] == "proposals"
