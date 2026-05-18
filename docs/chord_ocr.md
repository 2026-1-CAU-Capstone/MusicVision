# Printed Chord OCR Architecture

This branch adds printed chord-symbol OCR to the existing MusicVision OMR flow.
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
  -> run printed chord OCR on homr_processed.png
  -> assign chord tokens to measures
      -> prefer HOMR geometry
      -> fall back to CV barline detection only when needed
  -> write enriched result.json
```

The HOMR subprocess boundary is intentionally preserved in this first pass.
MusicVision still invokes vendored HOMR through the CLI and consumes additional
artifacts afterward.

## Why `homr_processed.png` matters

HOMR autocrops and resizes input images before detection. The geometry exported
in `geometry.json` is explicitly defined in the coordinate space of
`homr_processed.png`.

Chord OCR also runs on `homr_processed.png`, so OCR boxes and HOMR geometry align
directly. The pipeline does not mix those processed coordinates with original
upload coordinates.

## HOMR sidecar artifacts

For each successful job, HOMR now writes:

| Artifact | Purpose |
| --- | --- |
| `score.musicxml` | Existing HOMR musical output |
| `geometry.json` | Visual score geometry for downstream assignment |
| `homr_processed.png` | Exact processed image used for geometry detection |

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
- `measure_assignment.py` performs geometry-first assignment
- `fallback_barlines.py` preserves the legacy CV detector as a fallback

Assignment behavior:

1. assign each OCR token to the nearest HOMR system by y-position
2. build measure intervals from the barlines for that system
3. place each token into a measure by x-position
4. estimate beat position within the measure where practical
5. use the CV fallback only if HOMR geometry is missing, incomplete, or unusable

### Geometry repair heuristics

HOMR geometry remains the preferred source of truth, but the assignment stage
does two conservative repairs when HOMR geometry is clearly incomplete.

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
missing separator.

An interval is considered **over-wide** only when:

```text
1.6 * typical_measure_width <= gap <= 2.5 * typical_measure_width
```

The scan uses the system-height ROI and looks for vertical connected components
after a vertical morphological opening. A candidate is kept only when:

```text
height >= 75% of the system ROI height
width  <= 12 px
distance from either interval edge >= 24 px
```

If multiple candidates remain, the chosen split minimizes:

```text
abs((candidate_x - left_x)  - typical_measure_width)
+ abs((right_x - candidate_x) - typical_measure_width)
```

with midpoint proximity as the tiebreaker.

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

## Result payload

`result.json` keeps the existing job-level metadata and now includes structured
pages, systems, measures, and assigned chords. Each page includes an
`assignment_source` value:

- `homr_geometry`
- `cv_fallback`

Example shape:

```json
{
  "job_id": "demo-job",
  "musicxml_file": "score.musicxml",
  "geometry_file": "geometry.json",
  "processed_image_file": "homr_processed.png",
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
              "chords": [
                {
                  "text_raw": "Dm7",
                  "text_norm": "Dm7",
                  "beat": 2
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

## API surface

Existing MusicXML retrieval remains unchanged:

```text
GET /omr/jobs/{job_id}/musicxml
```

Structured result retrieval is now available at:

```text
GET /omr/jobs/{job_id}/result
```

## Manual verification

For a real local smoke test, run the service and post a bundled sample image:

```powershell
uvicorn app.main:app --reload
curl.exe -F "file=@resources/airegin-miles_davis.png" -F "job_id=manual-e2e-airegin" http://127.0.0.1:8000/omr/process
```

Then inspect:

```text
storage/jobs/manual-e2e-airegin/output/score.musicxml
storage/jobs/manual-e2e-airegin/output/geometry.json
storage/jobs/manual-e2e-airegin/output/homr_processed.png
storage/jobs/manual-e2e-airegin/output/result.json
```

The first EasyOCR run may take longer if the model weights are not already
present in the local EasyOCR cache.

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

For a chronological record of the implementation changes and verification
results, see `docs/chord_ocr_changelog.md`.
