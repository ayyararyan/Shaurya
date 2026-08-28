"""Restricted, discovery-only evaluator for OpenEvolve alpha formulas."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from types import CodeType
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

DISCOVERY_START = pd.Timestamp("2025-09-01")
DISCOVERY_END = pd.Timestamp("2026-06-30")
FEATURE_NAMES = (
    "ret_1",
    "ret_5",
    "ret_15",
    "ret_30",
    "ret_60",
    "rv_5",
    "rv_15",
    "rv_30",
    "rv_60",
    "session_return",
    "overnight_gap",
    "elapsed_fraction",
    "time_sin",
    "time_cos",
)
PARTICIPATION = 0.10
MAX_AST_NODES = 80
FloatArray = npt.NDArray[np.float64]

_ALLOWED_NUMPY_CALLS = {"abs", "clip", "maximum", "minimum", "sign", "tanh", "where"}
_ALLOWED_NODES = (
    ast.Module,
    ast.FunctionDef,
    ast.arguments,
    ast.arg,
    ast.Return,
    ast.Assign,
    ast.Expr,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.Call,
    ast.Attribute,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.USub,
    ast.UAdd,
    ast.And,
    ast.Or,
    ast.Gt,
    ast.GtE,
    ast.Lt,
    ast.LtE,
    ast.Eq,
    ast.NotEq,
    ast.IfExp,
)


def prepare_discovery_cache(index_zip: Path, output: Path) -> dict[str, Any]:
    """Materialize only the evolution discovery period; validation is deliberately absent."""
    from shaurya.research.intraday_alpha_tournament import build_tournament_panel

    panel, audit = build_tournament_panel(index_zip)
    discovery = panel[panel["date"].between(DISCOVERY_START, DISCOVERY_END)].copy()
    raw = discovery[list(FEATURE_NAMES)].to_numpy(float)
    median = np.nanmedian(raw, axis=0)
    q25 = np.nanquantile(raw, 0.25, axis=0)
    q75 = np.nanquantile(raw, 0.75, axis=0)
    scale = np.where(q75 > q25, q75 - q25, 1.0)
    features = np.clip((np.where(np.isfinite(raw), raw, median) - median) / scale, -10, 10)
    dates = discovery["date"].to_numpy(dtype="datetime64[D]").astype(np.int64)
    months = discovery["date"].dt.to_period("M").astype(str).to_numpy()
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        features=features,
        target_bps=discovery["forward_return_bps"].to_numpy(float),
        dates=dates,
        months=months,
        feature_names=np.asarray(FEATURE_NAMES),
        median=median,
        scale=scale,
    )
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    manifest = {
        "cache": str(output.resolve()),
        "sha256": digest,
        "rows": len(discovery),
        "sessions": int(discovery["date"].nunique()),
        "first": discovery["date"].min().date().isoformat(),
        "last": discovery["date"].max().date().isoformat(),
        "features": list(FEATURE_NAMES),
        "source_audit": audit,
        "excludes_validation_and_final": True,
    }
    output.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def _validated_code(source: str) -> tuple[CodeType, int]:
    tree = ast.parse(source)
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_AST_NODES:
        raise ValueError(f"formula exceeds {MAX_AST_NODES} AST nodes")
    if any(not isinstance(node, _ALLOWED_NODES) for node in nodes):
        rejected = sorted(
            {type(node).__name__ for node in nodes if not isinstance(node, _ALLOWED_NODES)}
        )
        raise ValueError(f"disallowed syntax: {rejected}")
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    other = [
        node
        for node in tree.body
        if not isinstance(node, ast.FunctionDef)
        and not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
    ]
    if len(functions) != 1 or functions[0].name != "alpha_score" or other:
        raise ValueError("program must contain only one alpha_score function")
    function = functions[0]
    arguments = [argument.arg for argument in function.args.args]
    if tuple(arguments) != FEATURE_NAMES or function.decorator_list:
        raise ValueError("alpha_score signature or decorators are invalid")
    allowed_names = {*FEATURE_NAMES, "np"}
    assigned_names = {
        target.id
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    allowed_names.update(assigned_names)
    for node in ast.walk(function):
        if isinstance(node, ast.Name) and node.id not in allowed_names:
            raise ValueError(f"disallowed name: {node.id}")
        if isinstance(node, ast.Attribute) and (
            not isinstance(node.value, ast.Name)
            or node.value.id != "np"
            or node.attr not in _ALLOWED_NUMPY_CALLS
        ):
            raise ValueError("only approved NumPy operations are allowed")
        if isinstance(node, ast.Call) and not isinstance(node.func, ast.Attribute):
            raise ValueError("direct function calls are not allowed")
    return compile(tree, "<evolved-alpha>", "exec"), len(nodes)


def _load_score(program_path: Path, features: FloatArray) -> tuple[FloatArray, int]:
    code, complexity = _validated_code(program_path.read_text(encoding="utf-8"))
    namespace: dict[str, Any] = {"np": np, "__builtins__": {}}
    exec(code, namespace)  # noqa: S102 - AST allowlist and empty builtins form the sandbox.
    arguments = [features[:, index] for index in range(features.shape[1])]
    score = np.asarray(namespace["alpha_score"](*arguments), dtype=float)
    if score.shape != (len(features),) or not np.isfinite(score).all():
        raise ValueError("alpha_score must return one finite score per row")
    if float(np.std(score)) <= 1e-12:
        raise ValueError("alpha_score is constant")
    return score, complexity


def _period_metric(
    target: FloatArray,
    dates: npt.NDArray[np.int64],
    position: FloatArray,
    mask: npt.NDArray[np.bool_],
    cost: float,
) -> tuple[float, float]:
    daily = _daily_pnl(target[mask], dates[mask], position[mask], cost)
    return float(daily["pnl"].mean()), float(daily["turnover"].mean() / 2.0)


def _daily_pnl(
    target: FloatArray,
    dates: npt.NDArray[np.int64],
    position: FloatArray,
    cost: float,
) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(dates, unit="D"),
            "target": target,
            "position": position,
        }
    )
    daily_rows: list[dict[str, float]] = []
    for _, day in frame.groupby("date", sort=True):
        day_position = day["position"].to_numpy(float)
        turnover = float(
            abs(day_position[0]) + np.abs(np.diff(day_position)).sum() + abs(day_position[-1])
        )
        gross = float((day_position * day["target"].to_numpy(float)).sum())
        daily_rows.append({"pnl": gross - turnover * cost / 2.0, "turnover": turnover})
    daily = pd.DataFrame(daily_rows)
    return daily


def evaluate_discovery_program(program_path: Path, cache_path: Path) -> dict[str, float]:
    """Score one evolved program without loading validation or final observations."""
    with np.load(cache_path) as cached:
        features = np.asarray(cached["features"], dtype=float)
        target = np.asarray(cached["target_bps"], dtype=float)
        dates = np.asarray(cached["dates"], dtype=np.int64)
    score, complexity = _load_score(program_path, features)
    threshold = float(np.quantile(np.abs(score), 1.0 - PARTICIPATION))
    position = np.where(np.abs(score) >= threshold, np.sign(score), 0.0)
    first = dates <= np.datetime64("2025-12-31").astype(np.int64)
    second = dates >= np.datetime64("2026-01-01").astype(np.int64)
    first_net, first_turnover = _period_metric(target, dates, position, first, 1.0)
    second_net, second_turnover = _period_metric(target, dates, position, second, 1.0)
    net_1bps, turnover = _period_metric(target, dates, position, np.ones(len(dates), bool), 1.0)
    net_6bps, _ = _period_metric(target, dates, position, np.ones(len(dates), bool), 6.0)
    robust_net = min(first_net, second_net)
    instability = abs(first_net - second_net)
    combined = robust_net - 0.25 * instability - 0.02 * complexity - 0.10 * turnover
    return {
        "combined_score": float(combined),
        "robust_net_1bps": float(robust_net),
        "net_1bps": float(net_1bps),
        "net_6bps": float(net_6bps),
        "first_period_net_1bps": float(first_net),
        "second_period_net_1bps": float(second_net),
        "average_round_trips_per_day": float((first_turnover + second_turnover) / 2.0),
        "complexity": float(complexity),
    }


def _validation_metric(daily: pd.DataFrame) -> dict[str, float]:
    from scipy import stats

    pnl = daily["pnl"].to_numpy(float)
    mean = float(pnl.mean())
    deviation = float(pnl.std(ddof=1))
    t_statistic = mean / (deviation / np.sqrt(len(pnl))) if deviation else 0.0
    return {
        "days": float(len(pnl)),
        "mean_daily_bps": mean,
        "annualized_sharpe": mean / deviation * np.sqrt(252) if deviation else 0.0,
        "t_statistic": float(t_statistic),
        "one_sided_p": float(stats.t.sf(t_statistic, len(pnl) - 1)),
        "average_round_trips_per_day": float(daily["turnover"].mean() / 2.0),
    }


def promote_discovery_program(
    program_path: Path, index_zip: Path, cache_path: Path
) -> dict[str, Any]:
    """Evaluate one discovery winner on validation; open final only after a strict pass."""
    from shaurya.research.intraday_alpha_tournament import build_tournament_panel

    with np.load(cache_path) as cached:
        discovery_features = np.asarray(cached["features"], dtype=float)
        median = np.asarray(cached["median"], dtype=float)
        scale = np.asarray(cached["scale"], dtype=float)
    discovery_score, complexity = _load_score(program_path, discovery_features)
    threshold = float(np.quantile(np.abs(discovery_score), 1.0 - PARTICIPATION))
    panel, _ = build_tournament_panel(index_zip)

    def evaluate_slice(start: str, end: str) -> dict[str, Any]:
        frame = panel[panel["date"].between(start, end)].copy()
        raw = frame[list(FEATURE_NAMES)].to_numpy(float)
        features = np.clip((np.where(np.isfinite(raw), raw, median) - median) / scale, -10, 10)
        score, _ = _load_score(program_path, features)
        position = np.where(np.abs(score) >= threshold, np.sign(score), 0.0)
        dates = frame["date"].to_numpy(dtype="datetime64[D]").astype(np.int64)
        target = frame["forward_return_bps"].to_numpy(float)
        return {
            f"cost_{cost:g}bps": _validation_metric(_daily_pnl(target, dates, position, cost))
            for cost in (0.0, 1.0, 2.0, 6.0)
        }

    validation = evaluate_slice("2026-07-01", "2026-08-14")
    primary = validation["cost_1bps"]
    passed = primary["mean_daily_bps"] > 0 and primary["one_sided_p"] < 0.05
    result: dict[str, Any] = {
        "protocol": {
            "candidate_count": 1,
            "validation": "2026-07-01 through 2026-08-14",
            "primary_cost_bps": 1.0,
            "promotion_rule": "positive and one-sided p < 0.05",
            "final_access_rule": "only after validation promotion",
        },
        "program": str(program_path.resolve()),
        "complexity": complexity,
        "discovery_threshold": threshold,
        "validation": validation,
        "promoted": passed,
        "final_week": (evaluate_slice("2026-08-17", "2026-08-21") if passed else "not accessed"),
    }
    return result
