# NSGVC prospective shadow protocol

The NSGVC v1.0 rule was frozen on 2026-09-02 after the independent raw-data audit. Only observations dated 2026-09-03 or later are prospective. The user confirmed that the 2026-09-02 capture is invalid, so it is explicitly excluded.

At approximately 09:20 IST, calculate the same Black-76 ATM integrated implied variance and RR400 used by the audited package. Apply the frozen linear model and enter the first observation for each nearest-weekly expiry satisfying both `predicted integrated RV / implied integrated variance <= 0.70` and `RR400 <= 0.027081006247852195`.

The preferred structure is the 500-point iron fly, with 400 points allowed only when the preferred structure violates the frozen 20%-of-current-equity defined-loss cap and the fallback fits it. One lot maximum, all four legs in one basket, broker basket margin checked before entry, and no naked short exposure. Hold through expiry; reserve six option points for completed-structure costs in research accounting.

No result may cause a change to the model, gates, timing, exclusions, cost assumption, widths or exit rule during this evaluation. Any proposed revision is a new strategy version with a new future start date. Record no-trade days as well as trades. Do not combine prospective results with the development, validation or already-inspected 2026 histories when reporting the prospective score.

The currently available consolidated historical option archive ends on 2026-05-14, so the initial baseline correctly contains zero post-freeze observations and zero signals. Replace the panel input only after a complete, valid post-freeze session has been generated under the same feature definitions.
