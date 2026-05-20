# MusicVision API Integration Docs

These notes are for the services that consume MusicVision:

- Spring Boot backend integration: [`spring_boot_backend.md`](spring_boot_backend.md)
- Frontend integration guidance: [`frontend.md`](frontend.md)

## Current API boundary

MusicVision currently accepts raster image uploads only:

```text
.png
.jpg
.jpeg
```

PDF upload is **not** supported by the current endpoint contract.

The main outputs are:

| Output | Purpose |
| --- | --- |
| `score.musicxml` | HOMR note / notation result |
| `chord_assignments.json` | Printed chord symbols assigned to visual measures |

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
POST /omr/process
GET  /omr/jobs/{job_id}
GET  /omr/jobs/{job_id}/musicxml
GET  /omr/jobs/{job_id}/chord-assignments
```
