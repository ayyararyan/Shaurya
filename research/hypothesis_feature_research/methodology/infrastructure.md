# Infrastructure and contracts methodology

## 1. Hypothesis

`H-infrastructure-001` asks whether versioned contracts, public package boundaries, CLIs,
dashboards, and fixtures preserve reproducible read-only research interfaces.

## 2. Source tests and entry points

`conftest.py`, both JSON fixtures, `test_release_metadata.py`, `test_remaining_contracts.py`,
`test_architecture_boundary.py`, `test_research_cli.py`, and dashboard server write-method tests.

## 3. Input lineage

Inputs are project metadata, AST imports, versioned JSON payloads, causal timestamps, session dates,
CLI arguments, and synthetic dashboard states. There is no market outcome lineage.

## 4. Feature derivation

No economic feature is inferred. Contract-level `F-source-completion-state`,
`F-feature-availability-time`, `F-surface-quality`, and `F-time-regime` fields are validated for
serialization and boundary behavior.

## 5. Temporal alignment and leakage

Causal timestamps reject future-information ordering and non-IST session labels where required.
The NSE derivatives close is date-versioned. Architecture tests require catalogue handles/public
Data facade instead of private collector imports.

## 6. Procedure and metrics

Golden round-trip equality, unsupported schema rejection, distribution version match, dependency
declaration, import scanning, deterministic CLI plan cardinality, and HTTP write-method refusal are
boolean contract checks.

## 7. Output interpretation

Passing demonstrates compatibility with the tested version and boundary. It provides no empirical
evidence about feature usefulness, surfaces, or market behavior.

## 8. Edge cases and quality checks

Unknown category/version, inconsistent age/staleness, finding windows after decisions, raw quoting
use, mismatched package metadata, forbidden imports, and HTTP mutation methods are explicit.

## 9. Limitations

Future provider/schema versions and deployment environments are not covered unless added as
fixtures/tests. AST checks cannot prove all runtime dynamic-import behavior.

## 10. Reproduction

```bash
cd research
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_release_metadata.py tests/test_remaining_contracts.py tests/test_architecture_boundary.py tests/research/test_research_cli.py
```

## 11. Researcher decisions

Approve schema/version changes, public boundary expansion, session-calendar updates, and any CLI or
dashboard mutation capability. These are governance decisions, not automatic migrations.
