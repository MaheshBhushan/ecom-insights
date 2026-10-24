"""Exercise comparison with real committed inputs and explicit API test doubles."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.insights.briefing import generate_briefing
from src.insights.comparison import (
    compare,
    deterministic_briefing,
    fingerprint,
    generate_candidate,
    main,
    validate_kpis,
)

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


@pytest.fixture
def kpis():
    return json.loads((REPORTS / "kpis.json").read_text())


@pytest.fixture
def briefing():
    return json.loads((REPORTS / "executive_briefing.json").read_text())


def fake_client(briefing, *, raw=None, cached=0):
    """Synthetic provider response for tests; never represents an actual run."""
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=raw if raw is not None else json.dumps(briefing))],
            usage=SimpleNamespace(input_tokens=200, output_tokens=100,
                                  cache_creation_input_tokens=cached, cache_read_input_tokens=0),
            model="test-model", stop_reason="end_turn",
        )

    return SimpleNamespace(messages=SimpleNamespace(create=create)), requests


def test_committed_inputs_compare_without_changing_figures(kpis, briefing):
    before = copy.deepcopy(kpis)
    result = compare(kpis, briefing)
    assert kpis == before
    assert result["kpis"] == before
    assert result["llm"]["consistency"] == {"passed": True, "issues": []}
    assert result["deterministic"]["consistency"]["passed"]
    assert result["llm"]["cost"]["estimated_usd"] is None
    assert result["deterministic"]["model_cost_usd"] == 0
    assert result["review_seconds_saved"] is None
    assert result["llm"]["review"] is None
    assert deterministic_briefing(kpis) == deterministic_briefing(kpis)
    assert fingerprint(dict(reversed(list(kpis.items())))) == result["kpi_sha256"]


@pytest.mark.parametrize("mutation", [
    lambda k: k.pop("total_cost"),
    lambda k: k.update(total_orders=True),
    lambda k: k.update(total_orders=-1),
    lambda k: k.update(total_cost=float("nan")),
    lambda k: k.update(net_revenue_total=k["net_revenue_total"] + 1),
    lambda k: k.update(average_order_value_net=5),
    lambda k: k.update(gross_margin_pct=5),
    lambda k: k.update(cancelled_order_share_pct=5),
    lambda k: k.update(period_end="2024-01-01"),
    lambda k: k.update(period_start="2025-02-30"),
    lambda k: k.update(order_statuses_excluded_from_revenue=[]),
    lambda k: k.update(gross_margin_basis="gross_revenue"),
    lambda k: k["top_category"].update(net_revenue=k["net_revenue_total"] + 1),
])
def test_bad_snapshot_is_rejected_without_repairs(kpis, mutation):
    mutation(kpis)
    before = copy.deepcopy(kpis)
    with pytest.raises(ValueError):
        validate_kpis(kpis)
    assert repr(kpis) == repr(before)


def test_zero_denominators_and_negative_margin_are_valid(kpis):
    kpis["total_cost"] = 2 * kpis["net_revenue_total"]
    kpis["gross_margin_pct"] = -100
    validate_kpis(kpis)
    for key in ("total_orders", "cancelled_order_count") + ("gross_revenue_total", "net_revenue_total", "total_discount_amount", "total_cost"):
        kpis[key] = 0
    for key in ("gross_margin_pct", "average_order_value_net", "cancelled_order_share_pct"):
        kpis[key] = None
    for key in ("top_category", "weakest_category"):
        kpis[key]["net_revenue"] = 0
    result = compare(kpis, deterministic_briefing(kpis))
    assert result["llm"]["consistency"]["passed"]


def test_rejects_fabrication_and_wrong_citation(kpis, briefing):
    briefing["summary"] += " Growth reached 987654321%."
    assert not compare(kpis, briefing)["llm"]["consistency"]["passed"]
    briefing = deterministic_briefing(kpis)
    briefing["recommendations"] = [{"text": f"Review revenue of {kpis['net_revenue_total']}.",
                                    "evidence": ["total_orders"]}]
    result = compare(kpis, briefing)
    assert not result["llm"]["consistency"]["passed"]
    assert "absent from its cited fields" in result["llm"]["consistency"]["issues"][0]


@pytest.mark.parametrize("candidate", [None, [], {}, "invalid response"])
def test_malformed_model_content_is_an_evaluation_failure(kpis, candidate):
    assert not compare(kpis, candidate)["llm"]["consistency"]["passed"]


def test_api_receives_fixed_snapshot_and_usage_survives_rejection(kpis, briefing):
    client, requests = fake_client(briefing, raw="not JSON")
    before = copy.deepcopy(kpis)
    candidate, usage = generate_candidate(kpis, "test-model", client)
    assert candidate == "not JSON"
    assert kpis == before
    assert requests[0]["model"] == "test-model"
    assert json.dumps(kpis, sort_keys=True) in requests[0]["messages"][0]["content"]
    assert usage["input_tokens"] == 200
    assert usage["output_tokens"] == 100
    assert usage["generation_seconds"] >= 0
    result = compare(kpis, candidate, usage, input_rate=2, output_rate=4)
    assert not result["llm"]["consistency"]["passed"]
    assert result["llm"]["cost"]["estimated_usd"] == pytest.approx(0.0008)
    # Existing generation callers still receive a validated briefing object.
    valid_client, _ = fake_client(briefing)
    assert generate_briefing(kpis, valid_client) == briefing


def test_cost_unknown_cache_usage_and_stale_usage(kpis, briefing):
    client, _ = fake_client(briefing, cached=50)
    candidate, usage = generate_candidate(kpis, "test-model", client)
    assert compare(kpis, candidate, usage)["llm"]["cost"]["estimated_usd"] is None
    assert "Cached-token" in compare(kpis, candidate, usage, input_rate=2, output_rate=4)["llm"]["cost"]["reason"]
    usage["kpi_sha256"] = "stale"
    with pytest.raises(ValueError, match="hashes"):
        compare(kpis, candidate, usage)


@pytest.mark.parametrize("rates", [(2, None), (-1, 2), (float("nan"), 2)])
def test_invalid_prices_are_rejected(kpis, briefing, rates):
    with pytest.raises(ValueError):
        compare(kpis, briefing, input_rate=rates[0], output_rate=rates[1])


def test_review_observations_are_bound_to_both_reports(kpis, briefing):
    initial = compare(kpis, briefing)
    review = {key: initial[key] for key in ("kpi_sha256", "llm_sha256", "deterministic_sha256")}
    review.update({name: {"reviewer": "test-reviewer", "seconds": seconds, "corrections": 0,
                          "verdict": "accepted"} for name, seconds in (("llm", 40), ("deterministic", 30))})
    assert compare(kpis, briefing, review=review)["review_seconds_saved"] == -10
    review["llm"]["seconds"] = float("inf")
    with pytest.raises(ValueError, match="finite"):
        compare(kpis, briefing, review=review)
    review["llm"]["seconds"] = 40
    review["llm_sha256"] = "stale"
    with pytest.raises(ValueError, match="hashes"):
        compare(kpis, briefing, review=review)


def test_cli_preserves_sources_and_writes_auditable_comparison(tmp_path):
    source_kpis = REPORTS / "kpis.json"
    source_briefing = REPORTS / "executive_briefing.json"
    before = [p.read_bytes() for p in (source_kpis, source_briefing)]
    output = tmp_path / "comparison"
    args = ["--kpis", str(source_kpis), "--briefing", str(source_briefing), "--output-dir", str(output)]
    assert main(args) == 0
    assert before == [p.read_bytes() for p in (source_kpis, source_briefing)]
    report = json.loads((output / "comparison.json").read_text())
    assert report["kpis"] == json.loads(source_kpis.read_text())
    assert (output / "deterministic.md").exists() and (output / "llm.md").exists()
    assert "Unknown" in (output / "comparison.md").read_text()
    template = json.loads((output / "review-template.json").read_text())
    assert template["llm"]["seconds"] is None
    assert template["llm_sha256"] == report["llm_sha256"]
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
    assert report == json.loads((output / "comparison.json").read_text())


def test_cli_retains_failed_briefing_without_publishing_markdown(tmp_path):
    invalid = tmp_path / "bad.json"
    invalid.write_text(json.dumps({"summary": "Fabricated"}))
    output = tmp_path / "rejected"
    assert main(["--kpis", str(REPORTS / "kpis.json"), "--briefing", str(invalid),
                 "--output-dir", str(output)]) == 1
    assert json.loads((output / "llm.json").read_text()) == {"summary": "Fabricated"}
    assert not (output / "llm.md").exists()


def test_live_cli_records_real_response_metadata_via_test_double(tmp_path, monkeypatch, briefing):
    client, _ = fake_client(briefing, raw="not JSON")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-key")
    monkeypatch.setattr("src.insights.briefing.anthropic.Anthropic", lambda **kwargs: client)
    output = tmp_path / "generated"
    assert main(["--kpis", str(REPORTS / "kpis.json"), "--generate", "--model", "test-model",
                 "--output-dir", str(output)]) == 1
    usage = json.loads((output / "usage.json").read_text())
    assert usage["model"] == "test-model"
    assert usage["input_tokens"] == 200
    assert usage["briefing_sha256"] == fingerprint("not JSON")
    result = json.loads((output / "comparison.json").read_text())
    assert result["llm"]["usage"] == usage


def test_duplicate_json_fields_fail_without_output(tmp_path):
    invalid = tmp_path / "duplicate.json"
    invalid.write_text('{"total_orders": 1, "total_orders": 2}')
    output = tmp_path / "duplicate-output"
    with pytest.raises(SystemExit) as exc:
        main(["--kpis", str(invalid), "--briefing", str(REPORTS / "executive_briefing.json"),
              "--output-dir", str(output)])
    assert exc.value.code == 2
    assert not output.exists()


def test_missing_api_credentials_fail_without_output(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("src.insights.briefing.load_dotenv", lambda: None)
    output = tmp_path / "missing-credentials"
    with pytest.raises(SystemExit) as exc:
        main(["--kpis", str(REPORTS / "kpis.json"), "--generate", "--model", "test-model",
              "--output-dir", str(output)])
    assert exc.value.code == 2
    assert not output.exists()
