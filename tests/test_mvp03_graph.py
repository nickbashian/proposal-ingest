"""Offline Graph contract checks: scoped pages, immutable capture, and read-only calls."""

import requests
import pytest

from proposal_app.adapters import ProviderFailure
from proposal_app.graph_source import ClientCredentialsTokenProvider, GraphSourceAdapter
from proposal_app.source_sync import disposition


class Response:
    def __init__(self, status=200, payload=None, content=b"", headers=None):
        self.status_code = status
        self.payload = payload
        self.content = content
        self.headers = headers or {}

    def json(self):
        if self.payload is None:
            raise ValueError("not JSON")
        return self.payload

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset : offset + chunk_size]

    def close(self):
        pass


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def item(item_id="i1", *, name="Draft.docx", etag='"v1"', size=3, folder=False):
    return {
        "id": item_id,
        "name": name,
        "eTag": etag,
        "size": size,
        "parentReference": {"id": "p1", "path": "/drives/d1/root:/2025/Proposal"},
        "folder" if folder else "file": {},
    }


def adapter(responses):
    session = Session(responses)
    source = GraphSourceAdapter(
        tenant_id="t1",
        site_id="s1",
        drive_id="d1",
        root_item_id="root1",
        token_provider=lambda: "secret-token",
        session=session,
    )
    return source, session


def test_delta_paging_and_stable_item_identity_across_rename():
    endpoint = "https://graph.microsoft.com/v1.0/drives/d1/items/root1/delta"
    next_link = endpoint + "?$skiptoken=page2"
    delta_link = endpoint + "?token=completed"
    source, session = adapter(
        [
            Response(payload={"value": [item()], "@odata.nextLink": next_link}),
            Response(
                payload={
                    "value": [item(name="Renamed.docx")],
                    "@odata.deltaLink": delta_link,
                }
            ),
        ]
    )
    first = source.delta_page("root1")
    second = source.delta_page("root1", first.next_cursor)
    assert first.complete is False and second.complete is True
    assert first.items[0].item_id == second.items[0].item_id == "i1"
    assert first.items[0].path.endswith("/Draft.docx")
    assert second.items[0].path.endswith("/Renamed.docx")
    assert second.items[0].upstream_version == '"v1"'
    assert [call[0] for call in session.calls] == ["GET", "GET"]


def test_delta_function_style_cursor_stays_scoped():
    endpoint = "https://graph.microsoft.com/v1.0/drives/d1/items/root1/delta"
    cursor = endpoint + "(token=opaque)"
    source, session = adapter(
        [Response(payload={"value": [], "@odata.deltaLink": endpoint + "?token=done"})]
    )
    assert source.delta_page("root1", cursor).complete
    assert session.calls[0][1] == cursor


def test_encoded_drive_and_qualified_function_cursors_are_accepted():
    endpoint = "https://graph.microsoft.com/v1.0/drives/b%21drive/items/root1/delta"
    source, session = adapter([Response(payload={"value": [], "@odata.deltaLink": endpoint})])
    source.drive_id = "b!drive"
    cursor = (
        "https://graph.microsoft.com/v1.0/drives/b!drive/items/root1/"
        "microsoft.graph.delta(token=opaque)"
    )
    assert source.delta_page("root1", cursor).complete
    assert session.calls[0][1] == cursor


def test_delta_without_parent_paths_resolves_ancestors_before_classification():
    endpoint = "https://graph.microsoft.com/v1.0/drives/d1/items/root1/delta"
    child = item(name="secret.pdf")
    child["parentReference"] = {"id": "hidden"}
    hidden = item("hidden", name=".private", folder=True)
    hidden["parentReference"] = {"id": "root1"}
    root = item("root1", name="Proposal", folder=True)
    root["parentReference"] = {"id": "year", "path": "/drives/d1/root:/2025"}
    source, _ = adapter(
        [
            Response(payload={"value": [child], "@odata.deltaLink": endpoint}),
            Response(payload=hidden),
            Response(payload=root),
        ]
    )
    observed = source.delta_page("root1").items[0]
    assert observed.path == "secret.pdf"
    resolved = source.resolve_scoped_item(observed, year=2025)
    assert resolved.path == "2025/Proposal/.private/secret.pdf"
    assert disposition(resolved)[0] == "administrative_exclusion"


def test_unresolved_graph_parent_fails_closed():
    child = item()
    child["parentReference"] = {"id": "other"}
    other = item("other", folder=True)
    other["parentReference"] = {"id": "other"}
    source, _ = adapter([Response(payload=other)])
    with pytest.raises(ProviderFailure, match="graph_unresolved_parent"):
        source.resolve_scoped_item(source._parse_item(child), year=2025)


def test_malformed_item_fields_fail_without_a_partial_page():
    endpoint = "https://graph.microsoft.com/v1.0/drives/d1/items/root1/delta"
    malformed = item()
    malformed["name"] = ["unexpected"]
    source, _ = adapter([Response(payload={"value": [malformed], "@odata.deltaLink": endpoint})])
    with pytest.raises(ProviderFailure, match="graph_invalid_response"):
        source.delta_page("root1")


def test_download_without_upstream_version_cannot_be_verified():
    raw = item()
    raw.pop("eTag")
    source, session = adapter([])
    with pytest.raises(ProviderFailure, match="inconsistent_snapshot"):
        source.download_verified(source._parse_item(raw))
    assert not session.calls


def test_download_stream_stops_at_size_limit_without_materializing_body():
    raw = item(size=4)

    class LargeResponse(Response):
        def iter_content(self, chunk_size):
            yield b"abc"
            yield b"def"
            raise AssertionError("Stream was read beyond the configured limit")

    source, session = adapter(
        [
            Response(payload=raw),
            Response(status=302, headers={"Location": "https://download.example/file"}),
            LargeResponse(),
        ]
    )
    source.max_download_bytes = 4
    with pytest.raises(ProviderFailure, match="graph_download_too_large"):
        source.download_verified(source._parse_item(raw))
    assert session.calls[-1][2]["stream"] is True
    assert session.calls[-1][2]["headers"] == {}


@pytest.mark.parametrize(
    "cursor",
    [
        "http://graph.microsoft.com/v1.0/drives/d1/items/root1/delta?x=1",
        "https://evil.example/v1.0/drives/d1/items/root1/delta?x=1",
        "https://graph.microsoft.com/v1.0/drives/d1/items/other/delta?x=1",
        "https://graph.microsoft.com/v1.0/drives/other/items/root1/delta?x=1",
        "https://user:password" + chr(64) + "graph.microsoft.com/v1.0/drives/d1/items/root1/delta",
    ],
)
def test_rejects_out_of_scope_checkpoint_before_request(cursor):
    source, session = adapter([])
    with pytest.raises(ProviderFailure, match="graph_invalid_response"):
        source.delta_page("root1", cursor)
    assert not session.calls


def test_expired_checkpoint_and_throttling_never_return_complete_crawl():
    source, _ = adapter([Response(status=410)])
    with pytest.raises(ProviderFailure, match="checkpoint_expired"):
        source.delta_page("root1")
    source, _ = adapter([Response(status=429, payload={"error": {"code": "tooManyRequests"}})])
    with pytest.raises(ProviderFailure) as caught:
        source.delta_page("root1")
    assert caught.value.retryable


def test_permission_and_network_failure_never_return_deletion_event():
    source, _ = adapter([Response(status=403, payload={"error": {"code": "accessDenied"}})])
    with pytest.raises(ProviderFailure) as denied:
        source.delta_page("root1")
    assert denied.value.code == "denied"
    source, _ = adapter([requests.ConnectionError("offline")])
    with pytest.raises(ProviderFailure) as offline:
        source.delta_page("root1")
    assert offline.value.code == "graph_network" and offline.value.retryable


def test_delta_deleted_event_is_explicit():
    endpoint = "https://graph.microsoft.com/v1.0/drives/d1/items/root1/delta"
    source, _ = adapter(
        [Response(payload={"value": [{"id": "i1", "deleted": {}}], "@odata.deltaLink": endpoint})]
    )
    page = source.delta_page("root1")
    assert page.complete and page.items[0].deleted


def test_download_uses_no_bearer_on_redirect_and_verifies_observed_version():
    raw = item()
    source, session = adapter(
        [
            Response(payload=raw),
            Response(status=302, headers={"Location": "https://files.example/private-content"}),
            Response(content=b"abc"),
            Response(payload=raw),
        ]
    )
    observed = source._parse_item(raw)
    assert source.download_verified(observed) == b"abc"
    assert [call[0] for call in session.calls] == ["GET"] * 4
    assert session.calls[2][2]["headers"] == {}
    assert all(
        call[2]["headers"].get("Authorization") == "Bearer secret-token"
        for index, call in enumerate(session.calls)
        if index != 2
    )


def test_changed_during_download_retries_then_reports_inconsistent():
    old = item()
    new = item(etag='"v2"')
    source, session = adapter([Response(payload=new), Response(payload=new)])
    with pytest.raises(ProviderFailure, match="inconsistent_snapshot") as caught:
        source.download_verified(source._parse_item(old))
    assert caught.value.retryable
    assert len(session.calls) == 2


def test_rejects_redirect_to_insecure_or_credentialed_location():
    raw = item()
    source, _ = adapter(
        [
            Response(payload=raw),
            Response(status=302, headers={"Location": "http://files.example/content"}),
        ]
    )
    with pytest.raises(ProviderFailure, match="graph_invalid_download_redirect"):
        source.download_verified(source._parse_item(raw))


def test_token_provider_is_runtime_only_and_caches_token():
    session = Session([Response(payload={"access_token": "opaque", "expires_in": 3600})])
    provider = ClientCredentialsTokenProvider("t1", "client", "private-secret", session=session)
    assert provider() == provider() == "opaque"
    assert len(session.calls) == 1
    method, endpoint, kwargs = session.calls[0]
    assert method == "POST" and endpoint.startswith("https://login.microsoftonline.com/t1/")
    assert kwargs["data"]["scope"] == "https://graph.microsoft.com/.default"
    assert "private-secret" not in endpoint


def test_environment_requires_separate_background_connector_identity(monkeypatch):
    monkeypatch.setenv("ENTRA_TENANT_ID", "tenant")
    monkeypatch.setenv("SHAREPOINT_SITE_ID", "site")
    monkeypatch.setenv("SHAREPOINT_DRIVE_ID", "drive")
    monkeypatch.setenv("ENTRA_CLIENT_ID", "web-login-client")
    monkeypatch.setenv("ENTRA_CLIENT_SECRET", "web-login-secret")
    monkeypatch.delenv("SHAREPOINT_CLIENT_ID", raising=False)
    monkeypatch.delenv("SHAREPOINT_CLIENT_SECRET", raising=False)
    with pytest.raises(ValueError, match="credentials are incomplete"):
        GraphSourceAdapter.from_environment(root_item_id="root")


def test_environment_passes_configured_download_limit(monkeypatch):
    for key, value in {
        "ENTRA_TENANT_ID": "tenant",
        "SHAREPOINT_SITE_ID": "site",
        "SHAREPOINT_DRIVE_ID": "drive",
        "SHAREPOINT_CLIENT_ID": "client",
        "SHAREPOINT_CLIENT_SECRET": "secret",
    }.items():
        monkeypatch.setenv(key, value)
    source = GraphSourceAdapter.from_environment(
        root_item_id="root", max_download_bytes=80 * 1024 * 1024
    )
    assert source.max_download_bytes == 80 * 1024 * 1024
