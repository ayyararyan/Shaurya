# VolARP dashboard — frozen implementation scope, 2026-09-09

Authority: Aryan's latest voice instruction supersedes `iron-carry-v1`: use one
ATM short iron butterfly with 500-point wings, and decide only at 10:00 IST from
the predicted RV / ATM IV volatility ratio. Read-only; no order execution.

## Model and assumptions (version volarp-v1)

- **Decision rule:** calculate `predicted annualized RV / ATM eSSVI IV`. At
  10:00 IST, a new position satisfies the entry condition only when the ratio
  is strictly below `0.70`. The page displays the condition at all times, but
  it is a 10:00 IST manual check — never an automatic order gate.
- **Position:** one NIFTY nearest-expiry ATM short iron butterfly: buy one put
  at `ATM − 500`, sell one ATM put, sell one ATM call, buy one call at
  `ATM + 500`; the centre is the nearest 50-point strike to the surface
  forward. No 400-point wing or alternative-centre ranking is part of VolARP.
- **Continuation/recentre:** at each following 10:00 IST check before expiry,
  continue only when RV / IV remains below `0.70`. If it continues and the
  surface forward is **more than** 250 points from the held centre, recenter to
  the nearest ATM 50-point centre. Aryan has not specified the action when the
  continuation condition fails; the dashboard says so rather than inventing an
  exit rule.
- **Displayed objects:** (1) predicted RV / ATM IV, (2) fitted ATM IV and
  forecast annualized RV, (3) the arbitrage-checked eSSVI surface, and (4) the
  exact ATM butterfly's executable credit and terminal payoff if settlement is
  at its centre. The terminal-at-centre figure is not a live P&L forecast.

## Retained pricing and data safeguards

- Current leg IV and model price from accepted eSSVI, inside observed support only.
  Executable credit uses short bids minus long asks. Show market mid/model value
  separately. Require known equal lot sizes and at least one lot at each entry BBO,
  positive/noncrossed complete books, no crossed/invalid/stale/partial quality flags,
  quote age <=3s, no future rows. Informational flags such as source sequence
  unavailable are retained, not treated as invalid BBO (matching the DAT/SUR boundary).
- Forward is the existing surface's forward (not observed spot). Scenario assumes
  driftless lognormal forward, frozen RV forecast and variance proportional to calendar
  elapsed time. Nontrading time thus carries variance; this is NOT a separately fitted
  overnight/gap forecast. Use verified 2026 NSE holiday calendar; fail explicitly outside
  its supported year. 1,024 antithetic paths, seed 20260909, shared across candidates.
- Future option marks in recentering and next-open valuation use flat front ATM IV,
  held constant within scenario; **a scenario assumption**, not future eSSVI extrapolation.
  Current pricing/Greeks retain full eSSVI strike IV. Report this distinction in UI.
  Base; RV x1.25 / future IV x1.20 / doubled friction stress; RV x0.8 / IV x0.8;
  additional +/-2% log-price jump at first nontrading interval ending next open.
  Stress means are conditional scenarios, not probability-weighted expected returns.
- Net signed forward Greeks use each leg's fixed fitted IV, Black-76 rate convention:
  delta per point, gamma per point squared, theta per elapsed calendar day, vega per
  one volatility point. Local daily carry = theta + .5*gamma*F^2*RV^2*year_fraction_day.
  This is an approximation, NOT expiry P&L and not continuous delta hedging.
- Charges: NSE April-2026 STT sell premium .15%; long exercised intrinsic .15%;
  exchange+IPFT .03553%, SEBI .0001%, GST18% on exchange/SEBI/brokerage; buy stamp .003%.
  Assume Kotak Trade API zero brokerage; show manual-route Rs10/order sensitivity
  as a cost estimate separately. One adverse tick/leg extra slippage. Future trades
  cross current per-leg half-spread (minimum .05 points), plus tick; stress doubles
  this friction. Full close+open charged on every recenter, no netting benefit assumed.
  No tax on short exercise premium again. All rates are approximate contract-note
  estimates; no invented margin, no financing charge because cash rate is the existing
  surface rate (currently zero), no capital allocation. Personal income tax excluded.
- Static expiry payoff bounds exclude exercise tax (which depends on terminal intrinsic)
  and do NOT bound losses over multiple recenterings. No finite after-exercise-tax bound
  claimed on an unbounded underlying. Show static max loss before exercise tax, Monte
  Carlo p05 / lower-tail mean, probability of loss, and stress outcomes separately.
- Conditional simulations and detailed risk diagnostics remain API/research objects,
  but do not rank or select a VolARP trade on the simple page. Current-position
  centre tracking is browser-local, not broker positions or persistent execution.

## Requirements / acceptance

| ID | Required | Verification |
|---|---|---|
| BFLY-01 | Signed 500-point ATM legs, expiry, actual lot metadata | Exact payoff and identity fixtures |
| BFLY-02 | Causal, fresh, supported, liquid entry BBO; explicit rejects | Stale/missing/crossed/depth tests |
| BFLY-03 | Model/mid/BBO, spread/slip/fees separated, settlement costs | Sign and fee fixtures |
| BFLY-04 | Signed Greeks, theta/gamma carry | Scalar pricing / finite differences |
| BFLY-05 | Next-open and expiry full nonlinear P&L | Terminal identity / deterministic paths |
| BFLY-06 | 10:00 IST continuation/recenter, holiday timing, strict >250 trigger | Schedule/threshold/no-lookahead tests |
| BFLY-07 | RV/IV/cost/gap stress and uncertainty | All scenarios present, cost monotonicity |
| BFLY-08 | Exact position payoff/credit per lot; no candidate ranking | Output identities |
| BFLY-09 | Four-value VolARP dashboard, leg detail, centre what-if | Browser desktop/mobile/history |
| BFLY-10 | Preserve RV/eSSVI/reference, unavailable/stale behavior | Existing tests and live snapshot checks |

## Sources checked 2026-09-09

- https://www.optionseducation.org/strategies/all-strategies/short-iron-butterfly
- https://www.nseindia.com/static/products-services/equity-derivatives-securities-transaction-tax
- https://nsearchives.nseindia.com/content/circulars/FA73061.pdf
- https://nsearchives.nseindia.com/content/circulars/FAOP71777.pdf
- https://www.nseindia.com/static/invest/first-time-investor-stamp-duty-charges-taxes
- https://www.kotakneo.com/pricing/
- https://www.kotakneo.com/calculator/brokerage-calculator/

Forecast calibration not changed or independently revalidated by this task. Future liquidity,
actual margin, overnight variance allocation and future smile are not observed quantities.

## Superseded presentation notes

Latest instruction: simplify substantially and remove unnecessary information. BFLY-09
now presents RV/IV, three candidates ranked by the unchanged carry/static-risk ratio,
net recentered expiry profit and p05 downside. Selected detail retains legs, initial
credit clearly distinguished from profit, total cost, unchanged-hold comparison, static
loss caveat and daily recenter rule. Centre what-if retained. Surface is optional.
Remove q hero, alternative sorts, show-all, Greek/stress/MC tables, duplicate ATM,
feed diagnostics and held-out monitor from the page. All full model outputs remain in
the API; no pricing, sampling, forecasting, simulation, cost or reference-policy change.
Freshness, unavailable and arbitrage-failure notices must remain visible. A saved
after-session snapshot must be labelled historical, never live or session-close data.

BFLY-09 tracker clarification: four fields only — signed forward drift, Recenter?
Yes/No, new centre (current centre marked unchanged if No), and next scheduled
check formatted as `10 Sep, 3:15 PM IST`. Freshness stays in the existing page notices.
No remaining check before expiry means no recenter and current centre unchanged.

The former q hero, 400/500 filter and candidate ranking are superseded by the
VolARP RV/IV volatility ratio, fixed 500-point wings and exact ATM position.
