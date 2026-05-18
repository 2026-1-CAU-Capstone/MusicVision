# Printed Chord OCR Changelog

This file records the implementation changes made for the printed chord OCR
branch in more detail than the architectural summary in `docs/chord_ocr.md`.

## 2026-05-18 - Initial image-based integration

### Added HOMR sidecar artifact export

Changed vendored HOMR so one CLI run can emit:

- `score.musicxml`
- `geometry.json`
- `homr_processed.png`

`geometry.json` now exports:

- `coordinate_space: "homr_processed_image"`
- processed image width and height
- system envelopes derived from HOMR `MultiStaff` groupings
- per-staff envelopes
- detected barline boxes

The normal HOMR MusicXML generation flow remains intact; MusicVision still runs
HOMR as a subprocess.

### Added the MusicVision chord OCR pipeline

Added the image-only first pass under `pipeline/chords/`:

- grammar and normalization helpers
- EasyOCR backend
- OCR preprocessing helpers
- legacy CV barline fallback
- geometry-first measure assignment

The assignment flow is:

1. OCR printed chord symbols on `homr_processed.png`
2. assign each token to the nearest HOMR system by y-position
3. build measure intervals from that system's barlines
4. assign the token by x-position and estimate beat position
5. use CV fallback only when HOMR geometry is absent or unusable

### Extended service/API output

Added:

- enriched `result.json`
- `GET /omr/jobs/{job_id}/result`

Kept:

- existing MusicXML endpoint behavior
- default unit-test suite free of real HOMR/EasyOCR execution

### Real integration smoke test

Ran a real local end-to-end pass on:

```text
resources/airegin-miles_davis.png
```

Initial observed output:

| Metric | Value |
| --- | --- |
| assignment source | `homr_geometry` |
| systems | `8` |
| measures | `36` |
| assigned OCR tokens | `37` |

The run proved the integrated artifact flow worked, but exposed two geometry
defects:

1. the first visual measure of each system was missing
2. the first system missed one interior barline after the opening double barline

It also exposed OCR-quality issues that remain for a later pass:

- not all printed chords are detected
- a rehearsal mark can be misclassified as a chord
- some `7`s are dropped by OCR

## 2026-05-18 - Geometry repair: preserve leading first measures

### Problem

The first detected HOMR barline in each system was treated as the first measure
boundary. On Airegin, that dropped the interval from the system's left edge to
the first barline, so the first visual measure of each system disappeared.

### Fix

Added a leading-boundary heuristic in `measure_assignment.py`:

- `MIN_MEASURE_WIDTH = 12 px`
- merge duplicate/near-duplicate barline positions within `1 px`
- compute `typical_measure_width` as the median of gaps `>= 12 px`
- add the system-left edge when:

```text
leading_gap >= max(24 px, 0.25 * typical_measure_width)
```

### Verification

Added regression coverage for a synthetic HOMR-like system whose first measure
starts at the system envelope rather than at an explicit left barline.

Re-ran Airegin:

| Metric | Before | After |
| --- | ---: | ---: |
| measures | `36` | `44` |

The extra `8` measures correspond to one restored leading measure in each of the
8 systems.

## 2026-05-18 - Geometry repair: recover one missed interior barline

### Problem

In Airegin's first system:

- HOMR exported the opening double barline around `x = 604.5` and `x = 612.5`
- HOMR missed the interior separator around `x ~= 958.5`
- the next interval became one over-wide span from `612.5` to `1227.5`
- `C7` was assigned to beat 3 of that span instead of beat 1 of the next measure

### Fix

Added a conservative recovery pass that inspects `homr_processed.png` only when
an existing HOMR interval is clearly too wide.

#### Over-wide interval rule

Let `typical_measure_width` be the median substantial HOMR gap for the system.
Only inspect an interval when:

```text
1.6 * typical_measure_width <= gap <= 2.5 * typical_measure_width
```

This intentionally targets "probably one missing separator" intervals rather
than arbitrary wide spans.

#### Vertical separator candidate rule

Inside the over-wide interval:

1. crop the exact system-height ROI
2. apply Otsu inverse thresholding
3. run a vertical morphological opening with kernel height:

```text
max(3 px, round(0.75 * ROI_height))
```

4. keep connected components only when:

```text
height >= 75% of ROI height
width  <= 12 px
distance from either interval edge >= 24 px
```

If multiple candidates remain, choose the candidate that best splits the
interval into two ordinary-looking measures by minimizing:

```text
abs((candidate_x - left_x)  - typical_measure_width)
+ abs((right_x - candidate_x) - typical_measure_width)
```

with distance to the interval midpoint as the tiebreaker.

#### Why this is not a generic note-stem classifier

The implementation does **not** prove that a candidate is a barline from shape
alone. Note stems can also be narrow and tall.

The repair is conservative because it requires all of the following context:

- a pre-existing HOMR interval that is a measure-width outlier
- a near-full-height vertical component inside the full system ROI
- a split point that restores ordinary-looking neighboring widths

That combination is what made the missing `x ~= 958.5` separator in Airegin the
best candidate, rather than one of the other note stems inside the same span.

### Verification

Added a synthetic regression test where one HOMR barline is omitted from an
otherwise regular system.

Re-ran Airegin:

| Metric | Before | After |
| --- | ---: | ---: |
| measures | `44` | `45` |
| `C7` location | beat 3 of the over-wide measure | beat 1 of the next measure |

Observed first-system boundaries after recovery:

```text
[110.0, 604.5]
[612.5, 958.5]
[958.5, 1227.5]
[1227.5, 1421.5]
[1421.5, 1740.0]
```

The new `958.5` boundary is the recovered visual separator.

## Current follow-up queue

The remaining work is OCR-quality work rather than geometry work:

1. improve cases where EasyOCR drops a character entirely, especially a trailing `7`
2. continue evaluating the heuristics on more scores before widening them

## 2026-05-18 - OCR diagnostics and conservative cleanup

### Problem

The real Airegin integration run made two things hard to reason about:

1. the service discarded EasyOCR rejects after extraction, so it was difficult to
   distinguish "not read" from "read but rejected"
2. two observed false positives survived the chord grammar:
   - lowercase `e` from notation near the staff
   - circled rehearsal `B`, read by EasyOCR as raw text `8`

The same run also exposed several high-confidence OCR reads that were very close
to valid chord labels but failed normalization:

- `cbmajz`
- `Bbinajz`
- `Bom?`
- `Fmn?`
- `Gmzbs`

### Fix

#### Persist the OCR decision trail

Extended `result.json` with:

```json
"chord_ocr": {
  "backend": "easyocr",
  "accepted_tokens": [],
  "rejected_hits": [],
  "filtered_hits": []
}
```

`rejected_hits` now keep JSON-safe confidence values and bounding boxes. Tokens
retain their EasyOCR confidence so accepted and filtered tokens can be audited
after the run.

#### Suppress circled rehearsal marks without banning real single-letter chords

Added `pipeline/chords/token_filters.py`.

For normalized single-letter roots `A` through `G`, a token is filtered as
`circled_rehearsal_mark` only when a surrounding contour:

```text
contains the token center
1.15 <= contour_width  / token_width  <= 3.0
1.15 <= contour_height / token_height <= 3.0
0.75 <= contour_aspect_ratio <= 1.35
```

Observed Airegin example:

```text
raw token:            8
normalized token:     B
contour bbox:         [1045.0, 911.0, 1092.0, 957.0]
width ratio:          1.567
height ratio:         1.438
aspect ratio:         1.022
```

The key design choice is that a plain `F` remains legal. The filter requires
visual evidence of the enclosing ring before removing a single-letter token.

#### Suppress one-letter notation that touches the staff envelope

For normalized single-letter roots `A` through `G`, a token is filtered as
`single_letter_touches_staff` when:

```text
nearest_system_top_y - token_bottom_y <= 6 px
```

Observed Airegin example:

```text
raw token:                         e
normalized token:                  E
nearest system index:              2
token_bottom_to_staff_top_px:     -0.321
threshold_px:                      6.0
```

This removed the notation false positive while leaving the actual printed
single-letter `F` chord labels intact because they remained visibly above the
staff envelope.

#### Add narrow, sample-backed OCR text repairs

Extended grammar normalization to cover:

| Raw OCR | Corrected |
| --- | --- |
| `z` in chord body | `7` |
| `inaj` | `maj` |
| root-position `o` | `b` |
| trailing `mn7` | `m7` |
| `bs` after a chord body | `b5` |

Observed corrections:

| Raw OCR | Before | After |
| --- | --- | --- |
| `cbmajz` | rejected | `Cbmaj7` |
| `Bbinajz` | rejected | `Bbmaj7` |
| `Bom?` | rejected | `Bbm7` |
| `Fmn?` | `Fmb7` | `Fm7` |
| `Gmzbs` | rejected | `Gm7b5` |

These are OCR spelling repairs only; they still do not infer chords from notes
or hallucinate a suffix that OCR omitted entirely.

#### Declare direct runtime dependencies

Added direct root requirements for:

- `numpy>=2.4.2,<3.0`
- `opencv-python-headless>=4.13.0.92,<5.0`

MusicVision imports both directly under `pipeline/chords/`, so relying on HOMR
or EasyOCR to bring them in transitively made local environments too fragile.

### Verification

Added deterministic tests for:

- the new OCR normalization cases
- circled rehearsal-mark filtering
- staff-touch filtering
- serialized OCR diagnostics in API output

Ran a fresh real HOMR + EasyOCR job on:

```text
resources/airegin-miles_davis.png
```

New output job:

```text
storage/jobs/manual-e2e-airegin-ocr-pass/output/result.json
```

Observed result:

| Metric | Before OCR cleanup | After OCR cleanup |
| --- | ---: | ---: |
| assigned OCR tokens | `37` | `39` |
| obvious false positives retained | `2` | `0` |
| filtered hits recorded | `0` | `2` |
| rejected hits recorded | discarded | `29` |

Filtered hits in the real run:

```text
e -> E    single_letter_touches_staff
8 -> B    circled_rehearsal_mark
```

Newly recovered or corrected labels in the real run included:

```text
Cbmaj7
Bbmaj7
Bbm7
Gm7b5
```

Against the manually observed `43` printed chords in the Airegin example, this
brings the current image-based first pass to `39 / 43` assigned chord tokens,
with the known rehearsal-mark false positive removed.

## 2026-05-18 - First-class assignment overlay artifact

### Problem

The geometry investigation had already used manually generated
`chord_assignment_overlay.png` files, but the production pipeline did not create
one. That meant the most useful debugging view disappeared on fresh OCR runs even
though the structured data needed to render it was already available.

### Fix

Added `pipeline/chords/overlay.py` and made every normal pipeline run write:

```text
chord_assignment_overlay.png
```

The overlay is rendered from:

- `homr_processed.png`
- structured measure assignment output
- persisted OCR diagnostics

It therefore stays in the same `homr_processed_image` coordinate space as the
rest of the feature branch.

### Overlay legend

| Colour | Meaning |
| --- | --- |
| blue | measure boxes and measure labels |
| green | assigned chord tokens, labelled as `m{measure} b{beat}` |
| orange | filtered grammar-valid hits such as rehearsal marks |
| red | OCR rejects that never reached assignment |

The legend also reports:

- measure count
- assigned-chord count
- filtered-hit count
- rejected-hit count
- assignment source

### Result schema change

`result.json` now records:

```json
"overlay_file": "chord_assignment_overlay.png"
```

so downstream code can discover the artifact without hard-coding its filename.

### Verification

Added deterministic tests for:

- overlay colour rendering on synthetic geometry/OCR data
- writing the PNG artifact
- production pipeline creation of the overlay during API processing

Generated the overlay retroactively for the existing real OCR sample run:

```text
storage/jobs/manual-e2e-airegin-ocr-pass/output/chord_assignment_overlay.png
```

The resulting image shows:

- `45` measures
- `39` assigned chords
- `2` filtered hits
- `29` OCR rejects

## Progress-by-the-numbers reference

For the consolidated metric history of the Airegin reference score, including
the initial `36`-measure / `35-of-43` chord baseline and the current
`45`-measure / `39-of-43` state, see:

```text
docs/chord_ocr_progress_metrics.md
```
