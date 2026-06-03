# Sheet Music Chord Processing Performance Notes

This document tracks runtime observations and optimization targets for printed
chord-symbol OCR. It is intentionally separate from
`docs/sheet_music_chord_processing_changelog.md`, which should remain focused on
implementation history.

## 2026-06-01 baseline

Input:

```text
resources/autumn_leaves_HQ.png
```

Environment:

- local Windows development machine
- project virtualenv
- CPU execution
- no GPU accelerator detected
- single-page raster input

These timings are local measurements, not a general production benchmark.

## 2026-06-03 Take The A Train OMR structure postprocess

Input:

```text
resources/Take_The_A_Train.png
```

Environment:

- local Windows development machine
- project virtualenv
- CPU execution
- no GPU accelerator detected
- single-page raster input
- benchmark runs used temporary directories and deleted results afterward

| Pipeline state | Time | Clefs in MusicXML | MusicXML endings |
| --- | ---: | ---: | ---: |
| Before clef/ending postprocess | `47.036s` | `7` | `0` |
| After clef/ending postprocess | `44.500s` | `1` | `4` |

The after run detected two visual ending markers and wrote start/stop MusicXML
endings for numbers `1` and `2`. The runtime difference should be treated as
normal local run-to-run variance; the added postprocess is small compared with
HOMR and EasyOCR.

## 2026-06-03 targeted chord-band OCR benchmark

Inputs:

```text
storage/jobs/take_the_a_train-clef_endings-20260603/output
storage/jobs/bench-chord-only-autumn-leaves-warm/output
```

Environment:

- local Windows development machine
- project virtualenv
- CPU execution
- no GPU accelerator detected
- EasyOCR reader warmed before the timed OCR comparisons
- benchmark reused saved `homr_processed.png` and `geometry.json`

This comparison isolates the OCR extraction and visual filtering stage. It does
not rerun HOMR.

Saved benchmark jobs:

```text
storage/jobs/bench-targeted-ocr-take-the-a-train-20260603
storage/jobs/bench-targeted-ocr-autumn-leaves-20260603
```

Each saved job includes a fresh `chord_assignments.json`,
`chord_assignment_overlay.png`, `job_status.json`, and
`output/benchmark_metadata.json` generated from the current targeted OCR path.

### Take The A Train

| OCR mode | Strategy | OCR+filter time | Accepted before filters | Kept after filters | Rejected hits |
| --- | --- | ---: | ---: | ---: | ---: |
| Full-page legacy | `full_page` | `25.801s` | `22` | `21` | `45` |
| Targeted policy | `targeted_only` | `14.705s` | `21` | `21` | `14` |

### Autumn Leaves

| OCR mode | Strategy | OCR+filter time | Accepted before filters | Kept after filters | Rejected hits |
| --- | --- | ---: | ---: | ---: | ---: |
| Full-page legacy | `full_page` | `24.747s` | `34` | `30` | `90` |
| Targeted policy | `targeted_only` | `13.599s` | `31` | `29` | `12` |

The targeted pass roughly halved warm OCR time on these two saved artifacts and
substantially reduced rejected OCR noise. The Autumn Leaves run also exposed a
recall tradeoff: targeted OCR produced one fewer kept token than full-page OCR,
while removing obvious non-chord noise such as the full-page `B4` false positive.

### Crop-padding experiment

After the first targeted benchmark, a wider global vertical crop context was
tested to see whether it would recover a locally missed Autumn Leaves token. It
helped on one isolated crop, but worsened full-sample behavior:

| Padding | Sample | OCR+filter time | Kept after filters | Rejected hits |
| ---: | --- | ---: | ---: | ---: |
| `20 px` | Autumn Leaves | `16.359s` | `28` | `12` |
| `40 px` | Autumn Leaves | `20.665s` | `28` | `49` |

The padding change was reverted. The tighter chord-band crop kept the better
runtime/noise balance, and the full-page fallback remains the safer recall path
when targeted OCR is globally sparse.

## Timing results

Cold-ish runs used separate Python processes, so each run included its own model
and OCR startup costs.

| Pipeline | Time |
| --- | ---: |
| Chord-only sheet music | `51.947s` |
| Full OMR plus chords | `57.289s` |

Warm runs preloaded the EasyOCR reader in one Python process before timing the
two pipelines.

| Pipeline | Time |
| --- | ---: |
| EasyOCR reader warmup | `6.428s` |
| Chord-only sheet music | `40.111s` |
| Full OMR plus chords | `48.161s` |

HOMR-only measurements on the same input:

| Pipeline | HOMR time | Total including preprocess |
| --- | ---: | ---: |
| HOMR geometry-only | `6.930s` | `6.934s` |
| Full HOMR only | `14.194s` | `14.198s` |

Generated benchmark artifacts:

```text
storage/jobs/bench-targeted-ocr-*
storage/jobs/bench-chord-only-autumn-leaves*
storage/jobs/bench-full-omr-autumn-leaves*
storage/jobs/bench-homr-geometry-only-autumn-leaves
storage/jobs/bench-homr-full-only-autumn-leaves
```

## Interpretation

The HOMR geometry-only optimization is working: skipping TrOMR/MusicXML saves
roughly 7 to 8 seconds on this input. The chord-only endpoint also avoids
producing `score.musicxml` and reports `measure_alignment.status` as
`visual_only`.

The larger remaining cost is EasyOCR. On the warmed comparison, HOMR
geometry-only takes about 7 seconds, while the full chord-only pipeline takes
about 40 seconds. That leaves most of the runtime in printed chord OCR and its
image preprocessing, not in HOMR visual measure extraction.

Both the chord-only and full OMR-plus-chords runs assigned:

- `34` visual measures
- `30` chord tokens

## Current bottleneck

The main optimization target is still the EasyOCR stage:

- EasyOCR reader startup costs several seconds in a cold process.
- The targeted chord-band pass reduces notation/header noise, but EasyOCR still
  dominates the warm pipeline on CPU.
- Unusual chord placement can still require the full-page fallback.
- OCR scale and preprocessing settings may still be more expensive than
  necessary for some inputs.

## Future optimization ideas

- Reuse the EasyOCR reader in the long-running API process.
- Refine the targeted/full-page fallback thresholds with more reviewed samples.
- Benchmark PaddleOCR recognition-only on the same targeted chord crops if a
  future dependency spike is approved.
- Evaluate JAZZMUS after the final MusicVision benchmark as an external
  handwritten jazz lead-sheet reference.
- Keep synthetic jazz-font fine-tuning as future research; it is likely useful
  for semi-handwritten Real Book-style symbols, but was out of scope for this
  pass.
- Tune OCR scale adaptively based on staff size or image resolution.
- Cache `homr_processed.png` and `geometry.json` during local benchmark work.

## Measurement caution

These numbers came from one image and one local CPU environment. Re-run the same
benchmark on representative uploads before using the timings to make product or
infrastructure decisions.
