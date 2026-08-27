# `features.csv` schema

One UTF-8 CSV row represents one canonical feature identity. Aliases and cross-references use `|`.

Required fields record ID/name/family/meaning; exact formula or algorithm; units/type/domain;
frequency/timezone/grain; raw fields and cleaning; window/warm-up/lag/availability; missing and
zero-denominator behavior; normalization and sign; producers/consumers; bias risks; and
verification status.

`feature_id` uses `F-<descriptive-slug>` and is not renamed when a code alias changes. If a formula
changes materially, add a versioned feature identity or document compatibility before updating the
row. Producer paths are repository-relative and must exist. `verification_status` is one or more
of the four evidence-basis labels documented in `hypotheses.schema.md`.

Several rows describe a stable feature family with declared axes (for example CCZ window and depth)
rather than expanding every parameter combination into thousands of IDs. The axes and producing
code remain part of the identity; a downstream feature-value file must add `feature_version` and
record the exact axis values.
