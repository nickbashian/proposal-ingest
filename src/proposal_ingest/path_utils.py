"""Path and ID helpers used by the early pipeline phases."""

from __future__ import annotations

import hashlib
import re

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_WHITESPACE_RE = re.compile(r"\s+")


def slugify(value: str) -> str:
    """Return a lowercase ASCII-ish slug suitable for stable IDs."""
    normalized = value.strip().lower()
    slug = _SLUG_RE.sub("-", normalized).strip("-")
    return slug or "item"


def short_hash(value: str, *, length: int = 8) -> str:
    """Return a short, stable hash for an input string."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def proposal_id_from_branch(
    *, year_folder: str, proposal_branch_name: str, relative_branch_path: str
) -> str:
    """Return a stable proposal ID for a branch path."""
    branch_slug = slugify(f"{year_folder}__{proposal_branch_name}")
    branch_hash = short_hash(relative_branch_path)
    return f"prop_{branch_slug}__{branch_hash}"


def sanitize_filename(filename: str) -> str:
    """Return a filesystem-safe filename while preserving most of the original name."""
    sanitized = _SAFE_FILENAME_RE.sub("_", filename)
    sanitized = _WHITESPACE_RE.sub("_", sanitized).strip("._")
    return sanitized or "file"
