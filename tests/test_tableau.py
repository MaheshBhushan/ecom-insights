"""Execute the Tableau workbook SQL in disposable PostgreSQL and reconcile its totals."""

import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import pytest

from src.reporting.tableau_workbook import SHEETS, SOURCES, WORKBOOK, build, ds_id
from tests.test_powerbi import edge_tables, embedded_queries, sample_tables

ROOT = Path(__file__).resolve().parents[1]


def workbook_queries():
    tree = ET.parse(WORKBOOK)
    return {ds.get("caption"): ds.find("connection/relation").text
            for ds in tree.getroot().iter("datasource") if ds.find("connection") is not None}


def test_workbook_is_regenerated_and_bound():
    assert WORKBOOK.read_text() == build(), "Regenerate with python -m src.reporting.tableau_workbook"
    root = ET.parse(WORKBOOK).getroot()
    assert set(workbook_queries()) == set(SOURCES)
    for ds in root.find("datasources"):
        named = ds.find("connection/named-connections/named-connection/connection")
        assert named.get("class") == "postgres" and not named.get("password")
        assert {c.get("name") for c in ds.findall("column")} == \
            {f"[{name}]" for name in SOURCES[ds.get("caption")][1]}
    for sheet in root.iter("worksheet"):
        source = SHEETS[sheet.get("name")][0]
        text = " ".join(e.text or e.get("column", "") for e in sheet.iter()
                        if e.tag in {"rows", "cols"} or e.get("column"))
        for ref in text.replace(" / ", " ").split():
            assert ref.startswith(f"[{ds_id(source)}].[")
            assert ref.split(":")[1] in SOURCES[source][1]
    zones = {z.get("name") for z in root.iter("zone") if z.get("name")}
    assert zones == set(SHEETS)


@pytest.fixture(scope="module")
def results():
    cases = {"bundled": sample_tables(), "edge": edge_tables()}
    ddl = "\n".join(line for line in (ROOT / "sql/star_schema.postgres.sql").read_text().splitlines()
                    if not line.startswith("DROP TABLE"))
    queries = {**workbook_queries(), "KPIs": embedded_queries()["KPIs"]}
    script = []
    for case, tables in cases.items():
        script.extend(["BEGIN;", ddl])
        for name, frame in tables.items():
            script.extend([
                f"COPY public.{name} ({', '.join(frame.columns)}) FROM STDIN WITH (FORMAT CSV, HEADER TRUE);",
                frame.to_csv(index=False).rstrip(), "\\.",
            ])
        for name, sql in queries.items():
            script.append(
                f"SELECT jsonb_build_object('case', '{case}', 'table', '{name}', "
                f"'rows', coalesce(jsonb_agg(result), '[]'::jsonb)) FROM ({sql}) result;")
        script.append("ROLLBACK;")
    # Isolated, network-less database built from an already-installed image.
    run = subprocess.run([
        "docker", "run", "--rm", "-i", "--pull=never", "--network=none",
        "--user=postgres", "--tmpfs", "/tmp", "--entrypoint", "sh", "postgres:16-alpine", "-c",
        ("set -eu\n"
         "initdb -D /tmp/pgdata -A trust --no-locale >/dev/null\n"
         "pg_ctl -D /tmp/pgdata -o \"-c listen_addresses='' -c unix_socket_directories=/tmp\" "
         "-l /tmp/postgres.log start >/dev/null\n"
         "exec psql -h /tmp -U postgres -d postgres -qAt -v ON_ERROR_STOP=1"),
    ], input="\n".join(script) + "\n", text=True, capture_output=True, timeout=20, check=False)
    assert run.returncode == 0, run.stderr
    out = {case: {} for case in cases}
    for line in run.stdout.splitlines():
        row = json.loads(line)
        out[row["case"]][row["table"]] = row["rows"]
    return cases, out


@pytest.mark.parametrize("case", ["bundled", "edge"])
def test_visual_totals_reconcile_with_kpi_sql(results, case):
    cases, out = results
    kpi = out[case]["KPIs"][0]
    revenue = pd.DataFrame(out[case]["Revenue"])
    for column, metric in [("net_revenue", "net_revenue_total"), ("gross_revenue", "gross_revenue_total"),
                           ("discount_amount", "total_discount_amount"), ("cost", "total_cost"),
                           ("orders", "total_orders")]:
        assert revenue[column].sum() == pytest.approx(kpi[metric], abs=0.005 * len(revenue)), column
    cohorts = pd.DataFrame(out[case]["Cohorts"])
    assert cohorts["net_revenue"].sum() == pytest.approx(kpi["net_revenue_total"], abs=0.005 * len(cohorts))
    facts = cases[case]["fact_sales"]
    buyers = facts[facts["order_status"] != "Cancelled"]["customer_id"].nunique()
    assert cohorts.loc[cohorts["months_since_first"] == 0, "active_customers"].sum() == buyers
    assert (cohorts["months_since_first"] >= 0).all()
    # A customer active in a later month must have more than one revenue order.
    repeaters = buyers * kpi["repeat_customer_rate_pct"] / 100
    later = cohorts[cohorts["months_since_first"] > 0]
    assert later.groupby("months_since_first")["active_customers"].sum().max(skipna=True) <= repeaters + 0.5 \
        or later.empty
    if case == "bundled":
        expected = json.loads((ROOT / "reports/kpis.json").read_text())
        assert revenue["net_revenue"].sum() == pytest.approx(expected["net_revenue_total"], abs=0.5)
        assert revenue["orders"].sum() == expected["total_orders"]


@pytest.mark.parametrize("case", ["bundled", "edge"])
def test_missing_data_matches_source_frames(results, case):
    cases, out = results
    for row in out[case]["Missing Data"]:
        if row["table_name"] == "dim_date":
            facts = cases[case]["fact_sales"]
            days = pd.date_range(facts["date_key"].min(), facts["date_key"].max()).strftime("%Y-%m-%d")
            dates = set(cases[case]["dim_date"]["date_key"])
            in_range = [d for d in days if d in dates]
            assert row["total_rows"] == len(in_range)
            assert row["missing_rows"] == len(set(in_range) - set(facts["date_key"]))
            continue
        frame = cases[case][row["table_name"]]
        assert row["total_rows"] == len(frame)
        assert row["missing_rows"] == int(frame[row["column_name"]].isna().sum()), row
    edge = {r["column_name"]: r["missing_rows"] for r in out["edge"]["Missing Data"]}
    assert edge["order_status"] == 1
