"""Build the source-controlled Power BI project from its tested SQL queries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "powerbi"
REPORT = "EcomInsights.Report"
MODEL = "EcomInsights.SemanticModel"
SCHEMAS = "https://developer.microsoft.com/json-schemas/fabric"

MONEY = '$#,0.00;($#,0.00);$0.00'
PERCENT = '0.00"%"'
METRICS = {
    "net_revenue_total": ("Net revenue", MONEY),
    "total_orders": ("Revenue orders", "#,0"),
    "average_order_value_net": ("Net AOV", MONEY),
    "gross_margin_pct": ("Gross margin on net revenue", PERCENT),
    "cancelled_order_share_pct": ("Cancelled order share", PERCENT),
    "repeat_customer_rate_pct": ("Repeat customer rate", PERCENT),
    "gross_revenue_total": ("Gross revenue", MONEY),
    "total_discount_amount": ("Discounts", MONEY),
    "total_cost": ("Cost", MONEY),
    "total_customers": ("Customers (all statuses)", "#,0"),
    "cancelled_order_count": ("Cancelled orders", "#,0"),
    "top_category": ("Top category", None),
    "top_category_net_revenue": ("Top category net revenue", MONEY),
    "weakest_category": ("Weakest category", None),
    "weakest_category_net_revenue": ("Weakest category net revenue", MONEY),
    "period_start": ("Period start", "yyyy-MM-dd"),
    "period_end": ("Period end", "yyyy-MM-dd"),
    "included_statuses": ("Revenue statuses", None),
    "excluded_statuses": ("Excluded revenue statuses", None),
    "gross_margin_basis": ("Margin basis", None),
}
COUNTS = {"total_orders", "total_customers", "cancelled_order_count"}
DATES = {"period_start", "period_end", "month"}


def schema(kind: str, version: str = "1.0.0") -> str:
    return f"{SCHEMAS}/item/report/definition/{kind}/{version}/schema.json"


def m_string(value: str) -> str:
    return '"' + value.replace('"', '""').replace("\n", "#(lf)") + '"'


def import_table(name: str, query: str, fields: dict) -> dict:
    columns = []
    for field, fmt in fields.items():
        data_type = (
            "dateTime" if field in DATES else "int64" if field in COUNTS or field == "orders"
            else "string" if fmt is None else "decimal"
        )
        column = {"name": field, "dataType": data_type, "sourceColumn": field,
                  "summarizeBy": "none"}
        if fmt:
            column["formatString"] = fmt
        columns.append(column)
    return {
        "name": name,
        "columns": columns,
        "partitions": [{"name": name, "mode": "import", "source": {
            "type": "m", "expression": [
                "let",
                f"    Sql = {m_string(query)},",
                "    Source = PostgreSQL.Database(WarehouseServer, WarehouseDatabase,",
                "        [Query = Sql, CreateNavigationProperties = false])",
                "in Source",
            ],
        }}],
    }


def field(table: str, name: str, measure: bool = True) -> dict:
    return {"Measure" if measure else "Column": {
        "Expression": {"SourceRef": {"Entity": table}}, "Property": name,
    }}


def visual(name: str, kind: str, x: int, y: int, width: int, height: int,
           roles: dict, title: str) -> dict:
    return {
        "$schema": schema("visualContainer", "2.3.0"),
        "name": name,
        "position": {"x": x, "y": y, "z": 0, "height": height, "width": width, "tabOrder": 0},
        "visual": {
            "visualType": kind,
            "query": {"queryState": {
                role: {"projections": [
                    {"field": field(table, column, measure), "queryRef": f"{table}.{column}"}
                    for table, column, measure in values
                ]} for role, values in roles.items()
            }},
            "visualContainerObjects": {"title": [{"properties": {
                "show": {"expr": {"Literal": {"Value": "true"}}},
                "text": {"expr": {"Literal": {"Value": "'" + title.replace("'", "''") + "'"}}},
            }}]},
            "drillFilterOtherVisuals": True,
        },
    }


def project_files() -> dict[str, dict]:
    """Return deterministic project files; SQL is embedded for portable refresh."""
    queries = {p.stem: p.read_text(encoding="utf-8").strip()
               for p in (PROJECT / "queries").glob("*.sql")}
    kpi_fields = {key: fmt for key, (_, fmt) in METRICS.items()}
    kpis = import_table("KPIs", queries["kpis"], kpi_fields)
    kpis["measures"] = [
        {"name": label, "expression": f"SELECTEDVALUE(KPIs[{key}])",
         **({"formatString": fmt} if fmt else {})}
        for key, (label, fmt) in METRICS.items()
    ]
    rollup_fields = {"net_revenue": MONEY, "gross_revenue": MONEY, "orders": "#,0"}
    categories = import_table("Categories", queries["categories"], {"category": None, **rollup_fields})
    monthly = import_table("Monthly", queries["monthly"], {"month": "yyyy-MM", **rollup_fields})
    for table in (categories, monthly):
        table["measures"] = [{"name": "Net revenue", "expression": f"SUM({table['name']}[net_revenue])",
                              "formatString": MONEY}]

    definitions = f"{REPORT}/definition"
    files = {
        "EcomInsights.pbip": {
            "$schema": f"{SCHEMAS}/pbip/pbipProperties/1.0.0/schema.json",
            "version": "1.0", "artifacts": [{"report": {"path": REPORT}}],
            "settings": {"enableAutoRecovery": True},
        },
        f"{REPORT}/definition.pbir": {
            "$schema": f"{SCHEMAS}/item/report/definitionProperties/2.0.0/schema.json",
            "version": "4.0", "datasetReference": {"byPath": {"path": f"../{MODEL}"}},
        },
        f"{MODEL}/definition.pbism": {
            "$schema": f"{SCHEMAS}/item/semanticModel/definitionProperties/1.0.0/schema.json",
            "version": "1.0", "settings": {},
        },
        f"{MODEL}/model.bim": {
            "name": "EcomInsights", "compatibilityLevel": 1567,
            "model": {
                "culture": "en-US", "defaultPowerBIDataSourceVersion": "powerBI_V3",
                "sourceQueryCulture": "en-US",
                "expressions": [
                    {"name": key, "kind": "m", "expression":
                     f'{m_string(value)} meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'}
                    for key, value in (("WarehouseServer", "localhost:5433"),
                                       ("WarehouseDatabase", "ecommerce"))
                ],
                "tables": [kpis, categories, monthly],
            },
        },
        f"{definitions}/version.json": {"$schema": schema("versionMetadata"), "version": "2.0.0"},
        f"{definitions}/report.json": {"$schema": schema("report", "2.0.0"), "themeCollection": {
            "baseTheme": {"name": "CY24SU06", "reportVersionAtImport": "5.55", "type": "SharedResources"},
        }},
        f"{definitions}/pages/pages.json": {"$schema": schema("pagesMetadata"),
                                             "pageOrder": ["Overview", "KPIAudit"], "activePageName": "Overview"},
    }
    overview = []
    for index, (_, (label, _)) in enumerate(list(METRICS.items())[:6]):
        overview.append(visual(f"KPI{index}", "card", 20 + index * 210, 20, 200, 140,
                               {"Values": [("KPIs", label, True)]}, label))
    overview.extend([
        visual("MonthlyRevenue", "lineChart", 20, 180, 620, 370, {
            "Category": [("Monthly", "month", False)], "Y": [("Monthly", "Net revenue", True)],
        }, "Is net revenue growing by month?"),
        visual("CategoryRevenue", "clusteredBarChart", 660, 180, 620, 370, {
            "Category": [("Categories", "category", False)], "Y": [("Categories", "Net revenue", True)],
        }, "Which categories generate net revenue?"),
        visual("Scope", "multiRowCard", 20, 570, 1260, 140, {"Values": [
            ("KPIs", METRICS[key][0], True) for key in
            ("period_start", "period_end", "included_statuses", "excluded_statuses")
        ]}, "Full warehouse snapshot | Synthetic sample data | Repeat rate is a data-quality artifact"),
    ])
    overview[6]["visual"]["query"]["sortDefinition"] = {
        "sort": [{"field": field("Monthly", "month", False), "direction": "Ascending"}],
    }
    overview[7]["visual"]["query"]["sortDefinition"] = {
        "sort": [{"field": field("Categories", "Net revenue"), "direction": "Descending"}],
    }
    audit = [visual("AllKPIs", "multiRowCard", 20, 20, 1260, 690, {
        "Values": [("KPIs", label, True) for label, _ in METRICS.values()],
    }, "KPI audit | Revenue excludes Cancelled, shipping, and tax | Margin uses net revenue")]
    for name, title, visuals in (("Overview", "Revenue and customers", overview),
                                 ("KPIAudit", "KPI definitions and audit", audit)):
        base = f"{definitions}/pages/{name}"
        # Snapshot tables have different grains. Disable cross-filtering to keep
        # the cards and audit values comparable with the whole-warehouse KPIs.
        files[f"{base}/page.json"] = {
            "$schema": schema("page", "2.0.0"), "name": name, "displayName": title,
            "displayOption": "FitToPage", "width": 1300, "height": 730,
            "visualInteractions": [
                {"source": source["name"], "target": target["name"], "type": "NoFilter"}
                for source in visuals for target in visuals if source != target
            ],
        }
        for item in visuals:
            files[f"{base}/visuals/{item['name']}/visual.json"] = item
    return files


def write_project(output: Path = PROJECT) -> None:
    for relative, value in project_files().items():
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT)
    args = parser.parse_args()
    write_project(args.output)
    print(f"Wrote Power BI project to {args.output}")


if __name__ == "__main__":
    main()
