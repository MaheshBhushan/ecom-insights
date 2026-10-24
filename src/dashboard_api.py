"""Read-only KPI endpoints over the star schema for the React dashboard.

Every filter is a bound parameter; the dashboard never sends SQL. Queries use
dim_date's year/month columns so they run unchanged on PostgreSQL and SQLite.
"""

import os
from datetime import date
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import bindparam, create_engine, text

MONTH = "d.year * 100 + d.month"


def label(month):
    month = int(month)
    return f"{month // 100}-{month % 100:02d}"


class Filters:
    def __init__(
        self,
        start: date | None = None,
        end: date | None = None,
        category: Annotated[list[str] | None, Query(max_length=50)] = None,
        country: Annotated[list[str] | None, Query(max_length=50)] = None,
        status: Annotated[list[str] | None, Query(max_length=20)] = None,
    ):
        if start and end and start > end:
            raise HTTPException(422, "start must not be after end")
        self.params, clauses, self.expanding = {}, [], []
        for name, column, value in (("start", "f.date_key >=", start), ("end", "f.date_key <=", end)):
            if value:
                clauses.append(f"{column} :{name}")
                self.params[name] = value.isoformat()
        for name, column, values in (("category", "p.category", category),
                                     ("country", "c.country", country),
                                     ("status", "f.order_status", status)):
            if values:
                clauses.append(f"{column} IN :{name}")
                self.params[name] = values
                self.expanding.append(name)
        self.where = " AND ".join(clauses) or "1 = 1"


BASE = """FROM fact_sales f
JOIN dim_date d ON d.date_key = f.date_key
JOIN dim_product p ON p.product_id = f.product_id
JOIN dim_customer c ON c.customer_id = f.customer_id"""


def create_app(*, database_url=None, allowed_origins=None):
    engine = create_engine(database_url or os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/ecommerce"))
    app = FastAPI(title="ecom-insights dashboard API")
    origins = allowed_origins if allowed_origins is not None else os.getenv("DASHBOARD_ORIGINS", "http://localhost:5173").split(",")
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"])

    def rows(sql, f: Filters, **extra):
        stmt = text(sql).bindparams(*(bindparam(n, expanding=True) for n in f.expanding))
        with engine.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(stmt, {**f.params, **extra})]

    @app.get("/api/dashboard/options")
    def options():
        with engine.connect() as conn:
            pick = lambda sql: [r[0] for r in conn.execute(text(sql)) if r[0] is not None]
            bounds = conn.execute(text("SELECT MIN(date_key), MAX(date_key) FROM fact_sales")).one()
            return {
                "categories": pick("SELECT DISTINCT category FROM dim_product ORDER BY 1"),
                "countries": pick("SELECT DISTINCT country FROM dim_customer ORDER BY 1"),
                "statuses": pick("SELECT DISTINCT order_status FROM fact_sales ORDER BY 1"),
                "min_date": str(bounds[0]) if bounds[0] else None,
                "max_date": str(bounds[1]) if bounds[1] else None,
            }

    @app.get("/api/dashboard/summary")
    def summary(f: Annotated[Filters, Depends()]):
        (row,) = rows(f"""SELECT COALESCE(SUM(f.net_revenue), 0) AS revenue,
            COUNT(DISTINCT f.order_id) AS orders,
            COUNT(DISTINCT f.customer_id) AS customers,
            COALESCE(SUM(f.quantity), 0) AS units {BASE} WHERE {f.where}""", f)
        orders = row["orders"]
        return {**{k: float(v) if k == "revenue" else int(v) for k, v in row.items()},
                "avg_order_value": round(float(row["revenue"]) / orders, 2) if orders else 0.0}

    @app.get("/api/dashboard/revenue")
    def revenue(f: Annotated[Filters, Depends()]):
        return [{"month": label(r["month"]), "revenue": round(float(r["revenue"]), 2),
                 "orders": int(r["orders"])}
                for r in rows(f"""SELECT {MONTH} AS month, SUM(f.net_revenue) AS revenue,
                    COUNT(DISTINCT f.order_id) AS orders {BASE} WHERE {f.where}
                    GROUP BY {MONTH} ORDER BY 1""", f)]

    @app.get("/api/dashboard/cohorts")
    def cohorts(f: Annotated[Filters, Depends()]):
        # Cohort = month of a customer's first order within the filtered scope.
        data = rows(f"""WITH scoped AS (SELECT f.customer_id, {MONTH} AS month {BASE} WHERE {f.where}),
            firsts AS (SELECT customer_id, MIN(month) AS cohort FROM scoped GROUP BY customer_id)
            SELECT fi.cohort, s.month, COUNT(DISTINCT s.customer_id) AS customers
            FROM scoped s JOIN firsts fi ON fi.customer_id = s.customer_id
            GROUP BY fi.cohort, s.month ORDER BY 1, 2""", f)
        index = lambda m: (int(m) // 100) * 12 + int(m) % 100
        out = {}
        for r in data:
            entry = out.setdefault(r["cohort"], {"cohort": label(r["cohort"]), "size": 0, "retention": []})
            offset = index(r["month"]) - index(r["cohort"])
            if offset == 0:
                entry["size"] = int(r["customers"])
            entry["retention"].append({"offset": offset, "customers": int(r["customers"]),
                                       "rate": round(int(r["customers"]) / entry["size"], 4) if entry["size"] else 0.0})
        return list(out.values())

    @app.get("/api/dashboard/orders")
    def orders(f: Annotated[Filters, Depends()], limit: Annotated[int, Query(ge=1, le=500)] = 50,
               offset: Annotated[int, Query(ge=0)] = 0):
        data = rows(f"""SELECT f.order_id, MIN(f.date_key) AS order_date, MIN(c.full_name) AS customer,
            MIN(c.country) AS country, MIN(f.order_status) AS status, SUM(f.quantity) AS items,
            SUM(f.net_revenue) AS revenue {BASE} WHERE {f.where}
            GROUP BY f.order_id ORDER BY order_date DESC, f.order_id DESC LIMIT :limit OFFSET :offset""",
                    f, limit=limit, offset=offset)
        return [{**r, "order_date": str(r["order_date"]), "items": int(r["items"]),
                 "revenue": round(float(r["revenue"]), 2)} for r in data]

    return app
