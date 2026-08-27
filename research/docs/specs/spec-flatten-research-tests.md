---
title: 'Flatten research test layout'
type: 'chore'
created: '2026-08-27'
status: 'done'
baseline_commit: '4296fedaf73b94b1d7ad71c8c82d6b69e3cfaf7c'
context:
  - 'research/pyproject.toml'
  - 'research/docs/specs/spec-post-market-research-pipeline.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Eight tests for the post-market research pipeline are unnecessarily nested under `research/tests/research/`, while the rest of the Research test suite lives directly under `research/tests/`. The split layout complicates discovery commands and documentation without providing package isolation.

**Approach:** Move all eight nested test modules into `research/tests/`, make only the path-depth adjustment required to preserve the installed end-to-end test's behavior, remove the empty redundant directory, and update tracked documentation that names the old paths or old focused-test command.

## Boundaries & Constraints

**Always:** Preserve test behavior and filenames; limit content changes to the human-approved path-depth adjustment required by relocation; keep the existing root `research/tests/conftest.py` and fixtures in place; preserve the unrelated modified `research/README.md` and untracked `research/hypothesis_feature_research/`; stage only reviewed flattening changes; push only to the verified GitHub remote.

**Ask First:** Stop if a destination filename collision, test-collection collision, merge conflict, remote divergence, or unexpected dependency on the nested path is found.

**Never:** Do not discard, stash, stage, commit, or alter pre-existing user work; do not push to the office-machine `origin`; do not change production or test behavior as part of the directory cleanup.

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| Normal flatten | Eight uniquely named files exist under `tests/research/` | The same files exist under `tests/` and collect successfully | N/A |
| Destination collision | A same-named root test exists | No overwrite or merge is attempted | Halt and report the collision |
| Explicit old path | Documentation references `tests/research` | Commands and links resolve to the flattened locations | Fail verification if stale tracked references remain |

</frozen-after-approval>

## Code Map

- `research/tests/research/test_*.py` -- eight nested test modules to relocate without content changes.
- `research/tests/` -- canonical flat destination already used by the rest of the Research tests.
- `research/tests/conftest.py` -- shared test configuration inherited by both old and new locations.
- `research/docs/specs/spec-post-market-research-pipeline.md` -- tracked commands, file lists, and review links that reference the old nested paths.
- `research/pyproject.toml` -- confirms pytest discovers the complete `tests` tree.

## Tasks & Acceptance

**Execution:**
- [x] `research/tests/research/test_*.py` -> `research/tests/test_*.py` -- move all eight files, apply the approved one-line path-depth correction in the installed end-to-end test, and remove the empty nested directory.
- [x] `research/docs/specs/spec-post-market-research-pipeline.md` -- update old nested test commands, file-list entries, and links to the new flat paths.
- [x] Git hygiene -- preserve the user-owned README/catalogue work and identify only the reviewed flattening/spec paths for delivery after review.

**Acceptance Criteria:**
- Given the current Research test tree, when pytest collection runs after the move, then all eight relocated modules are collected exactly once alongside the other root tests.
- Given the tracked repository, when stale-path searches run, then no active command or link refers to `tests/research`.
- Given the pre-existing dirty tree, when the commit is created, then `research/README.md` and `research/hypothesis_feature_research/` remain uncommitted and unchanged.

## Spec Change Log

## Verification

**Commands:**
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/../data/src:$PWD/src" uv run --python 3.11 --frozen --extra dev pytest -q` from `research/` -- expected: full Research suite passes.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/../data/src:$PWD/src" uv run --python 3.11 --frozen --extra dev ruff check tests/test_adversarial_acceptance.py tests/test_contracts_and_planner.py tests/test_ledger_state_lifecycle_executor.py tests/test_research_cli.py tests/test_surfaces_nulls_multiplicity.py tests/test_v3_seeded_full_pipeline.py tests/test_v3_source_bound_e2e.py tests/test_walkforward_and_synthetic.py` from `research/` -- expected: relocated tests pass lint.
- `git grep -n 'tests/research' -- ':!research/docs/specs/spec-flatten-research-tests.md'` -- expected: no stale tracked path references after documentation updates.
- `git diff --check` -- expected: no whitespace errors.

## Suggested Review Order

**Relocation compatibility**

- Preserve clean-install repository discovery after flattening the end-to-end test.
  [`test_v3_source_bound_e2e.py:253`](../../tests/test_v3_source_bound_e2e.py#L253)

- Confirm the relocated adversarial suite now lives beside all Research tests.
  [`test_adversarial_acceptance.py:1`](../../tests/test_adversarial_acceptance.py#L1)

**Documentation consistency**

- Verify the implementation record points to the flat test directory.
  [`spec-post-market-research-pipeline.md:61`](spec-post-market-research-pipeline.md#L61)

- Review the updated focused verification commands for flat test paths.
  [`spec-post-market-research-pipeline.md:81`](spec-post-market-research-pipeline.md#L81)

- Confirm historical review links resolve to the relocated test modules.
  [`spec-post-market-research-pipeline.md:195`](spec-post-market-research-pipeline.md#L195)
