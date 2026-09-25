import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

BACKEND_DIR = Path(__file__).resolve().parents[1]
if not os.getenv("CHRONIX_TESTING"):
    load_dotenv(BACKEND_DIR / ".env", override=False)

from app.api.incidents import router as incidents_router
from app.api.webhooks import router as webhooks_router

app = FastAPI(title="ChroniX", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174", "http://127.0.0.1:5174", "http://localhost:5175", "http://127.0.0.1:5175"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(incidents_router)
app.include_router(webhooks_router)


@app.get("/")
def root() -> dict[str, str]:
    return {"name": "ChroniX", "description": "Evidence-Driven Incident Intelligence"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
