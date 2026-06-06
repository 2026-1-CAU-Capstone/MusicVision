# Spring Boot Backend Integration Guide

This is the contract the Spring Boot backend should use when calling the
MusicVision service.

## 1. Choose the upload workflow

MusicVision exposes async upload endpoints for Spring Boot integration:

| Endpoint | Intended use | Callback behavior |
| --- | --- | --- |
| `POST /omr/dev/process` | local/dev integration and callback testing | accepts optional request `callback_url` |
| `POST /omr/prod/process` | deployed backend integration | requires request `callback_url`; host must match configured `OMR_CALLBACK_URL` |
| `POST /chords/sheet-music/dev/process` | local/dev chord-only sheet-music integration and callback testing | accepts optional request `callback_url`; requires `X-OMR-API-Key` |
| `POST /chords/sheet-music/prod/process` | deployed chord-only sheet-music integration | requires request `callback_url`; host must match configured `OMR_CALLBACK_URL`; requires `X-OMR-API-Key` |
| `POST /chords/chart/dev/process` | local/dev chord-chart integration and callback testing | accepts optional request `callback_url`; requires `X-OMR-API-Key` |
| `POST /chords/chart/prod/process` | deployed chord-chart integration | requires request `callback_url`; host must match configured `OMR_CALLBACK_URL`; requires `X-OMR-API-Key` |

These async endpoints store the upload, queue the OMR job, and return
`202 Accepted`. They also support polling with `GET /omr/jobs/{job_id}`.

### Development async endpoint

```text
POST /omr/dev/process
Content-Type: multipart/form-data
X-OMR-API-Key: <omr-api-key>
```

Use this endpoint when Spring Boot needs to supply a callback URL per request,
for example while testing a local callback controller.

Form fields:

| Field | Required | Notes |
| --- | --- | --- |
| `file` | yes | `.png`, `.jpg`, `.jpeg`, or `.webp` only |
| `job_id` | no | If supplied, use only letters, numbers, `_`, `-`; max 128 chars |
| `callback_url` | no | Absolute `http` or `https` URL; if omitted, poll the status endpoint |

Example with callback:

```bash
curl -H "X-OMR-API-Key: $OMR_API_KEY" -F "file=@score.png" -F "job_id=demo-job" -F "callback_url=http://localhost:8080/omr/callbacks" http://localhost:8000/omr/dev/process
```

Example without callback:

```bash
curl -H "X-OMR-API-Key: $OMR_API_KEY" -F "file=@score.png" -F "job_id=demo-job" http://localhost:8000/omr/dev/process
```

Success response:

```json
{
  "job_id": "demo-job",
  "status": "queued",
  "message": "OMR processing queued"
}
```

When `OMR_API_KEY` is configured, the OMR development endpoint requires
`X-OMR-API-Key`. In local development, leaving `OMR_API_KEY` empty keeps the OMR
development endpoint open for convenience. The chord-only sheet-music and
chord-chart development endpoints always require `OMR_API_KEY` to be configured
and supplied through `X-OMR-API-Key`.

### Production async endpoint

```text
POST /omr/prod/process
Content-Type: multipart/form-data
X-OMR-API-Key: <omr-api-key>
```

Use this endpoint for deployed Spring Boot integration. It requires a callback
URL per request, but only accepts callback URLs whose host matches the configured
`OMR_CALLBACK_URL` host.

Form fields:

| Field | Required | Notes |
| --- | --- | --- |
| `file` | yes | `.png`, `.jpg`, `.jpeg`, or `.webp` only |
| `job_id` | no | If supplied, use only letters, numbers, `_`, `-`; max 128 chars |
| `callback_url` | yes | Absolute `http` or `https` URL; host must match configured `OMR_CALLBACK_URL` host |

Example:

```bash
curl -H "X-OMR-API-Key: $OMR_API_KEY" -F "file=@score.png" -F "job_id=demo-job" -F "callback_url=https://spring.example/internal/omr/callbacks/demo-job" http://localhost:8000/omr/prod/process
```

Success response:

```json
{
  "job_id": "demo-job",
  "status": "queued",
  "message": "OMR processing queued"
}
```

### Callback rules

Spring Boot must send `callback_url` to the production endpoint. MusicVision
rejects the value unless it is an absolute `http` or `https` URL and its host
matches the host of the configured `OMR_CALLBACK_URL`.

Spring Boot may send `callback_url` to the development endpoint. MusicVision
rejects the value unless it is an absolute `http` or `https` URL.

`POST /omr/process` remains available as a legacy synchronous compatibility
endpoint. New backend integration should use `POST /omr/prod/process`.

The `musicxml_path` and `chord_assignments_path` returned by status/callback
payloads are **MusicVision-local artifact paths**, not frontend URLs.

The backend should retrieve the files through the API endpoints below rather than
depending on MusicVision's filesystem layout.

Chord-only sheet-music processing can be synchronous or async:

```text
POST /chords/sheet-music/process
POST /chords/sheet-music/dev/process
POST /chords/sheet-music/prod/process
Content-Type: multipart/form-data
X-OMR-API-Key: <omr-api-key>
```

The synchronous endpoint returns `chord_assignments.json` inline and also stores
it for retrieval through `GET /omr/jobs/{job_id}/chord-assignments`. The
dev/prod sheet-music chord endpoints queue the same chord-only pipeline and use
the callback rules above.

Chord-chart processing can also be synchronous or async:

```text
POST /chords/chart/process
POST /chords/chart/dev/process
POST /chords/chart/prod/process
Content-Type: multipart/form-data
X-OMR-API-Key: <omr-api-key>
```

The synchronous endpoint returns `chord_chart.json` inline and also stores it for
retrieval through `GET /omr/jobs/{job_id}/chord-chart`. The dev/prod chart
endpoints queue the same chart pipeline and use the callback rules above.

### Callback payload

When a callback URL is present, MusicVision posts a JSON payload after the job
reaches a terminal state. For `/omr/dev/process` and
`/chords/sheet-music/dev/process` and `/chords/chart/dev/process`, that URL
comes from the request `callback_url`; for `/omr/prod/process`,
`/chords/sheet-music/prod/process`, and `/chords/chart/prod/process`, it also
comes from the request `callback_url` after host validation against
`OMR_CALLBACK_URL`.

Callbacks are terminal notifications only. MusicVision does not send callbacks
for every progress update; use the status endpoint below for polling progress.

When `OMR_CALLBACK_API_KEY` is configured, MusicVision also sends:

```text
X-OMR-Callback-API-Key: <callback-api-key>
```

Spring Boot should reject callback requests that do not include the expected
header value.

Completed example:

```json
{
  "job_id": "demo-job",
  "status": "completed",
  "message": "OMR processing completed",
  "musicxml_path": "jobs/demo-job/output/score.musicxml",
  "chord_assignments_path": "jobs/demo-job/output/chord_assignments.json"
}
```

Completed chord-chart example:

```json
{
  "job_id": "demo-chart",
  "status": "completed",
  "message": "Chord chart processing completed",
  "chord_chart_path": "jobs/demo-chart/output/chord_chart.json"
}
```

Failed example:

```json
{
  "job_id": "demo-job",
  "status": "failed",
  "message": "OMR processing failed",
  "error": "..."
}
```

## 2. Retrieve the outputs

### MusicXML

```text
GET /omr/jobs/{job_id}/musicxml
X-OMR-API-Key: <omr-api-key>
```

Response:

```text
Content-Type: application/vnd.recordare.musicxml+xml
```

### Chord assignments

```text
GET /omr/jobs/{job_id}/chord-assignments
X-OMR-API-Key: <omr-api-key>
```

Response:

```text
Content-Type: application/json
```

Representative payload:

```json
{
  "job_id": "demo-job",
  "musicxml_file": "score.musicxml",
  "time_signature": "4/4",
  "beats_per_bar": 4,
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
  "pages": [
    {
      "page": 1,
      "assignment_source": "homr_geometry",
      "systems": [
        {
          "index": 1,
          "measures": [
            {
              "index": 2,
              "musicxml_measure_number": "2",
              "chords": [
                {
                  "text_raw": "Fmn?",
                  "text_norm": "Fm7",
                  "beat": 1
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

### Chord chart

```text
GET /omr/jobs/{job_id}/chord-chart
X-OMR-API-Key: <omr-api-key>
```

Response:

```text
Content-Type: application/json
```

Representative payload:

```json
{
  "job_id": "demo-chart",
  "source_file": "cherokee_chord_chart.jpg",
  "source_type": "chord_chart",
  "title": "Cherokee",
  "composer": "Ray Noble",
  "style": "Up Tempo Swing",
  "time_signature": {
    "numerator": 4,
    "denominator": 4
  },
  "beats_per_bar": 4,
  "measure_count": 36,
  "chords": [
    {
      "kind": "chord",
      "text": "Bb6",
      "measure_index": 1,
      "beat": 1,
      "section": "A",
      "source": "direct"
    },
    {
      "kind": "chord",
      "text": "%",
      "measure_index": 2,
      "beat": 1,
      "section": "A",
      "source": "repeat_previous_measure",
      "derived_from_measure_index": 1
    },
    {
      "kind": "chord",
      "text": "G7b9",
      "measure_index": 14,
      "beat": 2,
      "section": "A",
      "source": "direct"
    }
  ],
  "flow": {
    "sections": [
      {
        "section": "A",
        "start_measure_index": 1,
        "end_measure_index": 20
      },
      {
        "section": "B",
        "start_measure_index": 21,
        "end_measure_index": 36
      }
    ],
    "repeat_groups": [
      {
        "start_measure_index": 1,
        "end_measure_index": 16,
        "section": "A"
      }
    ],
    "endings": [
      {
        "number": 1,
        "start_measure_index": 13,
        "end_measure_index": 16,
        "section": "A"
      },
      {
        "number": 2,
        "start_measure_index": 17,
        "end_measure_index": 20,
        "section": "A"
      }
    ],
    "navigation": [
      {
        "type": "fine",
        "measure_index": 20,
        "section": "A",
        "text": "Fine"
      },
      {
        "type": "dc_al_ending",
        "measure_index": 36,
        "section": "B",
        "target_ending": 2,
        "text": "D.C. al 2nd ending"
      }
    ]
  },
  "warnings": []
}
```

`chord_chart.json` is intentionally slim. It does not include OCR boxes,
component splits, parser internals, or page/system/measure debug structure. Those
details are written to `chord_chart_debug.json` for MusicVision-side debugging
and are not part of the Spring Boot contract.

## 3. Recommended backend flows

### Development flow

1. Receive the uploaded image from the frontend or a local test client.
2. Send it to the selected development endpoint:
   - `POST /omr/dev/process` for full OMR
   - `POST /chords/sheet-music/dev/process` for chord-only sheet music
   - `POST /chords/chart/dev/process` for chord charts
3. Include:
   - `file`
   - optional `job_id`
   - optional `callback_url`
   - `X-OMR-API-Key` when MusicVision has `OMR_API_KEY` configured
4. Store the returned `job_id` and mark the backend job as queued.
5. If `callback_url` was supplied, wait for the MusicVision callback.
6. If no `callback_url` was supplied, poll `GET /omr/jobs/{job_id}` until it reports `completed` or `failed`.
7. When completed, fetch the artifact for the selected source type:
   - full OMR: `/musicxml` and `/chord-assignments`
   - chord-only sheet music: `/chord-assignments`
   - chord chart: `/chord-chart`
8. Apply the alignment handling below only for sheet-music chord assignments.

### Production flow

1. Receive the uploaded image from the frontend.
2. Send it to the selected production endpoint with `X-OMR-API-Key` and a
   domain-validated `callback_url`: `POST /omr/prod/process` for full OMR,
   `POST /chords/sheet-music/prod/process` for chord-only sheet music, or
   `POST /chords/chart/prod/process` for chord charts.
3. Store the returned `job_id` and mark the backend job as queued.
4. Wait for the MusicVision callback, or poll `GET /omr/jobs/{job_id}` until it reports `completed` or `failed`.
5. When completed, fetch the artifact for the selected source type:
   - full OMR: `/musicxml` and `/chord-assignments`
   - chord-only sheet music: `/chord-assignments`
   - chord chart: `/chord-chart`
6. For sheet-music chord assignments, check:
   ```json
   "measure_alignment.status"
   ```
7. For full OMR, join chord assignments to MusicXML for measures that have:
   ```json
   "musicxml_measure_number"
   ```
8. For chord charts, persist or transform `chord_chart.json` directly for the frontend.

Recommended handling:

| Status | Meaning | Backend behavior |
| --- | --- | --- |
| `aligned` | all visual systems match MusicXML measure counts | join all measures |
| `partial` | some systems match and some do not | join measures that have `musicxml_measure_number`; preserve warning metadata |
| `mismatch` | no safe system-level mapping exists | avoid automatic chord-to-MusicXML pairing |

## 4. What to do if measures do not fully align

If MusicVision returns:

```json
{
  "measure_alignment": {
    "status": "partial"
  }
}
```

do **not** silently join unmatched measures by array index. The result is still
useful: aligned systems keep `musicxml_measure_number`, and mismatched systems
should be forwarded as correction targets.

Recommended backend behavior:

- store the result for debugging
- surface a clear processing warning upstream
- join only measures that have `musicxml_measure_number`
- avoid presenting mismatched systems as automatically reliable

If MusicVision returns:

```json
{
  "measure_alignment": {
    "status": "mismatch"
  }
}
```

avoid automatic chord-to-MusicXML pairing for that job, but still consider
returning the raw MusicXML and chord-assignment payload so the frontend can show
or correct what is available.

## 5. Status endpoint

```text
GET /omr/jobs/{job_id}
X-OMR-API-Key: <omr-api-key>
```

Returns:

```json
{
  "job_id": "demo-job",
  "status": "completed",
  "message": "OMR processing completed",
  "musicxml_path": "jobs/demo-job/output/score.musicxml",
  "chord_assignments_path": "jobs/demo-job/output/chord_assignments.json",
  "chord_chart_path": null
}
```

While an async job is queued or processing, the status payload may include
polling-oriented progress fields:

```json
{
  "job_id": "demo-chart",
  "status": "processing",
  "message": "Reading chart cells (12/30)",
  "progress": 62,
  "stage": "cell_ocr",
  "current_step": 12,
  "total_steps": 30
}
```

`progress` is an integer percentage from `0` to `100`. The frontend should poll
the Spring Boot backend, and Spring Boot should poll this MusicVision endpoint
server-to-server with `X-OMR-API-Key`; do not expose the MusicVision API key to
the browser.

For chord-chart jobs, current stage values can include:

```text
queued
starting
preprocessing
loading_image
detecting_grid
page_ocr
row_ocr
selective_cell_ocr
parsing
overlay
exporting
completed
```

Possible statuses:

```text
queued
processing
completed
failed
not_found
```

If callback delivery fails, the job can still complete; the status payload may
include `callback_error` for diagnostics.

## 6. Error cases to handle

| Case | Response |
| --- | --- |
| missing or invalid OMR API key | `401` |
| missing OMR API key config for production async | `503` |
| unsupported upload extension | `400` |
| invalid `callback_url` | `400` |
| missing production `callback_url` | `400` |
| production `callback_url` host does not match configured host | `400` |
| missing callback host config for production async | `503` |
| missing MusicXML | `404` |
| missing chord assignments | `404` |
| missing chord chart | `404` |
| invalid `job_id` | `400` |

Example unsupported-file response:

```json
{
  "detail": "Unsupported file extension. Allowed extensions: .jpeg, .jpg, .png, .webp"
}
```

