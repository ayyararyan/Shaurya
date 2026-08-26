# ANL-05 — dashboard presentation redesign (2026-08-19, evening)

Presentation-only rework of `ANL-03`'s shell, plus two additions Aryan asked for after
seeing the first pass. Model meaning, thresholds and measured values are unchanged; the two
panels that were removed are recorded as an owner-approved specification change in
`TASKS.md` (ANL-05) and `docs/module-spec/ANL.md` (REQ-ANL-05).

## What changed

- Light/dark theme on CSS custom properties, header toggle, persisted to `localStorage`,
  defaulting to the OS `prefers-color-scheme`.
- Monospace type scale (`ui-monospace` → SF Mono / JetBrains Mono / IBM Plex Mono / Menlo /
  Consolas) with tabular numerals, so a live number does not jitter as digits change width.
- Hairline rules and a full-bleed status rail in place of rounded bordered cards.
- Aryan's muted palette throughout, including the Plotly scene: slate `#46586b`/`#8199b0`,
  brass `#b5851f`/`#d3a44a`, brick `#8f3327`/`#c05c46`, sage `#5b7a52`/`#8faa7c`, on ivory
  `#f4f2ec` / charcoal `#17191c`. Single-hue slate IV ramp, becoming copper/brick only when
  `SUR-05` fails.
- `SUR-05` violating points plotted at their own (k, T) as brick diamonds, not only listed.
- **Removed on Aryan's instruction:** the sustained-latency chart and the forward-source
  table. Both underlying objects are still computed and still served at `/api/state`.
- **ATM IV hero** — the fitted surface read at exactly k = 0, front expiry large, later
  expiries beside it, with the change since the previous fitted frame.
- **Free navigation** — rotate / pan / zoom drag modes, wheel zoom, and a reset, with the
  viewer's camera held across every live refresh.

## Verification

- 27 dashboard tests, 338 in the suite, all passing. `ruff` and `mypy` clean on the changed
  files.
- ATM parity: the hero number was checked against the k = 0 column of the grid the surface
  actually draws, on all three expiries of a real replay frame — agreement to 1e-12.

  | expiry | T (days) | ATM via `surface.evaluate` | grid at k = 0 |
  |---|---:|---:|---:|
  | 2026-08-25 | 6.137 | 0.0759452838 | 0.0759452838 |
  | 2026-09-01 | 13.132 | 0.0880596909 | 0.0880596909 |
  | 2026-09-29 | 41.113 | 0.0996292281 | 0.0996292281 |

- Camera persistence proven in a headless browser rather than asserted from source. Probe
  result: default eye `{1.16, 1.16, 0.88}` → viewer drags to `{3.10, 0.50, 0.10}` → a full
  re-render with a fresh payload → camera still `{3.10, 0.50, 0.10}`. `SURVIVED true`.
- Drag modes and reset likewise: `DRAGMODE pan/zoom | PAN_KEPT_CAMERA true | RESET_OK true`.
- Palette checked with the `dataviz` validator, not by eye. The slate → brass → brick
  escalation triad passes CVD separation and the normal-vision floor in both modes (light
  ΔE 11.0 CVD / 15.9 normal; dark 14.2 / 17.9). It fails the chroma floor and the dark
  lightness band by design: the palette is deliberately low-chroma and status must stay
  legible on charcoal. Status is additionally carried by a glyph and a word, never hue alone.

## Screenshots

Rendered from a 60,000-row slice of the `anl03-live` tape of 2026-08-19 (29 snapshots, 28
fits converged), in headless Chrome with software WebGL.

| File | State |
|---|---|
| `anl05-light.png` | healthy, light |
| `anl05-dark.png` | healthy, dark |
| `anl05-degraded-light.png` | forced DEAD feed + 3 `SUR-05` violations, light |
| `anl05-degraded-dark.png` | same, dark |

## Not verified

No live session has run against the redesigned shell, and these are headless renders, not
Aryan's own browser. `ANL-05` is Implemented and Tested, not Live verified.
