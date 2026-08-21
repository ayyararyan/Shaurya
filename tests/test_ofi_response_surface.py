from __future__ import annotations

from shaurya.analytics.ofi_response_surface import (
    HORIZONS_SECONDS,
    LOOKBACKS_SECONDS,
    TRAINING_WINDOWS_SECONDS,
    ResponseSurfaceTracker,
    surface_diagnostics,
)


def test_fresh_scan_has_exact_frozen_210_cell_grid() -> None:
    payload = ResponseSurfaceTracker().payload(source={})
    assert len(payload["cells"]) == 6 * 5 * 7 == 210
    assert payload["training_windows_seconds"] == list(TRAINING_WINDOWS_SECONDS)
    assert payload["lookbacks_seconds"] == list(LOOKBACKS_SECONDS)
    assert payload["horizons_seconds"] == list(HORIZONS_SECONDS)
    assert all(cell["scored_n"] == 0 for cell in payload["cells"])


def _surface(*, spike: bool) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for lookback in LOOKBACKS_SECONDS:
        for i, window in enumerate(TRAINING_WINDOWS_SECONDS):
            for j, horizon in enumerate(HORIZONS_SECONDS):
                value = 0.02 * i + 0.01 * j
                if spike and i == 2 and j == 3:
                    value += 1.0
                rows.append(
                    {
                        "lookback_seconds": lookback,
                        "training_window_minutes": window / 60.0,
                        "horizon_seconds": horizon,
                        "cumulative_oos_r2": value,
                    }
                )
    return rows


def test_smoothness_diagnostic_accepts_plane_and_rejects_isolated_spike() -> None:
    assert surface_diagnostics(_surface(spike=False))["verdict"] == "smooth"
    assert surface_diagnostics(_surface(spike=True))["verdict"] == "not_smooth"
