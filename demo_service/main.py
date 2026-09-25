import os

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="ChroniX Demo Payment Service")
WEBHOOK_URL = os.getenv("CHRONIX_WEBHOOK_URL", "http://127.0.0.1:8001/api/v1/webhooks/events")


class PaymentRequest(BaseModel):
    amount: float = 25.0
    currency: str = "USD"


EVENTS = [
    ("2026-09-25T10:02:00", "Payment API error rate increased", "HTTP 500 error rate exceeded threshold", "critical"),
    ("2026-09-25T10:03:00", "Database connection timeout", "Payment database connection timeout observed", "critical"),
    ("2026-09-25T10:05:00", "Payment service deployment started", "Deployment rollout 8f21 started", "warning"),
    ("2026-09-25T10:08:00", "Database failure suspected", "Database failure may be contributing to payment errors", "warning"),
    ("2026-09-25T10:10:00", "Payment service restarted", "Payment service restarted during incident response", "critical"),
    ("2026-09-25T10:12:00", "Database metrics returned to normal", "Database CPU and connection metrics returned to normal", "info"),
    ("2026-09-25T10:15:00", "Payment API error rate decreased", "HTTP 500 error rate returned toward baseline", "info"),
]


@app.get("/")
def root() -> dict[str, str]:
    return {"name": "ChroniX Demo Payment Service", "webhook_url": WEBHOOK_URL}


@app.post("/payment")
def payment(request: PaymentRequest) -> dict[str, object]:
    return {"status": "processed", "amount": request.amount, "currency": request.currency}


@app.post("/simulate-incident")
def simulate_incident() -> dict[str, object]:
    results = []
    try:
        with httpx.Client(timeout=10) as client:
            for index, (timestamp, event, raw_evidence, severity) in enumerate(EVENTS, start=1):
                payload = {
                    "source_type": "application",
                    "source_name": "ChroniX Demo Payment Service",
                    "source_id": f"demo-payment-{index:03d}",
                    "timestamp": timestamp,
                    "event": event,
                    "raw_evidence": raw_evidence,
                    "metadata": {"severity": severity, "service": "payment-api"},
                }
                response = client.post(WEBHOOK_URL, json=payload)
                response.raise_for_status()
                results.append(response.json())
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"ChroniX webhook delivery failed: {exc}") from exc
    return {"status": "sent", "events_sent": len(results), "results": results}
