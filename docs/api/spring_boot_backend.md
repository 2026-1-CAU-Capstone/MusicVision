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
    "visual_measure_count": 45
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
   "measure_alignment.status": "aligned"
   ```
6. Join chord assignments to MusicXML using:
   ```json
   "musicxml_measure_number"
   ```
7. Persist or transform the combined result for the frontend.

## 4. What to do if measures do not align

If MusicVision returns:

```json
{
  "measure_alignment": {
    "status": "mismatch"
  }
}
```

do **not** silently join measures by array index.

Recommended backend behavior:

- store the result for debugging
- surface a clear processing warning/error upstream
- avoid presenting chord-to-measure pairing as reliable for that job

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

