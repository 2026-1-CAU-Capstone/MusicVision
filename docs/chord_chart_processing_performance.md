# Chord Chart Processing Performance Notes

This document tracks runtime observations and optimization targets for the
chord-chart processing pipeline. It is intentionally separate from the
sheet-music chord processing performance notes because this branch skips HOMR
and spends most of its time in chart-grid OCR.

These timings are local measurements, not production benchmarks.

## 2026-06-03 Cherokee baseline

Input:

```text
resources/chord_charts/cherokee_chord_chart.jpg
```

Environment:

- local Windows development machine
- project virtualenv
- CPU execution
- no GPU accelerator detected
- single-page raster input
- measured through `run_chord_chart_pipeline`
- output, intermediate, and log directories were temporary and deleted after the
  run

Result:

| Metric | Value |
| --- | ---: |
| elapsed time | `286.389s` |
| elapsed minutes | `4.77` |
| detected systems | `9` |
| detected measures | `36` |

The run printed EasyOCR's CPU warning:

```text
Using CPU. Note: This module is much faster with a GPU.
```

## 2026-06-05 Cherokee OCR-region benchmark

Input:

```text
resources/chord_charts/cherokee_chord_chart.jpg
```

Environment:

- local Windows development machine
- project virtualenv
- CPU execution
- no GPU accelerator detected
- single-page raster input
- benchmark variants reused the existing chart grid parser and EasyOCR settings

Saved benchmark jobs:

```text
storage/jobs/chart-debug-cherokee-20260605-141920
storage/jobs/chart-debug-cherokee-page-only-20260605
storage/jobs/chart-debug-cherokee-full-cell-only-20260605-150749
storage/jobs/chart-debug-cherokee-row-system-20260605-151641
storage/jobs/chart-debug-cherokee-selective-20260605-163035
storage/jobs/chart-debug-cherokee-selective-crops-20260605-183210
```

| Variant | OCR calls after grid detection | Elapsed time | Detected measures | Chords | Non-empty chord matches vs full baseline |
| --- | ---: | ---: | ---: | ---: | ---: |
| Current full chart pipeline | `1 page + 216 cell` | `405.47s` | `36` | `26` | baseline |
| Page OCR only | `1 page` | `39.85s` | `36` | `26` | `15/26` |
| Page OCR + full-cell only | `1 page + 36 cell` | `108.67s` | `36` | `26` | `17/26` |
| Page OCR + row/system OCR | `1 page + 9 row` | `77.85s` | `36` | `27` | `18/26` |
| Page + row/system + generic selective cell fallback | `1 page + 9 row + 45 targeted cell` | `152.07s` | `36` | `27` | `23/26` |
| Page + row/system + chord-aware selective cell fallback | `1 page + 9 row + 45 targeted cell` | `129.15s` | `36` | `27` | `24/26` |

The row/system OCR variant scans one crop per detected chart row instead of one
or more crops per measure. On Cherokee it was about `5.2x` faster than the
current six-region cell OCR pipeline and slightly outperformed full-cell-only
for chord matches, but it still missed or simplified some suffixes and
accidentals. Examples included `Bb6 -> Bb`, `G7b9 -> G7`, and `C#m7 -> C7`.
It also introduced one extra chord assignment in measure 22.

This suggests row/system OCR is a useful optimization direction, but it should
probably be paired with selective targeted fallback for uncertain or low-detail
measures rather than replacing cell OCR outright.

The first selective fallback implementation does that pairing. It runs page OCR,
row/system OCR, marks suspicious measures with explainable rules, then runs only
targeted cell crops for those measures. The initial generic fallback used
`full`, `right`, and `low` crops. A follow-up chord-aware fallback used
`root`, `root_accidental`, and `suffix_lower_right` crops instead. On Cherokee,
the chord-aware fallback selected 15 of 36 measures and reduced the current
pipeline's 216 cell/subcell calls to 45 targeted cell calls. It recovered several
details that page/row OCR missed, including `Bb6`, `Fm7`, `G7b9`, `F7#5`, and
`Amaj7`, while keeping runtime around `3.1x` faster than the current full
six-region run.

The old full six-region output should not be treated as perfect ground truth.
For example, the selective run emits `Bb6` in measure 19 and `F7` in measure 22,
which appear visually plausible even though they differ from the saved full-pass
baseline. Known remaining Cherokee issues include measure 21 `C7` instead of
`C#m7`, and duplicate navigation tokens near the final `D.C. al 2nd ending`.
The `slash_bass_below_root` crop was tested separately, but it picked up
navigation text in later measures, so slash-bass fallback should be conditional
rather than part of the default suspicious-measure crop set.

## 2026-06-07 Root-anchor multi-chord and upscaling checks

### Autumn Leaves root-anchor run

Input:

```text
resources/chord_charts/autumn_leaves_chord_chart.jpg
```

Saved job:

```text
storage/jobs/chart-debug-autumn-leaves-root-anchor-suffix-20260607
```

| Metric | Value |
| --- | ---: |
| elapsed time | `92.90s` |
| page OCR | `31.72s` |
| semantic/root-anchor OCR | `60.95s` |
| detected measures | `24` |
| public chord events | `26` |
| core semantic OCR calls | `72` |
| root-anchor probe OCR calls | `2` |
| root-anchor local OCR calls | `12` |
| root anchors | `4` |

The target multi-chord measures were recovered as:

```text
measure 19: Gm7, Gb7
measure 20: Fm7, E7
```

### Body and Soul upscaled root-anchor run

Input:

```text
resources/chord_charts/body_and_soul-johnny_green-chord_chart.png
```

Saved job:

```text
storage/jobs/chart-debug-body-and-soul-root-anchor-20260607
```

| Metric | Value |
| --- | ---: |
| input size | `599x720` |
| processing size | `1198x1440` |
| elapsed time | `117.58s` |
| page OCR | `26.09s` |
| semantic/root-anchor OCR | `91.18s` |
| detected measures | `25` |
| public chord events | `34` |
| core semantic OCR calls | `75` |
| root-anchor probe OCR calls | `15` |
| root-anchor local OCR calls | `100` |
| root anchors | `37` |

Upscaling fixed the earlier grid-detection failure where only one measure cell
was detected. The remaining cost and accuracy issue is root-anchor
over-selection on dense/noisy measures. This run should be used as a diagnostic
baseline for anchor pruning, not as evidence that dense-chart multi-chord
selection is finished.

## Notes

The current chart parser runs EasyOCR over the full page and over multiple
regions per detected measure cell. That improves recall for fragmented jazz
symbols and stacked slash chords, but it also makes OCR the dominant runtime
cost.

Future optimization work should record before/after measurements here. Useful
candidate areas:

- reduce duplicate cell-region OCR passes where full-cell OCR is already
  confident
- cache OCR reader startup across batch runs or long-lived API workers
- use GPU-backed OCR when available
- benchmark whether targeted lower-region OCR is enough for stacked bass notes
  instead of running all crop variants for every cell
