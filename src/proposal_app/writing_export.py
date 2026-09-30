"""Export text with only server-resolved citation links, never model-supplied destinations."""

import html
import re
import uuid
from urllib.parse import urljoin, urlsplit

from .adapters import DeterministicDraftingAdapter


def render_revision(
    revision, export_format, base_url="", *, source_appendix=True, historical=False
):
    if export_format not in {"markdown", "text"}:
        raise ValueError("Export format must be markdown or text")
    if base_url and (
        urlsplit(base_url).scheme not in {"http", "https"} or not urlsplit(base_url).netloc
    ):
        raise ValueError("Export links require an HTTP application address")
    markdown = export_format == "markdown"

    def escape(value):
        value = str(value)
        value = re.sub(
            r"(?i)\b(?:[a-z][a-z0-9+.-]*://|www\.)[^\s<>]+", "(unverified URL omitted)", value
        )
        if not markdown:
            return value
        return (
            html.escape(value, quote=False)
            .replace("\\", "\\\\")
            .replace("[", "\\[")
            .replace("]", "\\]")
        )

    def link(label, path):
        destination = urljoin(base_url, path) if base_url else path
        return (
            f"[{escape(label)}]({destination})" if markdown else f"{escape(label)}: {destination}"
        )

    rows = revision.packet.payload
    allowed = {
        item[key]
        for item in rows
        for key in ("source_url", "artifact_url")
        if isinstance(item.get(key), str)
        and re.fullmatch(
            r"/(?:artifacts/[0-9a-f-]+|drafts/packets/[0-9a-f-]+/citations/C[1-9][0-9]*)/",
            item[key],
        )
    }
    citations = {
        row.get("citation_id"): row["source_url"]
        for row in rows
        if row.get("source_url") in allowed
    }
    text = revision.text
    for marker in (
        DeterministicDraftingAdapter.evidence_start,
        DeterministicDraftingAdapter.evidence_end,
    ):
        text = text.replace(marker, "")
    tokens = {}
    prefix = "CITATION" + uuid.uuid4().hex

    def preserve(label, path):
        token = f"{prefix}TOKEN{len(tokens)}"
        tokens[token] = link(label, path)
        return token

    def inline(match):
        label, destination = match.groups()
        return (
            preserve(label, destination)
            if destination in allowed
            else f"{label} (unverified link omitted)"
        )

    text = re.sub(r"!?\[([^\]\n]+)\]\(([^)\n]+)\)", inline, text)
    text = re.sub(r"(?m)^\s*\[[^\]\n]+\]:[^\n]*", "(unverified link reference omitted)", text)

    def identity(match):
        citation_id = match.group(1)
        return (
            preserve(citation_id, citations[citation_id])
            if citation_id in citations
            else f"(unresolved citation {citation_id})"
        )

    text = re.sub(r"\[(C[1-9][0-9]*)\]", identity, text)
    text = escape(text)
    for token, rendered in tokens.items():
        text = text.replace(token, rendered)
    warnings = []
    if revision.reuse_state != "ready_for_reuse":
        warnings.append("REQUIRES SOURCE REVIEW — unresolved claims, assertions, or gaps.")
    if historical:
        warnings.append(
            "HISTORICAL EVIDENCE — saved sources or voice are no longer eligible for new drafting."
        )
    if warnings:
        text = "\n".join(warnings) + "\n\n" + text
    if source_appendix:
        text += "\n\n## Saved source appendix\n"
        for row in rows:
            label = f"{row.get('citation_id', 'Source')}: {row.get('title', '')} — {row.get('locator_label', '')} — version {row.get('source_version_id', '')}"
            text += "\n- " + escape(label)
            for key, title in (
                ("source_url", "Saved citation"),
                ("artifact_url", "Original source"),
            ):
                if row.get(key) in allowed:
                    text += " · " + link(title, row[key])
            text += "\n"
    return text
