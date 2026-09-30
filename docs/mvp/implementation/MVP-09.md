# MVP-09 implementation and acceptance record

Base: merged `main` at `2a6d6d3` (MVP-07). This branch prepares a private,
offline acceptance harness; MVP-09 depends on the live MVP-08 connection and
three approved seed families. No private files or provider services were used.

| ID | Current status | Evidence required to close |
|---|---|---|
| 09-A | Pending live corpus audit | Complete recursive inventories and disposition/recovery for all three families; audit locators, exclusions, figures, and versions. |
| 09-B | Pending live evaluation | Frozen owner-checked labels, retrieval/gap/citation/scientific/writing results against every required metric. The offline scorer is described in [the harness guide](MVP-09-ACCEPTANCE-HARNESS.md). |
| 09-C | Pending live rerun and workload study | Persisted decisions under real reruns; uncapped questions, corrections, review time, and review-free resolution with denominators. |
| 09-D | Pending model calibration | Source-checked three-way comparison if Jev is authorized and available; otherwise record the incomplete experiment, select supported routes, and enable only a demonstrated safe policy. |
| 09-E | Pending owner sign-off | Nicholas reviews the five writing tasks, known limitations, sanitized acceptance report, and observed recurring cost. |

Offline evidence: ten pure harness tests passed; Black, Ruff, and mypy passed.
The source fixture is fictional and intentionally reports pending sample
coverage. The harness neither accesses the database nor makes a provider call.

Local CodeRabbit review completed on the draft branch (four findings). The
material A04 finding was valid: an oversized query panel could pass on an
absolute 18-hit count. The gate now requires exactly the 20 agreed answerable
queries in the acceptance matrix, with a regression test for an extra case.
The two A08 findings suggested allowing more than five writing tasks, but the
matrix specifies four of five representative tasks, so this fixed panel stays
at five; the same regression test checks an extra case remains pending. The
test-module naming suggestion was stylistic and has no runtime impact.
Required CI and final-head verification are recorded on the PR.

Rollback: remove the offline harness and its private evaluation outputs. It does
not change application records, publication, migrations, or automatic clearance.
