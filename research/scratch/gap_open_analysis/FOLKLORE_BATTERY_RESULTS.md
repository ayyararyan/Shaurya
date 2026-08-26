# Indian Options Folklore Battery

**Headline verdict (descriptive screening evidence): 3 of 15 registered tests clear the Bonferroni cutoff 0.00333 (H3, H7, H14), but H7, H14 clear in the folklore-opposite direction. Supported-direction survivors: H3 (positive breakeven room; tail FAIL: worst -250.7% and max drawdown -773.0 percentage points; not a strategy).** A threshold-clearing negative is a rejection of the folklore rule, not a candidate. This is a screening battery, not a strategy recommendation, and no gate is armed. H11 PCR and H14 max pain are **truncated-chain proxies**, not the true full-chain quantities. Option estimates use traded closes without bid–ask and are upper bounds for buyers and sellers alike.


## Single summary table

| Hypothesis | N | Mean | t / registered stat | Nominal p (Bonf. 0.00333) | Pass | Placebo p | Breakeven cost % | Worst session | Max drawdown |
|---|---:|---:|---:|---:|:---:|---:|---:|---|---:|
| H1 SELL_STRADDLE_0920_ALL | 1315 | 1.4483 % of entry premium | 1.260 | 0.2081 (0.00333) | FAIL | — | 2.551 | 2025-04-17: -429.123 | -784.972 |
| H2 SELL_STRADDLE_0920_EXPIRY | 275 | -1.5276 % of entry premium | -0.317 | 0.7516 (0.00333) | FAIL | 0.7721139430284858 | 2.538 | 2025-04-17: -429.123 | -1584.253 |
| H3 SELL_STRADDLE_0920_NONEXPIRY | 1040 | 2.2352 % of entry premium | 3.191 | 0.001462 (0.00333) | PASS | 0.0004997501249375312 | 2.553 | 2023-12-20: -250.683 | -772.995 |
| H4 SELL_STRADDLE_OVERNIGHT | 1035 | -2.3408 % of entry premium | -1.165 | 0.2442 (0.00333) | FAIL | — | 0.699 | 2021-06-10: -1655.602 | -2899.835 |
| H5 SELL_STRADDLE_HIGH_IV | 472 | 3.3656 % of entry premium | 1.322 | 0.1868 (0.00333) | FAIL | 0.25837081459270367 | 4.914 | 2025-04-17: -429.123 | -560.179 |
| H6 SELL_STRADDLE_BY_DTE | 1315 | 1.4483 % of entry premium | F=0.579 | 0.8325 (0.00333) | FAIL | 0.8325837081459271 | 2.551 | 2025-04-17: -429.123 | -784.972 |
| H7 BUY_OTM_EXPIRY_LOTTERY | 262 | -92.0057 % of entry premium | -27.326 | 1.566e-78 (0.00333) | PASS (opposite sign) | 0.0004997501249375312 | -94.145 | 2026-02-03: -99.922 | -24580.901 |
| H8 BUY_STRADDLE_LOW_IV | 842 | -0.3581 % of entry premium | -0.329 | 0.7425 (0.00333) | FAIL | 0.8835582208895553 | -1.067 | 2023-10-12: -92.210 | -1292.115 |
| H9 GAP_FADE | 1316 | 0.0136 % spot return | 0.709 | 0.4786 (0.00333) | FAIL | 0.47926036981509246 | — | 2021-02-01: -4.364 | -20.241 |
| H10 GAP_CONTINUATION | 1316 | -0.0136 % spot return | -0.709 | 0.4786 (0.00333) | FAIL | 0.47926036981509246 | — | 2022-06-16: -3.063 | -50.247 |
| H11 PCR_CONTRARIAN_TRUNCATED_CHAIN_PROXY | 1316 | 0.0276 % spot return | 1.444 | 0.149 (0.00333) | FAIL | 0.14642678660669664 | — | 2024-06-04: -3.337 | -12.235 |
| H12 WEEKDAY | 1317 | -0.0141 % spot return | F=2.017 | 0.04992 (0.00333) | FAIL | 0.0399800099950025 | — | 2024-06-04: -3.337 | -27.029 |
| H13 OVERNIGHT_VS_INTRADAY | 1316 | 0.0704 percentage-point return difference | 2.905 | 0.003738 (0.00333) | FAIL | — | — | 2025-04-07: -4.824 | -15.667 |
| H14 MAX_PAIN_PIN_TRUNCATED_CHAIN_PROXY | 276 | -57.3844 spot points closer to max-pain proxy | -9.239 | 7.03e-18 (0.00333) | PASS (opposite sign) | 0.0004997501249375312 | — | 2025-04-17: -460.300 | -15922.400 |
| H15 ROUND_NUMBER_PIN | 276 | -0.8667 spot-point closeness surplus vs uniform | -0.960 | 0.338 (0.00333) | FAIL | 0.40229885057471265 | — | 2024-10-17: -24.800 | -504.000 |

*Option-row means and per-year means are traded-close estimates. They exclude bid–ask and therefore are upper bounds for buyers and sellers alike. Breakeven cost is the round-trip cost as a percent of entry premium that sets mean point P&L to zero.*

## H1 — SELL_STRADDLE_0920_ALL

N=1315; mean=1.448316 % of entry premium; t=1.2595170884974094; nominal p=0.208067 (Bonferroni threshold 0.00333); Wilcoxon p=6.976721440139036e-18; lag-1 autocorrelation=-0.04259421781999086. Registered primary: one-sample t=1.2595170884974094, p=0.20806729542386504.
Breakeven round-trip cost=2.551048% of entry premium. Every mean in this section uses traded closes, excludes bid–ask, and is an upper bound for the buyer and for the seller alike.
Tail: worst five = 2025-04-17 -429.1226; 2022-06-16 -336.5016; 2024-09-12 -270.6667; 2023-12-20 -250.6834; 2022-12-15 -244.9743; max drawdown=-784.972192; p1=-156.755732; p99=91.073108. Tail survivability is not established because the frozen design has no capital/margin model.
**Tail verdict: FAIL.** The worst session lost at least 100% of entry premium. This catastrophic exposed tail means the positive mean, if any, is **not a strategy**.

### Per-year breakdown

| Year | N | Mean | t | Nominal p (Bonf. 0.00333) | Wilcoxon p |
|---:|---:|---:|---:|---:|---:|
| 2021 | 246 | 3.957087 | 1.8203155885941689 | 0.06993101157276957 | 1.718307002945124e-05 |
| 2022 | 247 | -2.089329 | -0.7478290503524854 | 0.45527756061485564 | 0.004865534302171645 |
| 2023 | 245 | 0.443594 | 0.175993301178622 | 0.860445180537728 | 0.0002999865102074412 |
| 2024 | 244 | 1.072412 | 0.3615273083976199 | 0.7180194409051781 | 0.0005322120241380482 |
| 2025 | 248 | 4.401283 | 1.56165112528777 | 0.11965050494981695 | 3.3966098037046737e-06 |
| 2026 | 85 | -0.173066 | -0.04051516233784126 | 0.9677785620594005 | 0.052509850458854444 |

## H2 — SELL_STRADDLE_0920_EXPIRY

N=275; mean=-1.527627 % of entry premium; t=-0.31686037547280566; nominal p=0.751591 (Bonferroni threshold 0.00333); Wilcoxon p=0.14792140171463417; lag-1 autocorrelation=-0.06250998782705819. Registered primary: one-sample t=-0.31686037547280566, p=0.7515908352995286.
Placebo: 2000 draws, seed 20260823, empirical p=0.7721139430284858.
Breakeven round-trip cost=2.538019% of entry premium. Every mean in this section uses traded closes, excludes bid–ask, and is an upper bound for the buyer and for the seller alike.
Tail: worst five = 2025-04-17 -429.1226; 2022-06-16 -336.5016; 2024-09-12 -270.6667; 2022-12-15 -244.9743; 2022-11-24 -234.3920; max drawdown=-1584.252775; p1=-251.654331; p99=97.100261. Tail survivability is not established because the frozen design has no capital/margin model.
**Tail verdict: FAIL.** The worst session lost at least 100% of entry premium. This catastrophic exposed tail means the positive mean, if any, is **not a strategy**.

### Per-year breakdown

| Year | N | Mean | t | Nominal p (Bonf. 0.00333) | Wilcoxon p |
|---:|---:|---:|---:|---:|---:|
| 2021 | 49 | 5.575863 | 0.6016072796181393 | 0.550266614883863 | 0.30377721953336945 |
| 2022 | 52 | -14.695823 | -1.2206461830975412 | 0.2278337282580254 | 0.7499220986895838 |
| 2023 | 52 | -2.563116 | -0.2662368972483775 | 0.7911302117686624 | 0.9709413538615811 |
| 2024 | 51 | -1.602979 | -0.1292181971318495 | 0.8977034075495914 | 0.49380905517129214 |
| 2025 | 52 | 4.319063 | 0.3462764684184395 | 0.730559514130998 | 0.13529737207114167 |
| 2026 | 19 | 3.226884 | 0.18833011389907017 | 0.8527248423981286 | 0.3320655822753906 |

## H3 — SELL_STRADDLE_0920_NONEXPIRY

N=1040; mean=2.235224 % of entry premium; t=3.190720887343511; nominal p=0.00146171 (Bonferroni threshold 0.00333); Wilcoxon p=1.2442952747199458e-20; lag-1 autocorrelation=-0.031105176470120774. Registered primary: one-sample t=3.190720887343511, p=0.0014617052291761867.
Placebo: 2000 draws, seed 20260823, empirical p=0.0004997501249375312.
Breakeven round-trip cost=2.552659% of entry premium. Every mean in this section uses traded closes, excludes bid–ask, and is an upper bound for the buyer and for the seller alike.
Year stability: the mean is positive in 2021–2025 but only 2025 individually clears 0.00333, and 2026 is negative. The aggregate screen is therefore a **lead, not a finding**; its catastrophic tail separately prevents strategy interpretation.
Tail: worst five = 2023-12-20 -250.6834; 2024-01-23 -167.8147; 2024-03-13 -148.2153; 2021-01-21 -127.2793; 2026-02-19 -114.0611; max drawdown=-772.995242; p1=-78.205291; p99=36.521234. Tail survivability is not established because the frozen design has no capital/margin model.
**Tail verdict: FAIL.** The worst session lost at least 100% of entry premium. This catastrophic exposed tail means the positive mean, if any, is **not a strategy**.

### Per-year breakdown

| Year | N | Mean | t | Nominal p (Bonf. 0.00333) | Wilcoxon p |
|---:|---:|---:|---:|---:|---:|
| 2021 | 197 | 3.554447 | 2.430014545099163 | 0.01599902215971606 | 5.971408059069662e-06 |
| 2022 | 195 | 1.272402 | 0.8781644847543034 | 0.3809407585085947 | 0.00035364793696207716 |
| 2023 | 193 | 1.253693 | 0.6607798768044145 | 0.5095455440098408 | 9.923490569269473e-06 |
| 2024 | 193 | 1.779380 | 0.9542717859841168 | 0.34114596807989306 | 0.00016823958152262434 |
| 2025 | 196 | 4.423096 | 3.1790884752094644 | 0.0017184871850941363 | 8.916751437260152e-06 |
| 2026 | 66 | -1.151840 | -0.43853757598754994 | 0.6624507854214643 | 0.14972250649831786 |

## H4 — SELL_STRADDLE_OVERNIGHT

N=1035; mean=-2.340817 % of entry premium; t=-1.1652208319923976; nominal p=0.244198 (Bonferroni threshold 0.00333); Wilcoxon p=1.180716403959077e-18; lag-1 autocorrelation=-0.0015444408438820894. Registered primary: one-sample t=-1.1652208319923976, p=0.24419834856438621.
Breakeven round-trip cost=0.698984% of entry premium. Every mean in this section uses traded closes, excludes bid–ask, and is an upper bound for the buyer and for the seller alike.
Expiry-session entries are unavailable: the WEEK1 contract expires before the next session and cannot be bought back at 09:15.
Tail: worst five = 2021-06-10 -1655.6017; 2025-09-02 -804.8986; 2021-07-29 -771.4943; 2021-01-21 -407.4614; 2022-02-23 -128.1250; max drawdown=-2899.834502; p1=-71.513894; p99=27.442463. Tail survivability is not established because the frozen design has no capital/margin model.
**Tail verdict: FAIL.** The worst session lost at least 100% of entry premium. This catastrophic exposed tail means the positive mean, if any, is **not a strategy**.

### Per-year breakdown

| Year | N | Mean | t | Nominal p (Bonf. 0.00333) | Wilcoxon p |
|---:|---:|---:|---:|---:|---:|
| 2021 | 195 | -14.129305 | -1.471211967866791 | 0.14285399534649604 | 0.0023247222819869954 |
| 2022 | 195 | 2.044140 | 1.6805020727077478 | 0.09446907732892958 | 3.9702356211211095e-07 |
| 2023 | 193 | -0.191953 | -0.29053983390297633 | 0.7717168594669469 | 0.3632187565081072 |
| 2024 | 193 | 0.928796 | 1.0223160030753824 | 0.307917723984235 | 5.455573675854258e-07 |
| 2025 | 195 | -2.005350 | -0.47598669819447215 | 0.6346194352206032 | 3.283311989640363e-05 |
| 2026 | 64 | 2.854596 | 1.2819793310477383 | 0.20454760051661608 | 0.005629305051710234 |

## H5 — SELL_STRADDLE_HIGH_IV

N=472; mean=3.365585 % of entry premium; t=1.3218802617419183; nominal p=0.18685 (Bonferroni threshold 0.00333); Wilcoxon p=4.24288806060647e-08; lag-1 autocorrelation=0.0010899447484244125. Registered primary: one-sample t=1.3218802617419183, p=0.18684966790463636.
Placebo: 2000 draws, seed 20260823, empirical p=0.25837081459270367.
Breakeven round-trip cost=4.914488% of entry premium. Every mean in this section uses traded closes, excludes bid–ask, and is an upper bound for the buyer and for the seller alike.
Tail: worst five = 2025-04-17 -429.1226; 2022-06-16 -336.5016; 2024-09-12 -270.6667; 2025-05-15 -191.6772; 2024-04-18 -185.6663; max drawdown=-560.179359; p1=-180.121988; p99=95.398581. Tail survivability is not established because the frozen design has no capital/margin model.
**Tail verdict: FAIL.** The worst session lost at least 100% of entry premium. This catastrophic exposed tail means the positive mean, if any, is **not a strategy**.

### Per-year breakdown

| Year | N | Mean | t | Nominal p (Bonf. 0.00333) | Wilcoxon p |
|---:|---:|---:|---:|---:|---:|
| 2021 | 107 | 5.877910 | 1.383756808118267 | 0.16933989906257674 | 0.0013104383078206998 |
| 2022 | 128 | -0.185757 | -0.0435424347914581 | 0.9653375245711895 | 0.05648483160350292 |
| 2023 | 33 | 15.495260 | 1.5181078748279777 | 0.13880596600511516 | 0.03534287237562239 |
| 2024 | 101 | 1.465827 | 0.22759456734102324 | 0.8204261259663762 | 0.06609292683591414 |
| 2025 | 61 | 2.896400 | 0.29734634984914754 | 0.7672291684670717 | 0.009220832772510188 |
| 2026 | 42 | 3.507714 | 0.6104967601384866 | 0.5449022928181572 | 0.02581143920224349 |

## H6 — SELL_STRADDLE_BY_DTE

N=1315; mean=1.448316 % of entry premium; t=1.2595170884974094; nominal p=0.832482 (Bonferroni threshold 0.00333); Wilcoxon p=6.976721440139036e-18; lag-1 autocorrelation=-0.04259421781999086. Registered primary: joint F(all cell means=0)=0.5786409574700498, p=0.8324822113692769.
Placebo: 2000 draws, seed 20260823, empirical p=0.8325837081459271.
Breakeven round-trip cost=2.551048% of entry premium. Every mean in this section uses traded closes, excludes bid–ask, and is an upper bound for the buyer and for the seller alike.
Tail: worst five = 2025-04-17 -429.1226; 2022-06-16 -336.5016; 2024-09-12 -270.6667; 2023-12-20 -250.6834; 2022-12-15 -244.9743; max drawdown=-784.972192; p1=-156.755732; p99=91.073108. Tail survivability is not established because the frozen design has no capital/margin model.
**Tail verdict: FAIL.** The worst session lost at least 100% of entry premium. This catastrophic exposed tail means the positive mean, if any, is **not a strategy**.

### Per-year breakdown

| Year | N | Mean | t | Nominal p (Bonf. 0.00333) | Wilcoxon p |
|---:|---:|---:|---:|---:|---:|
| 2021 | 246 | 3.957087 | 1.8203155885941689 | 0.06993101157276957 | 1.718307002945124e-05 |
| 2022 | 247 | -2.089329 | -0.7478290503524854 | 0.45527756061485564 | 0.004865534302171645 |
| 2023 | 245 | 0.443594 | 0.175993301178622 | 0.860445180537728 | 0.0002999865102074412 |
| 2024 | 244 | 1.072412 | 0.3615273083976199 | 0.7180194409051781 | 0.0005322120241380482 |
| 2025 | 248 | 4.401283 | 1.56165112528777 | 0.11965050494981695 | 3.3966098037046737e-06 |
| 2026 | 85 | -0.173066 | -0.04051516233784126 | 0.9677785620594005 | 0.052509850458854444 |

DTE-cell tests (each also contains t and Wilcoxon):
```json
{
  "1": {
    "n": 275,
    "mean": -1.5276267336781615,
    "sd": 79.9494838659855,
    "t": -0.31686037547280566,
    "t_p": 0.7515908352995286,
    "wilcoxon_stat": 17065.0,
    "wilcoxon_p": 0.14792140171463417
  },
  "2": {
    "n": 274,
    "mean": 2.856992846318176,
    "sd": 30.62462563358891,
    "t": 1.5442359046923566,
    "t_p": 0.12368956235046533,
    "wilcoxon_stat": 12538.0,
    "wilcoxon_p": 1.600488445893872e-06
  },
  "3": {
    "n": 274,
    "mean": 2.7470463803819927,
    "sd": 21.653532777777798,
    "t": 2.0999672014236754,
    "t_p": 0.03664940201806906,
    "wilcoxon_stat": 11653.0,
    "wilcoxon_p": 4.4409072571015926e-08
  },
  "4": {
    "n": 272,
    "mean": 1.7551658344546226,
    "sd": 16.52225516716463,
    "t": 1.7519966984443225,
    "t_p": 0.08090544398317681,
    "wilcoxon_stat": 12579.0,
    "wilcoxon_p": 4.0463014143888855e-06
  },
  "5": {
    "n": 200,
    "mean": 0.674034219268444,
    "sd": 17.275411827759598,
    "t": 0.551783276657559,
    "t_p": 0.5817159425392899,
    "wilcoxon_stat": 7469.0,
    "wilcoxon_p": 0.0016368491969918691
  },
  "6": {
    "n": 7,
    "mean": 23.981376815898436,
    "sd": 28.708827456316396,
    "t": 2.2100783895943312,
    "t_p": 0.06913582895438228,
    "wilcoxon_stat": 5.0,
    "wilcoxon_p": 0.15625
  },
  "7": {
    "n": 4,
    "mean": -0.7669583545820156,
    "sd": 13.522552665580957,
    "t": -0.11343396081335438,
    "t_p": 0.9168516225397533,
    "wilcoxon_stat": 4.0,
    "wilcoxon_p": 0.875
  },
  "8": {
    "n": 4,
    "mean": -2.5461169844336924,
    "sd": 30.423660366418233,
    "t": -0.16737742623790972,
    "t_p": 0.8777196014929963,
    "wilcoxon_stat": 4.0,
    "wilcoxon_p": 0.875
  },
  "9": {
    "n": 3,
    "mean": 1.405395254264078,
    "sd": 12.583752182081096,
    "t": 0.19344118907298716,
    "t_p": 0.8644783362895899,
    "wilcoxon_stat": 2.0,
    "wilcoxon_p": 0.75
  },
  "10": {
    "n": 2,
    "mean": 9.04042541714555,
    "sd": 5.750264444632265,
    "t": 2.2233920470360733,
    "t_p": 0.26907181255916385,
    "wilcoxon_stat": 0.0,
    "wilcoxon_p": 0.5
  }
}
```

Per-year DTE-cell means (% of entry premium):

| Year | DTE 1 | DTE 2 | DTE 3 | DTE 4 | DTE 5 | DTE 6 | DTE 7 | DTE 8 | DTE 9 | DTE 10 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2021 | 5.5759 | 6.4589 | 3.8395 | 1.8226 | -0.9626 | 46.7379 | 2.9115 | -9.1687 | 1.4054 | 9.0404 |
| 2022 | -14.6958 | 0.7999 | -1.2228 | 2.3336 | 3.7773 | — | — | — | — | — |
| 2023 | -2.5631 | -5.0022 | 6.2699 | 1.5457 | 2.5855 | — | — | — | — | — |
| 2024 | -1.6030 | 4.4608 | 2.2202 | 2.7914 | -3.4010 | -18.8475 | — | — | — | — |
| 2025 | 4.3191 | 7.5103 | 4.8103 | 2.5067 | 1.7766 | 15.0959 | -11.8023 | 17.3218 | — | — |
| 2026 | 3.2269 | 3.7118 | -3.2597 | -4.5813 | -1.6370 | 16.3117 | — | — | — | — |

## H7 — BUY_OTM_EXPIRY_LOTTERY

N=262; mean=-92.005690 % of entry premium; t=-27.325781370748135; nominal p=1.56557e-78 (Bonferroni threshold 0.00333); Wilcoxon p=6.602091190024238e-41; lag-1 autocorrelation=-0.01212481104688315. Registered primary: one-sample t=-27.325781370748135, p=1.5655690195681443e-78.
Placebo: 2000 draws, seed 20260823, empirical p=0.0004997501249375312.
Breakeven round-trip cost=-94.145387% of entry premium. Every mean in this section uses traded closes, excludes bid–ask, and is an upper bound for the buyer and for the seller alike.
The sign is decisively opposite the buying folklore: the average expiry lottery loses 92.0% of entry premium. This is evidence against the rule, not a survivor and not a strategy.
Tail: worst five = 2026-02-03 -99.9223; 2024-06-06 -99.8882; 2024-02-01 -99.8756; 2026-03-02 -99.8572; 2024-12-05 -99.8301; max drawdown=-24580.900508; p1=-99.864412; p99=55.800880. Tail survivability is not established because the frozen design has no capital/margin model.

### Per-year breakdown

| Year | N | Mean | t | Nominal p (Bonf. 0.00333) | Wilcoxon p |
|---:|---:|---:|---:|---:|---:|
| 2021 | 48 | -85.058392 | -6.749579150611977 | 1.9610407756064678e-08 | 3.048232266650979e-08 |
| 2022 | 50 | -97.891548 | -488.69877703754423 | 5.003443063736741e-92 | 7.543270531852816e-10 |
| 2023 | 52 | -96.456297 | -420.84883644653917 | 5.695144436284185e-92 | 3.492894283879003e-10 |
| 2024 | 47 | -90.688233 | -14.333268404583345 | 1.3912604157852289e-18 | 3.091003009103588e-10 |
| 2025 | 48 | -98.666982 | -746.8486681957157 | 2.065883336225359e-97 | 1.6306098573244595e-09 |
| 2026 | 17 | -65.530644 | -1.9382554200608577 | 0.07044325801656832 | 0.0031585693359375 |

## H8 — BUY_STRADDLE_LOW_IV

N=842; mean=-0.358054 % of entry premium; t=-0.32860460800492497; nominal p=0.742536 (Bonferroni threshold 0.00333); Wilcoxon p=1.236300064283058e-10; lag-1 autocorrelation=-0.02622774538615261. Registered primary: one-sample t=-0.32860460800492497, p=0.7425363681531179.
Placebo: 2000 draws, seed 20260823, empirical p=0.8835582208895553.
Breakeven round-trip cost=-1.066815% of entry premium. Every mean in this section uses traded closes, excludes bid–ask, and is an upper bound for the buyer and for the seller alike.
Tail: worst five = 2023-10-12 -92.2095; 2025-10-07 -91.4697; 2025-10-28 -90.4877; 2023-11-09 -88.5838; 2023-10-05 -82.3994; max drawdown=-1292.115398; p1=-73.094742; p99=120.488912. Tail survivability is not established because the frozen design has no capital/margin model.

### Per-year breakdown

| Year | N | Mean | t | Nominal p (Bonf. 0.00333) | Wilcoxon p |
|---:|---:|---:|---:|---:|---:|
| 2021 | 138 | -2.391366 | -1.1675207546715307 | 0.24502809603543774 | 0.008753122926748248 |
| 2022 | 119 | 4.136870 | 1.163651507238268 | 0.24691283599774563 | 0.038851074608478295 |
| 2023 | 212 | 1.899354 | 0.7861203585631351 | 0.43267891907924083 | 0.0030865071342587166 |
| 2024 | 143 | -0.794545 | -0.35322943159768 | 0.724440278816592 | 0.0024063778658897834 |
| 2025 | 187 | -4.892181 | -2.4462888226251724 | 0.015363431726375585 | 0.0001940724728601605 |
| 2026 | 43 | 3.768247 | 0.5955225403820098 | 0.5546898732319944 | 0.5142726046974531 |

## H9 — GAP_FADE

N=1316; mean=0.013570 % spot return; t=0.7087597793842529; nominal p=0.478599 (Bonferroni threshold 0.00333); Wilcoxon p=0.5148499666069033; lag-1 autocorrelation=0.037026317369562675. Registered primary: one-sample t=0.7087597793842529, p=0.47859918618602204.
Placebo: 2000 draws, seed 20260823, empirical p=0.47926036981509246.
H9 and its exact H10 mirror are reported alongside; the frozen family size remains 15.
Tail: worst five = 2021-02-01 -4.3644; 2024-06-04 -3.3374; 2022-02-24 -2.6329; 2022-02-15 -2.4902; 2024-06-05 -2.4214; max drawdown=-20.240999; p1=-1.713076; p99=1.819378. Tail survivability is not established because the frozen design has no capital/margin model.

### Per-year breakdown

| Year | N | Mean | t | Nominal p (Bonf. 0.00333) | Wilcoxon p |
|---:|---:|---:|---:|---:|---:|
| 2021 | 243 | -0.035161 | -0.6889920818081764 | 0.49148828484783624 | 0.7092394780396107 |
| 2022 | 247 | 0.066593 | 1.242969864911693 | 0.21506232989080698 | 0.1698269555166182 |
| 2023 | 245 | 0.012925 | 0.40241889866346897 | 0.6877280799608759 | 0.9164427542497126 |
| 2024 | 247 | 0.048553 | 1.080542983396821 | 0.2809586459144147 | 0.17149306157933641 |
| 2025 | 248 | 0.002185 | 0.06135057519033928 | 0.9511296263360338 | 0.6841694725241968 |
| 2026 | 86 | -0.066824 | -0.8753013066440483 | 0.3838766902790357 | 0.2423721380522239 |

## H10 — GAP_CONTINUATION

N=1316; mean=-0.013570 % spot return; t=-0.7087597793842529; nominal p=0.478599 (Bonferroni threshold 0.00333); Wilcoxon p=0.5148499666069033; lag-1 autocorrelation=0.037026317369562675. Registered primary: one-sample t=-0.7087597793842529, p=0.47859918618602204.
Placebo: 2000 draws, seed 20260823, empirical p=0.47926036981509246.
H9 and its exact H10 mirror are reported alongside; the frozen family size remains 15.
Tail: worst five = 2022-06-16 -3.0635; 2022-05-04 -2.3382; 2022-04-19 -2.3168; 2024-01-23 -2.2704; 2026-04-02 -2.1441; max drawdown=-50.247282; p1=-1.819378; p99=1.713076. Tail survivability is not established because the frozen design has no capital/margin model.

### Per-year breakdown

| Year | N | Mean | t | Nominal p (Bonf. 0.00333) | Wilcoxon p |
|---:|---:|---:|---:|---:|---:|
| 2021 | 243 | 0.035161 | 0.6889920818081764 | 0.49148828484783624 | 0.7092394780396107 |
| 2022 | 247 | -0.066593 | -1.242969864911693 | 0.21506232989080698 | 0.1698269555166182 |
| 2023 | 245 | -0.012925 | -0.40241889866346897 | 0.6877280799608759 | 0.9164427542497126 |
| 2024 | 247 | -0.048553 | -1.080542983396821 | 0.2809586459144147 | 0.17149306157933641 |
| 2025 | 248 | -0.002185 | -0.06135057519033928 | 0.9511296263360338 | 0.6841694725241968 |
| 2026 | 86 | 0.066824 | 0.8753013066440483 | 0.3838766902790357 | 0.2423721380522239 |

## H11 — PCR_CONTRARIAN_TRUNCATED_CHAIN_PROXY

N=1316; mean=0.027632 % spot return; t=1.444059100914224; nominal p=0.148961 (Bonferroni threshold 0.00333); Wilcoxon p=0.15156779873609144; lag-1 autocorrelation=0.014700912867489072. Registered primary: one-sample t=1.444059100914224, p=0.14896055299397742.
Placebo: 2000 draws, seed 20260823, empirical p=0.14642678660669664.
PCR uses only the archived ATM±10 chain and is a truncated-chain proxy, not the true full-chain PCR.
Tail: worst five = 2024-06-04 -3.3374; 2022-02-24 -2.6329; 2022-02-15 -2.4902; 2024-06-05 -2.4214; 2022-01-24 -2.4114; max drawdown=-12.234948; p1=-1.736874; p99=1.879807. Tail survivability is not established because the frozen design has no capital/margin model.

### Per-year breakdown

| Year | N | Mean | t | Nominal p (Bonf. 0.00333) | Wilcoxon p |
|---:|---:|---:|---:|---:|---:|
| 2021 | 243 | 0.021943 | 0.4297122904608108 | 0.6677873033412527 | 0.6147898312172873 |
| 2022 | 247 | -0.006520 | -0.1213163450335337 | 0.9035395093580086 | 0.8839957538563337 |
| 2023 | 245 | 0.023552 | 0.7338678021131246 | 0.46373388424797735 | 0.5477560335986569 |
| 2024 | 247 | 0.124497 | 2.808050149687698 | 0.005384082180369227 | 0.0023868265764693274 |
| 2025 | 248 | 0.003580 | 0.10049415810468862 | 0.9200335420739427 | 0.9851838178853982 |
| 2026 | 86 | -0.055423 | -0.7249429296428076 | 0.4704780279836491 | 0.4446798716821183 |

## H12 — WEEKDAY

N=1317; mean=-0.014105 % spot return; t=-0.7372442285514056; nominal p=0.049916 (Bonferroni threshold 0.00333); Wilcoxon p=0.9811310610713694; lag-1 autocorrelation=-0.08399901432314313. Registered primary: joint F(all cell means=0)=2.017252407617773, p=0.04991602834096224.
Placebo: 2000 draws, seed 20260823, empirical p=0.0399800099950025.
Tail: worst five = 2024-06-04 -3.3374; 2022-06-16 -3.0635; 2022-02-24 -2.6329; 2022-01-24 -2.4114; 2022-05-04 -2.3382; max drawdown=-27.029307; p1=-1.840105; p99=1.715404. Tail survivability is not established because the frozen design has no capital/margin model.

### Per-year breakdown

| Year | N | Mean | t | Nominal p (Bonf. 0.00333) | Wilcoxon p |
|---:|---:|---:|---:|---:|---:|
| 2021 | 244 | -0.037620 | -0.7403186453983007 | 0.4598213587152818 | 0.6414071321764345 |
| 2022 | 247 | -0.030179 | -0.5618927480430793 | 0.5747006752991822 | 0.7480810416303101 |
| 2023 | 245 | 0.013578 | 0.4227536905274442 | 0.6728473021694845 | 0.2705315479005618 |
| 2024 | 247 | -0.013765 | -0.305673252062416 | 0.7601119453858983 | 0.8741722080684777 |
| 2025 | 248 | -0.001863 | -0.05229269029245272 | 0.9583377440187856 | 0.8277883592388692 |
| 2026 | 86 | -0.016363 | -0.21343191226728808 | 0.8315011907241795 | 0.9742368148209887 |

Weekday-cell tests (joint F is the registered primary):
```json
{
  "Friday": {
    "n": 260,
    "mean": -0.05792200797158671,
    "sd": 0.6896049754684028,
    "t": -1.3543468338485969,
    "t_p": 0.17680612830147388,
    "wilcoxon_stat": 15381.0,
    "wilcoxon_p": 0.1918677829045704
  },
  "Monday": {
    "n": 266,
    "mean": 0.06408215755923108,
    "sd": 0.7126894546281075,
    "t": 1.4664849521663788,
    "t_p": 0.14370186604073193,
    "wilcoxon_stat": 15080.0,
    "wilcoxon_p": 0.03314290565823543
  },
  "Saturday": {
    "n": 3,
    "mean": -0.24290597084792123,
    "sd": 0.32173907475502384,
    "t": -1.307660511210178,
    "t_p": 0.32109429482385954,
    "wilcoxon_stat": 1.0,
    "wilcoxon_p": 0.5
  },
  "Sunday": {
    "n": 1,
    "mean": -2.0214407215475294,
    "sd": null,
    "t": null,
    "t_p": null,
    "wilcoxon_stat": 0.0,
    "wilcoxon_p": 1.0
  },
  "Thursday": {
    "n": 260,
    "mean": -0.04063900417404304,
    "sd": 0.7132800260092075,
    "t": -0.918691437690942,
    "t_p": 0.3591117488940699,
    "wilcoxon_stat": 16025.0,
    "wilcoxon_p": 0.43864964953206853
  },
  "Tuesday": {
    "n": 265,
    "mean": -0.01833037906505259,
    "sd": 0.7146580346924446,
    "t": -0.4175380920287408,
    "t_p": 0.6766242354703753,
    "wilcoxon_stat": 17180.0,
    "wilcoxon_p": 0.7230916145148136
  },
  "Wednesday": {
    "n": 262,
    "mean": -0.009115812628952663,
    "sd": 0.6291143857058342,
    "t": -0.23453972921914826,
    "t_p": 0.8147498800502396,
    "wilcoxon_stat": 16628.0,
    "wilcoxon_p": 0.6259143942102409
  }
}
```

Per-year weekday-cell means (% spot return):

| Year | Monday | Tuesday | Wednesday | Thursday | Friday |
|---:|---:|---:|---:|---:|---:|
| 2021 | 0.0335 | 0.1283 | -0.1434 | 0.0101 | -0.2263 |
| 2022 | 0.1133 | 0.1896 | -0.1091 | -0.2028 | -0.1328 |
| 2023 | 0.0711 | -0.0167 | -0.0079 | -0.0496 | 0.0706 |
| 2024 | -0.0403 | -0.2083 | 0.0668 | 0.0034 | 0.1473 |
| 2025 | 0.0718 | -0.1816 | 0.1333 | 0.0731 | -0.0950 |
| 2026 | 0.2583 | 0.0353 | 0.0381 | -0.1136 | -0.2097 |

## H13 — OVERNIGHT_VS_INTRADAY

N=1316; mean=0.070408 percentage-point return difference; t=2.904648372576396; nominal p=0.00373813 (Bonferroni threshold 0.00333); Wilcoxon p=0.00014882183721150503; lag-1 autocorrelation=-0.17971851482705248. Registered primary: one-sample t=2.904648372576396, p=0.0037381261317155816.
Tail: worst five = 2025-04-07 -4.8243; 2026-04-02 -4.2537; 2021-02-01 -3.8022; 2022-02-28 -3.4091; 2022-01-25 -3.2681; max drawdown=-15.667376; p1=-2.516030; p99=2.397556. Tail survivability is not established because the frozen design has no capital/margin model.

### Per-year breakdown

| Year | N | Mean | t | Nominal p (Bonf. 0.00333) | Wilcoxon p |
|---:|---:|---:|---:|---:|---:|
| 2021 | 243 | 0.163855 | 2.7290044989026794 | 0.006818891590707029 | 0.0005332409806824081 |
| 2022 | 247 | 0.083703 | 1.180549848246377 | 0.238921809636957 | 0.15459960309301723 |
| 2023 | 245 | 0.048892 | 1.2674279847001193 | 0.20621054660039576 | 0.285692916208074 |
| 2024 | 247 | 0.065583 | 1.2829823176424546 | 0.20070569776183586 | 0.11328210568175216 |
| 2025 | 248 | 0.046430 | 1.0107830632848642 | 0.3131094054532227 | 0.10946744151345936 |
| 2026 | 86 | -0.087526 | -0.6895158433230647 | 0.49237681720094334 | 0.568308384485334 |

Component tests:
```json
{
  "overnight_vs_zero": {
    "n": 1316,
    "mean": 0.05628664932391966,
    "sd": 0.5578626148723868,
    "t": 3.6602106713709928,
    "t_p": 0.0002619894540446248,
    "wilcoxon_stat": 345570.0,
    "wilcoxon_p": 1.995395450046605e-10
  },
  "intraday_vs_zero": {
    "n": 1316,
    "mean": -0.014120970608012082,
    "sd": 0.6945672135894108,
    "t": -0.7375274937895019,
    "t_p": 0.460933207856759,
    "wilcoxon_stat": 432951.0,
    "wilcoxon_p": 0.9802129521710169
  },
  "overnight_minus_intraday": {
    "n": 1316,
    "mean": 0.07040761993193174,
    "sd": 0.8793343581744041,
    "t": 2.904648372576396,
    "t_p": 0.0037381261317155816,
    "wilcoxon_stat": 380990.0,
    "wilcoxon_p": 0.00014882183721150503
  }
}
```

Per-year component means (percentage points):

| Year | Overnight | Intraday | Overnight − intraday |
|---:|---:|---:|---:|
| 2021 | 0.1261 | -0.0378 | 0.1639 |
| 2022 | 0.0535 | -0.0302 | 0.0837 |
| 2023 | 0.0625 | 0.0136 | 0.0489 |
| 2024 | 0.0518 | -0.0138 | 0.0656 |
| 2025 | 0.0446 | -0.0019 | 0.0464 |
| 2026 | -0.1039 | -0.0164 | -0.0875 |

## H14 — MAX_PAIN_PIN_TRUNCATED_CHAIN_PROXY

N=276; mean=-57.384420 spot points closer to max-pain proxy; t=-9.238947385647064; nominal p=7.03045e-18 (Bonferroni threshold 0.00333); Wilcoxon p=7.229595992975327e-17; lag-1 autocorrelation=-0.09037589938009291. Registered primary: one-sample t=-9.238947385647064, p=7.030448951995185e-18.
Placebo: 2000 draws, seed 20260823, empirical p=0.0004997501249375312.
Max pain uses only the archived ATM±10 chain and is a truncated-chain proxy, not true full-chain max pain.
The negative score means expiry closes move farther from the truncated max-pain proxy on average. The significant result rejects proxy pinning; it does not support it, and it says nothing definitive about true full-chain max pain.
Tail: worst five = 2025-04-17 -460.3000; 2022-02-24 -438.5508; 2022-06-16 -418.5498; 2025-05-15 -394.7000; 2025-01-02 -380.3500; max drawdown=-15922.400090; p1=-400.662450; p99=123.837500. Tail survivability is not established because the frozen design has no capital/margin model.

### Per-year breakdown

| Year | N | Mean | t | Nominal p (Bonf. 0.00333) | Wilcoxon p |
|---:|---:|---:|---:|---:|---:|
| 2021 | 49 | -45.462347 | -3.8277844916290413 | 0.00037409253942745065 | 0.0003546445036981538 |
| 2022 | 52 | -56.366342 | -3.555511791562739 | 0.0008244140097253359 | 0.0010104639629207376 |
| 2023 | 52 | -30.066254 | -3.0646298393133242 | 0.0034787687440883367 | 0.009699434173374561 |
| 2024 | 52 | -74.824038 | -4.889163077975404 | 1.0499542347429598e-05 | 3.556660156153242e-05 |
| 2025 | 52 | -69.835577 | -4.408841108204828 | 5.372641350008755e-05 | 2.3829506886951224e-05 |
| 2026 | 19 | -83.876316 | -2.8087717191492647 | 0.011616233888888296 | 0.00823211669921875 |

Expiry/non-expiry controls:
```json
{
  "expiry": {
    "n": 276,
    "mean": -57.384420253623155,
    "sd": 103.18725169470828,
    "t": -9.238947385647064,
    "t_p": 7.030448951995185e-18,
    "wilcoxon_stat": 8039.5,
    "wilcoxon_p": 7.229595992975327e-17
  },
  "nonexpiry": {
    "n": 1041,
    "mean": -47.591269814601354,
    "sd": 104.60291184419869,
    "t": -14.679419551636943,
    "t_p": 1.7754332815636083e-44,
    "wilcoxon_stat": 137990.0,
    "wilcoxon_p": 6.99897202406478e-43
  },
  "expiry_pin_success_rate_pct": 30.07246376811594,
  "nonexpiry_pin_success_rate_pct": 31.21998078770413
}
```

Per-year expiry/control means:

| Year | Expiry | Non-expiry |
|---:|---:|---:|
| 2021 | -45.4623 | -42.2325 |
| 2022 | -56.3663 | -39.2088 |
| 2023 | -30.0663 | -39.7215 |
| 2024 | -74.8240 | -58.1203 |
| 2025 | -69.8356 | -52.4888 |
| 2026 | -83.8763 | -65.2828 |

## H15 — ROUND_NUMBER_PIN

N=276; mean=-0.866679 spot-point closeness surplus vs uniform; t=-0.959778164897786; nominal p=0.33801 (Bonferroni threshold 0.00333); Wilcoxon p=0.34264127719402515; lag-1 autocorrelation=0.05018443954677232. Registered primary: one-sample t=-0.959778164897786, p=0.33800995717235877.
Placebo: 2000 draws, seed 20260823, empirical p=0.40229885057471265.
Tail: worst five = 2024-10-17 -24.8000; 2026-03-02 -24.7500; 2022-01-27 -24.3008; 2023-08-10 -24.2000; 2025-01-16 -24.2000; max drawdown=-504.000000; p1=-24.225200; p99=24.800200. Tail survivability is not established because the frozen design has no capital/margin model.

### Per-year breakdown

| Year | N | Mean | t | Nominal p (Bonf. 0.00333) | Wilcoxon p |
|---:|---:|---:|---:|---:|---:|
| 2021 | 49 | 1.905139 | 0.9123989747461809 | 0.36611868360727273 | 0.3277633323525144 |
| 2022 | 52 | -0.447192 | -0.21735736154544416 | 0.8287971091297367 | 0.8340890253600262 |
| 2023 | 52 | 3.167284 | 1.5055046671927241 | 0.13836323229578446 | 0.14012639559297696 |
| 2024 | 52 | -4.683654 | -2.1701912635639076 | 0.03467379093391904 | 0.035401012762322076 |
| 2025 | 52 | -3.866346 | -1.9119615347651995 | 0.06150671509430788 | 0.06255037428351914 |
| 2026 | 19 | -1.547368 | -0.5217289754235402 | 0.6082198434387339 | 0.7171903998703537 |

Expiry/non-expiry controls:
```json
{
  "expiry": {
    "n": 276,
    "mean": -0.8666790181159278,
    "sd": 15.001751189325851,
    "t": -0.959778164897786,
    "t_p": 0.33800995717235877,
    "wilcoxon_stat": 17853.5,
    "wilcoxon_p": 0.34264127719402515
  },
  "nonexpiry": {
    "n": 1041,
    "mean": -0.46234426609032314,
    "sd": 14.422502797155236,
    "t": -1.0343087741210166,
    "t_p": 0.30123228065438024,
    "wilcoxon_stat": 260090.5,
    "wilcoxon_p": 0.2989347520428379
  }
}
```

Per-year expiry/control means:

| Year | Expiry | Non-expiry |
|---:|---:|---:|
| 2021 | 1.9051 | -0.4590 |
| 2022 | -0.4472 | 1.6679 |
| 2023 | 3.1673 | -0.2847 |
| 2024 | -4.6837 | -2.4426 |
| 2025 | -3.8663 | -0.5298 |
| 2026 | -1.5474 | -1.2231 |

## Limitations

- **Truncated chain:** the archive contains only ATM−10 through ATM+10. H11 PCR and H14 max pain are proxies, not the real full-chain quantities; neither may be read as a test of true PCR or true max pain.
- **No bid–ask:** all option legs use traded close to traded close. This flatters buyers and sellers alike; the breakeven-cost column is the relevant room.
- **WEEK1 only:** no WEEK2/WEEK3, monthly options, or futures tape.
- **No margin model:** short-option results are gross of SPAN and intraday margin calls, so tail survivability cannot be certified.
- **No stops or targets:** the registered rules fully realise every tail.
- **Expiry metadata:** expiry sessions are selected only by `is_expiry_day`; no weekday is hardcoded, preserving the 2025 Thursday-to-Tuesday change.
- **Multiplicity and scope:** this is descriptive exploratory screening. A positive mean with an exposed catastrophic tail is not a strategy, and no result authorises live trading or arms any gate.
