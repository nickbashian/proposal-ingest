from __future__ import annotations

from scripts.connection_preflight import _parse_env_file, inspect_connections, main


def test_preflight_reports_missing_settings_without_exposing_secret_values(tmp_path):
    secret = "example-super-secret"
    checks = inspect_connections({"ENTRA_CLIENT_SECRET": secret, "PROPOSAL_SECRET_KEY": secret})
    report = "\n".join(f"{item.name} {item.detail} {item.action}" for item in checks)
    assert "Web sign-in" in report
    assert "ENTRA_TENANT_ID" in report
    assert secret not in report
    assert "CONFIGURED" not in next(
        item.status for item in checks if item.name == "Web sign-in (Entra OIDC)"
    )


def test_preflight_marks_present_settings_without_printing_values():
    values = {
        "DATABASE_URL": "postgres://private-user:" + "private-password@host/db",
        "AWS_PROFILE": "private-profile",
        "AWS_REGION": "us-east-1",
        "BEDROCK_CLASSIFICATION_MODEL_ID": "private-model-id",
        "BEDROCK_CLASSIFICATION_ESTIMATE_USD_PER_CALL": "0.02",
        "BEDROCK_DRAFTING_MODEL_ID": "private-model-id",
        "PROPOSAL_DRAFTING_RESERVATION_USD": "0.05",
        "BEDROCK_KNOWLEDGE_BASE_ID": "private-kb-id",
        "BEDROCK_DATA_SOURCE_ID": "private-ds-id",
        "PROPOSAL_CURATED_BUCKET": "private-bucket",
        "OIDC_ISSUER": "https://private-tenant.example",
        "ENTRA_TENANT_ID": "private-tenant-id",
        "ENTRA_CLIENT_ID": "private-client-id",
        "ENTRA_CLIENT_SECRET": "private-secret",
        "ENTRA_REDIRECT_URI": "https://private.example/callback",
        "SHAREPOINT_SITE_ID": "private-site-id",
        "SHAREPOINT_DRIVE_ID": "private-drive-id",
        "SHAREPOINT_CLIENT_ID": "private-sp-client",
        "SHAREPOINT_CLIENT_SECRET": "private-sp-secret",
    }
    checks = inspect_connections(values)
    assert all(item.status == "CONFIGURED" for item in checks)
    assert all("private-" not in item.detail and "private-" not in item.action for item in checks)


def test_preflight_rejects_unimplemented_snapshot_s3_mode():
    checks = inspect_connections({"PROPOSAL_STORAGE_BACKEND": "s3", "PROPOSAL_S3_BUCKET": "set"})
    assert any(
        item.name == "S3 storage" and item.status == "NEEDS IMPLEMENTATION" for item in checks
    )


def test_managed_kb_preflight_contract_uses_injected_scoped_read_client(settings, monkeypatch):
    from proposal_app.publication import ManagedKBAdapter

    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("PROPOSAL_CURATED_BUCKET", "private-bucket")
    monkeypatch.setenv("BEDROCK_KNOWLEDGE_BASE_ID", "private-kb")
    monkeypatch.setenv("BEDROCK_DATA_SOURCE_ID", "private-data-source")
    prefix = settings.APP["publication_s3_prefix"]

    class ControlClient:
        calls = []

        def get_data_source(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "dataSource": {
                    "status": "AVAILABLE",
                    "dataSourceConfiguration": {
                        "type": "S3",
                        "s3Configuration": {
                            "bucketArn": "arn:aws:s3:::private-bucket",
                            "inclusionPrefixes": [prefix],
                        },
                    },
                }
            }

    control = ControlClient()
    adapter = ManagedKBAdapter(s3=object(), control=control, runtime=object())
    adapter.verify_scope()
    assert control.calls == [
        {"knowledgeBaseId": "private-kb", "dataSourceId": "private-data-source"}
    ]


def test_graph_selected_folder_contract_uses_injected_read_only_session():
    from proposal_app.graph_source import GraphSourceAdapter

    class Response:
        status_code = 200

        def json(self):
            return {
                "value": [],
                "@odata.deltaLink": (
                    "https://graph.microsoft.com/v1.0/drives/private-drive/"
                    "items/approved-seed-folder/delta?token=done"
                ),
            }

    class Session:
        calls = []

        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            return Response()

    session = Session()
    source = GraphSourceAdapter(
        tenant_id="private-tenant",
        site_id="private-site",
        drive_id="private-drive",
        root_item_id="approved-seed-folder",
        token_provider=lambda: "private-token",
        session=session,
    )
    page = source.delta_page("approved-seed-folder")
    assert page.complete
    assert len(session.calls) == 1
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == (
        "https://graph.microsoft.com/v1.0/drives/private-drive/" "items/approved-seed-folder/delta"
    )
    assert kwargs["allow_redirects"] is False
    assert kwargs["headers"] == {"Authorization": "Bearer private-token"}


def test_identity_probe_is_opt_in_and_discards_provider_response(tmp_path, capsys):
    exit_code = main(["--env-file", str(tmp_path / "missing.env")])
    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Optional live probes (run only during the approved connection session)" in output
    assert "aws sts get-caller-identity --profile $env:AWS_PROFILE > $null" in output


def test_env_file_parser_handles_quotes_and_inline_comments_without_expansion(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        'AWS_REGION="us-east-1" # region\nPASSWORD=$(echo dont-run)\n', encoding="utf-8"
    )
    assert _parse_env_file(env_file) == {"AWS_REGION": "us-east-1", "PASSWORD": "$(echo dont-run)"}
