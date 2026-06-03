# Sheet Music Chord Processing Architecture

This branch adds printed chord-symbol processing to the existing MusicVision OMR flow.
It does **not** infer chords from HOMR-recognized notes. Instead, it reads chord
symbols that are printed on the sheet image, such as `Dm7`, `G7`, and `Cmaj7`,
and assigns them to visual measures.

## Pipeline

```text
upload
  -> preprocess input
  -> run HOMR subprocess once
      -> score.musicxml
      -> geometry.json
      -> homr_processed.png
  -> clean redundant single-staff clefs in score.musicxml
  -> run printed chord OCR on homr_processed.png
  -> assign chord tokens to measures
      -> prefer HOMR geometry
      -> fall back to CV barline detection only when needed
  -> detect visual ending brackets above staff systems
  -> align visual measures to MusicXML measures
  -> write MusicXML ending start/stop barlines when alignment is safe
  -> render chord_assignment_overlay.png
  -> write enriched chord_assignments.json
```

The HOMR subprocess boundary is intentionally preserved in this first pass.
MusicVision still invokes vendored HOMR through the CLI and consumes additional
artifacts afterward.

For the internal HOMR boundary between pre-TrOMR visual geometry and post-TrOMR
MusicXML generation, see [`homr_tromr_pipeline.md`](homr_tromr_pipeline.md).
For runtime baselines and EasyOCR optimization notes, see
[`sheet_music_chord_processing_performance.md`](sheet_music_chord_processing_performance.md).

## Why `homr_processed.png` matters

HOMR autocrops and resizes input images before detection. The geometry exported
in `geometry.json` is explicitly defined in the coordinate space of
`homr_processed.png`.

Chord OCR also runs on `homr_processed.png`, so OCR boxes and HOMR geometry align
directly. The pipeline does not mix those processed coordinates with original
upload coordinates.

## MusicXML structure postprocess

The full `/omr/process` pipeline keeps HOMR as the MusicXML generator, then
applies two conservative MusicVision postprocesses to `score.musicxml`.

First, `clean_single_staff_redundant_clefs()` removes later `<clef>` entries when
the output appears to be a single-staff lead sheet. It refuses to run on
multi-staff output by checking MusicXML `<staves>` values and numbered clefs, so
piano-style scores keep their legitimate staff clefs.

Second, `detect_ending_markers()` looks for first/second-ending brackets in
`homr_processed.png`. The detector searches the band above each visual system,
keeps long horizontal marks with a left bracket hook, rejects candidates too
close to the staff, and maps accepted brackets back to visual measure boxes.
Those markers are stored on affected measures as `form_markers`.

After measure alignment adds `musicxml_measure_number` to visual measures,
`apply_ending_markers_to_musicxml()` writes matching MusicXML `<ending>`
start/stop barlines. If alignment cannot provide both the start and end MusicXML
measure numbers, that marker is left out rather than guessed.

The resulting `chord_assignments.json` records this work in
`musicxml_postprocess`, including removed clef count, detected visual endings,
and added MusicXML ending elements.

## HOMR sidecar artifacts

For each successful full OMR job, the pipeline writes:

| Artifact | Purpose |
| --- | --- |
| `score.musicxml` | HOMR musical output after MusicVision clef/ending postprocess |
| `geometry.json` | Visual score geometry for downstream assignment |
| `homr_processed.png` | Exact processed image used for geometry detection |
| `chord_assignment_overlay.png` | Diagnostic view of measure assignment and OCR decisions |

`geometry.json` contains:

- processed image width and height
- system envelopes derived from HOMR `MultiStaff` groupings
- staff envelopes
- detected barline boxes
- an explicit `coordinate_space` value of `homr_processed_image`

System envelopes are exported from `MultiStaff`, not from a flat list of staves,
so one-staff lead-sheet systems and multi-staff systems share the same downstream
assignment model.

## Chord OCR and assignment

The image-only first pass lives under `pipeline/chords/`:

- `grammar.py` normalizes and validates printed chord text
- `easyocr_backend.py` performs EasyOCR token extraction
- `ocr_common.py` contains OCR preprocessing helpers
- `token_filters.py` removes a small set of visually obvious non-chords
- `measure_assignment.py` performs geometry-first assignment
- `fallback_barlines.py` preserves the legacy CV detector as a fallback

Assignment behavior:

1. assign targeted OCR tokens to their source HOMR system when available
2. otherwise assign each OCR token to the nearest HOMR system by y-position
3. build measure intervals from the barlines for that system
4. place each token into a measure by x-position
5. estimate beat position within the measure where practical
6. use the CV fallback only if HOMR geometry is missing, incomplete, or unusable

### Targeted chord-band OCR

The sheet-music OCR backend now uses HOMR geometry before recognition. Instead
of sending the full processed page to EasyOCR first, it crops a likely chord band
above each detected staff system and runs EasyOCR on those bands.

This is still conservative:

- the crop coordinates stay in `homr_processed_image` space
- the same grammar and visual filters run after OCR
- the original full-page EasyOCR pass remains available as a recall fallback

The fallback is triggered when the targeted pass looks implausibly sparse:

```text
accepted_tokens == 0
usable_system_crop_count / systems_total < 0.50
systems_with_chords / systems_total < 0.25
accepted_tokens / estimated_visual_measure_count < 0.20
```

When fallback runs, targeted and full-page OCR tokens are merged by normalized
text and overlapping/nearby bounding boxes. The higher-confidence duplicate is
kept. This lets targeted OCR remain the fast first pass while preserving the
previous broad OCR behavior for unusual layouts where chords are not in the
expected bands.

`chord_ocr.strategy` records which path was used:

```text
full_page
targeted_only
targeted_with_full_page_fallback
```

### Chord OCR correction and uncertain candidates

After EasyOCR returns text, the chord OCR path applies a bounded correction pass
before measure assignment. The goal is to fix high-confidence OCR structure
errors without turning the parser into a large per-song rulebase.

The EasyOCR call is constrained with a chord-character allowlist. This keeps the
recognizer focused on roots, lowercase chord-quality text, digits, accidentals,
slash chords, parentheses, and minor shorthand. It does not add another OCR pass.

The structural normalizer handles cases that are common and low risk:

```text
C 7     -> C7
Bb maj7 -> Bbmaj7
C_7     -> C-7
6m7     -> Gm7
CM7     -> Cmaj7
```

For harder OCR strings such as `Cm4it`, `Fm4T`, or `Bbmai7`, the pipeline does
not use one-off string replacements. Instead,
`pipeline/chords/candidate_resolution.py` compares the rejected text with a
small set of valid common chord candidates for the same likely root. It uses
weighted OCR-confusion costs for character-level mistakes such as `4` versus
`a`, `i` versus `j`, and `t`/`z` versus `7`.

A candidate is accepted only when it clears the score threshold and is clearly
better than the next-best candidate. Otherwise the hit remains rejected but is
reported as an uncertain chord candidate:

```json
{
  "text": "Am76s)",
  "text_norm": "Am76s)",
  "reason": "failed chord grammar",
  "candidate_kind": "uncertain_chord",
  "suggestions": [
    {
      "text_norm": "Am7b5",
      "score": 0.663,
      "reason": "near_valid_chord_candidate"
    }
  ]
}
```

This gives callers a way to show or inspect likely chord OCR misses without
silently assigning ambiguous text to a measure.

The same resolver also reviews accepted OCR text that passes the broad chord
grammar but does not look like a common chord form. This catches handwritten
font confusions that would otherwise be silently assigned:

```text
C-1  -> C-7
G1   -> G7
A-1  -> A-7
E67  -> Eb7
B6-7 -> Bb-7
B627 -> Bb-7
F87  -> F#7
```

Low-confidence hits now run through the resolver before being rejected. They are
not assigned as chords, but chord-like low-confidence hits can include
`candidate_kind: "uncertain_chord"` and candidate suggestions.

For handwritten-style `maj7` symbols, the resolver also emits a specific
`handwritten_major_seventh_candidate` suggestion when the text looks like a
damaged major-seventh suffix, such as `Ctin`, `Coi1`, `Can`, or `Cn+i`. These
suggestions are diagnostic-first: they do not auto-assign a chord unless the
normal near-valid candidate path also supports the same correction.

The OCR backend also has one bounded split-token repair for touching symbols in
the same targeted system crop. If EasyOCR reads a root-only token followed
immediately by a `maj7`-like tail fragment, the pair is merged into one chord
token:

```text
Bb + an7/Ab7 -> Bbmaj7
```

The merge requires same-system provenance when available, strong vertical
overlap, and a very small horizontal gap. Separated chords are left alone.

Targeted OCR tokens also keep their source `system_index`. During HOMR-geometry
assignment, that index is preferred over nearest-y grouping so chords that sit
between close staff systems stay attached to the system whose crop produced
them.

### Geometry repair heuristics

HOMR geometry remains the preferred source of truth, but the assignment stage
does conservative repairs when HOMR geometry is clearly incomplete.

#### 1. Preserve a leading first measure

HOMR barlines are visual separators; the left edge of a system can also be the
left boundary of the first measure even when no barline is drawn there.

The current rule:

- merge near-duplicate barline x-positions within `1 px`
- treat gaps below `12 px` as non-measure noise
- compute the median width of the remaining substantial gaps
- add the system's left edge as a leading boundary when:

```text
leading_gap >= max(24 px, 0.25 * typical_measure_width)
```

This restored the first visual measure of each system in the Airegin sample.

#### 2. Recover one missed interior barline inside an over-wide interval

If one HOMR interval is much wider than the other measures in the same system,
the assignment stage scans that interval in `homr_processed.png` for a plausible
missing separator. The system-left boundary is included before measuring typical
widths, so an already-merged wide interval cannot inflate the baseline as easily.

An interval is considered **over-wide** only when:

```text
1.6 * typical_measure_width <= gap <= 2.5 * typical_measure_width
```

When `score.musicxml` says the same visual system should contain more measures
than the current visual geometry produced, the scan can also inspect milder
outliers:

```text
1.25 * typical_measure_width <= gap <= 2.75 * typical_measure_width
```

MusicXML is only used as a count constraint. The split still requires image
evidence inside `homr_processed.png`; MusicXML does not provide the missing
x-coordinate.

The scan uses the system-height ROI and looks for vertical connected components
after a vertical morphological opening. A candidate is kept only when:

```text
height >= 75% of the system ROI height
width  <= 12 px
distance from either interval edge >= 24 px
```

If multiple candidates remain, the chosen split prefers candidates that restore
ordinary-looking adjacent widths, with a small bonus for stronger vertical
components:

```text
abs((candidate_x - left_x)  - typical_measure_width)
+ abs((right_x - candidate_x) - typical_measure_width)
```

with midpoint proximity as the final tiebreaker.

This repaired the missed interior separator in Airegin's first system, moving
`C7` from beat 3 of an over-wide measure to beat 1 of the following measure.

#### How this differs from note stems

The recovery pass does **not** claim that shape alone can perfectly separate
barlines from note stems. Some note stems can also be narrow and tall.

Instead, it reduces stem confusion through context:

- it only searches intervals that are already measure-width outliers
- it requires a separator to span most of the full staff/system ROI height
- it prefers the candidate that restores ordinary-looking adjacent measure
  widths

So the current implementation is best described as a conservative
**missing-boundary repair**, not a general-purpose visual barline classifier.

The more permissive CV fallback detector in `fallback_barlines.py` remains
separate and is still used only when HOMR geometry is missing or unusable.

### OCR observability and conservative cleanup

`chord_assignments.json` now preserves the OCR decision trail under `chord_ocr`:

- `accepted_tokens`
- `rejected_hits`
- `filtered_hits`

That distinction matters:

- `rejected_hits` are EasyOCR reads that never passed the grammar/confidence gate
- `filtered_hits` are grammar-valid reads that were later removed because the
  visual context strongly suggested they were not chord symbols

#### 1. Circled rehearsal-mark suppression

Single-letter chord names such as `F` are legitimate, so the pipeline does **not**
ban all one-character tokens. Instead, it only suppresses a single-letter token
when a surrounding contour looks like a rehearsal-mark circle.

The current rule is applied only to normalized single roots `A` through `G`.
Inside a padded ROI around that token, a contour is considered circle-like when:

```text
1.15 <= contour_width  / token_width  <= 3.0
1.15 <= contour_height / token_height <= 3.0
0.75 <= contour_aspect_ratio <= 1.35
```

and the contour bounding box contains the token center.

On Airegin, this removed the circled rehearsal `B` that EasyOCR read as raw text
`8` and normalized to chord `B`.

#### 2. Single-letter notation touching the staff

The Airegin sample also produced a false positive where a musical glyph inside
the notation was read as lowercase `e`, then normalized to chord `E`.

For normalized single roots `A` through `G`, the current rule suppresses the
token when:

```text
nearest_system_top_y - token_bottom_y <= 6 px
```

In other words, a one-letter token that touches or nearly touches the staff
envelope is treated as notation rather than a printed chord label. The rule is
intentionally limited to single-letter roots so multi-character labels such as
`C7` or `Fm7` are not affected.

#### 3. OCR text repairs added from observed EasyOCR misreads

The grammar layer now handles a few sample-backed OCR confusions:

| Raw OCR example | Corrected text |
| --- | --- |
| `cbmajz` | `Cbmaj7` |
| `Bbinajz` | `Bbmaj7` |
| `Bom?` | `Bbm7` |
| `Fmn?` | `Fm7` |
| `Gmzbs` | `Gm7b5` |

These are deliberately narrow text repairs rather than general chord inference.
The pipeline still does not invent a missing `7` when OCR omits it completely.

### Diagnostic overlay

Every completed run now writes:

```text
chord_assignment_overlay.png
```

The overlay is drawn directly on `homr_processed.png`, so it uses the same
processed-image coordinate space as both OCR boxes and HOMR geometry.

Current legend:

| Colour | Meaning |
| --- | --- |
| blue | visual measure boxes and measure labels |
| green | assigned chord tokens, labelled with measure and beat |
| orange | grammar-valid OCR hits removed by the contextual filters |
| red | OCR hits rejected before assignment |

This artifact is intentionally diagnostic rather than presentation-oriented. It
exists to make geometry repairs, OCR cleanup, and assignment mistakes inspectable
without re-running a debugger.

## Chord-assignment payload

`chord_assignments.json` keeps the job-level metadata and includes structured
pages, systems, measures, assigned chords, OCR diagnostics, and an explicit
MusicXML-alignment summary. Each page includes an `assignment_source` value:

- `homr_geometry`
- `cv_fallback`

Example shape:

```json
{
  "job_id": "demo-job",
  "musicxml_file": "score.musicxml",
  "geometry_file": "geometry.json",
  "processed_image_file": "homr_processed.png",
  "overlay_file": "chord_assignment_overlay.png",
  "musicxml_postprocess": {
    "removed_clefs": 6,
    "detected_endings": [
      {
        "type": "ending",
        "number": 1,
        "start_measure_index": 10,
        "end_measure_index": 10,
        "source": "visual_ending_bracket_detection"
      }
    ],
    "added_endings": 4
  },
  "measure_alignment": {
    "status": "aligned",
    "musicxml_measure_count": 45,
    "visual_measure_count": 45,
    "musicxml_system_count": 8,
    "visual_system_count": 8,
    "aligned_system_count": 8,
    "mismatched_system_count": 0,
    "system_alignment": [
      {
        "visual_system_index": 1,
        "musicxml_system_index": 1,
        "status": "aligned",
        "musicxml_measure_count": 5,
        "visual_measure_count": 5
      }
    ]
  },
  "chord_ocr": {
    "backend": "easyocr",
    "strategy": {
      "mode": "targeted_only",
      "targeted": {
        "attempted": true,
        "regions": 8,
        "systems_total": 8,
        "usable_system_crop_count": 8,
        "estimated_visual_measures": 31,
        "accepted_tokens_before_visual_filters": 30,
        "rejected_hits": 4,
        "systems_with_chords": 7
      },
      "fallback": {
        "triggered": false,
        "reason": null
      }
    },
    "accepted_tokens": [],
    "rejected_hits": [],
    "filtered_hits": []
  },
  "pages": [
    {
      "page": 1,
      "assignment_source": "homr_geometry",
      "systems": [
        {
          "index": 1,
          "measures": [
            {
              "index": 1,
              "musicxml_measure_number": "1",
              "chords": [
                {
                  "text_raw": "Dm7",
                  "text_norm": "Dm7",
                  "beat": 2
                }
              ],
              "form_markers": [
                {
                  "type": "ending",
                  "number": 1,
                  "source": "visual_ending_bracket_detection"
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

### Measure alignment with MusicXML

After HOMR produces `score.musicxml`, the pipeline reads the MusicXML measure
sequence and groups it by system using MusicXML `<print new-system="yes" />`
markers. It then compares those MusicXML systems with the visual systems used
for chord assignment.

If all system counts match, the payload reports:

```json
"measure_alignment": {
  "status": "aligned",
  "musicxml_measure_count": 45,
  "visual_measure_count": 45,
  "aligned_system_count": 8,
  "mismatched_system_count": 0
}
```

and each visual measure receives its corresponding
`musicxml_measure_number`.

If some systems match and some do not, the payload reports `"status": "partial"`.
Measures in matching systems still receive `musicxml_measure_number`; measures in
mismatched systems do not receive guessed numbers.

Example:

```json
"measure_alignment": {
  "status": "partial",
  "musicxml_measure_count": 33,
  "visual_measure_count": 32,
  "aligned_system_count": 7,
  "mismatched_system_count": 1,
  "system_alignment": [
    {
      "visual_system_index": 2,
      "musicxml_system_index": 2,
      "status": "mismatch",
      "musicxml_measure_count": 4,
      "visual_measure_count": 3
    }
  ]
}
```

If no safe system-level correspondence exists, the payload reports:

```json
"measure_alignment": {
  "status": "mismatch",
  "musicxml_measure_count": 45,
  "visual_measure_count": 44
  "visual_system_count": 7
}
```

The pipeline intentionally does **not** guess measure numbers for mismatched or
unmatched systems. That keeps downstream consumers from silently combining
incompatible sequences while still preserving usable partial results.

## API surface

OMR processing has one legacy synchronous endpoint and two explicit async
endpoints:

```text
POST /omr/process       # legacy sync
POST /omr/dev/process   # async, request callback allowed
POST /omr/prod/process  # async, domain-validated callback required
```

The async upload responses return `202 Accepted` with a queued `job_id`. Callers
can poll `GET /omr/jobs/{job_id}` or use the configured callback flow to receive
a completion/failure callback.

The OMR endpoints can require `X-OMR-API-Key`. Production should call
`POST /omr/prod/process` with a request `callback_url` whose host matches the
configured `OMR_CALLBACK_URL` host. See
[`api/security.md`](api/security.md) for the security configuration.

Existing MusicXML retrieval remains unchanged:

```text
GET /omr/jobs/{job_id}/musicxml
```

Structured chord-assignment retrieval is now available at:

```text
GET /omr/jobs/{job_id}/chord-assignments
```

## Manual verification

For a real local smoke test, run the service and post a bundled sample image:

```powershell
uvicorn app.main:app --reload
curl.exe -F "file=@resources/airegin-miles_davis.png" -F "job_id=manual-e2e-airegin" http://127.0.0.1:8000/omr/dev/process
curl.exe http://127.0.0.1:8000/omr/jobs/manual-e2e-airegin
```

Once the status is `completed`, inspect:

```text
storage/jobs/manual-e2e-airegin/output/score.musicxml
storage/jobs/manual-e2e-airegin/output/geometry.json
storage/jobs/manual-e2e-airegin/output/homr_processed.png
storage/jobs/manual-e2e-airegin/output/chord_assignment_overlay.png
storage/jobs/manual-e2e-airegin/output/chord_assignments.json
```

The first EasyOCR run may take longer if the model weights are not already
present in the local EasyOCR cache.

## Runtime dependencies

MusicVision now declares `numpy` and `opencv-python-headless` directly in the
root `requirements.txt` because code under `pipeline/chords/` imports both
directly.

Important detail:

- the import name is `cv2`
- the package to install is `opencv-python-headless`

If an editor or shell reports missing `cv2` / `numpy`, first make sure it is
using this repo's virtual environment, for example:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

and select `.\.venv\Scripts\python.exe` as the interpreter in the editor.

## Current first-pass scope

Included:

- raster image inputs already supported by MusicVision
- EasyOCR printed chord extraction
- HOMR-geometry-first measure assignment
- CV barline fallback

Intentionally deferred:

- vector PDF extraction
- TrOCR support
- HOMR in-process refactor
- reconstructing original-upload coordinates from processed-image coordinates
- broad OCR recovery when EasyOCR drops characters entirely, such as a missing
  trailing `7`

For a chronological record of the implementation changes and verification
results, see `docs/sheet_music_chord_processing_changelog.md`.

For a metrics-focused before/after summary of the Airegin reference run, see
`docs/sheet_music_chord_processing_progress_metrics.md`.
