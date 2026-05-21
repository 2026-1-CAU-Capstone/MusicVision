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
queues an OMR job and can optionally notify a supplied `callback_url` when the job
finishes. Completed jobs produce `.musicxml` output plus a structured
`chord_assignments.json` containing OCR-read printed chord symbols assigned to
visual measures.
Each completed job also writes `chord_assignment_overlay.png`, a diagnostic image
showing measure assignment and OCR decisions in the HOMR processed-image coordinate
space.
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

The printed chord-symbol OCR architecture, artifact contract, and coordinate-space
rules are documented in:

```text
docs/chord_ocr.md
```

Consumer-facing API integration docs for the Spring Boot backend and frontend are
in:

```text
docs/api/
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
