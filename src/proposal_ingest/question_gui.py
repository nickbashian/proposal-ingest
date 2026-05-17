"""Small Tkinter GUI for answering review-question CSV rows."""

from __future__ import annotations

import csv
from functools import partial
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import tempfile

from proposal_ingest.question_loop import REVIEW_COLUMNS
from proposal_ingest.schemas import QuestionStatus


@dataclass(frozen=True)
class QuestionChoiceModel:
    """Display-ready choice metadata for one question row."""

    choices: tuple[str, ...]
    allow_multiple: bool


def load_question_rows(csv_path: Path) -> list[dict[str, str]]:
    """Load question rows from a review CSV."""
    with csv_path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_question_rows(csv_path: Path, rows: list[dict[str, str]]) -> None:
    """Rewrite a review CSV after GUI edits while preserving known review columns."""
    fieldnames = _fieldnames_for_rows(rows)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=csv_path.parent,
        prefix=f".{csv_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        temp_path = Path(handle.name)
    try:
        temp_path.replace(csv_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def answer_row(
    row: dict[str, str], answer: str, *, status: str = QuestionStatus.answered.value
) -> None:
    """Set an answer on a question row and mark it ready for deterministic apply-answers."""
    row["user_answer"] = answer.strip()
    row["status"] = status
    row["updated_at"] = datetime.now(UTC).isoformat()


def skip_row(row: dict[str, str]) -> None:
    """Mark a question row as intentionally skipped."""
    row["status"] = QuestionStatus.skipped.value
    row["updated_at"] = datetime.now(UTC).isoformat()


def choices_for_row(row: dict[str, str]) -> QuestionChoiceModel:
    """Return normalized option-button choices for a question row."""
    answer_type = (row.get("answer_type") or "").strip().lower()
    raw_options = row.get("suggested_options") or ""
    choices = _parse_suggested_options(raw_options)
    if answer_type == "boolean" and not choices:
        choices = ["true", "false"]
    return QuestionChoiceModel(choices=tuple(choices), allow_multiple=answer_type == "list")


def launch_questions_gui(csv_path: Path) -> None:
    """Launch a minimal one-question-at-a-time GUI for a questions CSV."""
    # Import Tkinter lazily so headless/test environments can exercise the CSV logic.
    import tkinter as tk
    from tkinter import messagebox
    from tkinter import ttk

    rows = load_question_rows(csv_path)
    if not rows:
        raise ValueError(f"No question rows found in {csv_path}")

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise RuntimeError(
            "Tkinter GUI could not be initialized. Ensure a GUI display is available."
        ) from exc
    root.title(f"Proposal Questions - {csv_path.name}")
    root.geometry("820x560")

    current_index = tk.IntVar(value=0)
    answer_value = tk.StringVar()
    status_value = tk.StringVar()
    progress_value = tk.StringVar()
    context_value = tk.StringVar()
    field_value = tk.StringVar()
    priority_value = tk.StringVar()
    guess_value = tk.StringVar()

    main = ttk.Frame(root, padding=16)
    main.grid(row=0, column=0, sticky="nsew")
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    main.columnconfigure(0, weight=1)

    top = ttk.Frame(main)
    top.grid(row=0, column=0, sticky="ew")
    top.columnconfigure(1, weight=1)
    ttk.Button(top, text="← Previous", command=lambda: move(-1)).grid(row=0, column=0, padx=(0, 8))
    ttk.Label(top, textvariable=progress_value, anchor="center").grid(row=0, column=1, sticky="ew")
    ttk.Button(top, text="Next →", command=lambda: move(1)).grid(row=0, column=2, padx=(8, 0))

    meta = ttk.LabelFrame(main, text="Question context", padding=12)
    meta.grid(row=1, column=0, sticky="ew", pady=(16, 8))
    meta.columnconfigure(1, weight=1)
    ttk.Label(meta, text="File / branch:").grid(row=0, column=0, sticky="w")
    ttk.Label(meta, textvariable=context_value, wraplength=650).grid(row=0, column=1, sticky="w")
    ttk.Label(meta, text="Field:").grid(row=1, column=0, sticky="w")
    ttk.Label(meta, textvariable=field_value).grid(row=1, column=1, sticky="w")
    ttk.Label(meta, text="Priority:").grid(row=2, column=0, sticky="w")
    ttk.Label(meta, textvariable=priority_value).grid(row=2, column=1, sticky="w")
    ttk.Label(meta, text="Status:").grid(row=3, column=0, sticky="w")
    ttk.Label(meta, textvariable=status_value).grid(row=3, column=1, sticky="w")

    question_text = tk.Text(main, height=5, wrap="word", font=("TkDefaultFont", 12))
    question_text.grid(row=2, column=0, sticky="nsew", pady=(8, 8))
    question_text.configure(state="disabled")
    main.rowconfigure(2, weight=1)

    guess_frame = ttk.Frame(main)
    guess_frame.grid(row=3, column=0, sticky="ew", pady=(0, 8))
    guess_frame.columnconfigure(1, weight=1)
    ttk.Label(guess_frame, text="Suggested answer:").grid(row=0, column=0, sticky="w")
    ttk.Label(guess_frame, textvariable=guess_value, wraplength=520).grid(
        row=0, column=1, sticky="w", padx=(8, 8)
    )
    accept_button = ttk.Button(
        guess_frame, text="Accept suggestion", command=lambda: accept_guess()
    )
    accept_button.grid(row=0, column=2, sticky="e")

    options_frame = ttk.LabelFrame(main, text="Choices", padding=8)
    options_frame.grid(row=4, column=0, sticky="ew", pady=(0, 8))

    answer_frame = ttk.Frame(main)
    answer_frame.grid(row=5, column=0, sticky="ew")
    answer_frame.columnconfigure(1, weight=1)
    ttk.Label(answer_frame, text="Your answer:").grid(row=0, column=0, sticky="w")
    ttk.Entry(answer_frame, textvariable=answer_value).grid(row=0, column=1, sticky="ew", padx=8)
    ttk.Button(answer_frame, text="Save answer", command=lambda: save_answer()).grid(
        row=0, column=2, padx=(0, 8)
    )
    ttk.Button(answer_frame, text="Skip", command=lambda: skip_current()).grid(row=0, column=3)

    ttk.Button(main, text="Save CSV and close", command=lambda: close()).grid(
        row=6, column=0, sticky="e", pady=(16, 0)
    )

    def current_row() -> dict[str, str]:
        return rows[current_index.get()]

    def refresh() -> None:
        row = current_row()
        progress_value.set(f"Question {current_index.get() + 1} of {len(rows)}")
        context_value.set(_context_label(row))
        field_value.set(row.get("field") or "(not specified)")
        priority_value.set(row.get("priority") or "medium")
        status_value.set(row.get("status") or QuestionStatus.open.value)
        guess_value.set(row.get("model_guess") or "(none)")
        answer_value.set(row.get("user_answer") or "")
        question_text.configure(state="normal")
        question_text.delete("1.0", "end")
        question_text.insert("1.0", row.get("question") or "")
        question_text.configure(state="disabled")
        for child in options_frame.winfo_children():
            child.destroy()
        choice_model = choices_for_row(row)
        if not choice_model.choices:
            ttk.Label(options_frame, text="No controlled choices for this question.").grid(
                row=0, column=0, sticky="w"
            )
        else:
            for index, choice in enumerate(choice_model.choices):
                ttk.Button(
                    options_frame,
                    text=choice,
                    command=partial(choose_option, choice, choice_model.allow_multiple),
                ).grid(row=index // 4, column=index % 4, sticky="w", padx=4, pady=4)
        accept_button.state(
            ["!disabled"] if (row.get("model_guess") or "").strip() else ["disabled"]
        )

    def move(delta: int) -> None:
        if _sync_answer_draft(current_row(), answer_value.get()):
            write_question_rows(csv_path, rows)
        next_index = min(max(current_index.get() + delta, 0), len(rows) - 1)
        current_index.set(next_index)
        refresh()

    def accept_guess() -> None:
        guess = (current_row().get("model_guess") or "").strip()
        if not guess:
            messagebox.showinfo("No suggestion", "This question does not have a suggested answer.")
            return
        answer_row(current_row(), guess)
        write_question_rows(csv_path, rows)
        refresh()

    def choose_option(selected: str, allow_multiple: bool) -> None:
        if allow_multiple:
            existing = _parse_suggested_options(answer_value.get())
            if selected not in existing:
                existing.append(selected)
            answer_value.set(" | ".join(existing))
            return
        answer_value.set(selected)
        answer_row(current_row(), selected)
        write_question_rows(csv_path, rows)
        refresh()

    def save_answer() -> None:
        answer = answer_value.get().strip()
        if not answer:
            messagebox.showinfo("Missing answer", "Enter an answer, pick a choice, or click Skip.")
            return
        answer_row(current_row(), answer)
        write_question_rows(csv_path, rows)
        refresh()

    def skip_current() -> None:
        skip_row(current_row())
        write_question_rows(csv_path, rows)
        refresh()

    def close() -> None:
        if _sync_answer_draft(current_row(), answer_value.get()):
            write_question_rows(csv_path, rows)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    refresh()
    root.mainloop()


def _parse_suggested_options(raw_options: str) -> list[str]:
    cleaned = raw_options.strip()
    if not cleaned:
        return []
    if cleaned.startswith("[") and cleaned.endswith("]"):
        # Keep parsing deliberately simple: exported review CSVs use pipe-delimited text.
        cleaned = cleaned.removeprefix("[").removesuffix("]")
    delimiter = "|" if "|" in cleaned else ","
    return [option.strip().strip("\"'") for option in cleaned.split(delimiter) if option.strip()]


def _sync_answer_draft(row: dict[str, str], answer: str) -> bool:
    """Copy the entry-field answer into a row in place and return whether it changed."""
    normalized_answer = answer.strip()
    if normalized_answer == (row.get("user_answer") or ""):
        return False
    row["user_answer"] = normalized_answer
    row["updated_at"] = datetime.now(UTC).isoformat()
    return True


def _fieldnames_for_rows(rows: list[dict[str, str]]) -> list[str]:
    extras = sorted({key for row in rows for key in row if key not in REVIEW_COLUMNS})
    return [*REVIEW_COLUMNS, *extras]


def _context_label(row: dict[str, str]) -> str:
    branch = row.get("proposal_branch") or "(unknown branch)"
    file_name = row.get("file_name_original") or "(unknown file)"
    return f"{branch} / {file_name}"
