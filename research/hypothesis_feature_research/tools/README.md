# Catalogue maintenance tools

`catalogue.py` keeps mechanical inventory separate from human interpretation. It never edits
`HYPOTHESES.md`, `hypotheses.csv`, `features.csv`, `test_traceability.csv`, methodology files, or
researcher decisions.

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 research/hypothesis_feature_research/tools/catalogue.py --check
PYTHONDONTWRITEBYTECODE=1 python3 research/hypothesis_feature_research/tools/catalogue.py --update-inventory
```

`--check` validates exact CSV headers/shape/UTF-8, nonempty required cells, stable ID syntax and
uniqueness, statement-basis labels, cross-references, repository paths, feature-data artifact IDs
and integrity metadata, allowed statuses, recursive coverage of `research/tests`, and whether the
checked-in inventory is current. `--update-inventory` changes only `test_inventory.csv`, using
deterministic path order and content hashes; it avoids a rewrite when bytes are unchanged.

The tool intentionally does not parse source code to invent feature formulae, rationales,
hypotheses, or evidence conclusions. Those fields require review of code and evidence by a human.
