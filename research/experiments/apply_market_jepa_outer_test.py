"""Apply the complete frozen Market-JEPA protocol once to an unseen session."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, TypeAlias
from zoneinfo import ZoneInfo

import numpy as np
import torch
from market_jepa_20260826 import HORIZONS, Config, MarketJepa
from market_jepa_regime_analysis import aligned_representations, contiguous_ends, load_state
from numpy.typing import NDArray

from shaurya.research.market_jepa_outer_test import (
    H1_REPRESENTATIONS,
    H3_MODELS,
    FrozenRidge,
    apply_frozen_normalization,
    block_bootstrap_spearman,
    conditional_slope,
    file_sha256,
    frozen_probe_outputs,
    paired_block_comparison,
    prospective_decision,
    prospective_feature_sets,
    recent_atm_iv_change,
    require_complete_endpoint_count,
    score_frozen_probe,
    shock_quantile_summary,
    verify_bundle,
)
from shaurya.research.market_jepa_regimes import (
    downstream_targets,
    random_projection,
    transition_shock,
)

FloatArray: TypeAlias = NDArray[np.float64]


def _verify_source_lock(repo: Path, manifest: dict[str, Any]) -> None:
    for relative, expected in manifest["source_sha256"].items():
        path = repo / relative
        if not path.is_file() or file_sha256(path) != expected:
            raise ValueError(f"frozen source hash mismatch: {relative}")


def _validate_session(
    session: dict[str, Any], manifest: dict[str, Any], expected_columns: list[str]
) -> date:
    if session["columns"] != expected_columns:
        raise ValueError("outer-test columns differ from the frozen schema")
    trading_date = date.fromisoformat(session["trading_date"])
    if trading_date <= date.fromisoformat(manifest["freeze_cutoff"]):
        raise ValueError("outer-test date is not strictly after the freeze cutoff")
    if session["trading_date"] in manifest["prohibited_seen_dates"]:
        raise ValueError("session was already seen during development or diagnostics")
    if trading_date >= datetime.now(ZoneInfo("Asia/Kolkata")).date():
        raise ValueError("session is not a completed prior trading day in India")
    return trading_date


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = sorted({key for row in rows for key in row})
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _data_quality_failure(output: Path, error: Exception, session: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "status": "data_quality_failure",
        "session": str(session),
        "error": str(error),
        "bundle_consumed": False,
    }
    (output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    (output / "README.md").write_text(
        "# Market-JEPA prospective validation\n\n"
        "The proposed session was rejected before evaluation. The frozen bundle remains "
        f"unconsumed.\n\nReason: `{error}`\n"
    )


def _stability_rows(
    h1_metrics: dict[str, Any],
    paired: dict[str, Any],
    shock_results: dict[str, Any],
    h3_metrics: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    increments = np.asarray(
        [
            metrics["base_jepa"]["mae_skill"] - metrics["base_pca"]["mae_skill"]
            for metrics in h1_metrics.values()
        ]
    )
    rows.append(
        {
            "hypothesis": "H1_signed_atm_iv",
            "metric": "jepa_minus_pca_mae_skill",
            "median": float(np.median(increments)),
            "minimum": float(increments.min()),
            "maximum": float(increments.max()),
            "positive_seeds": int((increments > 0.0).sum()),
            "confidence_supported_seeds": sum(
                all(value["ci_low"] > 0.0 for value in blocks.values())
                for blocks in paired.values()
            ),
        }
    )
    for lag in ("5s", "30s", "60s"):
        for target in (
            "surface_displacement",
            "absolute_atm_iv_change",
            "realized_futures_volatility",
            "absolute_futures_return",
        ):
            values = np.asarray(
                [seed[lag][target]["60s"]["spearman"] for seed in shock_results.values()]
            )
            rows.append(
                {
                    "hypothesis": "H2_transition_shock",
                    "metric": f"{lag}_{target}_spearman",
                    "median": float(np.median(values)),
                    "minimum": float(values.min()),
                    "maximum": float(values.max()),
                    "positive_seeds": int((values > 0.0).sum()),
                    "confidence_supported_seeds": sum(
                        seed[lag][target]["60s"]["ci_low"] > 0.0 for seed in shock_results.values()
                    ),
                }
            )
    h3_increment = np.asarray(
        [
            seed["recent_base_jepa_interaction"]["mae_skill"]
            - seed["recent_base_jepa"]["mae_skill"]
            for seed in h3_metrics.values()
        ]
    )
    rows.append(
        {
            "hypothesis": "H3_iv_mean_reversion",
            "metric": "interaction_incremental_mae_skill",
            "median": float(np.median(h3_increment)),
            "minimum": float(h3_increment.min()),
            "maximum": float(h3_increment.max()),
            "positive_seeds": int((h3_increment > 0.0).sum()),
            "confidence_supported_seeds": "not_primary",
        }
    )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    bundle = args.bundle.resolve()
    output = args.output.resolve()
    consumed = bundle / "CONSUMED.json"
    if consumed.exists():
        raise RuntimeError(f"one-shot bundle has already been consumed: {consumed}")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite prospective result: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((bundle / "frozen_config.json").read_text())
    verify_bundle(bundle, manifest)
    repo = Path(__file__).resolve().parents[2]
    _verify_source_lock(repo, manifest)
    session_path = args.session.resolve()
    try:
        session = load_state(session_path)
        with np.load(bundle / "normalization.npz", allow_pickle=False) as normalization:
            center = normalization["center"].astype(np.float64)
            scale = normalization["scale"].astype(np.float64)
            model_columns = [str(item) for item in normalization["model_columns"].tolist()]
            raw_columns = [str(item) for item in normalization["raw_columns"].tolist()]
        trading_date = _validate_session(session, manifest, raw_columns)
        config = Config(**manifest["config"])
        ends = contiguous_ends(session["timestamps"], config.context_steps, max(HORIZONS))
        minimum = int(manifest["data_quality"]["minimum_contiguous_endpoints"])
        require_complete_endpoint_count(len(ends), minimum)
    except Exception as error:
        _data_quality_failure(output, error, session_path)
        print(json.dumps({"status": "data_quality_failure", "output": str(output)}))
        return 2

    indices = [raw_columns.index(name) for name in model_columns]
    selected = session["values"][:, indices]
    normalized = apply_frozen_normalization(selected, center, scale)
    with np.load(bundle / "pca.npz", allow_pickle=False) as pca:
        pca_mean = pca["mean"].astype(np.float64)
        pca_components = pca["components"].astype(np.float64)
    thresholds = np.load(bundle / "shock-quantile-thresholds.npz", allow_pickle=False)
    target_map = downstream_targets(session["values"], ends, raw_columns, 6)
    signed_iv = target_map["signed_atm_iv_change"]
    recent_iv = recent_atm_iv_change(session["values"], ends, raw_columns)
    blocks = manifest["frozen_protocol"]["bootstrap_block_seconds"]
    draws = int(manifest["frozen_protocol"]["bootstrap_draws"])

    h1_metrics: dict[str, Any] = {}
    h3_metrics: dict[str, Any] = {}
    paired: dict[str, Any] = {}
    shock_results: dict[str, Any] = {}
    conditional_slopes: dict[str, Any] = {}
    h1_rows: list[dict[str, Any]] = []
    shock_rows: list[dict[str, Any]] = []
    h3_rows: list[dict[str, Any]] = []
    device = torch.device("cpu")
    for seed in manifest["seeds"]:
        model = MarketJepa(len(model_columns), config).to(device)
        model.load_state_dict(
            torch.load(
                bundle / "checkpoints" / f"seed-{seed}.pt",
                map_location=device,
                weights_only=True,
            )
        )
        representation = aligned_representations(model, session, normalized, ends, config, device)
        representation["pca"] = (representation["flattened_context"] - pca_mean) @ pca_components.T
        projection = np.load(
            bundle / f"random-projection-seed-{seed}.npy", allow_pickle=False
        ).astype(np.float64)
        representation["random_encoder"] = random_projection(
            representation["flattened_context"], projection
        )
        permutation = np.random.default_rng(
            seed + int(manifest["frozen_protocol"]["shuffle_offsets"]["prospective"])
        ).permutation(len(ends))
        h1, h3 = prospective_feature_sets(representation, recent_iv, permutation)
        h1_metrics[str(seed)] = {}
        h3_metrics[str(seed)] = {}
        losses: dict[str, FloatArray] = {}
        for name in H1_REPRESENTATIONS:
            probe = FrozenRidge.load(bundle / "h1-probes" / f"seed-{seed}-{name}.npz")
            metrics = score_frozen_probe(probe, h1[name], signed_iv)
            h1_metrics[str(seed)][name] = metrics
            _, _, losses[name] = frozen_probe_outputs(probe, h1[name], signed_iv)
            h1_rows.append({"seed": seed, "row_type": "model", "model": name, **metrics})
        paired[str(seed)] = {}
        for block_seconds in blocks:
            comparison = paired_block_comparison(
                losses["base_pca"],
                losses["base_jepa"],
                block_rows=int(block_seconds) // 5,
                minimum_overlap_rows=6,
                draws=draws,
                seed=20260828 + seed + int(block_seconds),
            )
            paired[str(seed)][f"{block_seconds}s"] = comparison
            h1_rows.append(
                {
                    "seed": seed,
                    "row_type": "paired_jepa_vs_pca",
                    "model": "base_jepa_minus_base_pca",
                    "block_seconds": block_seconds,
                    **comparison,
                }
            )
        for name in H3_MODELS:
            probe = FrozenRidge.load(bundle / "h3-probes" / f"seed-{seed}-{name}.npz")
            metrics = score_frozen_probe(probe, h3[name], signed_iv)
            h3_metrics[str(seed)][name] = metrics
            h3_rows.append({"seed": seed, "model": name, **metrics})

        shock_results[str(seed)] = {}
        conditional_slopes[str(seed)] = {
            "overall_past_to_future": conditional_slope(recent_iv, signed_iv),
            "by_30s_transition_shock_quantile": [],
        }
        for lag in (1, 6, 12):
            lag_name = f"{lag * 5}s"
            shock = transition_shock(representation["jepa"], lag)
            boundary = thresholds[f"seed_{seed}_lag_{lag}"].astype(np.float64)
            shock_results[str(seed)][lag_name] = {}
            for target_name in (
                "surface_displacement",
                "absolute_atm_iv_change",
                "realized_futures_volatility",
                "absolute_futures_return",
            ):
                target = target_map[target_name]
                block_results: dict[str, Any] = {}
                for block_seconds in blocks:
                    block_result = block_bootstrap_spearman(
                        shock,
                        target,
                        block_rows=int(block_seconds) // 5,
                        minimum_overlap_rows=6,
                        draws=draws,
                        seed=20260828 + seed + lag + int(block_seconds),
                    )
                    block_results[f"{block_seconds}s"] = block_result
                    shock_rows.append(
                        {
                            "seed": seed,
                            "lag_seconds": lag * 5,
                            "target": target_name,
                            "block_seconds": block_seconds,
                            **block_result,
                        }
                    )
                quantile_result = shock_quantile_summary(shock, target, boundary)
                block_results["quantiles"] = quantile_result
                for bucket_row in quantile_result["buckets"]:
                    shock_rows.append(
                        {
                            "seed": seed,
                            "lag_seconds": lag * 5,
                            "target": target_name,
                            "quantile": bucket_row["quantile"],
                            "quantile_samples": bucket_row["samples"],
                            "quantile_mean": bucket_row["mean"],
                            "monotonic_non_decreasing": quantile_result["monotonic_non_decreasing"],
                            "bucket_mean_spearman": quantile_result["bucket_mean_spearman"],
                        }
                    )
                shock_results[str(seed)][lag_name][target_name] = block_results
            if lag == 6:
                finite = np.isfinite(shock) & np.isfinite(recent_iv) & np.isfinite(signed_iv)
                bucket = np.digitize(shock[finite], boundary)
                for quantile in range(5):
                    mask = bucket == quantile
                    conditional_slopes[str(seed)]["by_30s_transition_shock_quantile"].append(
                        {
                            "quantile": quantile + 1,
                            "samples": int(mask.sum()),
                            "past_to_future_slope": conditional_slope(
                                recent_iv[finite][mask], signed_iv[finite][mask]
                            ),
                        }
                    )
                    h3_rows.append(
                        {
                            "seed": seed,
                            "model": "observed_past_future_slope_by_shock_quantile",
                            "shock_quantile": quantile + 1,
                            "samples": int(mask.sum()),
                            "conditional_slope": conditional_slope(
                                recent_iv[finite][mask], signed_iv[finite][mask]
                            ),
                        }
                    )

    thresholds.close()
    stability = _stability_rows(h1_metrics, paired, shock_results, h3_metrics)
    decision = prospective_decision(h1_metrics, paired)
    result = {
        "status": "prospective_outer_test_complete",
        "bundle_fingerprint": manifest["semantic_sha256"],
        "analysis_git_sha": manifest["analysis_git_sha"],
        "session": {
            "path": str(session_path),
            "sha256": file_sha256(session_path),
            "trading_date": trading_date.isoformat(),
            "endpoints": int(len(ends)),
        },
        "hypothesis_1_signed_atm_iv": {"metrics": h1_metrics, "paired": paired},
        "hypothesis_2_transition_shock": shock_results,
        "hypothesis_3_iv_mean_reversion": {
            "metrics": h3_metrics,
            "conditional_slopes": conditional_slopes,
        },
        "seed_stability": stability,
        "final_scientific_decision": decision,
        "warning": "Research representation result only; no execution or P&L claim.",
    }
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    (temporary / "results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    shutil.copy2(bundle / "frozen_config.json", temporary / "frozen_config.json")
    _write_csv(temporary / "jepa_vs_pca.csv", h1_rows)
    _write_csv(temporary / "transition_shock.csv", shock_rows)
    _write_csv(temporary / "iv_mean_reversion.csv", h3_rows)
    _write_csv(temporary / "seed_stability.csv", stability)
    (temporary / "README.md").write_text(
        "# Market-JEPA prospective validation\n\n"
        f"Session: **{trading_date.isoformat()}**  \n"
        f"Decision: **{decision['decision']} — {decision['conclusion']}**\n\n"
        "This directory is the one-shot output for the three preregistered hypotheses. "
        "It is a representation study, not a trading or P&L result. See `results.json` and "
        "the four CSV tables for numerical details.\n"
    )
    temporary.rename(output)
    consumed.write_text(
        json.dumps(
            {
                "session_sha256": file_sha256(session_path),
                "trading_date": trading_date.isoformat(),
                "result_path": str(output),
                "result_sha256": file_sha256(output / "results.json"),
                "decision": decision,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "decision": decision["decision"],
                "output": str(output),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
