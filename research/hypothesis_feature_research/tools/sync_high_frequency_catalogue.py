#!/usr/bin/env python3
# ruff: noqa: E501
"""Synchronize the frozen high-frequency v2 registries into the CSV catalogue."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

CATALOGUE_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = CATALOGUE_ROOT.parent
REGISTRY_ROOT = RESEARCH_ROOT / "registries"


def catalogue_feature_id(canonical: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", canonical.lower()).strip("-")
    return f"F-hf-{slug}"


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames is not None
        return list(reader.fieldnames), list(reader)


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, lineterminator="\n", quoting=csv.QUOTE_ALL
        )
        writer.writeheader()
        writer.writerows(rows)


def semantic_text(constructor: str) -> tuple[str, str, str, str]:
    formulas = {
        "ccz_average": (
            "CCZ event OFI over (t-0.5s,t] divided by one common M=1 depth denominator.",
            "dimensionless",
            "[-infinity,+infinity]",
            "Positive is bid strengthening or ask depletion.",
        ),
        "order_count_imbalance": (
            "(sum bid order counts - sum ask order counts)/(sum bid + sum ask), over the registered depth.",
            "dimensionless",
            "[-1,+1]",
            "Positive means more visible bid-side resting orders.",
        ),
        "quantity_imbalance": (
            "(sum bid quantity - sum ask quantity)/(sum bid + sum ask), over the registered depth.",
            "dimensionless",
            "[-1,+1]",
            "Positive means more displayed bid quantity.",
        ),
        "futures_microprice_tilt_ticks": (
            "((A*q_bid+B*q_ask)/(q_bid+q_ask) - (A+B)/2)/0.05.",
            "futures ticks",
            "bounded by half the spread in ticks",
            "Positive tilts above midpoint.",
        ),
        "prior_move_ticks": (
            "(M_t-M_{t-5})/0.05 using exact same-epoch one-second endpoints.",
            "futures ticks",
            "real",
            "Positive means the prior move was upward.",
        ),
        "reversal_pressure_5s": (
            "Negative of futures.prior_mid_move_5s_ticks.v1.",
            "futures ticks",
            "real",
            "Positive predicts upward reversal pressure.",
        ),
        "exatm_forward_consensus": (
            "Median of K+CE_mid-PE_mid over ATM +/-1..4 strikes excluding ATM; minimum five fresh pairs.",
            "index points or support count",
            "feature-specific",
            "Forward level has no standalone alpha sign.",
        ),
        "basis_raw": (
            "Displayed futures midpoint minus ex-ATM synthetic-forward median.",
            "index points",
            "real",
            "Positive means futures rich to synthetic forward.",
        ),
        "lagged_median_basis": (
            "Median of the previous 30 one-second raw-basis observations; lag one; minimum ten.",
            "index points",
            "real",
            "Slow financing/measurement basis, not alpha.",
        ),
        "parity_pressure": (
            "Negative of (basis_raw-basis_slow); parity.syn_gap.v1 is the sign inverse.",
            "index points",
            "real",
            "Positive points upward for futures.",
        ),
        "fair_quality": (
            "parity_pressure/(range_exatm+0.25).",
            "scaled pressure",
            "real",
            "Same sign as parity pressure.",
        ),
        "inverse_depth_quantity_imbalance": (
            "Quantity imbalance across L1-L5 with inverse-level weights 1/l.",
            "dimensionless",
            "[-1,+1]",
            "Positive means bid-weighted option depth.",
        ),
        "microprice_shift": (
            "Option L1 microprice minus displayed midpoint.",
            "option price points",
            "within half-spread",
            "Positive tilts above midpoint.",
        ),
        "surface_residual_v2": (
            "Black-76 fair price from equal-weight ex-ATM eSSVI total-variance fit minus observed ATM midpoint.",
            "option price points",
            "real",
            "Positive means observed option is cheap to fitted surface.",
        ),
        "surface_residual_difference": (
            "CE leave-ATM residual minus PE leave-ATM residual at the same strike and second.",
            "option price points",
            "real",
            "Positive means call relatively cheaper or put richer.",
        ),
        "fit_leave_atm_essvi_v2": (
            "Equal-weight nonlinear least squares in eSSVI total variance, ATM excluded, followed by static-arbitrage checks.",
            "boolean",
            "true|false",
            "Quality gate only.",
        ),
        "l1_total_quantity": (
            "Current L1 bid quantity plus current L1 ask quantity.",
            "displayed contracts",
            "[0,+infinity)",
            "Liquidity support, not direction.",
        ),
        "log_l1_depth": (
            "log(1+current L1 total displayed quantity).",
            "log contracts",
            "[0,+infinity)",
            "Liquidity support, not direction.",
        ),
        "spread_ticks": (
            "(best ask-best bid)/0.05.",
            "futures ticks",
            "[0,+infinity)",
            "Cost/liquidity state, not direction.",
        ),
        "midpoint_volatility": (
            "Population standard deviation of one-second midpoint point changes over the registered trailing window.",
            "price points per one-second change",
            "[0,+infinity)",
            "Risk magnitude, not direction.",
        ),
        "relative_tertile_state": (
            "Current value classified against q33/q67 from prior 900 seconds, current excluded, minimum 120, same epoch.",
            "categorical",
            "low|mid|high",
            "Feature-specific support state.",
        ),
        "trend_efficiency": (
            "abs(M_t-M_t-10)/sum of absolute one-second midpoint changes over the same complete path.",
            "dimensionless",
            "(0,1] or missing",
            "Low is choppy; high is trending.",
        ),
        "ist_clock_bucket": (
            "Asia/Kolkata regular-session half-open time buckets.",
            "categorical",
            "open|morning|midday|late|close",
            "Support metadata only.",
        ),
        "sign_agreement": (
            "Strict non-zero same-sign agreement for v1 production interaction; historical variants retain zero-equals-zero semantics.",
            "boolean",
            "0|1 or missing",
            "Confidence metadata, not a direction head.",
        ),
        "atm_implied_volatility_state": (
            "Black-76 CE/PE inversion using F_exatm, exact expiry 15:30 IST time, r=0.055, and fresh quality-gated quotes.",
            "absolute volatility",
            "(0,+infinity)",
            "Level is support, not futures direction.",
        ),
        "iv_shock_bp": (
            "10000*(ATMIV_t-ATMIV_t-h) on exact same-epoch one-second endpoints.",
            "IV basis points",
            "real",
            "Positive means IV just rose.",
        ),
        "atm_cp_iv_difference_bp": (
            "10000*(ATM CE IV-ATM PE IV).",
            "IV basis points",
            "real",
            "Positive means call IV exceeds put IV.",
        ),
        "atm_surface_gap_bp": (
            "10000*(traded ATM IV-ex-ATM fitted surface IV).",
            "IV basis points",
            "real",
            "Positive means traded ATM IV is rich.",
        ),
        "iv_vol_of_vol_60s": (
            "Sample standard deviation (ddof=1) of valid one-second IV shocks over trailing 60 seconds; minimum 40.",
            "IV basis points",
            "[0,+infinity)",
            "Risk/gate support only.",
        ),
        "aligned_post_fill": (
            "position_sign*call_put_delta_sign*frozen predictor.",
            "predictor units",
            "real",
            "Sign aligned to reconstructed filled position benefit.",
        ),
    }
    if constructor.endswith("_gate"):
        return (
            "Deterministic conjunction of the versioned causal states named by the gate.",
            "boolean",
            "0|1 or missing",
            "Confidence/routing support only.",
        )
    return formulas.get(
        constructor,
        (
            f"Versioned deterministic {constructor} construction.",
            "feature-specific",
            "feature-specific",
            "See methodology; no unstated sign.",
        ),
    )


def main() -> None:
    features_registry = json.loads((REGISTRY_ROOT / "microstructure_features_v2.yaml").read_text())
    hypotheses_registry = json.loads((REGISTRY_ROOT / "alpha_hypotheses_v2.yaml").read_text())
    hypothesis_ids = [
        f"H-high-frequency-{index:03d}"
        for index, _ in enumerate(hypotheses_registry["templates"], 1)
    ]
    feature_hypotheses: dict[str, list[str]] = defaultdict(list)
    for hypothesis_id, definition in zip(
        hypothesis_ids, hypotheses_registry["templates"], strict=True
    ):
        for canonical in (
            *definition["predictor_feature_ids"],
            *definition["conditioning_variables"],
        ):
            feature_hypotheses[canonical].append(hypothesis_id)
    aliases_by_canonical: dict[str, list[str]] = defaultdict(list)
    for alias, metadata in features_registry.get("historical_aliases", {}).items():
        aliases_by_canonical[str(metadata["canonical"])].append(str(alias))

    feature_fields, feature_rows = read_csv(CATALOGUE_ROOT / "features.csv")
    feature_rows = [row for row in feature_rows if not row["feature_id"].startswith("F-hf-")]
    for definition in features_registry["features"]:
        canonical = definition["feature_id"]
        constructor = definition["constructor"]
        formula, units, domain, sign = semantic_text(constructor)
        is_gate = canonical.startswith("gate.") or "passed" in canonical or "converged" in canonical
        data_type = (
            "boolean"
            if is_gate or canonical.startswith("interaction.")
            else "categorical"
            if canonical.startswith("state.")
            else "float"
        )
        hypothesis_refs = feature_hypotheses.get(canonical) or hypothesis_ids
        feature_rows.append(
            {
                "feature_id": catalogue_feature_id(canonical),
                "canonical_name": canonical,
                "aliases": "|".join(sorted(aliases_by_canonical.get(canonical, ()))) or "none",
                "feature_family": str(definition["family"]).lower(),
                "plain_language_meaning": f"Versioned {definition['role']} variable for the high-frequency construction freeze.",
                "formula_or_algorithm": formula,
                "units": units,
                "data_type": data_type,
                "valid_domain": domain,
                "frequency": "instrument or option-contract|one-second decision anchor",
                "timestamp_convention": "Receive-time causal lineage; decision time in IST; source timestamps <= anchor.",
                "observation_key": "session|connection_epoch|decision_timestamp|instrument or option contract",
                "raw_source_fields": "canonical futures/option BBO; L1-L5 quantity/order count; receive timestamp; connection epoch; expiry/strike/type",
                "preprocessing": "Reject crossed/invalid/stale inputs; preserve exact one-second endpoints and source lineage.",
                "window_and_warmup": "Feature-specific frozen window; rolling states never cross epochs.",
                "lag_and_availability": "Available at decision anchor only after all source inputs have arrived.",
                "missing_and_zero_behavior": "Stale, incomplete, crossed, unsupported, or zero-denominator inputs are missing; zero is retained only when mathematically observed.",
                "normalization": "Exactly as formula; no implicit standardization.",
                "sign_interpretation": sign,
                "producing_paths": "data/src/shaurya/data/high_frequency.py|research/registries/microstructure_features_v2.yaml",
                "hypothesis_ids": "|".join(hypothesis_refs),
                "test_ids": "T-high-frequency-features|T-high-frequency-registries",
                "leakage_or_survivorship_risk": "Future endpoints, current-in-threshold leakage, stale as-of joins, reconnect bridging, and target-as-feature registration fail closed.",
                "verification_status": "Verified from code|Verified from existing documentation",
            }
        )
    write_csv(CATALOGUE_ROOT / "features.csv", feature_fields, feature_rows)

    feature_id_by_canonical = {
        definition["feature_id"]: catalogue_feature_id(definition["feature_id"])
        for definition in features_registry["features"]
    }
    hypothesis_fields, hypothesis_rows = read_csv(CATALOGUE_ROOT / "hypotheses.csv")
    hypothesis_rows = [
        row for row in hypothesis_rows if not row["hypothesis_id"].startswith("H-high-frequency-")
    ]
    for hypothesis_id, definition in zip(
        hypothesis_ids, hypotheses_registry["templates"], strict=True
    ):
        predictors = definition["predictor_feature_ids"]
        conditions = definition["conditioning_variables"]
        hypothesis_rows.append(
            {
                "hypothesis_id": hypothesis_id,
                "family_id": "HF-high-frequency",
                "title": definition["display_name"],
                "research_question": definition["display_name"]
                + " under the frozen causal construction?",
                "null_hypothesis": "The registered predictor has no stable held-out association with the registered target after declared controls and costs.",
                "alternative_hypothesis": "The registered predictor has a stable held-out association in the mechanism-consistent direction under the declared controls.",
                "expected_direction": "Mechanism-specific; parity/L1 are sign-aligned, midpoint and IV shocks are sign-reversed, range hypotheses concern magnitude.",
                "feature_ids": "|".join(
                    feature_id_by_canonical[item] for item in (*predictors, *conditions)
                ),
                "test_ids": "T-high-frequency-features|T-high-frequency-registries",
                "implementation_status": "implemented",
                "evidence_status": "result located but not validated",
                "input_data": "Canonical complete Shaurya futures and option-chain snapshots with one-second policy anchors",
                "output_locations": "not_generated:fresh_v2_walk_forward_and_shadow_validation_required",
                "source_paths": "data/src/shaurya/data/high_frequency.py|research/registries/alpha_hypotheses_v2.yaml",
                "unresolved_questions": "Three sessions freeze construction and shadow candidacy only; regime breadth, costs, fills, and promotion remain unresolved.",
                "statement_basis": "Verified from code|Verified from existing documentation",
            }
        )
    write_csv(CATALOGUE_ROOT / "hypotheses.csv", hypothesis_fields, hypothesis_rows)

    trace_fields, trace_rows = read_csv(CATALOGUE_ROOT / "test_traceability.csv")
    trace_rows = [
        row
        for row in trace_rows
        if row["test_id"] not in {"T-high-frequency-features", "T-high-frequency-registries"}
    ]
    trace_rows.append(
        {
            "test_id": "T-high-frequency-features",
            "repository_relative_path": "data/tests/test_high_frequency_features.py",
            "entry_points_or_functions": "book/parity/surface/IV/state/target identities; freshness; epochs; anti-leakage",
            "hypothesis_ids": "|".join(hypothesis_ids),
            "feature_ids": "|".join(feature_id_by_canonical.values()),
            "inputs": "synthetic canonical TapeRow books, option quotes, and exact one-second paths",
            "outputs": "pytest assertions only",
            "dependencies": "data/src/shaurya/data/high_frequency.py|data/src/shaurya/data/option_pricing.py",
            "execution_category": "feature_acceptance_test",
            "implementation_status": "implemented",
            "evidence_result_location": "none",
            "notes_or_unresolved_classification": "Formula and causality tests are not empirical support.",
        }
    )
    trace_rows.append(
        {
            "test_id": "T-high-frequency-registries",
            "repository_relative_path": "research/tests/test_high_frequency_registries.py",
            "entry_points_or_functions": "v2 registry load; constructor resolution; target separation; deterministic plan",
            "hypothesis_ids": "|".join(hypothesis_ids),
            "feature_ids": "|".join(feature_id_by_canonical.values()),
            "inputs": "frozen v1/v2 registries and public high-frequency constructors",
            "outputs": "pytest assertions only",
            "dependencies": "data/src/shaurya/data/high_frequency.py|research/src/shaurya/research/planner.py",
            "execution_category": "registry_acceptance_test",
            "implementation_status": "implemented",
            "evidence_result_location": "none",
            "notes_or_unresolved_classification": "Software correctness and registry consistency are not empirical evidence.",
        }
    )
    write_csv(CATALOGUE_ROOT / "test_traceability.csv", trace_fields, trace_rows)


if __name__ == "__main__":
    main()
