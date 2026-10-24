"""Execute the imported report SQL in disposable PostgreSQL and reconcile KPIs."""

import json
import subprocess
from pathlib import Path

import pandas as pd
import pytest
from jsonschema import Draft7Validator
from referencing import Registry, Resource

from src.insights import kpis
from src.reporting.powerbi_project import METRICS, MODEL, PROJECT, REPORT, project_files

ROOT = Path(__file__).resolve().parents[1]


def embedded_queries():
    model = json.loads((PROJECT / MODEL / "model.bim").read_text())["model"]
    queries = {}
    for table in model["tables"]:
        expression = table["partitions"][0]["source"]["expression"]
        literal = next(line for line in expression if line.startswith("    Sql = "))
        queries[table["name"]] = literal[len('    Sql = "'):-2].replace('""', '"').replace("#(lf)", "\n")
    return queries


def test_project_schema_bindings_and_regeneration():
    schemas = json.loads((ROOT / "tests/schemas/powerbi.json").read_text())
    registry = Registry().with_resources(
        (url, Resource.from_contents(value)) for url, value in schemas.items()
    )
    expected = project_files()
    actual_paths = {
        str(p.relative_to(PROJECT)) for p in PROJECT.rglob("*")
        if p.suffix in {".json", ".bim", ".pbip", ".pbir", ".pbism"}
        and ".pbi" not in p.parts
    }
    assert actual_paths == set(expected)
    for relative, value in expected.items():
        actual = json.loads((PROJECT / relative).read_text())
        assert actual == value, f"Regenerate {relative}"
        if "$schema" in actual:
            Draft7Validator(schemas[actual["$schema"]], registry=registry).validate(actual)

    model = expected[f"{MODEL}/model.bim"]["model"]
    tables = {t["name"]: t for t in model["tables"]}
    assert not model.get("relationships")
    assert {c["name"] for c in tables["KPIs"]["columns"]} == set(METRICS)
    for table in tables.values():
        assert table["partitions"][0]["mode"] == "import"
        source = "\n".join(table["partitions"][0]["source"]["expression"])
        assert "PostgreSQL.Database(WarehouseServer, WarehouseDatabase," in source
        assert "[Query = Sql, CreateNavigationProperties = false]" in source
        for measure in table["measures"]:
            if table["name"] == "KPIs":
                key = next(k for k, (label, _) in METRICS.items() if label == measure["name"])
                assert measure["expression"] == f"SELECTEDVALUE(KPIs[{key}])"
            else:
                assert measure["expression"] == f"SUM({table['name']}[net_revenue])"
    bound_metrics = set()
    for relative, visual in expected.items():
        if not relative.endswith("visual.json"):
            continue
        position = visual["position"]
        assert 0 <= position["x"] < position["x"] + position["width"] <= 1300
        assert 0 <= position["y"] < position["y"] + position["height"] <= 730
        for role in visual["visual"]["query"]["queryState"].values():
            for projection in role["projections"]:
                kind, ref = next(iter(projection["field"].items()))
                table = ref["Expression"]["SourceRef"]["Entity"]
                members = tables[table]["measures" if kind == "Measure" else "columns"]
                assert ref["Property"] in {member["name"] for member in members}
                if table == "KPIs":
                    bound_metrics.add(ref["Property"])
    assert bound_metrics == {label for label, _ in METRICS.values()}
    for relative, page in expected.items():
        if relative.endswith("/page.json"):
            assert all(i["type"] == "NoFilter" for i in page["visualInteractions"])
    assert expected[f"{REPORT}/definition.pbir"]["datasetReference"]["byPath"]["path"] == f"../{MODEL}"


def sample_tables():
    return {name: pd.read_csv(ROOT / "data/processed" / f"{name}.csv")
            for name in ("dim_customer", "dim_product", "dim_date", "fact_sales")}


def edge_tables():
    tables = sample_tables()
    facts = tables["fact_sales"].iloc[:6].copy().reset_index(drop=True)
    customers = tables["dim_customer"]["customer_id"].iloc[:3].tolist()
    products = tables["dim_product"]["product_id"].iloc[:2].tolist()
    facts["item_id"] = [f"TEST{i}" for i in range(6)]
    facts["order_id"] = ["A", "A", "B", "C", "D", "D"]
    facts["customer_id"] = [customers[i] for i in (0, 0, 0, 1, 2, 2)]
    facts["product_id"] = [products[i] for i in (0, 1, 0, 0, 0, 1)]
    facts["date_key"] = tables["dim_date"]["date_key"].iloc[0]
    facts["order_status"] = ["Completed", "Completed", None, "Shipped", "Cancelled", "Cancelled"]
    facts["quantity"] = 1
    facts["unit_price"] = 10
    facts["gross_revenue"] = 10
    facts["discount_rate"] = 0.1
    facts["discount_amount"] = 1
    facts["net_revenue"] = 9
    facts["cost"] = 5
    tables["fact_sales"] = facts
    return tables


@pytest.fixture(scope="module")
def report_results():
    """One isolated PG run covers all fixtures without ports or host credentials."""
    bundled = sample_tables()
    edge = edge_tables()
    zero = {key: frame.copy() for key, frame in edge.items()}
    zero["fact_sales"]["net_revenue"] = 0
    zero["fact_sales"]["discount_amount"] = zero["fact_sales"]["gross_revenue"]
    cancelled = {key: frame.copy() for key, frame in edge.items()}
    cancelled["fact_sales"]["order_status"] = "Cancelled"
    empty = {**edge, "fact_sales": edge["fact_sales"].iloc[:0]}
    cases = {"bundled": bundled, "edge": edge, "zero": zero, "cancelled": cancelled, "empty": empty}
    # The production DDL drops tables. Only CREATE statements go into this new,
    # network-isolated test database. No existing warehouse is accessed.
    ddl = "\n".join(line for line in (ROOT / "sql/star_schema.postgres.sql").read_text().splitlines()
                    if not line.startswith("DROP TABLE"))
    script = []
    for case, tables in cases.items():
        script.extend(["BEGIN;", ddl])
        for name, frame in tables.items():
            script.extend([
                f"COPY public.{name} ({', '.join(frame.columns)}) FROM STDIN WITH (FORMAT CSV, HEADER TRUE);",
                frame.to_csv(index=False).rstrip(), "\\.",
            ])
        for name, query in embedded_queries().items():
            script.append(
                f"SELECT jsonb_build_object('case', '{case}', 'table', '{name}', "
                f"'rows', coalesce(jsonb_agg(result), '[]'::jsonb)) FROM ({query}) result;"
            )
        script.append("ROLLBACK;")
    # Docker uses an already-installed image. tmpfs holds only fixture data;
    # --network none prevents any connection to production or other containers.
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
    results = {case: {} for case in cases}
    for line in run.stdout.splitlines():
        result = json.loads(line)
        results[result["case"]][result["table"]] = result["rows"]
    return cases, results


def assert_reconciled(actual, expected):
    flattened = {
        **{key: value for key, value in expected.items() if key in METRICS},
        "top_category": expected["top_category"]["category"],
        "top_category_net_revenue": expected["top_category"]["net_revenue"],
        "weakest_category": expected["weakest_category"]["category"],
        "weakest_category_net_revenue": expected["weakest_category"]["net_revenue"],
        "included_statuses": ", ".join(expected["order_statuses_included_in_revenue"]),
        "excluded_statuses": ", ".join(expected["order_statuses_excluded_from_revenue"]),
    }
    assert set(actual) == set(flattened) == set(METRICS)
    for key, value in flattened.items():
        if isinstance(value, (int, float)):
            assert actual[key] == pytest.approx(value, rel=0, abs=0.005), key
        else:
            assert actual[key] == value, key


@pytest.mark.parametrize("case", ["bundled", "edge", "zero"])
def test_report_sql_matches_existing_kpi_computation(report_results, monkeypatch, case):
    cases, results = report_results
    tables = cases[case]
    joined = tables["fact_sales"].merge(tables["dim_product"][["product_id", "category"]],
                                        on="product_id", validate="many_to_one")
    monkeypatch.setattr(kpis, "get_db_connection", lambda: None)
    # The old computation sorts its status list without a NULL guard. A
    # sentinel preserves its numeric inclusion rules while allowing sorting.
    # SQL still executes against the original NULL and omits it from the list.
    expected_frame = joined.copy()
    if case == "edge" or case == "zero":
        expected_frame["order_status"] = expected_frame["order_status"].fillna("Unknown")
    monkeypatch.setattr(kpis, "_load_fact_sales", lambda engine: expected_frame)
    expected = kpis.compute_kpis()
    if case in {"edge", "zero"}:
        expected["order_statuses_included_in_revenue"].remove("Unknown")
    actual = results[case]["KPIs"][0]
    assert_reconciled(actual, expected)
    if case == "bundled":
        assert_reconciled(actual, json.loads((ROOT / "reports/kpis.json").read_text()))
    if case == "edge":
        assert actual["total_orders"] == 3  # four revenue lines, three orders
        assert actual["total_customers"] == 3  # includes the cancelled-only customer
        assert actual["repeat_customer_rate_pct"] == 50
        assert actual["cancelled_order_count"] == 1  # two cancelled lines
        assert actual["cancelled_order_share_pct"] == 25
    for chart in ("Categories", "Monthly"):
        for metric in ("net_revenue", "gross_revenue"):
            assert sum(row[metric] for row in results[case][chart]) == pytest.approx(
                actual[f"{metric}_total"], rel=0, abs=0.005)


@pytest.mark.parametrize("case", ["cancelled", "empty"])
def test_empty_revenue_has_no_fabricated_rates(report_results, case):
    _, results = report_results
    actual = results[case]["KPIs"][0]
    assert actual["total_orders"] == 0
    assert actual["gross_revenue_total"] == actual["net_revenue_total"] == actual["total_cost"] == 0
    for metric in ("average_order_value_net", "gross_margin_pct", "repeat_customer_rate_pct",
                   "top_category", "weakest_category"):
        assert actual[metric] is None
    assert results[case]["Categories"] == results[case]["Monthly"] == []
    assert actual["cancelled_order_share_pct"] == (100 if case == "cancelled" else None)
