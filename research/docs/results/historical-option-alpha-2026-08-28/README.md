# Full-history option-surface alpha study

This analysis uses every completed historical session available in the one-minute NIFTY index
and rolling ATM-relative option archives. It does not use the invalid 2026-08-28 capture and does
not alter or consume the frozen prospective JEPA bundle.

## Result

**cash; no stable candidate**

- Matched sessions: 1270
- Decisions: 12693
- Decision range: 2021-01-01T10:00:00 to 2026-05-14T14:30:00
- Evaluation: monthly pseudo-live, beginning 2022-01
- Calibration: trailing 252 completed sessions before each month
- Primary assumed round-trip cost: 6 bps
- Holm-corrected passes: []
- Stable candidates: []

The option files are rolling moneyness buckets, not fixed tradable contracts. Accordingly, their
surface variables are used only as predictors. P&L uses the matched NIFTY index return as a
directional futures proxy, so any apparent survivor still requires fixed-contract futures data and
slippage validation before it can be called tradable.

## Candidate ranking at 6 bps

```csv
candidate,mean_daily_bps_6bps,annualized_sharpe_6bps,one_sided_p_6bps,positive_month_rate_6bps,average_round_trips_per_day,holm_pass,stable
positive_atm_richness,-2.233796338363835,-1.6207451583897978,0.9995147906064279,0.3018867924528302,0.5419047619047619,False,False
negative_atm_richness,-4.269060804493308,-2.8912847280038205,0.9999999975757433,0.1320754716981132,0.5419047619047619,False,False
positive_premium_skew,-6.254220223309792,-4.570894682309023,1.0,0.16981132075471697,1.3523809523809525,False,False
positive_atm_shock,-7.212388389963134,-4.54392629992394,1.0,0.07547169811320754,1.2866666666666666,False,False
positive_index_momentum,-8.188493078474298,-4.05979223392093,0.9999999999999998,0.09433962264150944,1.6542857142857144,False,False
negative_atm_shock,-8.227611610036865,-4.946764972585993,1.0,0.03773584905660377,1.2866666666666666,False,False
negative_volume_imbalance,-8.768275388480044,-4.870235663690144,1.0,0.05660377358490566,1.579047619047619,False,False
negative_premium_skew,-9.974351205261637,-6.9534014842604215,1.0,0.03773584905660377,1.3523809523809525,False,False
positive_volume_imbalance,-10.180296040091385,-5.760223998741744,1.0,0.018867924528301886,1.579047619047619,False,False
negative_index_momentum,-11.662935492954276,-5.9183699728147126,1.0,0.018867924528301886,1.6542857142857144,False,False
```

Machine-readable details are in `results.json`; monthly and yearly diagnostics are in the CSV
files alongside this report.
