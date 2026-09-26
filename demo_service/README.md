# ChroniX Demo Payment Service

A small external FastAPI service that sends realistic payment incident events to ChroniX over HTTP. It does not import ChroniX code or modify ChroniX state directly.

## Run

From the repository root:

```powershell
pip install -r demo_service\requirements.txt
uvicorn main:app --app-dir demo_service --port 9001
```

Set `CHRONIX_WEBHOOK_URL` to override the default `http://127.0.0.1:8001/api/v1/webhooks/events`.

## Demo

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:9001/payment -ContentType 'application/json' -Body '{"amount":25,"currency":"USD"}'
Invoke-RestMethod -Method Post http://127.0.0.1:9001/simulate-incident
```

The simulation sends seven separate HTTP POST requests to ChroniX.
