# Hypothesis and feature research catalogue

This catalogue translates the code and artifacts under `research/tests` into a durable map of
research question → feature → experiment → evidence. It does not replace source tests, raw tapes,
specifications, or retained results. Its most important rule is that software correctness and
empirical support are separate claims.

## Structure

- `HYPOTHESES.md`: human-readable master catalogue.
- `hypotheses.csv`, `features.csv`, `test_traceability.csv`: machine-readable registries.
- `methodology/`: one document per coherent hypothesis family, with formulas, timing, procedure,
  edge cases, reproduction, and unresolved decisions.
- `data_sources.md`: observed source formats, lineage, timing, and completeness boundaries.
- `feature_data/`: provenance schema and references to existing small derived results; no raw data.
- `schemas/`: CSV contracts and the `|` multi-value delimiter convention.
- `tools/`: deterministic inventory/validation and the mechanically derived test inventory.

Stable IDs form a many-to-many graph: an `HF-*` family contains `H-*` hypotheses; each hypothesis
uses `F-*` features and is exercised by `T-*` tests. A test can serve several hypotheses, and a
feature can be produced or consumed by several tests. IDs are explicitly registered in CSV and
are not reassigned when files sort differently.

## Status interpretation

Implementation status is one of `implemented`, `partially_implemented`, `planned_or_stub`,
`unclear`, `disabled`, or `superseded`. It describes code availability only.

Evidence status is one of `no result located`, `result located but not validated`, `inconclusive`,
`supports hypothesis`, `rejects hypothesis`, `mixed`, or `unable to determine`. “Supports” and
“rejects” are scoped to the located design/sample, never generalized beyond documented limits.
A passing test cannot change evidence status by itself.

Statements are labelled `Verified from code`, `Verified from existing documentation`, `Inferred`,
or `Unknown / researcher input required`. Inferences cite the motivating path/symbol in the
methodology file.

## Maintenance workflow

To add a hypothesis:

1. Choose an existing family or register a stable `HF-*` family.
2. Add the next unused explicit `H-<family>-NNN` row to `hypotheses.csv`.
3. Add the full human entry to `HYPOTHESES.md` and update the family methodology.
4. Keep null/alternative, direction, and evidence unknown unless code/docs support them.

To register a feature, add one `F-*` row to `features.csv` with formula, grain, timing,
availability, missing/zero behavior, provenance, risks, and consumers. A material semantic change
requires a versioned identity or an explicit compatibility decision; do not silently reuse an ID.

The high-frequency v2 registry rows are synchronized deterministically from the frozen runtime
registries before review:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 research/hypothesis_feature_research/tools/sync_high_frequency_catalogue.py
```

To map a test, add one `T-*` row to `test_traceability.csv`. Every recursive file under
`research/tests`, including fixtures/support, must have exactly one row. If classification is not
possible, use an explicit `needs_researcher_review` execution category and explain it.

To add feature data, prefer referencing an immutable existing artifact in
`feature_data/manifest.csv`. Generate new values only from completed verified local sources with a
bounded read-only derivation. Record keys, grain, exact feature version, dataset identity, code
revision, timestamps, quality status, row count, size, and checksum. Never copy raw tapes here.

Run validation from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 research/hypothesis_feature_research/tools/catalogue.py --check
```

After adding/removing an in-scope test, update only the mechanical inventory, review the diff, add
or retire its curated traceability row, then check again:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 research/hypothesis_feature_research/tools/catalogue.py --update-inventory
PYTHONDONTWRITEBYTECODE=1 python3 research/hypothesis_feature_research/tools/catalogue.py --check
```

## Contributor checklist

- [ ] Stable IDs added once; no existing IDs repurposed.
- [ ] Question, rationale, null/alternative, expected direction, and unknowns are evidence-labelled.
- [ ] Formula, units, grain, window, availability, missingness, and leakage risks are explicit.
- [ ] Test and source/result paths resolve; absent expected outputs use `not_generated:<reason>`.
- [ ] Implementation and evidence statuses are separate.
- [ ] Incomplete/cancelled/partial sources are not called complete.
- [ ] Feature data has provenance/hash/quality fields and contains no raw market tape.
- [ ] Validator passes; final diff contains no cache, bytecode, credentials, or unrelated changes.

Researcher judgment is always required for economic rationale, hypothesis direction, family
boundaries, interpretation of mixed evidence, promotion/falsification, economic materiality,
confirmatory eligibility, and any change to a preregistered design.
