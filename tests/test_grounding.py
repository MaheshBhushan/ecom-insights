"""
Tests for the T5 grounding validator (src/insights/briefing.py).

This is the one place a bad briefing would otherwise fail silently: if the
validator ever accepts a fabricated figure, a wrong number ships straight to
the exec briefing. So this file feeds the validator canned model responses
(no live API call) and checks both directions -- a fabricated figure is
rejected, and a fully-grounded response passes.
"""
import pytest

from src.insights.briefing import GroundingError, validate_briefing

KPIS = {
    "period_start": "2025-06-30",
    "period_end": "2026-06-30",
    "order_statuses_included_in_revenue": ["Completed", "Processing", "Shipped"],
    "order_statuses_excluded_from_revenue": ["Cancelled"],
    "revenue_basis_note": "net_revenue_total is gross_revenue minus discount_amount.",
    "total_orders": 1200,
    "total_customers": 500,
    "gross_revenue_total": 250000.0,
    "net_revenue_total": 231000.0,
    "total_discount_amount": 19000.0,
    "total_cost": 138600.0,
    "average_order_value_net": 192.5,
    "gross_margin_pct": 40.0,
    "gross_margin_basis": "net_revenue",
    "repeat_customer_rate_pct": 8.4,
    "top_category": {"category": "Electronics", "net_revenue": 90000.0},
    "weakest_category": {"category": "Books", "net_revenue": 8000.0},
    "cancelled_order_count": 130,
    "cancelled_order_share_pct": 9.77,
}


def _valid_response():
    return {
        "summary": (
            "Net revenue reached 231000.0 across 1200 orders, a 40.0% gross margin, "
            "led by the Electronics category."
        ),
        "risks": [
            "Repeat customer rate is only 8.4%, indicating weak retention.",
            "Cancelled orders account for 9.77% of all orders.",
        ],
        "recommendations": [
            {
                "text": (
                    "Invest in retention programs for the Electronics category, since it "
                    "drives 90000.0 in net revenue but repeat purchase rate is just 8.4%."
                ),
                "evidence": ["top_category.net_revenue", "repeat_customer_rate_pct"],
            },
            {
                "text": "Investigate why Books underperforms at 8000.0 in net revenue.",
                "evidence": ["weakest_category.net_revenue"],
            },
        ],
        "evidence": ["net_revenue_total", "gross_margin_pct", "top_category.category"],
    }


def test_valid_response_passes():
    assert validate_briefing(_valid_response(), KPIS) is True


def test_fabricated_number_is_rejected():
    response = _valid_response()
    # 27.3% appears nowhere in KPIS -- a classic hallucinated figure.
    response["summary"] += " Year-over-year growth was 27.3%."
    with pytest.raises(GroundingError, match="ungrounded numeric literal"):
        validate_briefing(response, KPIS)


def test_missing_required_key_is_rejected():
    response = _valid_response()
    del response["risks"]
    with pytest.raises(GroundingError, match="exactly the keys"):
        validate_briefing(response, KPIS)


def test_extra_key_is_rejected():
    response = _valid_response()
    response["conclusion"] = "All good."
    with pytest.raises(GroundingError, match="exactly the keys"):
        validate_briefing(response, KPIS)


def test_recommendation_without_evidence_is_rejected():
    response = _valid_response()
    response["recommendations"][0]["evidence"] = []
    with pytest.raises(GroundingError, match="no evidence entry"):
        validate_briefing(response, KPIS)


def test_recommendation_citing_unknown_field_is_rejected():
    response = _valid_response()
    response["recommendations"][0]["evidence"] = ["total_unicorns_sold"]
    with pytest.raises(GroundingError, match="unknown KPI field"):
        validate_briefing(response, KPIS)


def test_top_level_evidence_citing_unknown_field_is_rejected():
    response = _valid_response()
    response["evidence"].append("made_up_field")
    with pytest.raises(GroundingError, match="unknown KPI field"):
        validate_briefing(response, KPIS)


def test_non_dict_response_is_rejected():
    with pytest.raises(GroundingError, match="not a JSON object"):
        validate_briefing(["summary", "risks"], KPIS)


def test_year_and_ordinal_are_not_flagged_as_fabricated():
    """
    Numbers that are legitimately grounded via string fields (a year inside
    period_start) or that are ranking language ("the 1st recommendation")
    must not trip the numeric-grounding check.
    """
    response = _valid_response()
    response["summary"] += " This covers the period from 2025 to 2026."
    response["risks"].append("The 1st priority is fixing retention.")
    assert validate_briefing(response, KPIS) is True


def test_exact_date_reproduction_is_grounded_but_bare_component_is_not():
    """
    A model repeating the whole period_start/period_end date verbatim
    ("2025-06-30") must pass -- but that must not open the door to bare
    reuse of its day/month digits elsewhere in the same response.
    """
    response = _valid_response()
    response["summary"] += " The reporting window ran from 2025-06-30 to 2026-06-30."
    validate_briefing(response, KPIS)  # exact date tokens: should pass

    response["risks"].append("Only 30 days remain in the quarter.")
    with pytest.raises(GroundingError, match="ungrounded numeric literal"):
        validate_briefing(response, KPIS)


def test_date_component_is_not_grounded_as_a_standalone_number():
    """
    period_start = "2025-06-30" must ground the year 2025 (a model may
    legitimately restate the year in prose) but must NOT ground "30" or "06"
    as free-floating numbers -- those are date components, not data points,
    and a claim like "30 categories underperformed" is fabricated even
    though "30" appears inside a date string in kpis.json.
    """
    response = _valid_response()
    response["risks"].append("30 categories underperformed this period.")
    with pytest.raises(GroundingError, match="ungrounded numeric literal"):
        validate_briefing(response, KPIS)


def test_percent_and_fraction_formatting_variance_is_grounded():
    """
    The same underlying figure (repeat_customer_rate_pct = 8.4) should be
    accepted whether written as '8.4%', '8.4', or with different rounding.
    """
    response = _valid_response()
    response["risks"] = ["Retention sits at 8.4% of customers repeat-buying."]
    assert validate_briefing(response, KPIS) is True

def test_near_miss_on_a_real_value_is_rejected():
    """A figure close to a real one is drift, not rounding, and must not pass.

    Guards against a relative tolerance: 253081 sits within 0.5% of the real
    253080, so a percentage-based band would wave it through.
    """
    kpis = {"gross_revenue_total": 253080.0}
    response = {
        "summary": "Gross revenue was $253,081.00.",
        "risks": ["r"],
        "recommendations": [{"text": "x", "evidence": ["gross_revenue_total"]}],
        "evidence": ["gross_revenue_total"],
    }
    with pytest.raises(GroundingError):
        validate_briefing(response, kpis)
