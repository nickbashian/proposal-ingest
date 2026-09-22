# Synthetic fixture provenance

Everything under `sample_data/` is synthetic test material created for this repository. It does
not contain copied proposal text, customer records, personal information, credentials, or output
from the private archive.

| Fixture set | Purpose | Provenance |
|---|---|---|
| `fake_source_root/` | Scanner, extraction, review-loop, and mock-pipeline tests | Hand-created synthetic office files and tracker rows |
| `quality_benchmark/` | Deterministic proposal-level quality and exclusion tests | Hand-created fictional battery-proposal scenarios |
| `application_slice/` | MVP-02 review, publication, retrieval, drafting, and export workflow | Hand-created fictional passages with one exclusion and one voice-only item |

Before adding or changing a fixture:

1. Create it from fictional content; do not sanitize and copy private source prose.
2. Avoid real names, contact details, account identifiers, secrets, and screenshots.
3. Document its purpose here or in the fixture set's README.
4. Run `make secrets` and the relevant tests.
5. Keep real evaluation cases, screenshots, prompts, and model responses only in approved private
   storage and reference them by a sanitized artifact identifier.
