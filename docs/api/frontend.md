# Frontend Integration Guide

The frontend should treat the Spring Boot backend as its API boundary.

MusicVision itself is an internal OMR service; the frontend should **not** need
to know MusicVision filesystem paths such as:

```text
jobs/{job_id}/output/chord_assignments.json
```

## What the frontend likely needs from the backend

At minimum, the backend should provide:

| Data | Why the frontend may need it |
| --- | --- |
| job status | show loading / completed / failed state |
| MusicXML or a rendered-score derivative | display or further process the recognized score |
| chord assignments | show printed chord symbols attached to measures |
| measure-alignment status | know whether chord-to-measure pairing is trustworthy |

## Recommended frontend-facing shape

The exact Spring Boot DTO is up to the backend team, but a useful response shape
would look like:

```json
{
  "jobId": "demo-job",
  "status": "completed",
  "measureAlignment": {
    "status": "aligned",
    "musicxmlMeasureCount": 45,
    "visualMeasureCount": 45,
    "alignedSystemCount": 8,
    "mismatchedSystemCount": 0
  },
  "musicXml": "<score-partwise>...</score-partwise>",
  "chordAssignments": [
    {
      "measureNumber": "2",
      "chords": [
        {
          "text": "Fm7",
          "beat": 1
        }
      ]
    }
  ]
}
```

The backend may choose a different DTO, but the frontend should ideally receive
a **simple measure-oriented structure** rather than needing to understand every
internal field from MusicVision's full JSON.

## How to interpret chord assignments

Each assigned chord has:

| Field | Meaning |
| --- | --- |
| `text_norm` | normalized chord text to display, such as `Fm7` |
| `text_raw` | raw OCR text, mainly useful for debugging |
| `beat` | estimated beat position within the measure |
| `musicxml_measure_number` | measure number matching `score.musicxml` when alignment is valid |

For normal UI display, prefer:

```text
text_norm
```

not:

```text
text_raw
```

## Alignment rule the frontend should respect

The frontend can treat chord-to-measure pairing as fully reliable when:

```json
"measureAlignment.status": "aligned"
```

If the backend reports:

```json
{
  "measureAlignment": {
    "status": "partial"
  }
}
```

the frontend should still show the result. Measures that were aligned by the
backend can be displayed normally, while mismatched systems should be marked as
review/correction targets.

If the backend reports:

```json
{
  "measureAlignment": {
    "status": "mismatch"
  }
}
```

the frontend should avoid silently showing chords as if their measure mapping were
trusted. A simple first implementation could show a warning such as:

```text
Chord-to-measure alignment could not be verified for this score.
```

## What the frontend does not need

For normal product behavior, the frontend does not need:

- `geometry.json`
- `homr_processed.png`
- `chord_assignment_overlay.png`
- OCR reject diagnostics
- OCR bounding boxes

Those are useful for debugging and model improvement, but they are not necessary
for the main user-facing flow unless the product later adds an admin/debug view.

## Current upload limitation

The current MusicVision service accepts:

```text
.png
.jpg
.jpeg
.webp
```

PDF input is not supported by the current OMR endpoint yet.

If the user-facing product accepts PDFs, the backend will need either:

1. a separate rasterization step before calling MusicVision, or
2. future MusicVision PDF support once that branch is implemented
