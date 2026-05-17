This folder will contain synthetic fake proposal documents for local testing.
Real proposal documents must NEVER be placed here or committed to version control.

See docs/08_repo_and_dev_tooling.md (Sample data section) for the expected folder structure
and the types of fake files to create before running Phase 1 tests.

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

These files will be created as part of the Phase 1 (scanner) implementation.
