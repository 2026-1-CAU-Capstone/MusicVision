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

The main optimization target is now the EasyOCR stage:

- EasyOCR reader startup costs several seconds in a cold process.
- OCR is currently run over the processed score image rather than restricted to
  chord-likely regions.
- Text detection/recognition spends time on notation and other non-chord areas.
- OCR scale and preprocessing settings may be more expensive than necessary for
  some inputs.

## Future optimization ideas

- Reuse the EasyOCR reader in the long-running API process.
- Crop OCR to regions above staff systems before recognition.
- Run OCR per system or per likely chord band rather than over the full page.
- Compare alternate OCR backends for short printed chord labels.
- Tune OCR scale adaptively based on staff size or image resolution.
- Cache `homr_processed.png` and `geometry.json` during local benchmark work.

## Measurement caution

These numbers came from one image and one local CPU environment. Re-run the same
benchmark on representative uploads before using the timings to make product or
infrastructure decisions.
