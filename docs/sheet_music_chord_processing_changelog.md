# Sheet Music Chord Processing Changelog

This file records the implementation changes made for the sheet-music chord
processing branch in more detail than the architectural summary in
`docs/sheet_music_chord_processing.md`.

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

## 2026-05-18 - Canonical chord-assignment contract

### Problem

The generic `result.json` / `/result` naming no longer described the payload
well, and downstream use depends on the structured chord assignments lining up
with `score.musicxml` by measure.

### Fix

New jobs now write:

```text
chord_assignments.json
```

and expose the canonical endpoint:

```text
GET /omr/jobs/{job_id}/chord-assignments
```

The process response now returns:

```json
"chord_assignments_path": "jobs/{job_id}/output/chord_assignments.json"
```

For compatibility with earlier branch artifacts and callers:

- `GET /omr/jobs/{job_id}/result` remains as an alias
- retrieval can still read older saved `result.json` files when a canonical file
  does not yet exist

### Measure-alignment metadata

Added an explicit alignment check against `score.musicxml`.

When the MusicXML and visual sequences have the same measure count, the payload
contains:

```json
"measure_alignment": {
  "status": "aligned",
  "musicxml_measure_count": 45,
  "visual_measure_count": 45
}
```

and each visual measure receives:

```json
"musicxml_measure_number": "17"
```

If the counts diverge, the payload reports `"status": "mismatch"` and does not
invent a correspondence.

### Why this matters

On the Airegin sample:

| Output | Initial state | Current state |
| --- | ---: | ---: |
| MusicXML measure count | `45` | `45` |
| structured visual measure count | `36` | `45` |

The earlier geometry work fixed the actual mismatch; this cleanup makes that
alignment an explicit, machine-readable contract.

### Verification

Added deterministic tests for:

- aligned MusicXML/visual measure sequences
- mismatched sequences that must not receive guessed measure numbers
- canonical `/chord-assignments` retrieval
- backward-compatible `/result` retrieval from legacy files

## 2026-05-20 - Partial alignment and MusicXML-guided barline repair

### Problem

The alignment contract was too binary. If the visual measure sequence differed
from the MusicXML sequence by even one measure, the entire job was marked
`mismatch` and no visual measures received `musicxml_measure_number`.

The Giant Steps sample exposed why this was too strict:

```text
MusicXML measures: 33
visual measures:   32
```

The mismatch was localized to system 2, where HOMR's exported visual barline
geometry missed one usable interior boundary. Other systems still had matching
measure counts and could be mapped safely.

The same sample also exposed a weakness in the missing-barline repair heuristic.
The oversized interval polluted the median width calculation, so the interval was
not considered over-wide enough to inspect.

### Fix

#### System-level MusicXML alignment

`pipeline/musicxml_alignment.py` now groups MusicXML measures by system using
`<print new-system="yes" />` markers. When the MusicXML and visual system counts
match, each system is evaluated independently.

New behavior:

| Case | Status | Measure-number behavior |
| --- | --- | --- |
| all systems match | `aligned` | every visual measure receives `musicxml_measure_number` |
| some systems match | `partial` | only matching systems receive `musicxml_measure_number` |
| no safe mapping | `mismatch` | no guessed measure numbers |

The payload now includes:

```json
"measure_alignment": {
  "status": "partial",
  "musicxml_measure_count": 33,
  "visual_measure_count": 32,
  "musicxml_system_count": 8,
  "visual_system_count": 8,
  "aligned_system_count": 7,
  "mismatched_system_count": 1,
  "system_alignment": []
}
```

This lets downstream consumers keep usable results while marking only localized
problem systems for review.

#### Leading-boundary-aware missing-barline detection

The missing-boundary repair now includes the synthetic system-left boundary
before computing typical measure widths. That prevents an already-merged wide
interval from inflating the baseline enough to hide itself.

#### MusicXML system-count hint

The FastAPI pipeline now reads MusicXML measure counts by system before chord
assignment and passes them into `assign_chords_to_measures()`.

When a visual system is short relative to MusicXML, the repair pass can inspect
milder width outliers:

```text
1.25 * typical_measure_width <= gap <= 2.75 * typical_measure_width
```

This does not blindly trust MusicXML. A split still requires a vertical separator
candidate in `homr_processed.png`, because MusicXML does not contain the missing
x-coordinate.

#### Candidate scoring refinement

When multiple vertical candidates exist inside a suspicious interval, selection
now balances:

- how well the split restores plausible adjacent measure widths
- the strength of the vertical component
- midpoint proximity as a final tiebreaker

This avoids preferring a thin note-stem-like candidate only because it makes the
interval widths slightly more even.

### Verification

Added deterministic tests for:

- fully aligned system-level MusicXML mapping
- partial mapping where only matching systems receive `musicxml_measure_number`
- mismatched systems that still avoid guessed measure numbers
- leading-boundary-aware over-wide interval detection
- MusicXML expected-count-guided inspection of a suspicious gap

Replayed the existing Giant Steps artifacts through the updated assignment and
alignment code without rerunning HOMR/EasyOCR:

| Metric | Before | After |
| --- | ---: | ---: |
| visual measures | `32` | `33` |
| MusicXML measures | `33` | `33` |
| alignment status | `mismatch` | `aligned` |
| system 2 visual measures | `3` | `4` |

The repaired system 2 assignment now separates:

```text
Gmaj7 / Bb7
Ebmaj7 / F#7
```

instead of collapsing them into one oversized visual measure.

## 2026-05-21 - Async processing and callback contract

### Problem

`POST /omr/process` ran the full HOMR + chord OCR pipeline before returning.
That made the API fragile for longer scores because callers had to keep the
upload request open until every OMR stage finished.

### Fix

Changed the FastAPI endpoint to queue work in a background task:

- upload validation and file persistence still happen in the request path
- the process response now returns `202 Accepted` with `status: "queued"`
- job state is written to `job_status.json`
- the existing status endpoint now reports `queued`, `processing`, `completed`,
  `failed`, or `not_found`
- completed status payloads include the MusicXML and chord-assignment artifact
  paths
- failed jobs record an error message instead of leaving callers to infer failure
  from missing artifacts

Added an optional `callback_url` form field. When supplied, MusicVision posts a
JSON callback after the job reaches `completed` or `failed`. Callback delivery
errors are stored as `callback_error` on the job status without changing the
terminal job result.

The existing retrieval endpoints remain unchanged:

```text
GET /omr/jobs/{job_id}/musicxml
GET /omr/jobs/{job_id}/chord-assignments
```

### Verification

Updated the FastAPI tests to cover:

- queued upload response
- completed job status after the background task runs
- completion callback payload
- failed job status and failure callback payload
- invalid callback URL rejection

Ran:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_api.py
```

Result: `10 passed`.

## 2026-05-21 - OMR API key and fixed production callback configuration

### Problem

The async callback endpoint accepted a caller-provided `callback_url` in all
environments. That is useful locally, but in production it lets any authorized
request choose where MusicVision sends outbound callback traffic. The OMR
endpoints also did not have an application-level API key gate.

### Fix

Added a small configuration-based security layer:

- `OMR_API_KEY` enables `X-OMR-API-Key` checks on every `/omr/*` endpoint
- `APP_ENV=prod` fails closed if `OMR_API_KEY` is missing
- `OMR_CALLBACK_URL` configures the fixed Spring Boot callback URL
- `OMR_ALLOW_REQUEST_CALLBACK_URL=false` rejects request-supplied callback URLs
- `OMR_CALLBACK_API_KEY` sends `X-OMR-Callback-API-Key` on outbound callbacks

The default local behavior remains lightweight: when `APP_ENV` is not `prod` and
`OMR_API_KEY` is empty, the OMR endpoints remain open for development. Request
callback URLs are allowed by default outside production.

### Documentation

Added:

```text
docs/api/security.md
```

and updated the Spring Boot/API docs with the required headers, production
callback behavior, and error cases.

### Verification

Added FastAPI coverage for:

- rejecting request callback URLs when disabled
- using the configured callback URL when request callbacks are disabled
- requiring `X-OMR-API-Key` when `OMR_API_KEY` is configured
- sending `X-OMR-Callback-API-Key` on outbound callbacks

Ran:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Result: `33 passed`.

## 2026-05-22 - Explicit sync, dev async, and prod async OMR endpoints

### Problem

`POST /omr/process` had changed from the previous synchronous contract to the
new async contract, which broke callers expecting a completed response with
artifact paths. The dev/prod callback distinction also lived behind
environment configuration instead of being visible in the API path.

### Fix

Restored `POST /omr/process` as the legacy synchronous endpoint and added:

```text
POST /omr/dev/process
POST /omr/prod/process
```

The development async endpoint accepts an optional request `callback_url`. The
production async endpoint rejects request-supplied callback URLs, requires
`OMR_API_KEY`, and always uses the configured `OMR_CALLBACK_URL`.

Removed `OMR_ALLOW_REQUEST_CALLBACK_URL`; callback policy is now selected by the
endpoint rather than by an environment flag.

### Verification

Updated FastAPI coverage for:

- legacy synchronous `POST /omr/process`
- development async callback behavior
- production async static callback behavior
- production rejection of request-supplied callback URLs
- production fail-closed behavior for missing API key or callback config

Ran:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_api.py
.\.venv\Scripts\python.exe -m pytest
```

Result: `16 passed`; full suite `35 passed`.

## Progress-by-the-numbers reference

For the consolidated metric history of the Airegin reference score, including
the initial `36`-measure / `35-of-43` chord baseline and the current
`45`-measure / `39-of-43` state, see:

```text
docs/sheet_music_chord_processing_progress_metrics.md
```
