"""Immutable local object storage; keys never contain source names or paths."""

import hashlib
import os
import re
import tempfile
from pathlib import Path


class LocalObjectStorage:
    def __init__(self, output_root: Path):
        self.root = output_root.resolve()

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
        self.root.mkdir(parents=True, exist_ok=True)
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
        return digest

    def get(self, key: str) -> bytes:
        content = self._path(key).read_bytes()
        if hashlib.sha256(content).hexdigest() != key:
            raise ValueError("Stored object hash mismatch")
        return content
