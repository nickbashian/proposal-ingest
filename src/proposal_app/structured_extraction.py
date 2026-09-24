"""Bounded, source-faithful parsing of immutable snapshots.

The parser returns data only. Database writes, version selection, and reviewer annotations
belong to extraction_service. No parser has access to the source connector.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field, replace
from importlib.metadata import version as distribution_version
from pathlib import Path


@dataclass(frozen=True)
class ParsedUnit:
    key: str
    kind: str
    locator: dict
    text: str
    context: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedFigure:
    key: str
    locator: dict
    content: bytes
    mime_type: str
    caption: str = ""


@dataclass
class ExtractionResult:
    state: str
    reason: str
    recovery_action: str
    parser: str
    units: list[ParsedUnit] = field(default_factory=list)
    figures: list[ParsedFigure] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ExtractionLimit(ValueError):
    pass


def _limit(result: ExtractionResult, settings: dict) -> ExtractionResult:
    if (
        len(result.units) > settings["extraction_max_units"]
        or sum(len(unit.text) for unit in result.units) > settings["extraction_max_chars"]
    ):
        raise ExtractionLimit("extracted_unit_or_character_limit")
    if (
        len(result.figures) > settings["extraction_max_units"]
        or sum(len(figure.content) for figure in result.figures)
        > settings["extraction_max_uncompressed_bytes"]
    ):
        raise ExtractionLimit("figure_count_or_byte_limit")
    return result


def _check_archive(content: bytes, settings: dict) -> None:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        entries = archive.infolist()
        if len(entries) > settings["extraction_max_archive_entries"]:
            raise ExtractionLimit("archive_entry_limit")
        total = 0
        for entry in entries:
            total += entry.file_size
            if total > settings["extraction_max_uncompressed_bytes"]:
                raise ExtractionLimit("archive_uncompressed_limit")
            if entry.file_size > settings["extraction_max_source_bytes"]:
                raise ExtractionLimit("archive_member_limit")
            if entry.file_size and entry.compress_size == 0:
                raise ExtractionLimit("archive_compression_limit")
            if entry.file_size > 1000 * max(entry.compress_size, 1):
                raise ExtractionLimit("archive_compression_limit")


def _failure(reason: str, action: str, parser: str = "none") -> ExtractionResult:
    return ExtractionResult("failed", reason, action, parser)


def _attach_captions(units: list[ParsedUnit], figures: list[ParsedFigure]) -> list[ParsedFigure]:
    captions = [
        unit
        for unit in units
        if unit.kind == "caption" and re.match(r"^(?:Figure|Fig\.)\s+\d+", unit.text, re.I)
    ]
    attached = []
    for figure in figures:
        candidates = []
        for caption in captions:
            if "page" in figure.locator and caption.locator.get("page") == figure.locator["page"]:
                image_box = figure.locator.get("bbox")
                caption_box = caption.locator.get("bbox")
                if image_box and caption_box:
                    distance = min(
                        abs(caption_box[3] - image_box[1]), abs(caption_box[1] - image_box[3])
                    )
                    if distance <= 120:
                        candidates.append((distance, caption))
            elif "paragraph" in figure.locator and "paragraph" in caption.locator:
                distance = abs(caption.locator["paragraph"] - figure.locator["paragraph"])
                if distance <= 2:
                    candidates.append((distance, caption))
            elif (
                "slide" in figure.locator
                and caption.locator.get("slide") == figure.locator["slide"]
            ):
                distance = abs(caption.locator.get("shape", 0) - figure.locator.get("shape", 0))
                if distance <= 2:
                    candidates.append((distance, caption))
        if candidates:
            nearest = min(candidates, key=lambda item: item[0])[1]
            attached.append(
                replace(
                    figure,
                    caption=nearest.text,
                    locator={**figure.locator, "caption_key": nearest.key},
                )
            )
        else:
            attached.append(figure)
    return attached


def extract_snapshot(name: str, content: bytes, settings: dict) -> ExtractionResult:
    """Never label empty or partially parsed text as successful extraction."""
    suffix = Path(name).suffix.casefold()
    if len(content) > settings["extraction_max_source_bytes"]:
        return _failure("source_size_limit", "Defer or authorize a bounded local conversion.")
    if not content:
        return _failure("empty_file", "Inspect the source or defer it.")
    if suffix in {".doc", ".xls", ".ppt", ".rtf"}:
        return _failure(
            "legacy_format", "Authorize local conversion, then capture a new source version."
        )
    if suffix not in {".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".csv"}:
        return _failure("unsupported_format", "Defer or authorize a format-specific converter.")
    try:
        if suffix in {".docx", ".pptx", ".xlsx"}:
            _check_archive(content, settings)
        if suffix == ".pdf":
            result = _pdf(content, settings)
        elif suffix == ".docx":
            result = _docx(content, settings)
        elif suffix == ".pptx":
            result = _pptx(content, settings)
        elif suffix == ".xlsx":
            result = _xlsx(content, settings)
        else:
            result = _plain(content, suffix)
        result.figures = _attach_captions(result.units, result.figures)
        _limit(result, settings)
        if not result.units and result.state == "succeeded":
            if suffix == ".pdf" and result.figures:
                result.state = "scanned"
                result.reason = "no_selectable_text"
                result.recovery_action = (
                    "Request selective OCR or visual inspection for specific pages."
                )
            else:
                result.state = "failed"
                result.reason = "figure_only_non_pdf" if result.figures else "empty_extraction"
                result.recovery_action = (
                    "Inspect preserved figures manually or defer this source."
                    if result.figures
                    else "Try an alternate parser or defer this source."
                )
        return result
    except ExtractionLimit as exc:
        return _failure(str(exc), "Defer or use an authorized bounded conversion.")
    except Exception:
        # Provider/parser details can contain source bytes or paths. Persist a stable category.
        return _failure("malformed_or_unreadable", "Try an alternate parser or defer this source.")


def _pdf(content: bytes, settings: dict) -> ExtractionResult:
    import pymupdf

    document = pymupdf.open(stream=content, filetype="pdf")
    try:
        if document.needs_pass:
            return _failure("encrypted_pdf", "Obtain an authorized unencrypted copy.", "pymupdf")
        if document.page_count > settings["extraction_max_pages"]:
            raise ExtractionLimit("page_limit")
        result = ExtractionResult("succeeded", "", "", f"pymupdf-{pymupdf.VersionBind}")
        image_only_pages = []
        for page_index in range(document.page_count):
            page = document[page_index]
            page_number = page_index + 1
            page_units: list[ParsedUnit] = []
            tables = list(page.find_tables().tables)
            table_rects = [pymupdf.Rect(table.bbox) for table in tables]
            for table_index, table in enumerate(tables, 1):
                rows = table.extract()
                if not rows:
                    continue
                headers = [str(value or "") for value in rows[0]]
                for row_index, row in enumerate(rows, 1):
                    text = " | ".join(str(value or "") for value in row)
                    if text.strip(" |"):
                        page_units.append(
                            ParsedUnit(
                                f"p{page_number}-t{table_index}-r{row_index}",
                                "table_row",
                                {
                                    "page": page_number,
                                    "table": table_index,
                                    "row": row_index,
                                    "bbox": list(table.rows[row_index - 1].bbox),
                                },
                                text,
                                {"headers": headers, "units_as_printed": True},
                            )
                        )
            blocks = page.get_text("dict", sort=True).get("blocks", [])
            text_blocks = [block for block in blocks if block.get("type") == 0]
            sizes = [
                span.get("size", 0)
                for block in text_blocks
                for line in block.get("lines", [])
                for span in line.get("spans", [])
                if span.get("text", "").strip()
            ]
            typical_size = sorted(sizes)[len(sizes) // 2] if sizes else 0
            for block_index, block in enumerate(text_blocks, 1):
                bounds = pymupdf.Rect(block["bbox"])
                if any(
                    rect.contains(bounds)
                    or rect.intersects(bounds)
                    and (rect & bounds).get_area() >= bounds.get_area() * 0.8
                    for rect in table_rects
                ):
                    continue
                lines = []
                largest = 0.0
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    line_text = "".join(span.get("text", "") for span in spans)
                    if line_text.strip():
                        lines.append(line_text)
                        largest = max(largest, *(span.get("size", 0) for span in spans))
                text = "\n".join(lines).strip()
                if not text:
                    continue
                kind = "paragraph"
                if re.match(r"^(?:Figure|Fig\.|Table)\s+\d+", text, re.I):
                    kind = "caption"
                elif largest >= typical_size * 1.2 and len(text) < 180:
                    kind = "heading"
                page_units.append(
                    ParsedUnit(
                        f"p{page_number}-b{block_index}",
                        kind,
                        {"page": page_number, "block": block_index, "bbox": list(block["bbox"])},
                        text,
                        {"neighbor_page": page_number},
                        ["layout_order_inferred"] if len(text_blocks) > 1 else [],
                    )
                )
            result.units.extend(
                sorted(
                    page_units, key=lambda unit: (unit.locator["bbox"][1], unit.locator["bbox"][0])
                )
            )
            seen_images = set()
            page_images = page.get_images(full=True)
            if not page_units and page_images:
                image_only_pages.append(page_number)
            for image_index, image in enumerate(page_images, 1):
                xref = image[0]
                if xref in seen_images:
                    continue
                seen_images.add(xref)
                if image[2] * image[3] > settings["extraction_max_render_pixels"]:
                    result.warnings.append("figure_dimension_limit")
                    continue
                info = document.extract_image(xref)
                extension = info.get("ext", "")
                if extension not in {"png", "jpeg", "jpg", "tiff", "bmp"}:
                    result.warnings.append("unsupported_figure_encoding")
                    continue
                rectangles = page.get_image_rects(xref)
                for occurrence, rectangle in enumerate(rectangles or [None], 1):
                    result.figures.append(
                        ParsedFigure(
                            f"p{page_number}-image{image_index}-{occurrence}",
                            {
                                "page": page_number,
                                "image": image_index,
                                "bbox": list(rectangle) if rectangle else None,
                            },
                            info["image"],
                            "image/jpeg" if extension in {"jpeg", "jpg"} else f"image/{extension}",
                        )
                    )
        if image_only_pages:
            result.warnings.append("image_only_pages:" + ",".join(map(str, image_only_pages)))
            if not result.units:
                result.state = "scanned"
                result.reason = "no_selectable_text"
                result.recovery_action = (
                    "Request selective OCR or visual inspection for specific pages."
                )
        return result
    finally:
        document.close()


def _docx(content: bytes, settings: dict) -> ExtractionResult:
    from docx import Document
    from docx.table import Table

    document = Document(io.BytesIO(content))
    result = ExtractionResult(
        "succeeded", "", "", f"python-docx-{distribution_version('python-docx')}"
    )
    section = ""
    paragraph_number = 0
    table_number = 0

    def capture_images(paragraph, locator):
        for image_index, blip in enumerate(paragraph._p.xpath(".//a:blip"), 1):
            relationship = blip.get(
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
            )
            if not relationship or relationship not in document.part.related_parts:
                continue
            part = document.part.related_parts[relationship]
            if part.content_type not in {"image/png", "image/jpeg", "image/tiff", "image/bmp"}:
                result.warnings.append("unsupported_figure_encoding")
                continue
            result.figures.append(
                ParsedFigure(
                    f"figure-{len(result.figures) + 1}",
                    {**locator, "image": image_index},
                    part.blob,
                    part.content_type,
                )
            )

    for item in document.iter_inner_content():
        if isinstance(item, Table):
            table_number += 1
            headers = [cell.text for cell in item.rows[0].cells] if item.rows else []
            for row_number, row in enumerate(item.rows, 1):
                for cell_number, cell in enumerate(row.cells, 1):
                    locator = {
                        "section": section,
                        "table": table_number,
                        "row": row_number,
                        "cell": cell_number,
                    }
                    if cell.text.strip():
                        result.units.append(
                            ParsedUnit(
                                f"table{table_number}-r{row_number}-c{cell_number}",
                                "table_cell",
                                locator,
                                cell.text,
                                {"headers": headers, "units_as_printed": True},
                            )
                        )
                    for paragraph in cell.paragraphs:
                        capture_images(paragraph, locator)
            continue
        paragraph_number += 1
        if item.style and item.style.name.lower().startswith("heading"):
            section = item.text.strip()
            kind = "heading"
        elif re.match(r"^(?:Figure|Fig\.|Table)\s+\d+", item.text.strip(), re.I):
            kind = "caption"
        else:
            kind = "paragraph"
        locator = {"section": section, "paragraph": paragraph_number}
        if item.text.strip():
            result.units.append(
                ParsedUnit(f"paragraph-{paragraph_number}", kind, locator, item.text, {})
            )
        capture_images(item, locator)
    return result


def _pptx(content: bytes, settings: dict) -> ExtractionResult:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    presentation = Presentation(io.BytesIO(content))
    if len(presentation.slides) > settings["extraction_max_pages"]:
        raise ExtractionLimit("slide_limit")
    result = ExtractionResult(
        "succeeded", "", "", f"python-pptx-{distribution_version('python-pptx')}"
    )
    for slide_number, slide in enumerate(presentation.slides, 1):
        for shape_number, shape in enumerate(slide.shapes, 1):
            locator = {"slide": slide_number, "shape": shape_number}
            if shape.has_text_frame and shape.text.strip():
                kind = (
                    "caption"
                    if re.match(r"^(?:Figure|Fig\.|Table)\s+\d+", shape.text.strip(), re.I)
                    else "slide_text"
                )
                result.units.append(
                    ParsedUnit(
                        f"s{slide_number}-shape{shape_number}",
                        kind,
                        locator,
                        shape.text,
                        {},
                    )
                )
            if shape.has_table:
                headers = [cell.text for cell in shape.table.rows[0].cells]
                for row_number, row in enumerate(shape.table.rows, 1):
                    for cell_number, cell in enumerate(row.cells, 1):
                        if cell.text.strip():
                            result.units.append(
                                ParsedUnit(
                                    f"s{slide_number}-t{shape_number}-r{row_number}-c{cell_number}",
                                    "table_cell",
                                    {**locator, "row": row_number, "cell": cell_number},
                                    cell.text,
                                    {"headers": headers, "units_as_printed": True},
                                )
                            )
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                image = shape.image
                if image.content_type in {"image/png", "image/jpeg", "image/tiff", "image/bmp"}:
                    result.figures.append(
                        ParsedFigure(
                            f"s{slide_number}-image{shape_number}",
                            locator,
                            image.blob,
                            image.content_type,
                        )
                    )
                else:
                    result.warnings.append("unsupported_figure_encoding")
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame
            if notes and notes.text.strip():
                result.units.append(
                    ParsedUnit(
                        f"s{slide_number}-notes",
                        "notes",
                        {"slide": slide_number, "notes": True},
                        notes.text,
                        {},
                    )
                )
    return result


def _xlsx(content: bytes, settings: dict) -> ExtractionResult:
    from openpyxl import load_workbook

    source = io.BytesIO(content)
    workbook = load_workbook(source, read_only=True, data_only=False)
    values = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    result = ExtractionResult("succeeded", "", "", f"openpyxl-{distribution_version('openpyxl')}")
    try:
        if len(workbook.worksheets) > settings["extraction_max_pages"]:
            raise ExtractionLimit("sheet_limit")
        cells_seen = 0
        for sheet in workbook.worksheets:
            if (sheet.max_row or 0) * (sheet.max_column or 0) > settings[
                "extraction_max_spreadsheet_cells"
            ]:
                raise ExtractionLimit("spreadsheet_cell_limit")
            value_sheet = values[sheet.title]
            for row, value_row in zip(sheet.iter_rows(), value_sheet.iter_rows()):
                entries = []
                formula_cells = []
                for cell, value_cell in zip(row, value_row):
                    cells_seen += 1
                    if cells_seen > settings["extraction_max_spreadsheet_cells"]:
                        raise ExtractionLimit("spreadsheet_cell_limit")
                    if cell.value is None:
                        continue
                    value = str(cell.value)
                    if cell.data_type == "f":
                        cached = value_cell.value
                        formula_cells.append(
                            {"cell": cell.coordinate, "formula": value, "cached_value": cached}
                        )
                        value = (
                            f"{value} [cached: {cached if cached is not None else 'unavailable'}]"
                        )
                    entries.append(f"{cell.coordinate}: {value}")
                if entries:
                    row_number = next(cell.row for cell in row if cell.value is not None)
                    result.units.append(
                        ParsedUnit(
                            f"sheet-{sheet.title}-row-{row_number}",
                            "spreadsheet_row",
                            {
                                "sheet": sheet.title,
                                "row": row_number,
                                "cells": [
                                    cell.coordinate for cell in row if cell.value is not None
                                ],
                            },
                            " | ".join(entries),
                            {"formula_cells": formula_cells},
                            ["formula_cached_value_not_recalculated"] if formula_cells else [],
                        )
                    )
        return result
    finally:
        workbook.close()
        values.close()


def _plain(content: bytes, suffix: str) -> ExtractionResult:
    text = content.decode("utf-8", errors="replace")
    result = ExtractionResult("succeeded", "", "", "utf8-lines-v1")
    for number, line in enumerate(text.splitlines(), 1):
        if line.strip():
            result.units.append(
                ParsedUnit(
                    f"line-{number}",
                    "line",
                    {"line": number},
                    line,
                    {},
                    ["replacement_character"] if "\ufffd" in line else [],
                )
            )
    return result
