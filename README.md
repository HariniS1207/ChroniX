# ChroniX

**Evidence-Driven Incident Intelligence** turns fragmented operational evidence into one chronological, traceable incident story. Deterministic evidence remains the source of truth: conclusions link to evidence, uncertainty stays visible, and root cause remains **NOT CONFIRMED** unless evidence establishes it.

## Features

- FastAPI webhook and file evidence ingestion with normalization, validation, and deduplication.
- Timestamp-sorted incident timelines classified as FACT, INFERENCE, CONFLICT, or UNKNOWN.
- Deterministic chronology, semantic correlation, conflict links, and evidence graph with source IDs, confidence, and basis.
- SQLite persistence, incident revisions, restart recovery, archive/reset, and historical incident detail.
- Optional asynchronous local Ollama enrichment. It cannot change deterministic classification or root cause; evidence references are checked.
- React dashboard for live incidents, history, file uploads, investigation gaps, and relationships.
- Separate demo service sends seven repeatable payment incident events.

## Architecture and stack

- `backend/`: FastAPI, Pydantic, SQLite, evidence processors, analysis, and optional Ollama integration.
- `frontend/`: React, Vite, and CSS; no graph library is required.
- `demo_service/`: separate FastAPI service that posts sample events to the webhook API.
- `sample_data/`: small example logs, metrics, JSON, text, and PDF evidence.

SQLite is suitable for local and single-node deployment. This project does not implement distributed processing or production-scale infrastructure.

## Requirements and installation

Requires Python 3.11+ and Node.js 18+. From the repository root, in PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
pip install -r demo_service\requirements.txt
npm install --prefix frontend
```

Create `backend/.env` if you want to configure Ollama; the backend loads that file automatically. Configuration can also be set as environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `CHRONIX_DB_PATH` | `./data/chronix.db` | SQLite database path |
| `CHRONIX_LLM_PROVIDER` | `ollama` | Set `disabled` to turn off enrichment |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server |
| `OLLAMA_MODEL` | `qwen3:4b` | Local model name |
| `OLLAMA_TIMEOUT_SECONDS` | `90` | Enrichment request timeout |
| `CHRONIX_MAX_UPLOAD_MB` | `10` | Maximum upload size |
| `CHRONIX_WEBHOOK_URL` | `http://127.0.0.1:8001/api/v1/webhooks/events` | Demo service target |
| `CHRONIX_FRONTEND_ORIGINS` | Local Vite on ports 5173–5177 | Comma-separated browser origins allowed by the backend and demo service |
| `VITE_API_URL` | `http://localhost:8001` | Frontend API base URL |
| `VITE_DEMO_URL` | `http://localhost:9001` | Demo service base URL |

## Run the application

Start each service in its own terminal from the repository root:

```powershell
# Backend on port 8001
uvicorn app.main:app --app-dir backend --reload --port 8001
```

```powershell
# Frontend on port 5173
npm run dev --prefix frontend
```

```powershell
# Demo service on port 9001
uvicorn main:app --app-dir demo_service --reload --port 9001
```

Open the Vite URL (usually `http://localhost:5173`). To enable local enrichment, install and start [Ollama](https://ollama.com/), then fetch the model once:

```powershell
ollama pull qwen3:4b
```

The system remains usable if Ollama is not installed or running. It reports local unavailability and retains deterministic analysis.

## Demo workflow

1. Start backend, frontend, and demo service.
2. In the dashboard, trigger the demo service's `POST /simulate-incident` (or run the command below).
3. Analyze the active incident and review its seven events, classifications, relationships, uncertainty, missing evidence, and any local enrichment.
4. Upload a TXT, LOG, CSV, JSON, or text PDF file to add evidence; open **Incident History** to review archived incidents.

```powershell
Invoke-RestMethod -Method Post http://localhost:9001/simulate-incident
```

The seeded incident includes an API error increase, a database timeout, a deployment, a suspected failure, a restart, and recovery signals. These observations do not prove the database caused the incident. The analysis should keep root cause **NOT CONFIRMED** and show gaps such as database query/error logs, connection pool metrics, and deployment impact analysis. Replaying the same simulation is safe because event source IDs are deduplicated.

## API endpoints

Backend base URL: `http://localhost:8001`.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Health status |
| `POST` | `/api/v1/webhooks/events` | Ingest one normalized event |
| `GET` | `/api/v1/incidents/active` | Active evidence and count |
| `POST` | `/api/v1/incidents/analyze-active` | Analyze active incident |
| `GET` | `/api/v1/incidents/active/intelligence` | Latest active analysis |
| `GET` | `/api/v1/incidents/active/graph` | Active evidence graph |
| `POST` | `/api/v1/incidents/active/reset` | Archive/reset active incident |
| `POST` | `/api/v1/incidents/analyze` | Analyze uploaded files without archiving |
| `POST` | `/api/v1/evidence/upload` | Persist evidence to active or selected historical incident |
| `GET` | `/api/v1/incidents` | List persisted incidents |
| `GET` | `/api/v1/incidents/{incident_id}` | Historical incident detail and analysis |
| `GET` | `/api/v1/incidents/{incident_id}/graph` | Historical evidence graph |
| `POST` | `http://localhost:9001/simulate-incident` | Send seven demo webhook events |

## Evidence formats and limitations

TXT and LOG files are read as timestamped lines; CSV supports common timestamp, source, and event headers; JSON accepts event objects, arrays, and nested event lists; PDF extraction supports text PDFs. **Scanned PDFs require OCR and are rejected clearly; OCR is not implemented.** The optional model may be unavailable, slow, or reject invalid output; deterministic analysis remains available. Semantic matching is a lightweight, deterministic domain vocabulary and does not provide general-purpose language understanding. SQLite is intended for local or single-node use.

## Verification

```powershell
.venv\Scripts\python.exe -m pytest backend\tests -q
npm.cmd run build --prefix frontend
```
