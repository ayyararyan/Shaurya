# Short iron butterfly dashboard — frozen implementation scope, 2026-09-09

Authority: Aryan specified short iron butterflies, 400/500 points, recentering if
moved too far, and explicitly authorized reasonable assumptions and implementation.
This supersedes the earlier open-choice proposal. Read-only; no order execution.

## Model and assumptions (version iron-carry-v1)

- NIFTY nearest fitted expiry only. Wings **400 or 500 points each side** (800/1000
  total span). Buy lower put and upper call; sell central put and call, one lot each.
  Enumerate quoted 50-point centres within half a wing-width of the current forward.
- Current leg IV and model price from accepted eSSVI, inside observed support only.
  Executable credit uses short bids minus long asks. Show market mid/model value
  separately. Require known equal lot sizes and at least one lot at each entry BBO,
  positive/noncrossed complete books, no crossed/invalid/stale/partial quality flags,
  quote age <=3s, no future rows. Informational flags such as source sequence
  unavailable are retained, not treated as invalid BBO (matching the DAT/SUR boundary).
- Hold continuously, including nights/weekends/holidays, to cash settlement at expiry.
  Recenter check at 15:15 IST on exchange trading days strictly after valuation,
  never on expiry day. If |forward-centre| >= width/2, close all four old legs and
  open same-width butterfly centred on nearest 50-point strike. No futures hedge.
  Compare unchanged hold. No beneficial hindsight or optimizing threshold on paths.
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
- Ranking: baseline net recentered mean / static option risk, with MC standard error,
  mean hold P&L, overnight mark-to-market after estimated close costs, mean total friction,
  expected recenter count and worst stress mean. Positive scenario mean is not a trading
  recommendation; flag when mean <=2 standard errors or a stress mean is negative.
  User may sort by net carry, carry/risk, local gamma-theta or cost; no hidden score.
- Current-position centre tracker is a browser-local what-if, not broker positions or
  persistent strategy execution. Live/historical/stale state and source timestamp visible.

## Requirements / acceptance

| ID | Required | Verification |
|---|---|---|
| BFLY-01 | Signed legs, strikes, expiry, actual lot metadata, 400/500 each side | Exact payoff and identity fixtures |
| BFLY-02 | Causal, fresh, supported, liquid entry BBO; explicit rejects | Stale/missing/crossed/depth tests |
| BFLY-03 | Model/mid/BBO, spread/slip/fees separated, settlement costs | Sign and fee fixtures |
| BFLY-04 | Signed Greeks, theta/gamma carry | Scalar pricing / finite differences |
| BFLY-05 | Next-open and expiry full nonlinear P&L | Terminal identity / deterministic paths |
| BFLY-06 | Daily recenter vs hold, holiday timing, fixed threshold | Schedule/threshold/no-lookahead tests |
| BFLY-07 | RV/IV/cost/gap stress and uncertainty | All scenarios present, cost monotonicity |
| BFLY-08 | Explicit rankings and risk/cost comparison per lot | Sort and output identities |
| BFLY-09 | Simple dashboard, selectable leg detail, centre what-if | Browser desktop/mobile/history |
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

## User-authorized presentation revision — essentials view, 2026-09-09

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
