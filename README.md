# MusicVision

## Run the FastAPI OMR service

Requires Python 3.11.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API currently accepts `.png`, `.jpg`, and `.jpeg` inputs. Those files are passed
through HOMR to generate the returned `.musicxml` output. PDF upload support should
only be reintroduced once the preprocessing stage rasterizes PDF pages first.

After processing a job, retrieve the generated MusicXML bytes with:

```text
GET /omr/jobs/{job_id}/musicxml
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
