"""Helpers for stable SHA-256 hashes and content-derived IDs."""

from __future__ import annotations

import hashlib
from pathlib import Path

_READ_CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
	"""Return the SHA-256 hex digest for a file."""
	digest = hashlib.sha256()
	with path.open("rb") as handle:
		for chunk in iter(lambda: handle.read(_READ_CHUNK_SIZE), b""):
			digest.update(chunk)
	return digest.hexdigest()


def document_id_from_sha256(sha256_hex: str) -> str:
	"""Return a stable document ID derived from a SHA-256 digest."""
	return f"doc_{sha256_hex[:16]}"
