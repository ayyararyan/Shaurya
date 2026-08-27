# `test_traceability.csv` schema

There is exactly one row for every recursive file under `research/tests`, including `conftest.py`
and non-Python fixtures. `test_id` is stable and uses `T-<descriptive-slug>`.
Focused public-interface tests in sibling packages may also be registered; they do not broaden the
required exhaustive inventory beyond `research/tests`.

The row records repository path; executable entry points or important symbols; resolving
hypothesis and feature IDs; inputs/outputs/dependencies; execution category; implementation
status; evidence/result location; and classification notes. Multi-values use `|`.

`evidence_result_location=none` means no durable empirical output is associated with that test.
A pytest assertion or synthetic artifact is not silently promoted to empirical evidence. Removed
files remain visible in version history; the validator reports stale rows and new unmapped files.
