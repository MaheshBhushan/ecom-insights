"""Generate management-ready Excel and PowerPoint reports.

This module deliberately contains presentation logic only. Business metrics
come from the validated JSON and CSV artifacts produced by the pipeline.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from src.config import PATHS

PROJECT_NAME = "Ecom Insights"
DEFAULT_XLSX = "ecom_insights_analysis.xlsx"
DEFAULT_PPTX = "ecom_insights_management_briefing.pptx"

NAVY = "17324D"
BLUE = "1F77B4"
TEAL = "2A9D8F"
GREEN = "3A7D44"
AMBER = "E9A23B"
RED = "C84A4A"
INK = "24323F"
MUTED = "667788"
PALE = "EAF2F8"
LIGHT = "F5F7FA"
WHITE = "FFFFFF"

REQUIRED_CSVS = {
    "sales_trends": "sales_trends.csv",
    "product_performance": "product_performance.csv",
    "category_performance": "category_performance.csv",
    "segment_profiles": "segment_profiles.csv",
    "retention_matrix": "retention_matrix.csv",
    "fact_sales": "fact_sales.csv",
    "dim_product": "dim_product.csv",
}


class ReportInputError(RuntimeError):
    """Raised when a required reporting input is missing or malformed."""


@dataclass(frozen=True)
class ReportData:
    kpis: dict[str, Any]
    briefing: dict[str, Any] | None
    frames: dict[str, pd.DataFrame]


def _read_json(path: Path, required: bool = True) -> dict[str, Any] | None:
    if not path.exists():
        if required:
            raise ReportInputError(f"Required reporting input is missing: {path}")
        return None
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportInputError(f"Could not read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReportInputError(f"Expected a JSON object in {path}")
    return value


def load_report_data(
    processed_dir: Path | None = None, reports_dir: Path | None = None
) -> ReportData:
    """Load and validate the artifacts used by both Office outputs."""
    processed_dir = processed_dir or Path(PATHS["processed_data"])
    reports_dir = reports_dir or Path(PATHS["reports"])
    kpis = _read_json(reports_dir / "kpis.json")
    required_kpis = {
        "period_start",
        "period_end",
        "total_orders",
        "total_customers",
        "gross_revenue_total",
        "net_revenue_total",
        "total_discount_amount",
        "average_order_value_net",
        "gross_margin_pct",
        "repeat_customer_rate_pct",
        "cancelled_order_count",
        "cancelled_order_share_pct",
        "top_category",
        "weakest_category",
    }
    missing_kpis = required_kpis - set(kpis or {})
    if missing_kpis:
        raise ReportInputError(f"kpis.json is missing fields: {sorted(missing_kpis)}")

    frames: dict[str, pd.DataFrame] = {}
    for key, filename in REQUIRED_CSVS.items():
        path = processed_dir / filename
        if not path.exists():
            raise ReportInputError(f"Required reporting input is missing: {path}")
        try:
            frame = pd.read_csv(path)
        except Exception as exc:
            raise ReportInputError(f"Could not read {path}: {exc}") from exc
        if frame.empty:
            raise ReportInputError(f"Required reporting input is empty: {path}")
        frames[key] = frame

    expected_columns = {
        "sales_trends": {"period", "order_count", "total_revenue", "unique_customers"},
        "product_performance": {
            "product_name",
            "category",
            "total_revenue",
            "order_count",
        },
        "category_performance": {"category", "total_revenue", "order_count"},
        "segment_profiles": {
            "segment",
            "customer_count",
            "avg_total_spend",
            "avg_order_value",
        },
        "fact_sales": {"product_id", "order_status", "gross_revenue", "net_revenue"},
        "dim_product": {"product_id", "category"},
    }
    for key, columns in expected_columns.items():
        missing = columns - set(frames[key].columns)
        if missing:
            raise ReportInputError(
                f"{REQUIRED_CSVS[key]} is missing columns: {sorted(missing)}"
            )

    frames["sales_trends"]["period"] = pd.to_datetime(frames["sales_trends"]["period"])
    briefing = _read_json(reports_dir / "executive_briefing.json", required=False)
    return ReportData(kpis=kpis or {}, briefing=briefing, frames=frames)


def _net_category_performance(data: ReportData) -> pd.DataFrame:
    """Build a clearly labelled net-revenue category view from warehouse outputs."""
    fact = data.frames["fact_sales"]
    products = data.frames["dim_product"][["product_id", "category"]]
    included = ~fact["order_status"].isin(
        data.kpis.get("order_statuses_excluded_from_revenue", ["Cancelled"])
    )
    merged = fact.loc[included].merge(
        products, on="product_id", how="left", validate="many_to_one"
    )
    return (
        merged.groupby("category", as_index=False)
        .agg(net_revenue=("net_revenue", "sum"), gross_revenue=("gross_revenue", "sum"))
        .sort_values("net_revenue", ascending=False)
        .reset_index(drop=True)
    )


def _flatten_briefing(data: ReportData) -> tuple[str, list[str], list[str]]:
    if data.briefing:
        summary = str(data.briefing.get("summary", ""))
        risks = [str(item) for item in data.briefing.get("risks", [])]
        recommendations = [
            str(item.get("text", ""))
            for item in data.briefing.get("recommendations", [])
            if isinstance(item, dict)
        ]
        return summary, risks, recommendations
    k = data.kpis
    summary = (
        f"Net revenue was ${k['net_revenue_total']:,.2f} across {k['total_orders']:,} orders, "
        f"with a {k['gross_margin_pct']:.2f}% gross margin."
    )
    risks = [
        f"Cancelled orders represent {k['cancelled_order_share_pct']:.2f}% of all orders.",
        "Customer retention results come from synthetic sample data and should not guide real investment decisions.",
    ]
    recommendations = [
        "Investigate cancellation drivers before increasing acquisition spend.",
        "Review discounting and category mix against the net-revenue margin baseline.",
        "Validate customer behavior on production data before acting on retention metrics.",
    ]
    return summary, risks, recommendations


def _safe_excel_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if hasattr(value, "item"):
        return value.item()
    return value


def _style_sheet(ws, widths: dict[str, float] | None = None) -> None:
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A4"
    ws.auto_filter.ref = ws.dimensions
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.page_layout = "landscape"
    for key, width in (widths or {}).items():
        ws.column_dimensions[key].width = width


def _add_title(ws, title: str, subtitle: str, columns: int) -> None:
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=columns)
    cell = ws.cell(1, 1, title)
    cell.font = Font(name="Aptos Display", size=22, bold=True, color=WHITE)
    cell.fill = PatternFill("solid", fgColor=NAVY)
    cell.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 34
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=columns)
    ws.cell(2, 1, subtitle).font = Font(name="Aptos", size=10, italic=True, color=MUTED)
    ws.row_dimensions[2].height = 22


def _write_frame(
    ws, frame: pd.DataFrame, start_row: int = 4, table_name: str | None = None
) -> None:
    for col, name in enumerate(frame.columns, 1):
        cell = ws.cell(start_row, col, str(name).replace("_", " ").title())
        cell.font = Font(name="Aptos", bold=True, color=WHITE)
        cell.fill = PatternFill("solid", fgColor=BLUE)
        cell.alignment = Alignment(
            horizontal="center", vertical="center", wrap_text=True
        )
    for row, values in enumerate(
        frame.itertuples(index=False, name=None), start_row + 1
    ):
        for col, value in enumerate(values, 1):
            cell = ws.cell(row, col, _safe_excel_value(value))
            cell.font = Font(name="Aptos", size=10, color=INK)
            cell.fill = PatternFill("solid", fgColor=WHITE if row % 2 else LIGHT)
            if isinstance(cell.value, datetime):
                cell.number_format = "mmm yyyy"
            elif isinstance(cell.value, float):
                cell.number_format = "#,##0.00"
    if table_name:
        end_row = start_row + len(frame)
        end_col = len(frame.columns)
        table = Table(
            displayName=table_name,
            ref=f"A{start_row}:{get_column_letter(end_col)}{end_row}",
        )
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2",
            showRowStripes=True,
            showFirstColumn=False,
            showLastColumn=False,
        )
        ws.add_table(table)


def build_excel_report(data: ReportData, output_path: Path) -> Path:
    """Create a formatted, auditable Excel management workbook."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    wb.properties.title = f"{PROJECT_NAME} Analysis Workbook"
    wb.properties.subject = (
        "Management analysis generated from validated pipeline outputs"
    )
    wb.properties.creator = PROJECT_NAME
    k = data.kpis
    summary, risks, recommendations = _flatten_briefing(data)

    ws = wb.create_sheet("Executive Summary")
    _add_title(
        ws,
        "E-Commerce Performance at a Glance",
        f"Reporting period: {k['period_start']} to {k['period_end']}",
        12,
    )
    cards = [
        ("Net Revenue", k["net_revenue_total"], '"$"#,##0.00', TEAL),
        ("Orders", k["total_orders"], "#,##0", BLUE),
        ("Net AOV", k["average_order_value_net"], '"$"#,##0.00', NAVY),
        ("Gross Margin", k["gross_margin_pct"] / 100, "0.00%", GREEN),
        ("Discounts", k["total_discount_amount"], '"$"#,##0.00', AMBER),
        ("Cancelled Share", k["cancelled_order_share_pct"] / 100, "0.00%", RED),
    ]
    for index, (label, value, number_format, color) in enumerate(cards):
        col = 1 + (index % 3) * 4
        row = 4 + (index // 3) * 3
        ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + 2)
        ws.merge_cells(
            start_row=row + 1, start_column=col, end_row=row + 1, end_column=col + 2
        )
        ws.cell(row, col, label).font = Font(
            name="Aptos", size=10, bold=True, color=MUTED
        )
        ws.cell(row + 1, col, value).font = Font(
            name="Aptos Display", size=22, bold=True, color=color
        )
        ws.cell(row + 1, col).number_format = number_format
        for r in (row, row + 1):
            for c in range(col, col + 3):
                ws.cell(r, c).fill = PatternFill("solid", fgColor=LIGHT)
    ws["A11"] = "Management Summary"
    ws["A11"].font = Font(name="Aptos Display", size=15, bold=True, color=NAVY)
    ws.merge_cells("A12:L14")
    ws["A12"] = summary
    ws["A12"].alignment = Alignment(wrap_text=True, vertical="top")
    ws["A12"].font = Font(name="Aptos", size=11, color=INK)
    ws["A16"] = "Risks"
    ws["G16"] = "Recommended Actions"
    for address in ("A16", "G16"):
        ws[address].font = Font(name="Aptos Display", size=15, bold=True, color=NAVY)
    for idx, risk in enumerate(risks[:4], 17):
        ws.merge_cells(start_row=idx, start_column=1, end_row=idx, end_column=5)
        ws.cell(idx, 1, f"• {risk}").alignment = Alignment(
            wrap_text=True, vertical="top"
        )
        ws.row_dimensions[idx].height = 42
    for idx, recommendation in enumerate(recommendations[:4], 17):
        ws.merge_cells(start_row=idx, start_column=7, end_row=idx, end_column=12)
        ws.cell(idx, 7, f"• {recommendation}").alignment = Alignment(
            wrap_text=True, vertical="top"
        )
    ws.merge_cells("A23:L24")
    ws["A23"] = (
        "Data caution: the bundled dataset is synthetic. The reported 100% repeat-customer rate is a generator artifact and must not be treated as a real retention signal."
    )
    ws["A23"].fill = PatternFill("solid", fgColor="FFF2CC")
    ws["A23"].font = Font(name="Aptos", bold=True, color="7F6000")
    ws["A23"].alignment = Alignment(wrap_text=True, vertical="center")
    _style_sheet(ws, {get_column_letter(i): 13 for i in range(1, 13)})
    ws.freeze_panes = "A4"

    trends = data.frames["sales_trends"].copy()
    trend_columns = [
        "period",
        "order_count",
        "total_revenue",
        "unique_customers",
        "revenue_growth",
        "order_growth",
        "revenue_ma",
        "order_ma",
    ]
    trends = trends[
        [column for column in trend_columns if column in trends.columns]
    ].rename(columns={"total_revenue": "gross_revenue"})
    ws = wb.create_sheet("Sales Trends")
    _add_title(
        ws,
        "Sales Trends",
        "Gross revenue excludes Cancelled orders; growth values are period-over-period.",
        len(trends.columns),
    )
    _write_frame(ws, trends, table_name="SalesTrendsTable")
    for cell in ws["C"][4:]:
        cell.number_format = '"$"#,##0.00'
    for header in ("revenue_growth", "order_growth"):
        if header in trends.columns:
            col = trends.columns.get_loc(header) + 1
            for row in range(5, 5 + len(trends)):
                ws.cell(row, col).number_format = "0.0%"
    line = LineChart()
    line.title = "Gross Revenue Trend"
    line.y_axis.title = "Gross revenue ($)"
    line.height, line.width = 8, 15
    line.add_data(
        Reference(ws, min_col=3, min_row=4, max_row=4 + len(trends)),
        titles_from_data=True,
    )
    line.set_categories(Reference(ws, min_col=1, min_row=5, max_row=4 + len(trends)))
    line.legend = None
    ws.add_chart(line, "J4")
    _style_sheet(
        ws, {"A": 14, "B": 13, "C": 18, "D": 18, "E": 16, "F": 16, "G": 18, "H": 14}
    )

    categories = _net_category_performance(data)
    ws = wb.create_sheet("Categories")
    _add_title(
        ws,
        "Category Performance",
        "Gross and net revenue both exclude Cancelled orders.",
        len(categories.columns),
    )
    _write_frame(ws, categories, table_name="CategoryPerformanceTable")
    for col in (2, 3):
        for row in range(5, 5 + len(categories)):
            ws.cell(row, col).number_format = '"$"#,##0.00'
    bar = BarChart()
    bar.type = "bar"
    bar.style = 10
    bar.title = "Net Revenue by Category"
    bar.x_axis.title = "Net revenue ($)"
    bar.add_data(
        Reference(ws, min_col=2, min_row=4, max_row=4 + len(categories)),
        titles_from_data=True,
    )
    bar.set_categories(Reference(ws, min_col=1, min_row=5, max_row=4 + len(categories)))
    bar.legend = None
    bar.height, bar.width = 8, 14
    ws.add_chart(bar, "F4")
    _style_sheet(ws, {"A": 20, "B": 18, "C": 18})

    products = (
        data.frames["product_performance"]
        .copy()
        .sort_values("total_revenue", ascending=False)
    )
    products = products.rename(columns={"total_revenue": "gross_revenue"})
    ws = wb.create_sheet("Products")
    _add_title(
        ws,
        "Product Performance",
        "Product revenue is gross revenue and excludes Cancelled orders.",
        len(products.columns),
    )
    _write_frame(ws, products, table_name="ProductPerformanceTable")
    revenue_col = products.columns.get_loc("gross_revenue") + 1
    for row in range(5, 5 + len(products)):
        ws.cell(row, revenue_col).number_format = '"$"#,##0.00'
    _style_sheet(ws)
    for col, name in enumerate(products.columns, 1):
        width = max(
            12,
            min(
                24,
                max(
                    len(str(name)),
                    *(len(str(value)) for value in products[name].head(50)),
                )
                + 2,
            ),
        )
        ws.column_dimensions[get_column_letter(col)].width = width

    segments = data.frames["segment_profiles"].copy()
    ws = wb.create_sheet("Customer Segments")
    _add_title(
        ws,
        "Customer Segments",
        "Descriptive output from the synthetic sample dataset; validate before business use.",
        len(segments.columns),
    )
    _write_frame(ws, segments, table_name="CustomerSegmentsTable")
    for name in ("avg_total_spend", "avg_order_value"):
        if name in segments.columns:
            col = segments.columns.get_loc(name) + 1
            for row in range(5, 5 + len(segments)):
                ws.cell(row, col).number_format = '"$"#,##0.00'
    _style_sheet(ws)
    for col in range(1, len(segments.columns) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 23

    retention = data.frames["retention_matrix"].copy()
    retention.columns = [f"Month {column}" for column in retention.columns]
    ws = wb.create_sheet("Cohort Retention")
    _add_title(
        ws,
        "Cohort Retention",
        "Retention percentages from the synthetic sample dataset.",
        len(retention.columns) + 1,
    )
    retention.insert(
        0, "Cohort", [f"Cohort {index + 1}" for index in range(len(retention))]
    )
    _write_frame(ws, retention, table_name="CohortRetentionTable")
    for row in range(5, 5 + len(retention)):
        for col in range(2, len(retention.columns) + 1):
            if ws.cell(row, col).value is not None:
                ws.cell(row, col).value = ws.cell(row, col).value / 100
                ws.cell(row, col).number_format = "0.0%"
    range_ref = f"B5:{get_column_letter(len(retention.columns))}{4 + len(retention)}"
    ws.conditional_formatting.add(
        range_ref,
        ColorScaleRule(
            start_type="min",
            start_color="F8696B",
            mid_type="percentile",
            mid_value=50,
            mid_color="FFEB84",
            end_type="max",
            end_color="63BE7B",
        ),
    )
    _style_sheet(
        ws, {get_column_letter(i): 16 for i in range(1, len(retention.columns) + 1)}
    )

    dictionary = pd.DataFrame(
        [
            (
                "Net revenue",
                "Gross line revenue less discounts; excludes Cancelled orders.",
                "reports/kpis.json / fact_sales.csv",
            ),
            (
                "Gross revenue",
                "Quantity multiplied by unit price; excludes Cancelled orders.",
                "fact_sales.csv / analysis CSVs",
            ),
            (
                "Gross margin",
                "(Net revenue - cost) / net revenue.",
                "reports/kpis.json",
            ),
            ("Net AOV", "Net revenue divided by included orders.", "reports/kpis.json"),
            (
                "Cancelled share",
                "Cancelled orders divided by all orders.",
                "reports/kpis.json",
            ),
            (
                "Customer metrics",
                "Synthetic sample output; validate against production data before action.",
                "customer_segments.csv",
            ),
        ],
        columns=["Metric", "Definition", "Source"],
    )
    ws = wb.create_sheet("Data Dictionary")
    _add_title(
        ws,
        "Metric Definitions and Lineage",
        "Every management figure is traceable to a validated pipeline artifact.",
        3,
    )
    _write_frame(ws, dictionary, table_name="DataDictionaryTable")
    _style_sheet(ws, {"A": 22, "B": 72, "C": 38})
    for row in range(5, 5 + len(dictionary)):
        ws.cell(row, 2).alignment = Alignment(wrap_text=True, vertical="top")

    wb.save(output_path)
    return output_path


def _rgb(hex_color: str) -> RGBColor:
    return RGBColor.from_string(hex_color)


def _set_background(slide, color: str = WHITE) -> None:
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = _rgb(color)


def _add_text(
    slide,
    text: str,
    left: float,
    top: float,
    width: float,
    height: float,
    *,
    size: int = 18,
    color: str = INK,
    bold: bool = False,
    align=PP_ALIGN.LEFT,
    font="Aptos",
    valign=MSO_ANCHOR.TOP,
):
    shape = slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height)
    )
    frame = shape.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.vertical_anchor = valign
    paragraph = frame.paragraphs[0]
    paragraph.text = text
    paragraph.alignment = align
    paragraph.font.name = font
    paragraph.font.size = Pt(size)
    paragraph.font.bold = bold
    paragraph.font.color.rgb = _rgb(color)
    return shape


def _add_title_band(slide, title: str, slide_number: int) -> None:
    _add_text(
        slide,
        title,
        0.7,
        0.35,
        11.7,
        0.65,
        size=28,
        color=NAVY,
        bold=True,
        font="Aptos Display",
    )
    line = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0.7), Inches(1.1), Inches(1.25), Inches(0.06)
    )
    line.fill.solid()
    line.fill.fore_color.rgb = _rgb(TEAL)
    line.line.fill.background()
    _add_text(
        slide,
        f"{PROJECT_NAME}  •  {slide_number}",
        10.4,
        7.05,
        2.2,
        0.25,
        size=9,
        color=MUTED,
        align=PP_ALIGN.RIGHT,
    )


def _add_kpi(
    slide, label: str, value: str, left: float, top: float, accent: str
) -> None:
    box = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE,
        Inches(left),
        Inches(top),
        Inches(3.6),
        Inches(1.35),
    )
    box.fill.solid()
    box.fill.fore_color.rgb = _rgb(LIGHT)
    box.line.color.rgb = _rgb("D9E2EA")
    stripe = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(left), Inches(top), Inches(0.08), Inches(1.35)
    )
    stripe.fill.solid()
    stripe.fill.fore_color.rgb = _rgb(accent)
    stripe.line.fill.background()
    _add_text(
        slide,
        value,
        left + 0.25,
        top + 0.2,
        3.1,
        0.55,
        size=24,
        color=accent,
        bold=True,
        font="Aptos Display",
    )
    _add_text(
        slide, label, left + 0.25, top + 0.82, 3.1, 0.3, size=12, color=MUTED, bold=True
    )


def _add_bullets(
    slide,
    items: list[str],
    left: float,
    top: float,
    width: float,
    height: float,
    size: int = 17,
) -> None:
    shape = slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height)
    )
    frame = shape.text_frame
    frame.clear()
    frame.word_wrap = True
    for index, item in enumerate(items):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = item
        paragraph.level = 0
        paragraph.font.name = "Aptos"
        paragraph.font.size = Pt(size)
        paragraph.font.color.rgb = _rgb(INK)
        paragraph.space_after = Pt(12)
        paragraph.text = f"• {item}"


def _add_notes(slide, sources: list[str]) -> None:
    notes_frame = slide.notes_slide.notes_text_frame
    notes_frame.text = "[Sources]\n" + "\n".join(sources)


def _add_chart(
    slide,
    chart_type,
    categories: list[str],
    series: list[tuple[str, list[float]]],
    left: float,
    top: float,
    width: float,
    height: float,
    *,
    currency: bool = False,
):
    data = CategoryChartData()
    data.categories = categories
    for name, values in series:
        data.add_series(name, values)
    chart = slide.shapes.add_chart(
        chart_type, Inches(left), Inches(top), Inches(width), Inches(height), data
    ).chart
    chart.has_legend = len(series) > 1
    if chart.has_legend:
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
    chart.has_title = False
    chart.value_axis.has_major_gridlines = True
    chart.value_axis.tick_labels.font.size = Pt(11)
    chart.category_axis.tick_labels.font.size = Pt(11)
    if currency:
        chart.value_axis.tick_labels.number_format = "$#,##0"
        chart.value_axis.tick_labels.number_format_is_linked = False
    return chart


def build_powerpoint_report(data: ReportData, output_path: Path) -> Path:
    """Create a concise management deck from the same validated inputs."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    k = data.kpis
    _, _, recommendations = _flatten_briefing(data)

    slide = prs.slides.add_slide(blank)
    _set_background(slide, NAVY)
    _add_text(
        slide,
        "E-Commerce\nManagement Briefing",
        0.85,
        1.55,
        7.5,
        1.75,
        size=38,
        color=WHITE,
        bold=True,
        font="Aptos Display",
    )
    _add_text(
        slide,
        f"{k['period_start']} — {k['period_end']}",
        0.9,
        3.65,
        5.5,
        0.4,
        size=18,
        color="B9D7EA",
    )
    _add_text(
        slide,
        "Validated pipeline outputs • Excel and PowerPoint reporting",
        0.9,
        5.95,
        8.0,
        0.4,
        size=14,
        color="B9D7EA",
    )
    accent = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(9.8), Inches(0), Inches(3.533), Inches(7.5)
    )
    accent.fill.solid()
    accent.fill.fore_color.rgb = _rgb(TEAL)
    accent.line.fill.background()
    _add_text(
        slide,
        "ECOM\nINSIGHTS",
        10.25,
        2.75,
        2.6,
        1.3,
        size=26,
        color=WHITE,
        bold=True,
        align=PP_ALIGN.CENTER,
        valign=MSO_ANCHOR.MIDDLE,
    )
    _add_notes(slide, ["reports/kpis.json"])

    slide = prs.slides.add_slide(blank)
    _set_background(slide)
    _add_title_band(slide, "Revenue is healthy, but one in four orders is cancelled", 2)
    _add_kpi(slide, "Net revenue", f"${k['net_revenue_total']:,.0f}", 0.8, 1.55, TEAL)
    _add_kpi(slide, "Included orders", f"{k['total_orders']:,}", 4.85, 1.55, BLUE)
    _add_kpi(
        slide,
        "Net average order value",
        f"${k['average_order_value_net']:,.2f}",
        8.9,
        1.55,
        NAVY,
    )
    _add_kpi(slide, "Gross margin", f"{k['gross_margin_pct']:.2f}%", 0.8, 3.35, GREEN)
    _add_kpi(
        slide, "Discounts", f"${k['total_discount_amount']:,.0f}", 4.85, 3.35, AMBER
    )
    _add_kpi(
        slide,
        "Cancelled order share",
        f"{k['cancelled_order_share_pct']:.2f}%",
        8.9,
        3.35,
        RED,
    )
    _add_text(
        slide,
        "Management implication",
        0.8,
        5.25,
        3.0,
        0.35,
        size=17,
        color=NAVY,
        bold=True,
    )
    _add_text(
        slide,
        "Cancellation reduction is the clearest near-term lever for protecting realized revenue.",
        0.8,
        5.7,
        11.4,
        0.65,
        size=21,
        color=INK,
    )
    _add_notes(slide, ["reports/kpis.json"])

    trends = data.frames["sales_trends"].copy()
    slide = prs.slides.add_slide(blank)
    _set_background(slide)
    _add_title_band(
        slide, "Gross revenue remains broadly stable after the launch month", 3
    )
    _add_chart(
        slide,
        XL_CHART_TYPE.LINE_MARKERS,
        [d.strftime("%b %y") for d in trends["period"]],
        [("Gross revenue", trends["total_revenue"].astype(float).tolist())],
        0.75,
        1.45,
        8.3,
        4.9,
        currency=True,
    )
    _add_text(
        slide, "What it means", 9.45, 1.65, 2.4, 0.4, size=18, color=NAVY, bold=True
    )
    _add_bullets(
        slide,
        [
            "The first partial month should not be compared with full months.",
            "Subsequent months stay within a relatively narrow band.",
            "This chart shows gross revenue; headline KPIs use net revenue after discounts.",
        ],
        9.35,
        2.25,
        3.2,
        3.5,
        size=16,
    )
    _add_notes(slide, ["data/processed/sales_trends.csv", "reports/kpis.json"])

    categories = _net_category_performance(data)
    slide = prs.slides.add_slide(blank)
    _set_background(slide)
    _add_title_band(slide, "Sports leads net revenue; Electronics needs diagnosis", 4)
    _add_chart(
        slide,
        XL_CHART_TYPE.BAR_CLUSTERED,
        categories["category"].tolist(),
        [("Net revenue", categories["net_revenue"].astype(float).tolist())],
        0.75,
        1.4,
        8.0,
        5.2,
        currency=True,
    )
    top, weakest = k["top_category"], k["weakest_category"]
    _add_text(
        slide, "Category spread", 9.15, 1.55, 2.5, 0.4, size=18, color=NAVY, bold=True
    )
    _add_text(
        slide,
        f"{top['category']}\n${top['net_revenue']:,.0f}",
        9.15,
        2.2,
        3.1,
        1.0,
        size=24,
        color=GREEN,
        bold=True,
    )
    _add_text(
        slide,
        f"{weakest['category']}\n${weakest['net_revenue']:,.0f}",
        9.15,
        3.65,
        3.1,
        1.0,
        size=24,
        color=RED,
        bold=True,
    )
    _add_text(
        slide,
        "Protect the leader while testing pricing, assortment, and demand in the weakest category.",
        9.15,
        5.15,
        3.2,
        0.85,
        size=15,
        color=INK,
    )
    _add_notes(
        slide,
        [
            "data/processed/fact_sales.csv",
            "data/processed/dim_product.csv",
            "reports/kpis.json",
        ],
    )

    products = (
        data.frames["product_performance"]
        .nlargest(8, "total_revenue")
        .sort_values("total_revenue")
    )
    slide = prs.slides.add_slide(blank)
    _set_background(slide)
    _add_title_band(slide, "Top products concentrate gross-revenue performance", 5)
    _add_chart(
        slide,
        XL_CHART_TYPE.BAR_CLUSTERED,
        products["product_name"].tolist(),
        [("Gross revenue", products["total_revenue"].astype(float).tolist())],
        0.75,
        1.4,
        8.0,
        5.2,
        currency=True,
    )
    _add_text(
        slide, "Use the ranking", 9.15, 1.6, 2.6, 0.4, size=18, color=NAVY, bold=True
    )
    _add_bullets(
        slide,
        [
            "Prioritize availability for the strongest products.",
            "Separate volume effects from price effects before changing assortment.",
            "Product revenue is gross and excludes Cancelled orders.",
        ],
        9.05,
        2.25,
        3.3,
        3.5,
        size=16,
    )
    _add_notes(slide, ["data/processed/product_performance.csv"])

    slide = prs.slides.add_slide(blank)
    _set_background(slide)
    _add_title_band(slide, "Customer retention is a data-quality warning, not a win", 6)
    _add_text(
        slide,
        f"{k['repeat_customer_rate_pct']:.0f}%",
        0.85,
        1.55,
        3.4,
        1.0,
        size=44,
        color=RED,
        bold=True,
        font="Aptos Display",
    )
    _add_text(
        slide,
        "reported repeat-customer rate",
        0.9,
        2.65,
        3.8,
        0.45,
        size=18,
        color=MUTED,
    )
    warning = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(4.7), Inches(1.5), Inches(7.6), Inches(2.0)
    )
    warning.fill.solid()
    warning.fill.fore_color.rgb = _rgb("FFF2CC")
    warning.line.color.rgb = _rgb(AMBER)
    _add_text(
        slide,
        "Why this cannot guide action",
        5.05,
        1.85,
        4.0,
        0.4,
        size=20,
        color="7F6000",
        bold=True,
    )
    _add_text(
        slide,
        "The synthetic generator repeatedly assigns orders across only 100 customers. The result reflects test-data construction, not real loyalty.",
        5.05,
        2.4,
        6.75,
        0.75,
        size=17,
        color=INK,
    )
    _add_text(slide, "Next step", 0.9, 4.2, 2.0, 0.4, size=19, color=NAVY, bold=True)
    _add_text(
        slide,
        "Re-run segmentation and cohort analysis on production data before funding retention or loyalty initiatives.",
        0.9,
        4.85,
        10.9,
        0.9,
        size=25,
        color=INK,
        bold=True,
    )
    _add_notes(
        slide,
        [
            "reports/kpis.json",
            "README.md#limitations",
            "data/processed/customer_segments.csv",
        ],
    )

    slide = prs.slides.add_slide(blank)
    _set_background(slide)
    _add_title_band(
        slide, "Three actions protect revenue and improve decision quality", 7
    )
    actions = recommendations[:3] or [
        "Investigate cancellations.",
        "Review discounting.",
        "Validate customer data.",
    ]
    accents = [RED, AMBER, TEAL]
    for idx, action in enumerate(actions):
        top_y = 1.45 + idx * 1.65
        _add_text(
            slide,
            f"0{idx + 1}",
            0.9,
            top_y,
            0.85,
            0.55,
            size=27,
            color=accents[idx],
            bold=True,
            font="Aptos Display",
        )
        _add_text(slide, action, 1.9, top_y, 10.1, 1.0, size=19, color=INK, bold=True)
    _add_text(
        slide,
        "Success means management reporting stays traceable: every number maps back to a validated KPI or processed dataset.",
        0.9,
        6.35,
        11.5,
        0.45,
        size=15,
        color=MUTED,
    )
    _add_notes(slide, ["reports/executive_briefing.json", "reports/kpis.json"])

    prs.core_properties.title = f"{PROJECT_NAME} Management Briefing"
    prs.core_properties.subject = (
        "Management briefing generated from validated pipeline outputs"
    )
    prs.core_properties.author = PROJECT_NAME
    prs.save(output_path)
    return output_path


def validate_outputs(xlsx_path: Path, pptx_path: Path, data: ReportData) -> None:
    """Perform structural and reconciliation checks after generation."""
    wb = load_workbook(xlsx_path, data_only=False)
    expected_sheets = [
        "Executive Summary",
        "Sales Trends",
        "Categories",
        "Products",
        "Customer Segments",
        "Cohort Retention",
        "Data Dictionary",
    ]
    if wb.sheetnames != expected_sheets:
        raise RuntimeError(f"Unexpected workbook sheets: {wb.sheetnames}")
    if wb["Executive Summary"]["A5"].value != data.kpis["net_revenue_total"]:
        raise RuntimeError("Workbook net revenue does not reconcile to kpis.json")
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and any(
                    error in cell.value
                    for error in ("#REF!", "#DIV/0!", "#VALUE!", "#NAME?")
                ):
                    raise RuntimeError(f"Formula error in {ws.title}!{cell.coordinate}")
    prs = Presentation(pptx_path)
    if len(prs.slides) != 7:
        raise RuntimeError(f"Expected 7 slides, found {len(prs.slides)}")
    for index, slide in enumerate(prs.slides, 1):
        if not slide.shapes:
            raise RuntimeError(f"Slide {index} is empty")


def generate_office_reports(
    output_dir: str | os.PathLike[str] | None = None,
) -> tuple[Path, Path]:
    data = load_report_data()
    destination = Path(output_dir) if output_dir else Path(PATHS["reports"])
    xlsx_path = build_excel_report(data, destination / DEFAULT_XLSX)
    pptx_path = build_powerpoint_report(data, destination / DEFAULT_PPTX)
    validate_outputs(xlsx_path, pptx_path, data)
    return xlsx_path, pptx_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Excel and PowerPoint management reports"
    )
    parser.add_argument(
        "--output-dir", help="Destination directory; defaults to reports/"
    )
    args = parser.parse_args()
    xlsx_path, pptx_path = generate_office_reports(args.output_dir)
    print(f"Wrote {xlsx_path}")
    print(f"Wrote {pptx_path}")


if __name__ == "__main__":
    main()
