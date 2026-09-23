"""Read-only, scoped Microsoft Graph drive source adapter.

The caller owns durable crawl checkpoints and reconciliation. This adapter returns
one delta page at a time and never interprets a failed page as a deletion.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import os
import time
from typing import Callable
from urllib.parse import quote, unquote, urlsplit

import requests

from .adapters import ProviderFailure, normalize_error

GRAPH_ORIGIN = "https://graph.microsoft.com"


@dataclass(frozen=True)
class GraphItem:
    item_id: str
    name: str
    parent_id: str | None
    path: str
    etag: str | None
    upstream_version: str | None
    size: int | None
    is_folder: bool
    is_file: bool
    deleted: bool


@dataclass(frozen=True)
class GraphPage:
    items: tuple[GraphItem, ...]
    next_cursor: str | None
    complete: bool
    delta_cursor: str | None = None


class ClientCredentialsTokenProvider:
    """Acquire app-only Graph tokens; secrets and tokens remain process memory only."""

    def __init__(self, tenant_id: str, client_id: str, client_secret: str, *, session=None):
        if not all((tenant_id, client_id, client_secret)):
            raise ValueError("Graph client credentials are incomplete")
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = session or requests.Session()
        self._token: str | None = None
        self._expires_at = 0.0

    def __call__(self) -> str:
        if self._token and time.monotonic() < self._expires_at:
            return self._token
        endpoint = (
            f"https://login.microsoftonline.com/{quote(self.tenant_id, safe='')}"
            "/oauth2/v2.0/token"
        )
        try:
            response = self.session.request(
                "POST",
                endpoint,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                    "grant_type": "client_credentials",
                },
                timeout=30,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise ProviderFailure("graph_auth_network", retryable=True, unknown=True) from exc
        if response.status_code != 200:
            raise ProviderFailure("graph_auth_failed", retryable=response.status_code >= 500)
        try:
            payload = response.json()
            token = payload["access_token"]
            lifetime = int(payload["expires_in"])
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderFailure("graph_auth_invalid_response") from exc
        if not isinstance(token, str) or not token or lifetime <= 0:
            raise ProviderFailure("graph_auth_invalid_response")
        self._token = token
        self._expires_at = time.monotonic() + max(0, lifetime - 60)
        return token


class GraphSourceAdapter:
    """Use a configured drive and root item with application supplied credentials."""

    def __init__(
        self,
        *,
        tenant_id: str,
        site_id: str,
        drive_id: str,
        root_item_id: str,
        token_provider: Callable[[], str],
        session: requests.Session | None = None,
        timeout_seconds: int = 30,
        max_download_bytes: int = 64 * 1024 * 1024,
    ):
        if not all((tenant_id, site_id, drive_id, root_item_id)):
            raise ValueError("Graph source scope requires tenant, site, drive, and root item")
        if timeout_seconds <= 0 or max_download_bytes <= 0:
            raise ValueError("Graph request limits must be positive")
        self.tenant_id = tenant_id
        self.site_id = site_id
        self.drive_id = drive_id
        self.root_item_id = root_item_id
        self.token_provider = token_provider
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds
        self.max_download_bytes = max_download_bytes

    @classmethod
    def from_environment(
        cls,
        *,
        root_item_id: str,
        session: requests.Session | None = None,
        max_download_bytes: int = 64 * 1024 * 1024,
    ) -> GraphSourceAdapter:
        """Read the runtime-only app identity and configured source scope."""
        tenant = os.environ.get("ENTRA_TENANT_ID", "")
        site = os.environ.get("SHAREPOINT_SITE_ID", "")
        drive = os.environ.get("SHAREPOINT_DRIVE_ID", "")
        client = os.environ.get("SHAREPOINT_CLIENT_ID", "")
        secret = os.environ.get("SHAREPOINT_CLIENT_SECRET", "")
        provider = ClientCredentialsTokenProvider(tenant, client, secret, session=session)
        return cls(
            tenant_id=tenant,
            site_id=site,
            drive_id=drive,
            root_item_id=root_item_id,
            token_provider=provider,
            session=session,
            max_download_bytes=max_download_bytes,
        )

    def _item_url(self, item_id: str) -> str:
        return f"{GRAPH_ORIGIN}/v1.0/drives/{quote(self.drive_id, safe='')}/items/{quote(item_id, safe='')}"

    def _delta_url(self) -> str:
        return self._item_url(self.root_item_id) + "/delta"

    @staticmethod
    def _validate_cursor(cursor: str, endpoint: str) -> None:
        parsed, allowed = urlsplit(cursor), urlsplit(endpoint)
        path, allowed_path = unquote(parsed.path), unquote(allowed.path)
        base = allowed_path.removesuffix("/delta")
        if (
            parsed.scheme != "https"
            or parsed.netloc.lower() != allowed.netloc.lower()
            or not (
                path == allowed_path
                or (
                    path.endswith(")")
                    and (
                        path.startswith(allowed_path + "(")
                        or path.startswith(base + "/microsoft.graph.delta(")
                    )
                )
            )
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("Graph cursor leaves the configured endpoint")

    def _graph_get(self, url: str, *, stream: bool = False):
        token = self.token_provider()
        if not token:
            raise ProviderFailure("missing_graph_token")
        try:
            response = self.session.request(
                "GET",
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=self.timeout_seconds,
                allow_redirects=False,
                stream=stream,
            )
        except requests.RequestException as exc:
            raise ProviderFailure("graph_network", retryable=True, unknown=True) from exc
        if response.status_code == 410:
            raise ProviderFailure("checkpoint_expired", retryable=False)
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            raise normalize_error(payload, response.status_code)
        return response

    @staticmethod
    def _parse_item(raw: dict) -> GraphItem:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
            raise ProviderFailure("graph_invalid_response")
        parent = raw.get("parentReference") or {}
        if not isinstance(parent, dict):
            raise ProviderFailure("graph_invalid_response")
        size = raw.get("size")
        if size is not None and (type(size) is not int or size < 0):
            raise ProviderFailure("graph_invalid_response")
        parent_path = parent.get("path")
        name = raw.get("name", "")
        if (
            not isinstance(name, str)
            or not isinstance(parent_path, (str, type(None)))
            or not isinstance(parent.get("id"), (str, type(None)))
            or not isinstance(raw.get("eTag"), (str, type(None)))
            or not isinstance(raw.get("cTag"), (str, type(None)))
        ):
            raise ProviderFailure("graph_invalid_response")
        return GraphItem(
            item_id=raw["id"],
            name=name,
            parent_id=parent.get("id"),
            path=(parent_path.rstrip("/") + "/" + name) if parent_path else name,
            etag=raw.get("eTag"),
            upstream_version=raw.get("eTag") or raw.get("cTag"),
            size=size,
            is_folder="folder" in raw,
            is_file="file" in raw,
            deleted="deleted" in raw,
        )

    def delta_page(self, root_item_id: str, cursor: str | None = None) -> GraphPage:
        """Return one scoped delta page; only a final deltaLink completes a crawl."""
        if root_item_id != self.root_item_id:
            raise ValueError("Graph root is outside the configured source scope")
        endpoint = self._delta_url()
        if cursor is not None:
            try:
                self._validate_cursor(cursor, endpoint)
            except ValueError:
                raise ProviderFailure("graph_invalid_response") from None
        response = self._graph_get(cursor or endpoint)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderFailure("graph_invalid_response") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
            raise ProviderFailure("graph_invalid_response")
        next_cursor = payload.get("@odata.nextLink")
        delta_cursor = payload.get("@odata.deltaLink")
        if bool(next_cursor) == bool(delta_cursor):
            raise ProviderFailure("graph_invalid_response")
        selected = next_cursor or delta_cursor
        if not isinstance(selected, str):
            raise ProviderFailure("graph_invalid_response")
        try:
            self._validate_cursor(selected, endpoint)
        except ValueError:
            raise ProviderFailure("graph_invalid_response") from None
        items = tuple(self._parse_item(item) for item in payload["value"])
        return GraphPage(items, next_cursor, bool(delta_cursor), delta_cursor)

    def get_item(self, item_id: str) -> GraphItem:
        response = self._graph_get(self._item_url(item_id))
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderFailure("graph_invalid_response") from exc
        item = self._parse_item(payload)
        if item.item_id != item_id:
            raise ProviderFailure("graph_invalid_response")
        return item

    def resolve_scoped_item(self, item: GraphItem, *, year: int) -> GraphItem:
        """Build a path from IDs; delta responses do not carry parent paths."""
        if item.deleted:
            return item
        names = []
        visited = {item.item_id}
        current = item
        while current.item_id != self.root_item_id:
            if not current.name or not current.parent_id or current.parent_id in visited:
                raise ProviderFailure("graph_unresolved_parent")
            names.append(current.name)
            visited.add(current.parent_id)
            current = self.get_item(current.parent_id)
            if current.deleted:
                raise ProviderFailure("graph_unresolved_parent")
        if current.item_id == item.item_id:
            current = self.get_item(self.root_item_id)
        root_parts = current.path.replace("\\", "/").rstrip("/").split("/")
        if len(root_parts) < 2 or root_parts[-2] != str(year):
            raise ProviderFailure("scope_mismatch")
        return replace(item, path="/".join((str(year), current.name, *reversed(names))))

    def download_verified(self, observed: GraphItem) -> bytes:
        """Download exact observed bytes or fail for a changed source version."""
        if not observed.is_file or observed.deleted:
            raise ValueError("Only live file items can be downloaded")
        for attempt in range(2):
            try:
                return self._download_once(observed)
            except ProviderFailure as failure:
                if failure.code != "inconsistent_snapshot" or attempt:
                    raise
        raise AssertionError("unreachable")

    def _download_once(self, observed: GraphItem) -> bytes:
        if not observed.upstream_version:
            raise ProviderFailure("inconsistent_snapshot", retryable=True)
        before = self.get_item(observed.item_id)
        if (
            before.upstream_version != observed.upstream_version
            or before.etag != observed.etag
            or before.size != observed.size
            or before.deleted
        ):
            raise ProviderFailure("inconsistent_snapshot", retryable=True)
        response = self._graph_get(self._item_url(observed.item_id) + "/content", stream=True)
        if response.status_code == 302:
            location = response.headers.get("Location", "")
            response.close()
            parsed = urlsplit(location)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
            ):
                raise ProviderFailure("graph_invalid_download_redirect")
            try:
                # The redirect is preauthenticated. Never forward the Graph bearer token.
                response = self.session.request(
                    "GET",
                    location,
                    headers={},
                    timeout=self.timeout_seconds,
                    allow_redirects=False,
                    stream=True,
                )
            except requests.RequestException:
                # A preauthenticated URL can contain a bearer-like query token.
                raise ProviderFailure("graph_network", retryable=True, unknown=True) from None
        if response.status_code != 200:
            response.close()
            raise ProviderFailure(
                "graph_download_failed", retryable=response.status_code in {429, 500, 502, 503, 504}
            )
        chunks = []
        size = 0
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                size += len(chunk)
                if size > self.max_download_bytes:
                    raise ProviderFailure("graph_download_too_large")
                chunks.append(chunk)
        except requests.RequestException:
            raise ProviderFailure("graph_network", retryable=True, unknown=True) from None
        finally:
            response.close()
        content = b"".join(chunks)
        after = self.get_item(observed.item_id)
        if (
            after.upstream_version != observed.upstream_version
            or after.etag != observed.etag
            or after.size != observed.size
            or after.deleted
            or (observed.size is not None and len(content) != observed.size)
        ):
            raise ProviderFailure("inconsistent_snapshot", retryable=True)
        return content
