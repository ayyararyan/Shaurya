"""REQ-SUR-08: explicit strike/maturity support and interpolation policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class StrikeInterpolation(StrEnum):
    ESSVI_FUNCTIONAL_FORM = "essvi_functional_form_within_observed_support"


class MaturityInterpolation(StrEnum):
    LINEAR_TOTAL_VARIANCE = "linear_total_variance_between_fitted_maturities"


class StrikeExtrapolation(StrEnum):
    NONE = "none"


class MaturityExtrapolation(StrEnum):
    NONE = "none"


@dataclass(frozen=True, slots=True)
class SurfaceInterpolationPolicy:
    """The conservative module default: interpolate, but never fabricate outside support."""

    strike_interpolation: StrikeInterpolation = StrikeInterpolation.ESSVI_FUNCTIONAL_FORM
    maturity_interpolation: MaturityInterpolation = MaturityInterpolation.LINEAR_TOTAL_VARIANCE
    strike_extrapolation: StrikeExtrapolation = StrikeExtrapolation.NONE
    maturity_extrapolation: MaturityExtrapolation = MaturityExtrapolation.NONE

    def to_dict(self) -> dict[str, str]:
        return {
            "strike_interpolation": self.strike_interpolation.value,
            "maturity_interpolation": self.maturity_interpolation.value,
            "strike_extrapolation": self.strike_extrapolation.value,
            "maturity_extrapolation": self.maturity_extrapolation.value,
        }
