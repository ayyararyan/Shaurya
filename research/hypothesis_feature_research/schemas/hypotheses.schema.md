# `hypotheses.csv` schema

One UTF-8 CSV row represents one stable hypothesis. The header is authoritative and all cells are
present. Multi-valued cells use `|`; `none` means deliberately empty.

- `hypothesis_id`: `H-<family-slug>-NNN`, immutable after publication.
- `family_id`: `HF-<descriptive-slug>`.
- `title`, `research_question`: human-readable identity and question.
- `null_hypothesis`, `alternative_hypothesis`, `expected_direction`: use `Unknown / researcher
  input required` when the code/docs do not support a formulation.
- `feature_ids`, `test_ids`: resolving `|`-delimited IDs.
- `implementation_status`: `implemented`, `partially_implemented`, `planned_or_stub`, `unclear`,
  `disabled`, or `superseded`.
- `evidence_status`: `no result located`, `result located but not validated`, `inconclusive`,
  `supports hypothesis`, `rejects hypothesis`, `mixed`, or `unable to determine`.
- `input_data`, `output_locations`, `source_paths`: lineage; paths are repository-relative.
  An absent expected artifact uses `not_generated:<reason>`.
- `unresolved_questions`: decisions or evidence gaps, not hidden assumptions.
- `statement_basis`: one or more of `Verified from code`, `Verified from existing documentation`,
  `Inferred`, or `Unknown / researcher input required`.

Evidence status never derives from a software test passing.
