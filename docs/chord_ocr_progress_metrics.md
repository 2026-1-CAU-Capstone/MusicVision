# Printed Chord OCR Progress Metrics

This document records the measurable progress made on the Airegin reference
image during the first MusicVision printed-chord OCR implementation.

It is intentionally narrow:

- one reference score: `resources/airegin-miles_davis.png`
- one manually reviewed printed-chord total supplied during review: `43`
- saved pipeline runs under `storage/jobs/`

The goal is to preserve a numerical baseline for this branch, not to claim a
general benchmark across many scores.

## Executive summary

| Metric | Initial integrated run | Current run | Change |
| --- | ---: | ---: | ---: |
| detected systems | `8` | `8` | unchanged |
| detected measures | `36` | `45` | `+9` measures |
| assigned OCR tokens | `37` | `39` | `+2` net tokens |
| manually confirmed real chord detections | `35 / 43` | `39 / 43` | `+4` chords |
| known false positives retained | `2` | `0` | `-2` |
| chord recall on this reviewed sample | `81.4%` | `90.7%` | `+9.3 pp` |
| precision against the reviewed labels | `94.6%` | `100.0%` | `+5.4 pp` |
| reviewed-sample F1 | `87.5%` | `95.1%` | `+7.6 pp` |

The largest structural improvement was measure geometry:

- from `36` detected measures initially
- to `45` after repairing the missing first measure of each system and one missed
  interior separator

The largest OCR improvement was quality rather than volume:

- four more real printed chords were recovered
- the two confirmed false positives were removed
- the system now records accepted, rejected, and filtered OCR decisions instead
  of discarding that evidence

## Milestone timeline

| Saved run | Main change represented | Systems | Measures | Assigned OCR tokens |
| --- | --- | ---: | ---: | ---: |
| `manual-e2e-airegin` | first real integrated HOMR + EasyOCR pass | `8` | `36` | `37` |
| `manual-e2e-airegin-leading-fix` | preserve leading first measure of each system | `8` | `44` | `37` |
| `manual-e2e-airegin-barline-fix` | recover missed interior barline in first system | `8` | `45` | `37` |
| `manual-e2e-airegin-ocr-pass` | OCR cleanup, filtering, diagnostics | `8` | `45` | `39` |

## Geometry progress

### Starting point

The first real integrated run detected:

```text
36 measures
```

Two geometry failures were visible:

1. the first visual measure of every system was omitted
2. one interior separator in the first system was missed, causing an over-wide
   interval after the opening double barline

### After preserving leading measures

Adding the leading-boundary repair changed:

```text
36 -> 44 measures
```

That is exactly `+8` measures, matching the `8` systems on the page.

### After recovering the missed interior separator

Adding the conservative over-wide-interval repair changed:

```text
44 -> 45 measures
```

That recovered the one missed interior separator in the first system.

Overall geometry gain:

```text
36 -> 45 measures
+9 measures
+25.0% relative increase in detected visual measures
```

### Assignment correction visible in the first system

Before the interior-barline repair:

```text
C7 -> beat 3 of the over-wide measure
```

After the repair:

```text
C7 -> beat 1 of the next measure
```

This is an important improvement because it shows that the geometry work did not
just increase a count; it corrected the musical placement of a chord.

## OCR progress

The manually reviewed Airegin score contains:

```text
43 printed chord symbols
```

### Initial OCR state

In the first integrated run:

```text
37 assigned OCR tokens
35 manually confirmed real chords
2 known false positives
8 missed real chords
```

The two known false positives were:

1. a notation-like glyph read as lowercase `e`, normalized to chord `E`
2. the circled rehearsal mark `B`, read as raw OCR text `8` and normalized to
   chord `B`

Derived reviewed-sample metrics:

```text
precision = 35 / 37 = 94.6%
recall    = 35 / 43 = 81.4%
F1        = 87.5%
```

### Current OCR state

After adding persisted diagnostics, contextual filtering, and narrow
normalization repairs:

```text
39 assigned OCR tokens
39 manually confirmed real chords
0 known false positives retained
4 missed real chords
```

The new run also records the full OCR decision trail:

```text
39 accepted tokens
2 filtered hits
29 rejected hits
```

The filtered hits were the two known false positives:

```text
e -> E    single_letter_touches_staff
8 -> B    circled_rehearsal_mark
```

Derived reviewed-sample metrics:

```text
precision = 39 / 39 = 100.0%
recall    = 39 / 43 = 90.7%
F1        = 95.1%
```

### OCR improvement summary

```text
real chord detections: 35 -> 39
missed chords:          8 -> 4
known false positives:  2 -> 0
recall:               81.4% -> 90.7%
```

Newly recovered or corrected examples in the current run include:

```text
Cbmaj7
Bbmaj7
Bbm7
Gm7b5
```

## Artifact and observability progress

The branch also improved what can be measured after a run.

| Capability | Initial run | Current run |
| --- | --- | --- |
| `geometry.json` | present | present |
| `homr_processed.png` | present | present |
| structured OCR diagnostics in `result.json` | absent | present |
| `chord_assignment_overlay.png` | manual only | generated automatically |
| accepted / rejected / filtered OCR counts | not persisted | persisted |

The current real sample overlay reports:

```text
45 measures
39 assigned chords
2 filtered hits
29 OCR rejects
```

This matters because future OCR work no longer has to be judged from visual
inspection alone; there is now a saved trail for what the OCR saw, what the
grammar rejected, what the filters removed, and what was finally assigned.

## What has not yet improved enough

The remaining gap on the reviewed Airegin sample is:

```text
4 printed chords still not assigned
```

The largest unresolved class is no longer measure geometry. It is OCR recall,
especially cases where EasyOCR drops a character entirely, such as a trailing
`7`. The current branch intentionally avoids inventing those characters because
that would move from OCR cleanup toward chord inference.

## Source runs used

All milestone numbers above were read from saved local outputs:

```text
storage/jobs/manual-e2e-airegin/output/result.json
storage/jobs/manual-e2e-airegin-leading-fix/output/result.json
storage/jobs/manual-e2e-airegin-barline-fix/output/result.json
storage/jobs/manual-e2e-airegin-ocr-pass/output/result.json
```

