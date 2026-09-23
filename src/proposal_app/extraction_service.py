"""Versioned extraction and selective visual inspection over captured snapshots."""

from __future__ import annotations

import hashlib
import base64
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.http import Http404

from . import models as m, services, source_sync
from .storage import LocalObjectStorage
from .structured_extraction import ExtractionResult, ParsedFigure, ParsedUnit


def _snapshot_name(version: m.SourceVersion) -> str:
    return Path(version.observed_path or version.source.display_path).name


def extraction_fingerprint(version: m.SourceVersion) -> str:
    relevant = {
        key: settings.APP[key]
        for key in settings.APP
        if key.startswith("extraction_") and key != "extraction_schema_revision"
    }
    revision = (
        settings.APP["extraction_revision"]
        + ":"
        + hashlib.sha256(json.dumps(relevant, sort_keys=True).encode()).hexdigest()[:16]
    )
    # Filename extension selects the parser and must participate in reuse decisions.
    revision += ":" + Path(_snapshot_name(version)).suffix.casefold()
    return source_sync.work_fingerprint(
        "extract",
        source_digest=version.blob.sha256,
        revisions={"extractor": revision, "schema": settings.APP["extraction_schema_revision"]},
    )


def _store_figure(content: bytes) -> m.ContentBlob:
    digest = hashlib.sha256(content).hexdigest()
    key = LocalObjectStorage(
        settings.LOCAL_STORAGE_ROOT, require_durable=settings.MODE == "production"
    ).put_immutable(digest, content)
    blob, _ = m.ContentBlob.objects.get_or_create(
        sha256=digest, defaults={"size": len(content), "storage_key": key}
    )
    if blob.size != len(content) or blob.storage_key != key:
        raise ValueError("Figure storage metadata mismatch")
    return blob


def _parse_bounded(name: str, content: bytes) -> ExtractionResult:
    """Kill parser CPU work after the configured timeout, without touching sources."""
    root = settings.LOCAL_STORAGE_ROOT.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as directory:
        folder = Path(directory)
        source_path = folder / "snapshot.bin"
        output_path = folder / "result.json"
        config_path = folder / "limits.json"
        source_path.write_bytes(content)
        config_path.write_text(json.dumps(settings.APP), encoding="utf-8")
        try:
            call = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "proposal_app.extraction_worker",
                    str(source_path),
                    str(output_path),
                    name,
                    str(config_path),
                ],
                capture_output=True,
                timeout=settings.APP["extraction_parser_timeout_seconds"],
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ExtractionResult(
                "failed",
                "parser_timeout",
                "Try an alternate parser or defer this source.",
                "isolated-worker",
            )
        except OSError:
            return ExtractionResult(
                "failed",
                "parser_worker_unavailable",
                "Restore the local parser runtime.",
                "isolated-worker",
            )
        if call.returncode or not output_path.is_file():
            return ExtractionResult(
                "failed",
                "parser_worker_error",
                "Try an alternate parser or defer this source.",
                "isolated-worker",
            )
        try:
            if output_path.stat().st_size > (
                settings.APP["extraction_max_uncompressed_bytes"] * 2
                + settings.APP["extraction_max_chars"] * 4
            ):
                raise ValueError("Oversized parser result")
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            result = ExtractionResult(
                state=payload["state"],
                reason=payload["reason"],
                recovery_action=payload["recovery_action"],
                parser=payload["parser"],
                units=[ParsedUnit(**unit) for unit in payload["units"]],
                figures=[
                    ParsedFigure(
                        **{**figure, "content": base64.b64decode(figure["content"], validate=True)}
                    )
                    for figure in payload["figures"]
                ],
                warnings=payload["warnings"],
            )
        except (ValueError, KeyError, TypeError, UnicodeError, OSError):
            return ExtractionResult(
                "failed",
                "parser_worker_error",
                "Try an alternate parser or defer this source.",
                "isolated-worker",
            )
        return result


@transaction.atomic
def extract_version(user, version_id, *, force: bool = False) -> m.ExtractionRun:
    version = m.SourceVersion.objects.select_related("source", "blob").filter(pk=version_id).first()
    if version is None:
        raise Http404
    services.authorize(user, version.source.collection_id)
    # Serialize concurrent extraction for one version, including cache lookup and activation.
    m.SourceVersion.objects.select_for_update().get(pk=version.pk)
    fingerprint = extraction_fingerprint(version)
    if not force:
        cached = (
            m.ExtractionRun.objects.filter(version=version, fingerprint=fingerprint)
            .order_by("-number")
            .first()
        )
        if cached is not None:
            return cached
    number = (
        m.ExtractionRun.objects.filter(version=version).aggregate(Max("number"))["number__max"] or 0
    ) + 1
    try:
        content = LocalObjectStorage(
            settings.LOCAL_STORAGE_ROOT, require_durable=settings.MODE == "production"
        ).get(version.blob.storage_key)
        if (
            len(content) != version.blob.size
            or hashlib.sha256(content).hexdigest() != version.blob.sha256
        ):
            raise ValueError("Snapshot metadata mismatch")
    except (OSError, ValueError):
        content = None
    result = _parse_bounded(_snapshot_name(version), content) if content is not None else None
    run = m.ExtractionRun.objects.create(
        version=version,
        number=number,
        fingerprint=fingerprint,
        extractor_revision=settings.APP["extraction_revision"],
        parser=result.parser if result else "none",
        state=result.state if result else "failed",
        reason=result.reason if result else "snapshot_unavailable",
        recovery_action=(
            result.recovery_action
            if result
            else "Restore the verified source snapshot, then retry extraction."
        ),
        warnings=result.warnings if result else [],
    )
    if result:
        # Unit identities include run number. Prior citations keep their original UUIDs.
        unit_revision = f"{settings.APP['extraction_revision']}:{fingerprint[:12]}:r{number}"
        m.ExtractedUnit.objects.bulk_create(
            [
                m.ExtractedUnit(
                    version=version,
                    extraction_run=run,
                    extractor_revision=unit_revision,
                    key=unit.key,
                    kind=unit.kind,
                    locator=unit.locator,
                    text=unit.text,
                    context=unit.context,
                    warnings=unit.warnings,
                    ordinal=ordinal,
                    support_kind="factual" if result.state == "succeeded" else "unusable",
                )
                for ordinal, unit in enumerate(result.units, 1)
            ]
        )
        for figure in result.figures:
            m.FigureAsset.objects.create(
                run=run,
                key=figure.key,
                locator=figure.locator,
                blob=_store_figure(figure.content),
                mime_type=figure.mime_type,
                caption=figure.caption,
            )
    if run.state == "succeeded":
        m.ExtractionRun.objects.filter(version=version, active=True).update(active=False)
        run.active = True
        run.save(update_fields=["active"])
    m.AuditRecord.objects.create(
        actor=user,
        action="extraction.completed",
        object_id=run.id,
        details={"state": run.state, "reason": run.reason, "number": number},
    )
    return run


@transaction.atomic
def request_visual(
    user, run_id, *, kind: str, locator: dict, figure_id=None, expected_version_id=None
):
    run = m.ExtractionRun.objects.select_related("version__source").filter(pk=run_id).first()
    if run is None:
        raise Http404
    services.authorize(user, run.version.source.collection_id)
    if expected_version_id is not None and str(run.version_id) != str(expected_version_id):
        raise Http404
    if kind not in {"ocr", "figure"}:
        raise ValueError("Unsupported inspection kind")
    figure = None
    if figure_id:
        figure = m.FigureAsset.objects.filter(pk=figure_id, run=run).first()
        if figure is None:
            raise Http404
    if kind == "figure" and figure is None:
        raise ValueError("Select one preserved figure")
    if kind == "ocr" and figure is not None:
        raise ValueError("OCR uses a page locator")
    if kind == "ocr" and (run.state != "scanned" or not locator.get("page")):
        raise ValueError("Select a page from an unreadable PDF")
    if kind == "ocr":
        import pymupdf

        content = LocalObjectStorage(settings.LOCAL_STORAGE_ROOT).get(run.version.blob.storage_key)
        with pymupdf.open(stream=content, filetype="pdf") as document:
            page_number = locator["page"]
            if (
                not isinstance(page_number, int)
                or page_number < 1
                or page_number > document.page_count
            ):
                raise ValueError("Select a page in the captured PDF")
    m.SourceVersion.objects.select_for_update().get(pk=run.version_id)
    existing = m.VisualInspection.objects.filter(
        run=run, figure=figure, kind=kind, locator=locator
    ).first()
    if existing is not None:
        return existing
    if (
        m.VisualInspection.objects.filter(run__version=run.version).count()
        >= settings.APP["extraction_max_visual_tasks_per_version"]
    ):
        raise ValueError("Selective visual inspection limit reached")
    task = m.VisualInspection.objects.create(
        run=run,
        figure=figure,
        kind=kind,
        locator=locator,
        actor=user,
    )
    return task


@transaction.atomic
def complete_visual(user, task_id, *, text: str, source_check: str, expected_version_id=None):
    task = (
        m.VisualInspection.objects.select_for_update()
        .select_related("run__version__source")
        .filter(pk=task_id)
        .first()
    )
    if task is None:
        raise Http404
    services.authorize(user, task.run.version.source.collection_id)
    if expected_version_id is not None and str(task.run.version_id) != str(expected_version_id):
        raise Http404
    if task.state not in {"requested", "needs_source_check"}:
        raise ValueError("Inspection is already complete")
    if not text.strip() or not source_check.strip():
        raise ValueError("Interpretation and source check are required")
    if len(text) > settings.APP["extraction_max_visual_text_chars"]:
        raise ValueError("Interpretation exceeds the configured character limit")
    task.interpretation = text.strip()
    task.source_check = source_check.strip()
    task.state = "source_checked"
    task.actor = user
    task.save(update_fields=["interpretation", "source_check", "state", "actor"])
    m.AuditRecord.objects.create(
        actor=user,
        action="visual.source_checked",
        object_id=task.id,
        details={"kind": task.kind, "source_version_id": str(task.run.version_id)},
    )
    return task


@transaction.atomic
def run_selective_ocr(user, task_id, *, expected_version_id=None):
    """Use optional local OCR on one captured PDF page, pending a human source check."""
    import pymupdf

    task = (
        m.VisualInspection.objects.select_for_update()
        .select_related("run__version__source", "run__version__blob")
        .filter(pk=task_id)
        .first()
    )
    if task is None:
        raise Http404
    services.authorize(user, task.run.version.source.collection_id)
    if expected_version_id is not None and str(task.run.version_id) != str(expected_version_id):
        raise Http404
    if task.kind != "ocr" or task.state != "requested":
        raise ValueError("OCR task is not awaiting an adapter")
    executable = settings.APP.get("extraction_ocr_executable")
    if not executable or not shutil.which(executable):
        raise ValueError("Local OCR is unavailable; use manual source inspection or defer")
    page_number = task.locator.get("page")
    if not isinstance(page_number, int) or page_number < 1:
        raise ValueError("Select a valid page")
    version = task.run.version
    content = LocalObjectStorage(settings.LOCAL_STORAGE_ROOT).get(version.blob.storage_key)
    document = pymupdf.open(stream=content, filetype="pdf")
    try:
        if document.needs_pass or page_number > document.page_count:
            raise ValueError("Selected page is unavailable")
        page = document[page_number - 1]
        zoom = settings.APP["extraction_ocr_dpi"] / 72
        if (
            page.rect.width * page.rect.height * zoom * zoom
            > settings.APP["extraction_max_render_pixels"]
        ):
            raise ValueError("Selected page exceeds render pixel limit")
        image = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).tobytes("png")
    finally:
        document.close()
    root = settings.LOCAL_STORAGE_ROOT.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as directory:
        image_path = Path(directory) / "selected-page.png"
        image_path.write_bytes(image)
        try:
            call = subprocess.run(
                [executable, str(image_path), "stdout"],
                capture_output=True,
                text=True,
                timeout=settings.APP["extraction_ocr_timeout_seconds"],
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError("Local OCR failed or timed out; use manual inspection") from None
    if call.returncode or not call.stdout.strip():
        raise ValueError("Local OCR returned no readable text; use manual inspection")
    if len(call.stdout) > settings.APP["extraction_max_visual_text_chars"]:
        raise ValueError("OCR text exceeds the selective inspection limit")
    task.interpretation = call.stdout.strip()
    task.adapter_revision = "local-ocr-v1"
    task.state = "needs_source_check"
    task.save(update_fields=["interpretation", "adapter_revision", "state"])
    return task
