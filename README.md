# MusicVision

## Run the FastAPI OMR service

Requires Python 3.11.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API currently accepts `.png`, `.jpg`, and `.jpeg` inputs. `POST /omr/process`
is the legacy synchronous endpoint and returns after OMR completes. Async callers
should use `POST /omr/dev/process` for request-supplied callbacks or
`POST /omr/prod/process` for domain-validated production callbacks.
Completed jobs produce `.musicxml` output plus a structured
`chord_assignments.json` containing OCR-read printed chord symbols assigned to
visual measures.

For callers that only need printed chord symbols from sheet music, use:

```text
POST /chords/sheet-music/process
```

This returns the structured chord assignments directly and stores the same
`chord_assignments.json` artifact. This endpoint runs HOMR only through visual
geometry detection for staff systems and barlines, then skips TrOMR/MusicXML
generation. Because no MusicXML is produced, its measure alignment status is
`visual_only`.

For Real Book-style chord charts that use chart grids, section markers, repeat
symbols, endings, navigation text, and slash chords, use:

```text
POST /chords/chart/process
POST /chords/chart/dev/process
POST /chords/chart/prod/process
```

The first endpoint returns and stores `chord_chart.json` synchronously. The
dev/prod endpoints queue the same chart pipeline and support callbacks; both
require `X-OMR-API-Key`, and the prod endpoint validates the request
`callback_url` host against `OMR_CALLBACK_URL`. The chart payload is separate
from `chord_assignments.json` because it contains chart-flow symbols such as
`%`, repeat boundaries, first/second endings, `Fine`, and `D.C. al ...`
navigation in addition to normalized chord symbols.

Sheet-music chord jobs write `chord_assignment_overlay.png` in the HOMR
processed-image coordinate space. Chord-chart jobs write
`chord_chart_overlay.png` in chart-image coordinates.
PDF upload support should only be reintroduced once the preprocessing stage
rasterizes PDF pages first.

Check job state with:

```text
GET /omr/jobs/{job_id}
```

After a job completes, retrieve the generated MusicXML bytes with:

```text
GET /omr/jobs/{job_id}/musicxml
```

Retrieve the structured chord-assignment JSON with:

```text
GET /omr/jobs/{job_id}/chord-assignments
```

Retrieve the structured chord-chart JSON with:

```text
GET /omr/jobs/{job_id}/chord-chart
```

The sheet-music chord processing architecture, artifact contract, and
coordinate-space rules are documented in:

```text
docs/sheet_music_chord_processing.md
```

Optional handwritten-style chord rescue can be enabled with an isolated
PaddleOCR virtualenv so the main HOMR/EasyOCR environment keeps its NumPy
version:

```powershell
$env:MUSICVISION_PADDLEOCR_PYTHON = "$env:TEMP\musicvision-paddleocr-venv\Scripts\python.exe"
$env:MUSICVISION_PADDLEOCR_RESCUE_MODE = "adjudicated"
```

Leave `MUSICVISION_PADDLEOCR_RESCUE_MODE` unset or set to `off` to use the
default EasyOCR-only production path.

Consumer-facing API integration docs for the Spring Boot backend and frontend are
in:

```text
docs/api/
```

The chord-chart parser contract is documented in:

```text
docs/chord_charts.md
```

The chord-chart implementation history and reviewed parser fixes are documented
in:

```text
docs/chord_chart_processing_changelog.md
```

The OMR endpoints can be protected with `X-OMR-API-Key`, and the production
async endpoint requires a fixed Spring Boot callback URL. See:

```text
docs/api/security.md
```

Open the API docs at:

```text
http://127.0.0.1:8000/docs
```

## Run tests

```powershell
python -m pip install -r requirements-dev.txt
pytest
```

(this is separate from homr's tests, it only tests the FastAPI microservice)
