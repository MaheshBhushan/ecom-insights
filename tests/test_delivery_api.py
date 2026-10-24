"""Offline delivery checks using committed reports and isolated receivers."""

import json
import shutil
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from src.delivery_api import create_app

ROOT = Path(__file__).resolve().parents[1]
AUTH = {"Authorization": "Bearer offline-test-token"}
HEADERS = {**AUTH, "Idempotency-Key": "sales-2026-10-19"}


@pytest.fixture
def setup(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    for name in ("kpis.json", "executive_briefing.json"):
        shutil.copyfile(ROOT / "reports" / name, reports / name)
    return {"report_dir": reports, "database_path": tmp_path / "deliveries.sqlite3",
            "token": "offline-test-token", "destinations": {
                "sales": "https://receiver.invalid/sales", "marketing": "https://receiver.invalid/marketing"}}


def test_validated_report_and_authentication(setup):
    with TestClient(create_app(**setup)) as client:
        for url in ("/briefings/sales", "/deliveries", "/deliveries/missing"):
            assert client.get(url).status_code == 401
        assert client.post("/deliveries/sales", headers={"Idempotency-Key": "x"}).status_code == 401
        for audience in ("sales", "marketing"):
            response = client.get(f"/briefings/{audience}", headers=AUTH)
            assert response.status_code == 200
            report = response.json()
            assert report["audience"] == audience
            assert report["briefing"] == json.loads((ROOT / "reports/executive_briefing.json").read_text())
            assert report["kpis"] == json.loads((ROOT / "reports/kpis.json").read_text())
            assert report["period_end"] in report["markdown"]
        assert client.get("/briefings/unknown", headers=AUTH).status_code == 422
        assert client.post("/deliveries/sales", headers=AUTH).status_code == 422
        assert client.post("/deliveries/sales", headers={**AUTH, "Idempotency-Key": "../bad"}).status_code == 422
        assert client.get("/deliveries/missing", headers=AUTH).status_code == 404


def test_success_is_deduplicated_across_restart_and_audiences(setup):
    calls = []

    def receiver(request):
        calls.append(request)
        return httpx.Response(204)

    setup["transport"] = httpx.MockTransport(receiver)
    with TestClient(create_app(**setup)) as client:
        first = client.post("/deliveries/sales", headers=HEADERS)
        assert first.status_code == 200
        assert first.json()["status"] == "delivered"
    # A restarted process with unavailable reports must still return the receipt.
    (setup["report_dir"] / "kpis.json").write_text("invalid")
    with TestClient(create_app(**setup)) as client:
        assert client.post("/deliveries/sales", headers=HEADERS).json() == first.json()
        assert client.post("/deliveries/marketing", headers=HEADERS).status_code == 409
        assert client.get("/deliveries?status=failed", headers=AUTH).json() == []
        assert client.get("/deliveries?status=delivered", headers=AUTH).json() == [first.json()]
    assert len(calls) == 1
    assert calls[0].headers["Idempotency-Key"] == HEADERS["Idempotency-Key"]
    assert json.loads(calls[0].content)["delivery_key"] == HEADERS["Idempotency-Key"]


@pytest.mark.parametrize("failure,expected", [
    (500, "webhook_http_500"), (302, "webhook_http_302"),
    ("timeout", "webhook_timeout"), ("connection", "webhook_connection_error"),
])
def test_failed_delivery_is_durable_and_retry_keeps_snapshot(setup, failure, expected):
    payloads = []

    def receiver(request):
        payloads.append(json.loads(request.content))
        if len(payloads) == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("secret URL must not be recorded", request=request)
            if failure == "connection":
                raise httpx.ConnectError("secret URL must not be recorded", request=request)
            return httpx.Response(failure, headers={"Location": "https://other.invalid"})
        return httpx.Response(200)

    setup["transport"] = httpx.MockTransport(receiver)
    with TestClient(create_app(**setup)) as client:
        result = client.post("/deliveries/sales", headers=HEADERS)
        assert result.status_code == 502
        failed = client.get("/deliveries?status=failed", headers=AUTH).json()[0]
        assert failed["last_error"] == expected
        assert failed["attempts"] == 1
    # Retry uses the pinned snapshot even if the source report changes or disappears.
    (setup["report_dir"] / "executive_briefing.json").write_text("{}")
    with TestClient(create_app(**setup)) as client:
        result = client.post("/deliveries/sales", headers=HEADERS)
        assert result.status_code == 200
        assert result.json()["attempts"] == 2
        assert result.json()["last_error"] is None
    assert payloads[0] == payloads[1]


@pytest.mark.parametrize("file,content", [
    ("executive_briefing.json", "{}"), ("executive_briefing.json", "not json"),
    ("kpis.json", '{"total_orders": 1, "total_orders": 2}'), ("kpis.json", "[]"),
])
def test_invalid_report_never_leaves_api_and_failure_is_recorded(setup, file, content):
    calls = []
    setup["transport"] = httpx.MockTransport(lambda request: calls.append(request))
    (setup["report_dir"] / file).write_text(content)
    with TestClient(create_app(**setup)) as client:
        assert client.get("/briefings/sales", headers=AUTH).status_code == 503
        assert client.post("/deliveries/sales", headers=HEADERS).status_code == 503
        row = client.get("/deliveries?status=failed", headers=AUTH).json()[0]
        assert row["last_error"] == "validated_report_unavailable"
        assert row["briefing_sha256"] is None
    assert calls == []


def test_missing_destination_and_changed_destination(setup):
    destinations = setup["destinations"]
    setup["destinations"] = {}
    with TestClient(create_app(**setup)) as client:
        assert client.post("/deliveries/sales", headers=HEADERS).status_code == 503
        assert client.get("/deliveries", headers=AUTH).json()[0]["last_error"] == "destination_not_configured"
    setup["destinations"] = destinations
    setup["transport"] = httpx.MockTransport(lambda request: httpx.Response(500))
    with TestClient(create_app(**setup)) as client:
        assert client.post("/deliveries/sales", headers=HEADERS).status_code == 502
    setup["destinations"] = {"sales": "https://different.invalid"}
    with TestClient(create_app(**setup)) as client:
        assert client.post("/deliveries/sales", headers=HEADERS).status_code == 409


def test_concurrent_calls_and_interrupted_delivery_recovery(setup):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def receiver(request):
        calls.append(request)
        entered.set()
        assert release.wait(3)
        return httpx.Response(204)

    setup["transport"] = httpx.MockTransport(receiver)
    with TestClient(create_app(**setup)) as client, ThreadPoolExecutor() as pool:
        pending = pool.submit(client.post, "/deliveries/sales", headers=HEADERS)
        try:
            assert entered.wait(3)
            assert client.post("/deliveries/sales", headers=HEADERS).status_code == 409
        finally:
            release.set()
        assert pending.result().status_code == 200
        assert len(calls) == 1
        # Simulate a process crash after a persisted claim.
        with sqlite3.connect(setup["database_path"]) as conn:
            conn.execute("UPDATE deliveries SET status='sending', lease_until=0")
        interrupted = client.get("/deliveries?status=failed", headers=AUTH).json()[0]
        assert interrupted["last_error"] == "delivery_interrupted"
        assert client.post("/deliveries/sales", headers=HEADERS).status_code == 200
        assert len(calls) == 2


def test_real_local_http_receiver_gets_both_audiences(setup):
    received = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, self.headers["Idempotency-Key"], payload))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    setup["destinations"] = {a: f"http://127.0.0.1:{server.server_port}/{a}" for a in ("sales", "marketing")}
    try:
        with TestClient(create_app(**setup)) as client:
            for audience in ("sales", "marketing"):
                headers = {**AUTH, "Idempotency-Key": f"{audience}-local"}
                assert client.post(f"/deliveries/{audience}", headers=headers).status_code == 200
        assert [r[0] for r in received] == ["/sales", "/marketing"]
        assert [r[2]["audience"] for r in received] == ["sales", "marketing"]
        assert all(key == payload["delivery_key"] for _, key, payload in received)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_startup_requires_token_and_valid_destination(setup):
    with pytest.raises(RuntimeError, match="BRIEFING_API_TOKEN"):
        create_app(**{**setup, "token": ""})
    with pytest.raises(ValueError, match="Webhook URLs"):
        create_app(**{**setup, "destinations": {"sales": "file:///tmp/no"}})
