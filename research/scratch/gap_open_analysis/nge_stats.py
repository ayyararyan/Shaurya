#!/usr/bin/env python3
"""Small statistics toolkit for the NGE path-quality test.

New module.  Hand-rolled because the analysis virtualenv carries numpy/pandas/scipy but not
statsmodels, and because every estimator used here is short enough that a visible
implementation is preferable to a hidden one.

Offline analysis only.  No broker, credential, exchange network, or order path.
"""
from __future__ import annotations

import numpy as np
from scipy import stats


def ols(y: np.ndarray, X: np.ndarray, nw_lags: int = 5) -> dict:
    """OLS with an intercept, reporting both classical and Newey-West standard errors.

    ``X`` is (n, k) WITHOUT the intercept column; it is prepended here.  Newey-West uses the
    Bartlett kernel at ``nw_lags``, matching the convention in Baltussen et al. (2021).
    """
    y = np.asarray(y, dtype=float)
    X = np.asarray(X, dtype=float)
    if X.ndim == 1:
        X = X[:, None]
    ok = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
    y, X = y[ok], X[ok]
    n, k = X.shape
    Z = np.column_stack([np.ones(n), X])
    XtX_inv = np.linalg.pinv(Z.T @ Z)
    beta = XtX_inv @ (Z.T @ y)
    resid = y - Z @ beta
    dof = n - k - 1
    ss_res = float(resid @ resid)
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    r2_adj = 1.0 - (1.0 - r2) * (n - 1) / dof if dof > 0 else np.nan

    se_ols = np.sqrt(np.maximum(np.diag(XtX_inv) * ss_res / max(dof, 1), 0.0))

    # Newey-West
    u = Z * resid[:, None]
    S = u.T @ u
    for L in range(1, min(nw_lags, n - 1) + 1):
        w = 1.0 - L / (nw_lags + 1.0)
        G = u[L:].T @ u[:-L]
        S += w * (G + G.T)
    V = XtX_inv @ S @ XtX_inv
    se_nw = np.sqrt(np.maximum(np.diag(V), 0.0))

    t_nw = np.where(se_nw > 0, beta / np.where(se_nw > 0, se_nw, 1.0), np.nan)
    p_nw = 2.0 * stats.t.sf(np.abs(t_nw), max(dof, 1))
    t_ols = np.where(se_ols > 0, beta / np.where(se_ols > 0, se_ols, 1.0), np.nan)
    p_ols = 2.0 * stats.t.sf(np.abs(t_ols), max(dof, 1))
    return {
        "n": int(n), "k": int(k), "beta": beta, "se_nw": se_nw, "t_nw": t_nw, "p_nw": p_nw,
        "se_ols": se_ols, "t_ols": t_ols, "p_ols": p_ols, "r2": r2, "r2_adj": r2_adj,
    }


def zscore_by(values: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """Within-group z-score.

    Used to absorb BOTH the secular growth in NIFTY option open interest over 2021-2026 and
    any NIFTY lot-size regime change, neither of which is a signal.  A lot-size multiplier is
    a positive constant inside a period, so it cancels exactly in a within-year z-score.
    """
    values = np.asarray(values, dtype=float)
    out = np.full(len(values), np.nan)
    for g in np.unique(groups):
        m = groups == g
        v = values[m]
        fin = np.isfinite(v)
        if fin.sum() < 3:
            continue
        mu, sd = np.nanmean(v[fin]), np.nanstd(v[fin], ddof=1)
        if sd > 0:
            out[m] = (v - mu) / sd
    return out


def bonferroni_bh(pvals: list[float], alpha: float = 0.05) -> dict:
    p = np.asarray([x for x in pvals if np.isfinite(x)], dtype=float)
    m = len(p)
    if m == 0:
        return {"m": 0, "raw_hits": 0, "bonferroni_survivors": 0, "bh_survivors": 0,
                "bonferroni_alpha": np.nan, "bh_threshold": np.nan}
    order = np.argsort(p)
    ps = p[order]
    bh_ok = ps <= alpha * np.arange(1, m + 1) / m
    kmax = int(np.flatnonzero(bh_ok)[-1]) + 1 if bh_ok.any() else 0
    return {
        "m": m,
        "raw_hits": int((p < alpha).sum()),
        "expected_by_chance": round(alpha * m, 2),
        "bonferroni_alpha": alpha / m,
        "bonferroni_survivors": int((p < alpha / m).sum()),
        "bh_threshold": float(ps[kmax - 1]) if kmax else 0.0,
        "bh_survivors": kmax,
    }


def detectable_r(n: int, power: float = 0.80, alpha: float = 0.05) -> float:
    """Smallest |Pearson r| detectable at the given power, via Fisher's z."""
    if n < 10:
        return np.nan
    za, zb = stats.norm.isf(alpha / 2.0), stats.norm.isf(1.0 - power)
    z = (za + zb) / np.sqrt(n - 3)
    return float(np.tanh(z))


def detectable_mean(sd: float, n: int, power: float = 0.80, alpha: float = 0.05) -> float:
    if n < 3 or not np.isfinite(sd):
        return np.nan
    za, zb = stats.norm.isf(alpha / 2.0), stats.norm.isf(1.0 - power)
    return float((za + zb) * sd / np.sqrt(n))
