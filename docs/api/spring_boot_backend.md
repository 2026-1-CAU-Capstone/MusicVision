# Spring Boot Backend Integration Guide

This is the contract the Spring Boot backend should use when calling the
MusicVision service.

## 1. Choose the upload workflow

MusicVision exposes async upload endpoints for Spring Boot integration:

| Endpoint | Intended use | Callback behavior |
| --- | --- | --- |
| `POST /omr/dev/process` | local/dev integration and callback testing | accepts optional request `callback_url` |
| `POST /omr/prod/process` | deployed backend integration | requires request `callback_url`; host must match configured `OMR_CALLBACK_URL` |
| `POST /chords/chart/dev/process` | local/dev chord-chart integration and callback testing | accepts optional request `callback_url`; requires `X-OMR-API-Key` |
| `POST /chords/chart/prod/process` | deployed chord-chart integration | requires request `callback_url`; host must match configured `OMR_CALLBACK_URL`; requires `X-OMR-API-Key` |

Both endpoints store the upload, queue the OMR job, and return
`202 Accepted`. Both also support polling with `GET /omr/jobs/{job_id}`.

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
| `file` | yes | `.png`, `.jpg`, or `.jpeg` only |
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
development endpoint open for convenience. The chord-chart development endpoint
always requires `OMR_API_KEY` to be configured and supplied through
`X-OMR-API-Key`.

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
| `file` | yes | `.png`, `.jpg`, or `.jpeg` only |
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

Chord-chart processing can be synchronous or async:

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
`/chords/chart/dev/process`, that URL comes from the request `callback_url`; for
`/omr/prod/process` and `/chords/chart/prod/process`, it also comes from the
request `callback_url` after host validation against `OMR_CALLBACK_URL`.

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
  "source_type": "chord_chart",
  "time_signature": {
    "text_raw": "4/4",
    "numerator": 4,
    "denominator": 4
  },
  "flow": {
    "repeat_groups": [],
    "endings": [],
    "navigation": [
      {
        "type": "dc_al_ending",
        "text_raw": "D.C. al 2nd ending",
        "target_ending": 2
      }
    ]
  },
  "pages": [
    {
      "page": 1,
      "assignment_source": "chart_grid_detection",
      "systems": [
        {
          "index": 1,
          "section": "A",
          "measures": [
            {
              "index": 1,
              "left_boundary": { "kind": "start_repeat" },
              "right_boundary": { "kind": "single" },
              "chords": [
                {
                  "text_raw": "Ab-7b5",
                  "text_norm": "Abm7b5",
                  "beat": 1
                }
              ],
              "symbols": []
            }
          ]
        }
      ]
    }
  ]
}
```

## 3. Recommended backend flows

### Development flow

1. Receive the uploaded image from the frontend or a local test client.
2. Send it to `POST /omr/dev/process` with:
   - `file`
   - optional `job_id`
   - optional `callback_url`
   - `X-OMR-API-Key` when MusicVision has `OMR_API_KEY` configured
3. Store the returned `job_id` and mark the backend job as queued.
4. If `callback_url` was supplied, wait for the MusicVision callback.
5. If no `callback_url` was supplied, poll `GET /omr/jobs/{job_id}` until it reports `completed` or `failed`.
6. When completed, fetch:
   - `/musicxml`
   - `/chord-assignments`
7. Apply the alignment handling below before joining chords to MusicXML.

### Production flow

1. Receive the uploaded image from the frontend.
2. Send it to `POST /omr/prod/process` with `X-OMR-API-Key` and a
   domain-validated `callback_url`.
3. Store the returned `job_id` and mark the backend job as queued.
4. Wait for the MusicVision callback, or poll `GET /omr/jobs/{job_id}` until it reports `completed` or `failed`.
5. When completed, fetch:
   - `/musicxml`
   - `/chord-assignments`
6. Check:
   ```json
   "measure_alignment.status"
   ```
7. Join chord assignments to MusicXML for measures that have:
   ```json
   "musicxml_measure_number"
   ```
8. Persist or transform the combined result for the frontend.

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
  "chord_assignments_path": "jobs/demo-job/output/chord_assignments.json"
}
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
| invalid `job_id` | `400` |

Example unsupported-file response:

```json
{
  "detail": "Unsupported file extension. Allowed extensions: .jpeg, .jpg, .png"
}
```

