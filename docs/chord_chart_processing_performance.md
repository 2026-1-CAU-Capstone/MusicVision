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
