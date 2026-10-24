"""Dashboard API checks against the committed star-schema CSVs loaded into SQLite."""

import csv
import sqlite3
from collections import defaultdict
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.dashboard_api import create_app

PROCESSED = Path(__file__).resolve().parents[1] / "data" / "processed"
TABLES = ("dim_customer", "dim_product", "dim_date", "fact_sales")


def read(table):
    with open(PROCESSED / f"{table}.csv", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db = tmp_path_factory.mktemp("wh") / "warehouse.sqlite3"
    with sqlite3.connect(db) as conn:
        for table in TABLES:
            data = read(table)
            cols = list(data[0])
            types = {"year": " INTEGER", "month": " INTEGER", "quantity": " INTEGER", "net_revenue": " REAL"}
            conn.execute(f"CREATE TABLE {table} ({', '.join(c + types.get(c, '') for c in cols)})")
            conn.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(cols))})",
                             [[r[c] or None for c in cols] for r in data])
    return TestClient(create_app(database_url=f"sqlite:///{db}", allowed_origins=[]))


def test_summary_matches_fact_table(client):
    facts = read("fact_sales")
    body = client.get("/api/dashboard/summary").json()
    assert body["revenue"] == pytest.approx(sum(float(r["net_revenue"]) for r in facts))
    assert body["orders"] == len({r["order_id"] for r in facts})
    assert body["customers"] == len({r["customer_id"] for r in facts})


def test_filters_are_bound_and_combined(client):
    facts, products = read("fact_sales"), {r["product_id"]: r["category"] for r in read("dim_product")}
    category = sorted(set(products.values()))[0]
    start = "2025-09-01"
    expected = sum(float(r["net_revenue"]) for r in facts
                   if products[r["product_id"]] == category and r["date_key"] >= start)
    body = client.get("/api/dashboard/summary", params={"category": category, "start": start}).json()
    assert body["revenue"] == pytest.approx(expected)
    injected = client.get("/api/dashboard/summary", params={"category": "x' OR '1'='1"}).json()
    assert injected["orders"] == 0


def test_revenue_by_month_sums_to_total(client):
    months = client.get("/api/dashboard/revenue").json()
    total = client.get("/api/dashboard/summary").json()["revenue"]
    assert [m["month"] for m in months] == sorted(m["month"] for m in months)
    assert sum(m["revenue"] for m in months) == pytest.approx(total, abs=0.05)


def test_cohorts_start_at_full_retention(client):
    facts = read("fact_sales")
    first = defaultdict(lambda: "9999")
    for r in facts:
        first[r["customer_id"]] = min(first[r["customer_id"]], r["date_key"][:7])
    cohorts = client.get("/api/dashboard/cohorts").json()
    assert sum(c["size"] for c in cohorts) == len(first)
    for c in cohorts:
        assert c["retention"][0] == {"offset": 0, "customers": c["size"], "rate": 1.0}


def test_orders_paginate_and_validate(client):
    page = client.get("/api/dashboard/orders", params={"limit": 5}).json()
    assert len(page) == 5 and page[0]["order_date"] >= page[-1]["order_date"]
    assert client.get("/api/dashboard/orders", params={"limit": 0}).status_code == 422
    assert client.get("/api/dashboard/summary", params={"start": "2025-10-01", "end": "2025-09-01"}).status_code == 422
    opts = client.get("/api/dashboard/options").json()
    assert opts["categories"] and opts["min_date"] <= opts["max_date"]
