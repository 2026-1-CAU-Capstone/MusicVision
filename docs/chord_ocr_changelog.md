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

1. preserve accepted and rejected OCR hits for debugging
2. suppress rehearsal marks such as circled `A` / `B`
3. improve recall for missed chord symbols
4. later, tune cases where OCR drops a `7`
