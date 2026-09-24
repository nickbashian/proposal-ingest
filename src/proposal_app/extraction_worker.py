"""Isolated local parser entry point; called only with private temporary files."""

from __future__ import annotations

import json
import base64
import sys
from dataclasses import asdict
from pathlib import Path

from .structured_extraction import extract_snapshot


def main() -> int:
    if len(sys.argv) != 5:
        return 2
    source_path, output_path, name, config_path = map(Path, sys.argv[1:])
    settings = json.loads(config_path.read_text(encoding="utf-8"))
    result = extract_snapshot(name.name, source_path.read_bytes(), settings)
    payload = asdict(result)
    for figure in payload["figures"]:
        figure["content"] = base64.b64encode(figure["content"]).decode("ascii")
    output_path.write_text(json.dumps(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
