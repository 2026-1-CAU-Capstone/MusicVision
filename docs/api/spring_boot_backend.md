# Spring Boot Backend Integration Guide

This is the contract the Spring Boot backend should use when calling the
MusicVision service.

## 1. Upload an image

```text
POST /omr/process
Content-Type: multipart/form-data
```

Form fields:

| Field | Required | Notes |
| --- | --- | --- |
| `file` | yes | `.png`, `.jpg`, or `.jpeg` only |
| `job_id` | no | If supplied, use only letters, numbers, `_`, `-`; max 128 chars |

Example:

```bash
curl -F "file=@score.png" -F "job_id=demo-job" http://localhost:8000/omr/process
```

Current success response:

```json
{
  "job_id": "demo-job",
  "status": "completed",
  "musicxml_path": "jobs/demo-job/output/score.musicxml",
  "chord_assignments_path": "jobs/demo-job/output/chord_assignments.json",
  "message": "OMR processing completed"
}
```

### Important

The returned `musicxml_path` and `chord_assignments_path` are **MusicVision-local
artifact paths**, not frontend URLs.

The backend should retrieve the files through the API endpoints below rather than
depending on MusicVision's filesystem layout.

## 2. Retrieve the outputs

### MusicXML

```text
GET /omr/jobs/{job_id}/musicxml
```

Response:

```text
Content-Type: application/vnd.recordare.musicxml+xml
```

### Chord assignments

```text
GET /omr/jobs/{job_id}/chord-assignments
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

## 3. Recommended backend flow

1. Receive the uploaded image from the frontend.
2. Send it to `POST /omr/process`.
3. Use the returned `job_id`.
4. Fetch:
   - `/musicxml`
   - `/chord-assignments`
5. Check:
   ```json
   "measure_alignment.status"
   ```
6. Join chord assignments to MusicXML for measures that have:
   ```json
   "musicxml_measure_number"
   ```
7. Persist or transform the combined result for the frontend.

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
```

Returns:

```json
{
  "job_id": "demo-job",
  "status": "completed"
}
```

Possible statuses:

```text
completed
processing
not_found
```

The current processing endpoint is synchronous and currently returns only after
completion, but this endpoint is already available if the backend later wants to
support polling-oriented workflows.

## 6. Error cases to handle

| Case | Response |
| --- | --- |
| unsupported upload extension | `400` |
| missing MusicXML | `404` |
| missing chord assignments | `404` |
| invalid `job_id` | `400` |

Example unsupported-file response:

```json
{
  "detail": "Unsupported file extension. Allowed extensions: .jpeg, .jpg, .png"
}
```

