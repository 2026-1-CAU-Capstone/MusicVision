# Handwritten Chord Recognizer Bakeoff

This branch evaluates whether a handwriting-capable recognizer can improve the
current EasyOCR-based sheet-music chord pipeline.

## Scope

The first experiment tested PaddleOCR on the same HOMR chord-band crops used by
targeted EasyOCR. PaddleOCR was not wired into production endpoints. The raw
PaddleOCR text was passed through the existing MusicVision chord resolver so the
comparison stayed close to the current downstream behavior.

The bakeoff script is:

```text
scripts/paddleocr_chord_bakeoff.py
```

It writes JSON summaries and diagnostic overlays under a saved benchmark job.

## Environment notes

PaddleOCR was installed in an isolated temporary virtual environment instead of
the project `.venv`.

Reason: PaddleX/PaddleOCR currently requires `numpy < 2.4`, while the vendored
HOMR dependency requires `numpy >= 2.4.2`. Installing PaddleOCR directly into the
project venv downgrades NumPy and conflicts with HOMR.

The script redirects Paddle/PaddleX cache paths into temp directories because
the default Paddle cache locations are outside the workspace sandbox.

## Commands used

Default PaddleOCR detector settings:

```powershell
$venv = Join-Path $env:TEMP 'musicvision-paddleocr-venv'
& (Join-Path $venv 'Scripts\python.exe') scripts\paddleocr_chord_bakeoff.py `
  --output-dir storage\jobs\bench-paddleocr-chord-crops-20260604\output
```

Raised detector resolution:

```powershell
$venv = Join-Path $env:TEMP 'musicvision-paddleocr-venv'
& (Join-Path $venv 'Scripts\python.exe') scripts\paddleocr_chord_bakeoff.py `
  --output-dir storage\jobs\bench-paddleocr-chord-crops-det160-20260604\output `
  --text-det-limit-side-len 160 `
  --text-det-limit-type min
```

## Saved jobs

```text
storage/jobs/bench-paddleocr-chord-crops-20260604
storage/jobs/bench-paddleocr-chord-crops-det160-20260604
```

Each job includes `output/summary.json`, per-sample JSON files, diagnostic
overlays, and `job_status.json`.

## Results

Default PaddleOCR settings:

| Sample | Paddle time | Raw hits | Accepted | Rejected | Uncertain rejects |
| --- | ---: | ---: | ---: | ---: | ---: |
| Afternoon in Paris | `33.706s` | `38` | `32` | `6` | `3` |
| Airegin | `36.364s` | `34` | `26` | `8` | `2` |
| Agua de Beber | `29.919s` | `25` | `15` | `10` | `2` |

Detector minimum side raised to `160px`:

| Sample | Paddle time | Raw hits | Accepted | Rejected | Uncertain rejects |
| --- | ---: | ---: | ---: | ---: | ---: |
| Afternoon in Paris | `48.928s` | `38` | `33` | `5` | `3` |
| Airegin | `52.578s` | `35` | `24` | `11` | `3` |
| Agua de Beber | `44.723s` | `24` | `16` | `8` | `0` |

For comparison, the current EasyOCR path on these same samples was about
`14-17s` per page for OCR, filtering, and assignment.

## Observations

PaddleOCR does recover some handwritten chord shapes that EasyOCR struggles
with:

```text
Dbmaj7
G-7b5
C7b9
Abmaj7
F1#9 -> F7#9
Cmmj7 -> Cmaj7
```

However, it is not a drop-in robust fix:

- runtime is roughly two to three times slower than the current EasyOCR pass
- complex chord symbols are often split into root and suffix fragments
- suffix-only fragments such as `7#9` and `7#5` are rejected because they lack
  a root
- some wrong but grammar-valid symbols are still accepted, such as `Abmu7 ->
  Abm7`, `G7ba -> Gmaj7`, `G769`, `B761`, standalone `E`, and standalone `B`
- slash chords remain weak; Agua de Beber still has poor slash-chord recovery

The `160px` detector setting improves a few individual symbols, including
`G7b9`, `Abmaj7`, `C/G`, and `Cmaj7`, but the runtime increase is large and the
overall quality is mixed.

## Hybrid rescue experiment

The follow-up experiment kept EasyOCR as the baseline and ran PaddleOCR only on
EasyOCR rejected hits plus low-confidence/high-risk accepted boxes.

The hybrid rescue script is:

```text
scripts/paddleocr_hybrid_chord_rescue.py
```

Command:

```powershell
$venv = Join-Path $env:TEMP 'musicvision-paddleocr-venv'
& (Join-Path $venv 'Scripts\python.exe') scripts\paddleocr_hybrid_chord_rescue.py `
  --output-dir storage\jobs\bench-paddleocr-hybrid-rescue-20260604\output
```

Saved job:

```text
storage/jobs/bench-paddleocr-hybrid-rescue-20260604
```

Default settings:

- PaddleOCR detector defaults
- EasyOCR accepted-token rescue threshold: `0.50`
- rescue crop padding: `36px` horizontal, `28px` vertical
- replacements are reported as candidates only; they are not applied unless
  `--apply-replacements` is passed

| Sample | Baseline EasyOCR accepted | Rescue regions | Paddle time | Raw hits | Paddle accepted | Paddle rejects | Safe additions | Suppressed additions | Replacement candidates | Hybrid accepted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Afternoon in Paris | `32` | `21` | `15.765s` | `21` | `16` | `5` | `3` | `0` | `4` | `35` |
| Airegin | `29` | `15` | `10.506s` | `14` | `11` | `3` | `1` | `0` | `6` | `30` |
| Agua de Beber | `16` | `22` | `16.578s` | `26` | `20` | `6` | `5` | `4` | `6` | `21` |

Safe additions included:

```text
Cmmj7 -> Cmaj7
Cmuj7 -> Cmaj7
Abmai7 -> Abmaj7
C7b9
B7#9
Fmmj 7 -> Fmaj7
A-7
```

No root-plus-suffix Paddle fragment merges occurred in this saved run, although
the script now has a bounded merge helper for cases like `C` + `7#9` and `E` +
`7#5`.

The replacement candidates are useful diagnostics but too noisy to apply
automatically. Some look plausible, such as:

```text
Abm11 -> Abmaj7
C19 -> C7#9
F1 -> F7#9
B769 -> B7b9
```

Others are dangerous:

```text
C79 -> Gmaj7
C7b9 -> G7b
C-7 -> G-7b5
B+ -> E
```

Agua de Beber also produced Paddle-only additions that were accepted by the
broad chord grammar but suppressed by the hybrid script because they were
root-only or uncommon:

```text
E
E-765
C
```

## Candidate adjudication experiment

The next experiment grouped the saved EasyOCR baseline, Paddle additions, and
Paddle replacement candidates by physical chord location, then selected a
first-pass winner with explicit reasons.

The adjudication script is:

```text
scripts/chord_candidate_adjudication.py
```

Command:

```powershell
.\.venv\Scripts\python.exe scripts\chord_candidate_adjudication.py `
  --hybrid-output-dir storage\jobs\bench-paddleocr-hybrid-rescue-20260604\output `
  --output-dir storage\jobs\bench-chord-candidate-adjudication-20260604\output
```

Saved job:

```text
storage/jobs/bench-chord-candidate-adjudication-20260604
```

Each sample writes a `*_candidate_groups.json` file plus a review CSV. The
script does not rerun OCR.

Selection policy:

- Paddle additions without EasyOCR overlap are selected automatically.
- Replacement candidates are selected only when the EasyOCR baseline is
  suspicious and the Paddle candidate is a common same-root or same-letter
  accidental repair.
- Different-root conflicts and plausible-baseline conflicts remain review
  groups.
- Suppressed Paddle-only additions remain ignored.

| Sample | Candidate groups | Selected EasyOCR | Selected Paddle additions | Auto Paddle replacements | Review groups | Ignored groups |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Afternoon in Paris | `35` | `30` | `3` | `2` | `1` | `0` |
| Airegin | `30` | `25` | `1` | `4` | `2` | `0` |
| Agua de Beber | `25` | `12` | `5` | `4` | `1` | `4` |

Auto-selected Paddle replacements:

```text
Afternoon in Paris:
Abm11 -> Abmaj7
G9) -> G7

Airegin:
C19 -> C7#9
Bb5 -> Bb-7
F1 -> F7#9
F41 -> F#7

Agua de Beber:
A7 -> A-7
B761 -> B7b9
A567 -> Ab7
B769 -> B7b9
```

Review groups:

```text
Afternoon in Paris:
C79 vs Gmaj7

Airegin:
Cmaj7 vs Cm9
C-7 vs G-7b5

Agua de Beber:
E9 vs Esus4
```

The adjudicator is promising because it matches the observed pattern that the
right answer is often present in the candidate set. It is still not production
logic: the selected replacements need to be checked against reviewed ground
truth before wiring them into the API path.

## Production worker validation

The production integration keeps PaddleOCR in a separate Python process. The
main HOMR/EasyOCR virtualenv does not import PaddleOCR, which avoids the NumPy
version conflict.

Production worker:

```text
scripts/paddleocr_rescue_worker.py
pipeline/chords/paddleocr_rescue.py
```

Runtime opt-in:

```powershell
$env:MUSICVISION_PADDLEOCR_PYTHON = "$env:TEMP\musicvision-paddleocr-venv\Scripts\python.exe"
$env:MUSICVISION_PADDLEOCR_RESCUE_MODE = "adjudicated"
```

The worker was run against saved benchmark outputs without rerunning HOMR or
EasyOCR.

Saved validation job:

```text
storage/jobs/bench-production-paddleocr-rescue-20260604
```

Robust-case sanity check:

| Sample | Baseline | Final | Rescue regions | Paddle time | Additions | Auto replacements | Review groups |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Take The A Train | `30` | `32` | `19` | `11.721s` | `2` | `0` | `1` |
| Autumn Leaves | `32` | `33` | `5` | `3.540s` | `1` | `0` | `0` |

The robust cases are important because they check whether the rescue pass
damages already-good EasyOCR output. In this run it applied no replacements.
It added:

```text
Take The A Train: Bbmaj7, Cmaj7
Autumn Leaves: Am7b5
```

and left one cross-root `G7` vs `D7` conflict for review.

Hard handwritten-style cases:

| Sample | Baseline | Final | Rescue regions | Paddle time | Additions | Auto replacements | Review groups |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Afternoon in Paris | `32` | `35` | `21` | `15.706s` | `3` | `2` | `1` |
| Airegin | `29` | `30` | `15` | `10.854s` | `1` | `4` | `2` |
| Agua de Beber | `16` | `21` | `22` | `16.526s` | `5` | `4` | `1` |

This is promising enough to keep the opt-in production hook. The default remains
EasyOCR-only, and Paddle rescue should be enabled only in environments that
provide the isolated PaddleOCR Python executable.

## Recommendation

Do not replace EasyOCR with PaddleOCR as-is.

The useful signal is that PaddleOCR sometimes reads handwritten chord bodies
better, especially major-seventh and altered dominant shapes. The failure mode
is detection segmentation: it frequently separates roots from suffixes. The
hybrid rescue and adjudication experiments now point to this workflow:

1. keep EasyOCR as the primary fast path
2. run PaddleOCR only on EasyOCR red boxes or high-risk uncertain areas
3. add a bounded root-plus-suffix merge for Paddle fragments such as `C` +
   `7#9`, `E` + `7#5`, and `C/G` + `C7#9/G`
4. group EasyOCR/Paddle options by physical chord location
5. select safe Paddle additions and conservative same-location replacement
   repairs only after validating against reviewed ground truth

The hybrid rescue run did reduce some red/missing boxes, and the adjudicator
picked several plausible wrong-green-box repairs. The opt-in production hook is
now wired through an isolated PaddleOCR subprocess. The current next step is to
review production-worker outputs against ground truth before enabling
`adjudicated` mode broadly. More conservative deployments can start with
`additions` mode.

If reviewed hybrid results still cannot reduce wrong green boxes reliably, the
next recognizer to evaluate should be JAZZMUS or another
jazz-lead-sheet-specific model rather than another general OCR pass.
