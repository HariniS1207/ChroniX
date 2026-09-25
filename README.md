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
- Connectors normalize source inputs into a common Evidence model. The file connector delegates CSV, text/log, and PDF parsing to the existing processors; a generic webhook connector is ready for future producers.
- The analysis service correlates keyword-overlapping events, sorts timestamps, and classifies claims.
- The optional LLM adapter is isolated in `backend/app/services/llm_service.py`; local analysis remains the fallback.
- React renders the upload workflow and evidence timeline.

## Tech Stack

Python, FastAPI, Pydantic, pypdf, React, Vite, and CSS.

## Project Structure

```text
backend/app/       API, connectors, models, processors, and analysis services
backend/tests/     Core pipeline and endpoint tests
frontend/src/      ChroniX dashboard
sample_data/       Coherent payment incident demo evidence
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

### Optional LLM narrative

Set `OPENAI_API_KEY` to enable the structured narrative adapter. Optional settings are `OPENAI_BASE_URL` for an OpenAI-compatible provider and `OPENAI_MODEL` (default `gpt-4o-mini`). Timeline events remain the locally extracted, source-linked events; API failures automatically use the deterministic analysis.

## Running Frontend

In another terminal:

```powershell
npm run dev --prefix frontend
```

Open the Vite URL, normally `http://localhost:5173`.

## Demo

Upload `sample_data/monitoring.csv`, `sample_data/engineer_chat.txt`, `sample_data/deployment.log`, and `sample_data/incident_report.pdf`. The payment API incident shows increased errors, suspected database trouble, a payment-service restart, and recovery signals. The root cause remains **NOT CONFIRMED** because database query/error logs are missing.

## Tests

```powershell
pytest backend\tests
```
