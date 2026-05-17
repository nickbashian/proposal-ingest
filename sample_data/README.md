This folder contains synthetic fake proposal documents for local testing.
Real proposal documents must NEVER be placed here or committed to version control.

See docs/08_repo_and_dev_tooling.md (Sample data section) for the expected folder structure
and the types of fake files included for Phase 1-4 validation.

Expected structure:
  fake_source_root/
    2025/
      2025 Fake DOE SBIR Battery Project/
        Technical Volume FINAL.docx
        Budget.xlsx
        FOA Instructions.pdf
        Quad Chart.pdf
        Quad Chart.pptx        <-- should be marked superseded_by_pdf
        Support Letter.docx
    General/
      Empower Grant Activities/
        Grants In Progress/
          fake_grants_tracker.xlsx

The checked-in files are plain-text stand-ins with proposal-like filenames. They are
intended for scanner, inventory, schema, and mock-analysis validation only. Later
extractor tests should add format-appropriate fixtures when real PDF/DOCX/XLSX parsing
is exercised.
