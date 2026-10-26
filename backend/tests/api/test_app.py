"""App factory, settings, CORS, and OpenAPI (tasks 1.2, 1.3, 5.3)."""

from pathlib import Path

from acme.settings import get_settings

ENDPOINTS = {
    ("post", "/api/invoices"), ("get", "/api/invoices"), ("get", "/api/invoices.csv"),
    ("get", "/api/invoices/{run_id}"), ("get", "/api/invoices/{run_id}/file"),
    ("post", "/api/invoices/{run_id}/review"), ("get", "/api/payments"), ("get", "/api/payments.csv"),
    ("get", "/api/payment-queue"), ("post", "/api/payment-queue/execute"), ("get", "/api/payment-batches"),
    ("get", "/api/stats"), ("get", "/api/events"),
}


def test_api_settings_defaults(monkeypatch):
    for name in ("UPLOAD_DIR", "PAYMENT_AUTO_IDLE"):
        monkeypatch.delenv(name)
    get_settings.cache_clear()
    s = get_settings()
    assert s.api_cors_origin == "http://localhost:4200"
    assert s.upload_dir == Path("uploads") and s.upload_max_bytes == 10 * 1024 * 1024
    assert s.allowed_upload_extensions == [".pdf", ".txt", ".csv", ".json", ".xml", ".eml"]
    assert s.worker_concurrency == 1 and s.payment_auto_idle is True


def test_cors_allows_the_angular_dev_server(client):
    response = client.get("/api/stats", headers={"Origin": "http://localhost:4200"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:4200"
    preflight = client.options("/api/invoices", headers={
        "Origin": "http://localhost:4200", "Access-Control-Request-Method": "POST"})
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:4200"


def test_cors_refuses_other_origins(client):
    response = client.get("/api/stats", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers
    preflight = client.options("/api/invoices", headers={
        "Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in preflight.headers


def test_openapi_lists_every_endpoint(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert ENDPOINTS <= {(method, path) for path, ops in paths.items() for method in ops}
    assert client.get("/docs").status_code == 200


def test_startup_seeds_an_empty_database(client, conn):
    assert conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] > 0
