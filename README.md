# ChroniX

ChroniX is an evidence-driven incident intelligence MVP. It accepts fragmented operational evidence and reconstructs a traceable incident story where every event keeps its timestamp, source, evidence, and classification.

## Problem

Incidents are spread across monitoring exports, deployment logs, engineer conversations, and reports. Manually reconstructing what happened makes it easy to miss sequence, context, or uncertainty.

## Solution

ChroniX extracts timestamped events from CSV, TXT/LOG, and PDF uploads, correlates related signals, sorts them into a timeline, and separates facts from inferences, conflicts, and unknowns. The deterministic fallback works without an API key.

## Core Differentiator

Evidence -> Events -> Correlation -> Timeline -> Incident Intelligence. The app does not present an unsupported summary: each timeline item links back to the source evidence that produced it.

## Architecture

- FastAPI handles uploads and the `/api/v1/incidents/analyze` endpoint.
- FastAPI also accepts normalized operational events at `/api/v1/webhooks/events`, keeps them in isolated in-memory active state, and exposes `/api/v1/incidents/active` and `/api/v1/incidents/analyze-active` for the MVP demo.
- Connectors normalize source inputs into a common Evidence model. The file connector delegates CSV, text/log, and PDF parsing to the existing processors; the generic webhook connector is exercised by the local demo service.
- The analysis service correlates keyword-overlapping events, sorts timestamps, and classifies claims.
- The LLM adapter is isolated in `backend/app/services/llm_service.py`. It receives deterministic structured context, returns typed evidence-referenced enrichment, and cannot rewrite the grounded timeline or root-cause status.
- React renders the upload workflow and evidence timeline.

## Tech Stack

Python, FastAPI, Pydantic, pypdf, React, Vite, and CSS.

## Project Structure

```text
backend/app/       API, connectors, models, processors, and analysis services
backend/tests/     Core pipeline and endpoint tests
frontend/src/      ChroniX dashboard
sample_data/       Coherent payment incident demo evidence
demo_service/      External FastAPI payment service for webhook delivery
```

## Setup

Requires Python 3.11+ and Node.js 18+. Python 3.14 users should use a current Pydantic release, as captured by the backend requirement range.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
npm install --prefix frontend
```

## Running Backend

From the repository root:

```powershell
uvicorn app.main:app --app-dir backend --reload
```

The API is available at `http://localhost:8000`.

### LLM enrichment

Copy `.env.example` to `.env` or export the variables in the shell:

```powershell
$env:OPENAI_API_KEY="your_key_here"
$env:OPENAI_BASE_URL="https://api.openai.com/v1"
$env:OPENAI_MODEL="gpt-4o-mini"
```

The adapter uses `httpx` and the OpenAI-compatible `/chat/completions` endpoint. The dashboard reports `used`, `unavailable`, `failed`, or `invalid_response`. Without a key, or when a request/response fails validation, ChroniX keeps deterministic analysis and does not display fabricated AI output.

## Running Frontend

In another terminal:

```powershell
npm run dev --prefix frontend
```

Open the Vite URL, normally `http://localhost:5173`.

## Running the Webhook Demo

Start the separate payment service in another terminal:

```powershell
pip install -r demo_service\requirements.txt
$env:CHRONIX_WEBHOOK_URL="http://127.0.0.1:8000/api/v1/webhooks/events"
uvicorn main:app --app-dir demo_service --port 8001
```

Then send seven real HTTP events into ChroniX:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8001/simulate-incident
```

The dashboard's Live Sources panel polls the active event count. Use **Analyze Active Incident** to run the same analysis pipeline used by file uploads. Replaying the simulation returns duplicate responses for the existing `source_id` values and does not grow active state.

## Demo

Upload `sample_data/monitoring.csv`, `sample_data/engineer_chat.txt`, `sample_data/deployment.log`, and `sample_data/incident_report.pdf`. The payment API incident shows increased errors, suspected database trouble, a payment-service restart, and recovery signals. The root cause remains **NOT CONFIRMED** because database query/error logs are missing.

## Tests

```powershell
pytest backend\tests
```
