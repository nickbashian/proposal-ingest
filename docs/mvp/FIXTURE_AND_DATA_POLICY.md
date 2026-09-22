# Fixture, evidence, and repository data policy

Git contains source code, configuration templates, and explicitly synthetic fixtures only. The
proposal archive is read-only and remains outside the repository. A treatment label or filename
change does not make private content safe to commit.

## Repository-safe material

- Fictional fixtures documented in `sample_data/PROVENANCE.md`.
- Aggregate counts, hashes, run identifiers, and sanitized implementation evidence.
- Empty configuration keys and unmistakable local-only/example values.

## Private storage only

- Original proposals, excerpts, extracted tables/figures, screenshots, and evaluations.
- Prompts or model responses containing private text.
- Credentials, account/tenant/resource identifiers, database dumps, and infrastructure state.
- Drafting output or citation packets derived from private sources.

The ignored directories `private_data/`, `private_evaluations/`, `private_screenshots/`,
`raw_model_responses/`, and `db_dumps/` are convenience boundaries, not access controls. The
canonical `make check` also scans tracked and untracked candidate files for common credentials and
forbidden private-artifact paths. Any false positive must be removed or narrowly justified in the
scanner; do not weaken a pattern globally to make a check pass.

CodeRabbit and public PR comments receive sanitized code and evidence only. Store real evaluation
artifacts privately and cite an opaque artifact identifier in implementation reports.
