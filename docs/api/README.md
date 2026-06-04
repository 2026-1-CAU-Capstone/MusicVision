# MusicVision API Integration Docs

These notes are for the services that consume MusicVision:

- Spring Boot backend integration: [`spring_boot_backend.md`](spring_boot_backend.md)
- Frontend integration guidance: [`frontend.md`](frontend.md)
- OMR API security: [`security.md`](security.md)

## Current API boundary

MusicVision currently accepts raster image uploads only:

```text
.png
.jpg
.jpeg
.webp
```

PDF upload is **not** supported by the current endpoint contract.

`POST /omr/process` remains the legacy synchronous endpoint: it saves the upload,
runs OMR before returning, and responds with completed artifact paths.

`POST /chords/sheet-music/process` is the synchronous chord-only sheet-music
endpoint. It accepts the same raster image uploads, runs printed chord-symbol OCR
and measure assignment, returns the structured chord assignments inline, and
stores `chord_assignments.json`. It runs HOMR visual geometry detection only and
skips TrOMR/MusicXML generation, so its response does not include a MusicXML path
and its alignment status is `visual_only`.

`POST /chords/sheet-music/dev/process` and
`POST /chords/sheet-music/prod/process` are the async chord-only sheet-music
endpoints. They queue the same HOMR-geometry-only chord pipeline and return
`202 Accepted`. Both require `X-OMR-API-Key`; the prod endpoint also requires a
request `callback_url` whose host matches the configured `OMR_CALLBACK_URL`
host.

`POST /chords/chart/process` is the synchronous chord-chart endpoint for clean
grid charts. It accepts the same raster image uploads, skips HOMR, detects chart
rows/measures from barlines, parses chord symbols plus chart-flow symbols, returns
the structured chart inline, and stores `chord_chart.json`.

`POST /chords/chart/dev/process` and `POST /chords/chart/prod/process` are the
async chord-chart endpoints. They queue the same chart pipeline and return
`202 Accepted`. Both require `X-OMR-API-Key`; the prod endpoint also requires a
request `callback_url` whose host matches the configured `OMR_CALLBACK_URL`
host.

Async processing is exposed through explicit dev/prod endpoints:

```text
POST /omr/dev/process
POST /omr/prod/process
POST /chords/sheet-music/dev/process
POST /chords/sheet-music/prod/process
POST /chords/chart/dev/process
POST /chords/chart/prod/process
```

All async endpoints save the upload, queue the job, and return `202 Accepted`.
Callers may poll the job-status endpoint, and callback delivery can be used for
completion/failure events.

In production, Spring Boot should use the prod endpoint for the selected source
type: `POST /omr/prod/process` for full OMR/sheet-music processing,
`POST /chords/sheet-music/prod/process` for chord-only sheet music, or
`POST /chords/chart/prod/process` for chart processing. Prod endpoints require
API keys and a request `callback_url` whose host matches the configured
`OMR_CALLBACK_URL` host. See
[`security.md`](security.md).

The main outputs are:

| Output | Purpose |
| --- | --- |
| `score.musicxml` | HOMR note / notation result |
| `chord_assignments.json` | Printed chord symbols assigned to visual measures |
| `chord_chart.json` | Chord-chart grid, chords, repeats, endings, and navigation |

The important integration guarantee is the measure-alignment block inside
`chord_assignments.json`:

```json
{
  "measure_alignment": {
    "status": "aligned",
    "musicxml_measure_count": 45,
    "visual_measure_count": 45,
    "aligned_system_count": 8,
    "mismatched_system_count": 0
  }
}
```

When `status` is `"aligned"`, each visual measure includes the corresponding
`musicxml_measure_number`, so consumers can join printed chords to MusicXML
measures safely.

When `status` is `"partial"`, the payload includes system-level alignment
metadata. Measures in aligned systems still receive `musicxml_measure_number`;
measures in mismatched systems intentionally do not. Consumers should preserve
the result and surface the mismatched systems as review/correction targets.

## Canonical endpoints

```text
POST /omr/process              # legacy sync
POST /omr/dev/process          # async, request callback allowed
POST /omr/prod/process         # async, domain-validated callback required
POST /chords/sheet-music/process
POST /chords/sheet-music/dev/process
POST /chords/sheet-music/prod/process
POST /chords/chart/process
POST /chords/chart/dev/process
POST /chords/chart/prod/process
GET  /omr/jobs/{job_id}
GET  /omr/jobs/{job_id}/musicxml
GET  /omr/jobs/{job_id}/chord-assignments
GET  /omr/jobs/{job_id}/chord-chart
```

Job statuses are:

```text
queued
processing
completed
failed
not_found
```
