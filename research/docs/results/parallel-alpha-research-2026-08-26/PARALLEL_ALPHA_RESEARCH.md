# Parallel alpha research tournament

**Verdict: no candidate survived the shared protocol.**

Candidates in shared correction: 59
Families: baseline_return_models, baseline_rules, formula_mining, regime_jump
Holm validation passes: none
Final survivors: none

## Shared validation leaders

| candidate | family | net 1bp/day | Sharpe | p-value | round trips/day |
|---|---|---:|---:|---:|---:|
| baseline__gap_continuation | baseline_rules | +8.220 | +3.09 | 0.1357 | 1.00 |
| regime_jump__large_gap_continuation_first_hour | regime_jump | +2.745 | +3.07 | 0.1375 | 0.27 |
| formula__positive__product_rank_overnight_gap__rv_30 | formula_mining | +2.027 | +3.14 | 0.1322 | 0.76 |
| formula__positive__sum_rank_session_return__overnight_gap | formula_mining | +1.974 | +1.75 | 0.2659 | 0.55 |
| formula__positive__rank_session_return | formula_mining | +0.695 | +0.85 | 0.3804 | 0.39 |
| formula__positive__sum_rank_overnight_gap__rv_30 | formula_mining | +0.339 | +0.47 | 0.4324 | 1.18 |
| formula__negative__product_rank_session_return__overnight_gap | formula_mining | +0.287 | +0.33 | 0.4531 | 0.33 |
| formula__negative__rank_overnight_gap | formula_mining | -0.012 | -0.04 | 0.5055 | 0.06 |
| formula__positive__rank_overnight_gap | formula_mining | -0.110 | -0.36 | 0.5520 | 0.06 |
| regime_jump__post_jump_continuation | regime_jump | -0.274 | -0.91 | 0.6274 | 0.39 |

## Separate-horizon tracks

- Sparse quarter-hour grid: 144 candidates; selected `cash`. Best active was `phase_h5_p5_cd0_midday` at -0.042 net bps/day using the 6bp hurdle.
- Formula grammar: 72 formulas; selected `cash` after Holm correction at the 6bp hurdle.

The final week is accessed only for strategies that pass corrected validation. Index returns remain a proxy because futures fills and basis are unavailable.
