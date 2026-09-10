"""Frozen Day + Gamma-night NIFTY realized-variance forecaster.

Model: RV-V2-DAY-GAMMA-ESSVI-2026-09-10.
The model is intentionally deterministic: coefficients, standardization and the
10:00 information set are frozen. Data acquisition / feature accumulation is
kept outside this module so callers cannot silently substitute future values.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Mapping

RV_V2_MODEL_VERSION = "RV-V2-DAY-GAMMA-ESSVI-2026-09-10"
RV_V2_MODEL_SCOPE = "nearest_weekly_10am_total_integrated_variance"
RV_V2_Q_THRESHOLD = 0.825
RV_V2_Q_SENSITIVITY_LOW = 0.80
RV_V2_Q_SENSITIVITY_HIGH = 0.85
RV_V2_DAY_SMEARING = 1.0966512633204137
RV_V2_DAY_INTERCEPT = -9.648343925288218
RV_V2_NIGHT_INTERCEPT = -1.205448400603679
RV_V2_NIGHT_ETA_MIN = -5.0
RV_V2_NIGHT_ETA_MAX = 5.0

DAY_FEATURE_NAMES = (
    "log_iv_total", "log_T", "intra1", "intra5", "intra22", "cur_var",
    "cur_abs_ret", "gap_abs", "gapv5", "gapv22", "iv_rel22", "dow", "n_nights",
)
DAY_MEAN = (
    -9.177698266154685, -5.379262967337332, 3.9188779732937314e-05,
    3.934352172730787e-05, 3.961842764429738e-05, 1.2629983876649383e-05,
    0.0025668314137354833, 0.0032150170623446, 2.8268475512702603e-05,
    2.8154089381604225e-05, 1.0093659894331788, 2.013681592039801,
    1.88681592039801,
)
DAY_SD = (
    0.9498846607572238, 1.1654241129631058, 7.813306321137725e-05,
    4.432669450017428e-05, 2.504889584031637e-05, 3.02580534573773e-05,
    0.0023724789738808765, 0.004234631348333535, 7.053762027469176e-05,
    4.0168481469471224e-05, 0.3733017261228411, 1.4250990637153758,
    1.3761924945424961,
)
DAY_BETA = (
    0.6685858762046506, 0.1553439295482904, 0.04887494167572405,
    -0.04174052977725379, 0.020940448426976514, 0.02639763927521407,
    0.01428158006064002, -0.0006490292299893205, -0.034856894302420505,
    0.011509549743423659, 0.08494979192436947, 0.010370360966890708,
    0.05343645814667035,
)

NIGHT_FEATURE_NAMES = (
    "log_iv", "iv_chg1", "iv_rel22", "gap_abs", "gapv1", "gapv5", "gapv22",
    "gap_max5", "gap_max22", "intra1", "intra5", "intra22", "cur_var",
    "cur_abs_ret", "cur_max_abs", "next_night_years", "dow", "weekend_night",
)
NIGHT_MEAN = (
    -1.8992176494086217, 0.00014926237751070254, 1.0093659894331788,
    0.0032150170623446, 2.8227797072983143e-05, 2.8268475512702603e-05,
    2.8154089381604225e-05, 0.007173847455601584, 0.013376727579988059,
    3.9188779732937314e-05, 3.934352172730787e-05, 3.961842764429738e-05,
    1.2629983876649383e-05, 0.0025668314137354833, 0.0016527298269568376,
    0.0033335679197744137, 2.013681592039801, 0.24502487562189054,
)
NIGHT_SD = (
    0.3691192052276169, 0.38925734903661935, 0.3733017261228411,
    0.004234631348333535, 0.00014484609801291253, 7.053762027469176e-05,
    4.0168481469471224e-05, 0.007097832794574199, 0.011140665458512495,
    7.813306321137725e-05, 4.432669450017428e-05, 2.504889584031637e-05,
    3.02580534573773e-05, 0.0023724789738808765, 0.0014256135949580974,
    0.002397630202809061, 1.4250990637153758, 0.43010194831966014,
)
NIGHT_BETA = (
    -0.030191038796307437, -0.06808573529335785, -0.02170203372817811,
    -0.01821359644198082, -0.016887213602699458, -0.004866811367018528,
    0.04165958458451388, 0.0018679280573727923, 0.011539281126896044,
    0.07640427766611238, 0.018587995809888715, -0.002176578787405274,
    0.015024168689966377, 0.03254190875455768, 0.03947232993244027,
    -0.0013030651833680503, -0.020424963128883724, 0.010696367522425405,
)


@dataclass(frozen=True, slots=True)
class FrozenRVFeatures:
    """All non-surface inputs observable at the 10:00 IST forecast origin."""

    intra1: float
    intra5: float
    intra22: float
    cur_var: float
    cur_abs_ret: float
    gap_abs: float
    gapv1: float
    gapv5: float
    gapv22: float
    gap_max5: float
    gap_max22: float
    cur_max_abs: float
    iv_chg1: float
    iv_rel22: float
    dow: float
    n_nights: float
    next_night_years: float
    weekend_night: float
    night_years: float

    @classmethod
    def from_mapping(cls, values: Mapping[str, float]) -> "FrozenRVFeatures":
        missing = [name for name in cls.__dataclass_fields__ if name not in values]
        if missing:
            raise ValueError(f"missing frozen RV features: {', '.join(missing)}")
        return cls(**{name: float(values[name]) for name in cls.__dataclass_fields__})

    def validate(self) -> None:
        for name, value in asdict(self).items():
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.n_nights < 0 or self.night_years < 0 or self.next_night_years < 0:
            raise ValueError("night counts/year fractions cannot be negative")
        if self.weekend_night not in (0.0, 1.0):
            raise ValueError("weekend_night must be 0 or 1")


@dataclass(frozen=True, slots=True)
class FrozenRVForecast:
    model_version: str
    model_scope: str
    implied_integrated_variance: float
    maturity_years: float
    atm_iv: float
    forecast_day_integrated_variance: float
    forecast_overnight_integrated_variance: float
    forecast_integrated_realized_variance: float
    forecast_annualized_realized_variance: float
    forecast_annualized_realized_volatility: float
    forecast_overnight_share: float
    q_ratio: float
    rv_iv_vol_ratio: float
    q_reference_threshold: float
    q_below_reference: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _linear_predictor(
    values: tuple[float, ...],
    means: tuple[float, ...],
    sds: tuple[float, ...],
    betas: tuple[float, ...],
    intercept: float,
) -> float:
    return intercept + sum(
        beta * ((value - mean) / sd)
        for value, mean, sd, beta in zip(values, means, sds, betas, strict=True)
    )


def forecast_frozen_rv(
    *,
    implied_integrated_variance: float,
    maturity_years: float,
    features: FrozenRVFeatures,
) -> FrozenRVForecast:
    """Evaluate the frozen Day + Gamma-night model without any refitting."""

    if not math.isfinite(implied_integrated_variance) or implied_integrated_variance <= 0:
        raise ValueError("implied_integrated_variance must be finite and positive")
    if not math.isfinite(maturity_years) or maturity_years <= 0:
        raise ValueError("maturity_years must be finite and positive")
    features.validate()

    atm_iv = math.sqrt(implied_integrated_variance / maturity_years)
    day_map = {
        "log_iv_total": math.log(implied_integrated_variance),
        "log_T": math.log(maturity_years),
        "intra1": features.intra1,
        "intra5": features.intra5,
        "intra22": features.intra22,
        "cur_var": features.cur_var,
        "cur_abs_ret": features.cur_abs_ret,
        "gap_abs": features.gap_abs,
        "gapv5": features.gapv5,
        "gapv22": features.gapv22,
        "iv_rel22": features.iv_rel22,
        "dow": features.dow,
        "n_nights": features.n_nights,
    }
    night_map = {
        "log_iv": math.log(atm_iv),
        "iv_chg1": features.iv_chg1,
        "iv_rel22": features.iv_rel22,
        "gap_abs": features.gap_abs,
        "gapv1": features.gapv1,
        "gapv5": features.gapv5,
        "gapv22": features.gapv22,
        "gap_max5": features.gap_max5,
        "gap_max22": features.gap_max22,
        "intra1": features.intra1,
        "intra5": features.intra5,
        "intra22": features.intra22,
        "cur_var": features.cur_var,
        "cur_abs_ret": features.cur_abs_ret,
        "cur_max_abs": features.cur_max_abs,
        "next_night_years": features.next_night_years,
        "dow": features.dow,
        "weekend_night": features.weekend_night,
    }
    day_values = tuple(day_map[name] for name in DAY_FEATURE_NAMES)
    night_values = tuple(night_map[name] for name in NIGHT_FEATURE_NAMES)
    eta_day = _linear_predictor(day_values, DAY_MEAN, DAY_SD, DAY_BETA, RV_V2_DAY_INTERCEPT)
    eta_night = _linear_predictor(
        night_values, NIGHT_MEAN, NIGHT_SD, NIGHT_BETA, RV_V2_NIGHT_INTERCEPT
    )
    day_variance = RV_V2_DAY_SMEARING * math.exp(eta_day)
    night_budget = (implied_integrated_variance / maturity_years) * features.night_years
    clipped_night_eta = max(RV_V2_NIGHT_ETA_MIN, min(RV_V2_NIGHT_ETA_MAX, eta_night))
    night_variance = night_budget * math.exp(clipped_night_eta)
    total = day_variance + night_variance
    ann_var = total / maturity_years
    ann_vol = math.sqrt(ann_var)
    q = total / implied_integrated_variance
    return FrozenRVForecast(
        model_version=RV_V2_MODEL_VERSION,
        model_scope=RV_V2_MODEL_SCOPE,
        implied_integrated_variance=implied_integrated_variance,
        maturity_years=maturity_years,
        atm_iv=atm_iv,
        forecast_day_integrated_variance=day_variance,
        forecast_overnight_integrated_variance=night_variance,
        forecast_integrated_realized_variance=total,
        forecast_annualized_realized_variance=ann_var,
        forecast_annualized_realized_volatility=ann_vol,
        forecast_overnight_share=(night_variance / total if total > 0 else 0.0),
        q_ratio=q,
        rv_iv_vol_ratio=math.sqrt(q),
        q_reference_threshold=RV_V2_Q_THRESHOLD,
        q_below_reference=q < RV_V2_Q_THRESHOLD,
    )
