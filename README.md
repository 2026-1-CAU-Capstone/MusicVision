# MusicVision

## Run the FastAPI OMR service

Requires Python 3.11.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
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
