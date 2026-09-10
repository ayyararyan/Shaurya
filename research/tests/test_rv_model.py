from __future__ import annotations

import math
from dataclasses import replace

import pytest

from shaurya.analytics.rv_model import (
    RV_V2_Q_THRESHOLD,
    FrozenRVFeatures,
    forecast_frozen_rv,
)


FEATURES = FrozenRVFeatures(
    intra1=2.637051181916088e-05,
    intra5=2.6387054049377336e-05,
    intra22=4.297528915466681e-05,
    cur_var=1.8799248156793035e-05,
    cur_abs_ret=0.0002238041910924,
    gap_abs=0.0008134034270579,
    gapv1=4.989199791240132e-06,
    gapv5=2.4554934245749538e-05,
    gapv22=2.124545267950141e-05,
    gap_max5=0.0080270345932208,
    gap_max22=0.0087103535347361,
    cur_max_abs=0.00291181222571,
    iv_chg1=-0.2845617035737725,
    iv_rel22=0.6819721872348102,
    dow=4.0,
    n_nights=2.0,
    next_night_years=0.0075005703855806,
    weekend_night=1.0,
    night_years=0.0095254391968971,
)


def test_frozen_worked_example_is_reproduced_exactly() -> None:
    result = forecast_frozen_rv(
        implied_integrated_variance=0.0002092675583887,
        maturity_years=0.0115788272872461,
        features=FEATURES,
    )
    assert result.forecast_day_integrated_variance == pytest.approx(
        0.0001241848824323, abs=1e-15
    )
    assert result.forecast_overnight_integrated_variance == pytest.approx(
        5.447078355436037e-05, abs=1e-15
    )
    assert result.forecast_integrated_realized_variance == pytest.approx(
        0.0001786556659867, abs=1e-15
    )
    assert result.q_ratio == pytest.approx(0.8537188820011348, abs=2e-13)
    assert result.q_reference_threshold == RV_V2_Q_THRESHOLD == 0.825
    assert result.q_below_reference is False
    assert result.rv_iv_vol_ratio == pytest.approx(math.sqrt(result.q_ratio))


def test_no_future_night_zeroes_overnight_component() -> None:
    features = replace(
        FEATURES,
        n_nights=0.0,
        next_night_years=0.0,
        weekend_night=0.0,
        night_years=0.0,
    )
    result = forecast_frozen_rv(
        implied_integrated_variance=0.0002,
        maturity_years=0.003,
        features=features,
    )
    assert result.forecast_overnight_integrated_variance == 0.0
    assert (
        result.forecast_integrated_realized_variance
        == result.forecast_day_integrated_variance
    )


def test_missing_feature_fails_closed() -> None:
    values = {
        name: getattr(FEATURES, name) for name in FrozenRVFeatures.__dataclass_fields__
    }
    del values["gapv22"]
    with pytest.raises(ValueError, match="gapv22"):
        FrozenRVFeatures.from_mapping(values)


def test_nonfinite_feature_fails_closed() -> None:
    with pytest.raises(ValueError, match="cur_var"):
        forecast_frozen_rv(
            implied_integrated_variance=0.0002,
            maturity_years=0.01,
            features=replace(FEATURES, cur_var=float("nan")),
        )
