import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

DEMO_MAIN = Path(__file__).parents[2] / "demo_service" / "main.py"
spec = importlib.util.spec_from_file_location("chronix_demo_main", DEMO_MAIN)
demo_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(demo_module)


@pytest.mark.parametrize("origin", ["http://127.0.0.1:5173", "http://localhost:5177"])
def test_demo_endpoint_allows_local_vite_browser_preflight(origin):
    client = TestClient(demo_module.app)

    response = client.options(
        "/simulate-incident",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "POST" in response.headers["access-control-allow-methods"]
