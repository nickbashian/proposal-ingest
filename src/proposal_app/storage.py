"""Immutable local object storage; keys never contain source names or paths."""

import hashlib
import os
import re
import tempfile
from pathlib import Path

DIRECTORY_FSYNC = os.name != "nt"


def _sync_directory(path: Path):
    """Persist directory entries on the production POSIX filesystem."""
    if DIRECTORY_FSYNC:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class LocalObjectStorage:
    def __init__(self, output_root: Path, *, require_durable=False):
        if require_durable and not DIRECTORY_FSYNC:
            raise ValueError("Production local storage requires POSIX directory synchronization")
        self.root = output_root.resolve()

    def _ensure_root(self):
        missing = []
        directory = self.root
        while not directory.exists():
            missing.append(directory)
            directory = directory.parent
        for directory in reversed(missing):
            directory.mkdir(exist_ok=True)
            _sync_directory(directory.parent)

    def _path(self, key):
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise ValueError("Invalid object key")
        path = self.root / key
        if path.is_symlink():
            raise ValueError("Object must not be a symlink")
        return path

    def put_immutable(self, digest: str, content: bytes) -> str:
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("Object hash mismatch")
        path = self._path(digest)
        self._ensure_root()
        # Write/fsync a private temporary file, then atomically link without overwrite.
        # A competing writer can only install the same digest; verify existing bytes.
        with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException:
                stream.close()
                temporary.unlink(missing_ok=True)
                raise
        try:
            try:
                os.link(temporary, path)
            except FileExistsError:
                if self.get(digest) != content:
                    raise ValueError("Existing object differs") from None
        finally:
            temporary.unlink(missing_ok=True)
        # Also sync when another writer installed the object: its directory sync
        # might not have completed yet. Do not let the database commit first.
        _sync_directory(self.root)
        return digest

    def get(self, key: str) -> bytes:
        content = self._path(key).read_bytes()
        if hashlib.sha256(content).hexdigest() != key:
            raise ValueError("Stored object hash mismatch")
        return content
