from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.incidents import router as incidents_router

app = FastAPI(title="ChroniX", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(incidents_router)


@app.get("/")
def root() -> dict[str, str]:
    return {"name": "ChroniX", "description": "Evidence-Driven Incident Intelligence"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
