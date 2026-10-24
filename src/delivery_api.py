"""Serve validated briefing snapshots and persist retry-safe webhook deliveries."""

import hashlib
import hmac
import json
import os
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query

from src.config import PATHS
from src.insights.briefing import _render_markdown
from src.insights.comparison import (
    _read_json,
    check_consistency,
    fingerprint,
    validate_kpis,
)

Audience = Literal["sales", "marketing"]
Key = Annotated[str, Header(alias="Idempotency-Key", pattern=r"^[A-Za-z0-9._:-]{1,128}$")]


def load_briefing(report_dir, audience):
    """Use existing validation; never generate, refresh, or repair the report."""
    kpis = _read_json(report_dir / "kpis.json")
    briefing = _read_json(report_dir / "executive_briefing.json")
    validate_kpis(kpis)
    if not check_consistency(briefing, kpis)["passed"]:
        raise ValueError("Briefing failed grounding validation")
    return {
        "audience": audience,
        "kpi_sha256": fingerprint(kpis),
        "briefing_sha256": fingerprint(briefing),
        "period_start": kpis["period_start"], "period_end": kpis["period_end"],
        "kpis": kpis, "briefing": briefing,
        "markdown": _render_markdown(briefing, kpis),
    }


def create_app(*, report_dir=None, database_path=None, token=None, destinations=None, transport=None):
    """Factory used by uvicorn and offline tests. Production secrets come from env."""
    token = token if token is not None else os.getenv("BRIEFING_API_TOKEN", "")
    if not token:
        raise RuntimeError("BRIEFING_API_TOKEN is required")
    report_dir = Path(report_dir or PATHS["reports"])
    database_path = Path(database_path or os.getenv("DELIVERY_DB", "var/deliveries.sqlite3"))
    destinations = destinations if destinations is not None else {
        audience: os.getenv(f"{audience.upper()}_BRIEFING_WEBHOOK_URL", "")
        for audience in ("sales", "marketing")
    }
    for url in destinations.values():
        if url:
            parts = urlsplit(url)
            # Validate ports and characters before persisting a sending claim.
            httpx.URL(url)
            if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password:
                raise ValueError("Webhook URLs require HTTP(S), a host, and no userinfo")
    database_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect():
        with closing(sqlite3.connect(database_path, timeout=2)) as conn:
            conn.row_factory = sqlite3.Row
            with conn:
                yield conn

    with connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS deliveries (
            key TEXT PRIMARY KEY, audience TEXT NOT NULL, status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0, payload TEXT, destination_sha256 TEXT,
            last_error TEXT, lease_until REAL NOT NULL DEFAULT 0,
            created_at REAL NOT NULL, updated_at REAL NOT NULL
        )""")

    def authorize(authorization: Annotated[str | None, Header()] = None):
        expected = f"Bearer {token}".encode()
        if not authorization or not hmac.compare_digest(authorization.encode(), expected):
            raise HTTPException(401, "Invalid bearer token")

    def receipt(row):
        payload = json.loads(row["payload"]) if row["payload"] else {}
        return {**{name: row[name] for name in (
            "key", "audience", "status", "attempts", "last_error", "created_at", "updated_at"
        )}, "kpi_sha256": payload.get("kpi_sha256"),
            "briefing_sha256": payload.get("briefing_sha256")}

    def expire(conn):
        now = time.time()
        conn.execute("""UPDATE deliveries SET status='failed', last_error='delivery_interrupted',
            updated_at=? WHERE status='sending' AND lease_until <= ?""", (now, now))

    app = FastAPI(title="Ecom Insights briefing delivery", dependencies=[Depends(authorize)])

    @app.get("/briefings/{audience}")
    def get_briefing(audience: Audience):
        try:
            return load_briefing(report_dir, audience)
        except (OSError, ValueError, TypeError, KeyError):
            raise HTTPException(503, "Validated report unavailable") from None

    @app.get("/deliveries")
    def list_deliveries(status: Literal["failed", "delivered", "sending"] | None = None,
                        limit: Annotated[int, Query(ge=1, le=100)] = 100):
        with connect() as conn:
            expire(conn)
            rows = conn.execute("""SELECT * FROM deliveries WHERE (? IS NULL OR status=?)
                ORDER BY updated_at DESC LIMIT ?""", (status, status, limit)).fetchall()
        return [receipt(row) for row in rows]

    @app.get("/deliveries/{key}")
    def get_delivery(key: str):
        with connect() as conn:
            expire(conn)
            row = conn.execute("SELECT * FROM deliveries WHERE key=?", (key,)).fetchone()
        if row is None:
            raise HTTPException(404, "Delivery not found")
        return receipt(row)

    @app.post("/deliveries/{audience}")
    def deliver(audience: Audience, key: Key):
        destination = destinations.get(audience, "")
        destination_hash = hashlib.sha256(destination.encode()).hexdigest()
        error = None
        # ponytail: SQLite serializes claims on one node; use a server DB for multiple hosts.
        with connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            expire(conn)
            row = conn.execute("SELECT * FROM deliveries WHERE key=?", (key,)).fetchone()
            if row:
                if row["audience"] != audience:
                    raise HTTPException(409, "Key belongs to another audience")
                if row["status"] == "delivered":
                    return receipt(row)
                if row["status"] == "sending":
                    raise HTTPException(409, "Delivery in progress", headers={"Retry-After": "5"})
                if row["payload"] and row["destination_sha256"] != destination_hash:
                    raise HTTPException(409, "Destination changed; restore it before retrying this key")
            payload = json.loads(row["payload"]) if row and row["payload"] else None
            if not destination:
                error = "destination_not_configured"
            elif payload is None:
                try:
                    payload = load_briefing(report_dir, audience)
                    payload["delivery_key"] = key
                except (OSError, ValueError, TypeError, KeyError):
                    error = "validated_report_unavailable"
            now = time.time()
            conn.execute("""INSERT INTO deliveries
                (key, audience, status, created_at, updated_at) VALUES (?, ?, 'failed', ?, ?)
                ON CONFLICT(key) DO NOTHING""", (key, audience, now, now))
            conn.execute("""UPDATE deliveries SET status=?, attempts=attempts+1,
                payload=?, destination_sha256=?, last_error=?, lease_until=?, updated_at=? WHERE key=?""",
                ("failed" if error else "sending", json.dumps(payload) if payload else None,
                 destination_hash, error, now + 60, now, key))
            attempt = conn.execute("SELECT attempts FROM deliveries WHERE key=?", (key,)).fetchone()[0]
        if error:
            raise HTTPException(503, {"key": key, "status": "failed", "error": error})

        try:
            with (
                httpx.Client(transport=transport, timeout=10, follow_redirects=False, trust_env=False) as client,
                client.stream("POST", destination, json=payload, headers={"Idempotency-Key": key}) as response,
            ):
                if not 200 <= response.status_code < 300:
                    error = f"webhook_http_{response.status_code}"
        except httpx.TimeoutException:
            error = "webhook_timeout"
        except httpx.RequestError:
            error = "webhook_connection_error"
        with connect() as conn:
            conn.execute("""UPDATE deliveries SET status=?, last_error=?, lease_until=0,
                updated_at=? WHERE key=? AND attempts=? AND status='sending'""",
                ("failed" if error else "delivered", error, time.time(), key, attempt))
            row = conn.execute("SELECT * FROM deliveries WHERE key=?", (key,)).fetchone()
        if row["status"] == "sending":
            raise HTTPException(409, "Delivery in progress", headers={"Retry-After": "5"})
        if row["status"] == "failed":
            raise HTTPException(502, receipt(row))
        return receipt(row)

    return app
