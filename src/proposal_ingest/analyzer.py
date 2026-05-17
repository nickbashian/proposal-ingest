"""Batch document analysis — runs mock or real Bedrock for each eligible inventory record."""

from __future__ import annotations

import json
from pathlib import Path

from proposal_ingest.metadata_store import MetadataStore
from proposal_ingest.mock_bedrock import analyze_document_mock
from proposal_ingest.schemas import (
    DocumentMetadata,
    InventoryRecord,
)


def find_latest_inventory_jsonl(output_root: Path) -> Path | None:
    """Return the most recent file_inventory.jsonl under output_root/logs, or None."""
    logs_dir = output_root / "logs"
    if not logs_dir.is_dir():
        return None
    candidates = sorted(
        logs_dir.glob("run_*/inventory/file_inventory.jsonl"),
        key=lambda p: p.parts[-3],  # sort by run_id dir name
    )
    return candidates[-1] if candidates else None


def load_inventory_jsonl(path: Path) -> list[InventoryRecord]:
    """Deserialize an inventory JSONL file into InventoryRecord objects."""
    records: list[InventoryRecord] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(InventoryRecord.model_validate(json.loads(line)))
    return records


def analyze_inventory(
    run_dir: Path,
    inventory_records: list[InventoryRecord],
    run_id: str,
    *,
    use_mock: bool,
) -> list[DocumentMetadata]:
    """Analyze eligible inventory records and write metadata to run_dir.

    Args:
        run_dir: The run-scoped output directory (must already exist or be createable).
        inventory_records: All records from the scan inventory.
        run_id: The run identifier to embed in each DocumentMetadata record.
        use_mock: When True, calls ``analyze_document_mock``; when False, raises
                  NotImplementedError (real Bedrock is Phase 5+).

    Returns:
        List of DocumentMetadata objects produced (eligible documents only).
    """
    if not use_mock:
        raise NotImplementedError(
            "Real Bedrock analysis is not yet implemented. Use --mock-bedrock."
        )

    store = MetadataStore(run_dir)
    results: list[DocumentMetadata] = []

    eligible = [r for r in inventory_records if r.eligible_for_processing]

    for record in eligible:
        metadata = analyze_document_mock(record, run_id)
        store.write_document_metadata(metadata)
        results.append(metadata)

    return results


def analyze_from_output_root(
    output_root: Path,
    *,
    use_mock: bool,
) -> tuple[Path, list[DocumentMetadata]]:
    """Locate the latest scan inventory under output_root and analyze it.

    Returns:
        (run_dir, list of DocumentMetadata) for the run that was analyzed.

    Raises:
        FileNotFoundError: if no inventory JSONL is found under output_root/logs/.
    """
    inventory_path = find_latest_inventory_jsonl(output_root)
    if inventory_path is None:
        raise FileNotFoundError(
            f"No file_inventory.jsonl found under {output_root}/logs/. "
            "Run 'proposal-ingest scan' first."
        )

    run_dir = inventory_path.parent.parent  # .../logs/run_id/inventory/.. -> run_id dir
    run_id = run_dir.name

    records = load_inventory_jsonl(inventory_path)
    results = analyze_inventory(run_dir, records, run_id, use_mock=use_mock)

    # Update the run manifest to reflect Bedrock mode used
    manifest_path = run_dir / "run_manifest.json"
    if manifest_path.exists():
        import json as _json
        raw = _json.loads(manifest_path.read_text(encoding="utf-8"))
        raw["mock_bedrock"] = use_mock
        raw["command"] = "analyze"
        manifest_path.write_text(
            _json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    return run_dir, results
