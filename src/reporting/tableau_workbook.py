"""Build the source-controlled Tableau workbook from its tested SQL queries."""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "tableau"
WORKBOOK = PROJECT / "EcomInsights.twb"
SERVER, PORT, DATABASE = "localhost", "5433", "ecommerce"

# Data source name -> (query file, {column: (datatype, role, type)})
SOURCES = {
    "Revenue": ("revenue_monthly.sql", {
        "month": ("date", "dimension", "ordinal"),
        "gross_revenue": ("real", "measure", "quantitative"),
        "discount_amount": ("real", "measure", "quantitative"),
        "net_revenue": ("real", "measure", "quantitative"),
        "cost": ("real", "measure", "quantitative"),
        "orders": ("integer", "measure", "quantitative"),
    }),
    "Cohorts": ("cohorts.sql", {
        "cohort_month": ("date", "dimension", "ordinal"),
        "months_since_first": ("integer", "dimension", "ordinal"),
        "active_customers": ("integer", "measure", "quantitative"),
        "net_revenue": ("real", "measure", "quantitative"),
    }),
    "Missing Data": ("missing_data.sql", {
        "table_name": ("string", "dimension", "nominal"),
        "column_name": ("string", "dimension", "nominal"),
        "total_rows": ("integer", "measure", "quantitative"),
        "missing_rows": ("integer", "measure", "quantitative"),
    }),
}

# Worksheet -> (source, rows, columns, mark, extra encodings)
SHEETS = {
    "Monthly net revenue": ("Revenue", "sum:net_revenue", "tmn:month", "Line", {}),
    "Cohort activity": ("Cohorts", "tmn:cohort_month", "none:months_since_first", "Square",
                        {"color": "sum:active_customers", "text": "sum:active_customers"}),
    "Missing values": ("Missing Data", "none:table_name none:column_name", "sum:missing_rows",
                       "Bar", {"text": "sum:missing_rows"}),
}


def query(source: str) -> str:
    return (PROJECT / "queries" / SOURCES[source][0]).read_text().strip()


def ds_id(source: str) -> str:
    return "postgres." + source.lower().replace(" ", "_")


def field(source: str, token: str) -> str:
    derivation, name = token.split(":")
    kind = "qk" if derivation == "sum" else "ok"
    return f"[{ds_id(source)}].[{derivation}:{name}:{kind}]"


def shelf(source: str, spec: str) -> str:
    return " / ".join(field(source, token) for token in spec.split())


def datasource(parent: ET.Element, source: str) -> None:
    ds = ET.SubElement(parent, "datasource", caption=source, inline="true",
                       name=ds_id(source), version="18.1")
    conn = ET.SubElement(ds, "connection", {"class": "federated"})
    named = ET.SubElement(ET.SubElement(conn, "named-connections"), "named-connection",
                          caption=f"{SERVER}:{PORT}/{DATABASE}", name="warehouse")
    ET.SubElement(named, "connection", {
        "class": "postgres", "server": SERVER, "port": PORT, "dbname": DATABASE,
        "authentication": "username-password", "username": "", "sslmode": "",
        "one-time-sql": "",
    })
    relation = ET.SubElement(conn, "relation", connection="warehouse", name=source,
                             type="text")
    relation.text = query(source)
    for name, (datatype, role, kind) in SOURCES[source][1].items():
        ET.SubElement(ds, "column", datatype=datatype, name=f"[{name}]", role=role, type=kind)


def worksheet(parent: ET.Element, name: str) -> None:
    source, rows, cols, mark, encodings = SHEETS[name]
    table = ET.SubElement(ET.SubElement(parent, "worksheet", name=name), "table")
    view = ET.SubElement(table, "view")
    ET.SubElement(view, "datasources").append(
        ET.Element("datasource", caption=source, name=ds_id(source)))
    ET.SubElement(view, "aggregation", value="true")
    pane = ET.SubElement(ET.SubElement(table, "panes"), "pane")
    ET.SubElement(pane, "mark", {"class": mark})
    if encodings:
        enc = ET.SubElement(pane, "encodings")
        for kind, token in encodings.items():
            ET.SubElement(enc, kind, column=field(source, token))
    ET.SubElement(table, "rows").text = shelf(source, rows)
    ET.SubElement(table, "cols").text = shelf(source, cols)


def build() -> str:
    workbook = ET.Element("workbook", {"source-build": "2024.2.0", "source-platform": "linux",
                                       "version": "18.1"})
    sources = ET.SubElement(workbook, "datasources")
    for source in SOURCES:
        datasource(sources, source)
    sheets = ET.SubElement(workbook, "worksheets")
    for name in SHEETS:
        worksheet(sheets, name)
    dashboard = ET.SubElement(ET.SubElement(workbook, "dashboards"), "dashboard",
                              name="Warehouse validation")
    ET.SubElement(dashboard, "size", maxheight="800", maxwidth="1200",
                  minheight="800", minwidth="1200")
    zones = ET.SubElement(ET.SubElement(dashboard, "zones"), "zone", id="1", type="layout-basic",
                          x="0", y="0", w="100000", h="100000")
    for i, (name, (x, y, w, h)) in enumerate(zip(SHEETS, [
            (0, 0, 100000, 40000), (0, 40000, 60000, 60000), (60000, 40000, 40000, 60000)]), 2):
        ET.SubElement(zones, "zone", id=str(i), name=name, x=str(x), y=str(y),
                      w=str(w), h=str(h))
    ET.indent(workbook)
    return "<?xml version='1.0' encoding='utf-8' ?>\n" + ET.tostring(workbook, "unicode") + "\n"


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    WORKBOOK.write_text(build())
    print(WORKBOOK)


if __name__ == "__main__":
    main()
