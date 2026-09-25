import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

BACKEND_DIR = Path(__file__).resolve().parents[1]
if not os.getenv("CHRONIX_TESTING"):
    load_dotenv(BACKEND_DIR / ".env", override=False)

from app.api.incidents import router as incidents_router
from app.api.evidence import router as evidence_router
from app.api.webhooks import router as webhooks_router

app = FastAPI(title="ChroniX", version="0.1.0")
FRONTEND_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CHRONIX_FRONTEND_ORIGINS",
        ",".join(
            f"http://{host}:{port}"
            for port in range(5173, 5178)
            for host in ("localhost", "127.0.0.1")
        ),
    ).split(",")
    if origin.strip()
]
app.add_middleware(CORSMiddleware, allow_origins=FRONTEND_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(incidents_router)
app.include_router(evidence_router)
app.include_router(webhooks_router)


@app.get("/")
def root() -> dict[str, str]:
    return {"name": "ChroniX", "description": "Evidence-Driven Incident Intelligence"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
