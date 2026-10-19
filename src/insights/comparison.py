"""Compare model and deterministic briefings without recomputing source KPIs."""

import argparse
import hashlib
import json
import math
from datetime import date
from pathlib import Path
from time import perf_counter

from src.config import PATHS
from src.insights.briefing import (
    GroundingError,
    _flatten,
    _parse_json_response,
    _render_markdown,
    build_grounding_set,
    find_ungrounded_numbers,
    request_briefing,
    validate_briefing,
)

COUNTS = ("total_orders", "total_customers", "cancelled_order_count")
MONEY = ("gross_revenue_total", "net_revenue_total", "total_discount_amount", "total_cost")
RATES = ("gross_margin_pct", "repeat_customer_rate_pct", "cancelled_order_share_pct")


def fingerprint(value):
    """Hash JSON content independently of whitespace and object key order."""
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _number(value, name, *, nullable=False, negative=False):
    if value is None and nullable:
        return
    if type(value) not in (int, float) or not math.isfinite(value) or (value < 0 and not negative):
        raise ValueError(f"{name} must be a finite {'number' if negative else 'non-negative number'}")


def validate_kpis(kpis):
    """Validate snapshot types, definitions, and internal arithmetic; never repair it."""
    if not isinstance(kpis, dict):
        raise ValueError("KPI snapshot must be an object")
    required = set(COUNTS + MONEY + RATES) | {
        "period_start", "period_end", "average_order_value_net", "gross_margin_basis",
        "revenue_basis_note", "order_statuses_included_in_revenue",
        "order_statuses_excluded_from_revenue", "top_category", "weakest_category",
    }
    if required - kpis.keys():
        raise ValueError(f"Missing KPI fields: {sorted(required - kpis.keys())}")
    for name in COUNTS:
        if type(kpis[name]) is not int or kpis[name] < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    for name in MONEY + RATES + ("average_order_value_net",):
        _number(kpis[name], name, nullable=name in RATES or name == "average_order_value_net",
                negative=name == "gross_margin_pct")
    for name in RATES:
        if kpis[name] is not None and kpis[name] > 100:
            raise ValueError(f"{name} must not exceed 100")
    for name in ("period_start", "period_end"):
        if not isinstance(kpis[name], str) or date.fromisoformat(kpis[name]).isoformat() != kpis[name]:
            raise ValueError(f"{name} must be an ISO date")
    if kpis["period_start"] > kpis["period_end"]:
        raise ValueError("KPI period is reversed")
    included = kpis["order_statuses_included_in_revenue"]
    excluded = kpis["order_statuses_excluded_from_revenue"]
    for statuses in (included, excluded):
        if not isinstance(statuses, list) or not all(isinstance(s, str) and s for s in statuses):
            raise ValueError("Revenue statuses must be lists of non-empty strings")
    if set(included) & set(excluded) or "Cancelled" not in excluded:
        raise ValueError("Revenue statuses must be disjoint and exclude Cancelled")
    if kpis["gross_margin_basis"] != "net_revenue" or not isinstance(kpis["revenue_basis_note"], str):
        raise ValueError("Revenue definitions must specify the net-revenue margin basis")
    for name in ("top_category", "weakest_category"):
        category = kpis[name]
        if not isinstance(category, dict) or not isinstance(category.get("category"), str) or not category["category"]:
            raise ValueError(f"{name} must contain a category name")
        _number(category.get("net_revenue"), f"{name}.net_revenue")
    if not (kpis["weakest_category"]["net_revenue"] <= kpis["top_category"]["net_revenue"] <= kpis["net_revenue_total"]):
        raise ValueError("Category revenues must respect their ranking and total")

    net = kpis["net_revenue_total"]
    orders = kpis["total_orders"]
    cancelled = kpis["cancelled_order_count"]
    expected = {
        "net_revenue_total": round(kpis["gross_revenue_total"] - kpis["total_discount_amount"], 2),
        "average_order_value_net": round(net / orders, 2) if orders else None,
        "gross_margin_pct": round((net - kpis["total_cost"]) / net * 100, 2) if net else None,
        "cancelled_order_share_pct": round(cancelled / (orders + cancelled) * 100, 2) if orders + cancelled else None,
    }
    for name, value in expected.items():
        actual = kpis[name]
        if (actual is None) != (value is None) or (value is not None and abs(actual - value) > 0.010000001):
            raise ValueError(f"KPI arithmetic mismatch: {name}")
    # Validate every extra leaf too: JSON extensions cannot introduce NaN or Infinity.
    fingerprint(kpis)


def deterministic_briefing(kpis):
    """Fill a fixed template with unchanged source values and evidence citations."""
    validate_kpis(kpis)
    report = {
        "summary": (
            f"Net revenue was ${kpis['net_revenue_total']:,.2f} across "
            f"{kpis['total_orders']:,} revenue orders. Gross revenue was "
            f"${kpis['gross_revenue_total']:,.2f}; discounts were "
            f"${kpis['total_discount_amount']:,.2f}."
        ),
        "risks": [
            f"Cancelled orders: {kpis['cancelled_order_count']:,}.",
            "Customer-data quality and business implications require human review.",
        ],
        "recommendations": [{
            "text": "Review cancellation drivers and discount policies against the source KPIs.",
            "evidence": ["cancelled_order_count", "total_discount_amount"],
        }],
        "evidence": sorted(kpis),
    }
    validate_briefing(report, kpis)
    return report


def check_consistency(briefing, kpis):
    """Check schema, numeric membership, and numeric membership within cited fields."""
    issues = []
    try:
        validate_briefing(briefing, kpis)
    except GroundingError as exc:
        return {"passed": False, "issues": [str(exc)]}
    flat = _flatten(kpis)
    blocks = [("summary", briefing["summary"], briefing["evidence"])]
    blocks += [(f"risks[{i}]", text, briefing["evidence"]) for i, text in enumerate(briefing["risks"])]
    blocks += [(f"recommendations[{i}]", rec["text"], rec["evidence"])
               for i, rec in enumerate(briefing["recommendations"])]
    for name, text, evidence in blocks:
        if not evidence:
            issues.append(f"{name} has no evidence citations")
            continue
        cited = {field: flat[field] if field in flat else kpis[field] for field in evidence}
        bad = find_ungrounded_numbers(text, *build_grounding_set(cited))
        if bad:
            issues.append(f"{name} contains numbers absent from its cited fields: {bad}")
    return {"passed": not issues, "issues": issues}


def generate_candidate(kpis, model, client=None):
    """Capture actual response usage even when the model returns invalid JSON."""
    validate_kpis(kpis)
    start = perf_counter()
    response = request_briefing(kpis, client=client, model=model)
    seconds = perf_counter() - start
    raw = "".join(block.text for block in response.content if block.type == "text")
    try:
        briefing = _parse_json_response(raw)
        fingerprint(briefing)
    except ValueError:
        briefing = raw
    usage = response.usage
    return briefing, {
        "kpi_sha256": fingerprint(kpis), "briefing_sha256": fingerprint(briefing),
        "model": response.model, "generation_seconds": seconds,
        "stop_reason": response.stop_reason,
        "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }


def model_cost(usage, input_rate=None, output_rate=None):
    """Estimate USD from recorded tokens and caller-supplied prices; never infer rates."""
    for name, rate in (("input price", input_rate), ("output price", output_rate)):
        if rate is not None:
            _number(rate, name)
    if (input_rate is None) != (output_rate is None):
        raise ValueError("Supply both input and output USD prices per million tokens")
    if usage is None:
        return {"estimated_usd": None, "reason": "Token usage was not recorded"}
    if not isinstance(usage, dict) or not {"input_tokens", "output_tokens"} <= usage.keys():
        raise ValueError("Usage requires input_tokens and output_tokens")
    for field in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        if type(usage.get(field, 0)) is not int or usage.get(field, 0) < 0:
            raise ValueError(f"Invalid usage: {field}")
    if input_rate is None:
        return {"estimated_usd": None, "reason": "Token prices were not supplied"}
    if usage.get("cache_creation_input_tokens") or usage.get("cache_read_input_tokens"):
        return {"estimated_usd": None, "reason": "Cached-token pricing is not supported; consult provider billing"}
    return {
        "estimated_usd": (usage["input_tokens"] * input_rate + usage["output_tokens"] * output_rate) / 1_000_000,
        "input_usd_per_million": input_rate, "output_usd_per_million": output_rate,
        "reason": "Token-only estimate using supplied prices; excludes other fees",
    }


def compare(kpis, briefing, usage=None, review=None, input_rate=None, output_rate=None):
    """Return both alternatives and audit data bound to their exact input content."""
    baseline = deterministic_briefing(kpis)
    ids = {"kpi_sha256": fingerprint(kpis), "llm_sha256": fingerprint(briefing),
           "deterministic_sha256": fingerprint(baseline)}
    if usage is not None:
        if not isinstance(usage, dict) or usage.get("kpi_sha256") != ids["kpi_sha256"] or usage.get("briefing_sha256") != ids["llm_sha256"]:
            raise ValueError("Usage must match the KPI and briefing hashes")
        for field in ("input_tokens", "output_tokens"):
            if field not in usage:
                raise ValueError(f"Usage is missing {field}")
    efforts = {"deterministic": None, "llm": None}
    if review is not None:
        if not isinstance(review, dict) or any(review.get(key) != value for key, value in ids.items()):
            raise ValueError("Review must match the KPI and both briefing hashes")
        for name in efforts:
            entry = review.get(name)
            if not isinstance(entry, dict) or not isinstance(entry.get("reviewer"), str) or not entry["reviewer"].strip():
                raise ValueError(f"{name} review requires a reviewer")
            _number(entry.get("seconds"), f"{name} review seconds")
            if type(entry.get("corrections")) is not int or entry["corrections"] < 0:
                raise ValueError(f"{name} review requires a non-negative correction count")
            if entry.get("verdict") not in ("accepted", "rejected"):
                raise ValueError(f"{name} review requires an accepted/rejected verdict")
            efforts[name] = entry
    return {
        "schema_version": 1, **ids, "kpis": kpis,
        "deterministic": {"briefing": baseline, "consistency": check_consistency(baseline, kpis),
                          "model_cost_usd": 0, "review": efforts["deterministic"]},
        "llm": {"briefing": briefing, "consistency": check_consistency(briefing, kpis),
                "usage": usage, "cost": model_cost(usage, input_rate, output_rate), "review": efforts["llm"]},
        "review_seconds_saved": None if review is None else efforts["deterministic"]["seconds"] - efforts["llm"]["seconds"],
        "limitations": [
            "Automated checks cover schema, numeric literals, and cited-field numeric membership.",
            "Human review must check metric attribution, category names, written-out numbers, causality, and recommendations.",
            "Replay checks cannot verify which input originally generated an external briefing or usage record.",
            "Snapshot validation checks internal consistency; it does not re-query or certify warehouse data.",
            "Missing review observations and model costs remain null; no benefit is inferred.",
        ],
    }


def _read_json(path):
    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON field: {key}")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_fields)


def _comparison_markdown(result):
    cost = result["llm"]["cost"]["estimated_usd"]
    lines = ["# Briefing comparison", "", f"KPI snapshot: `{result['kpi_sha256']}`", "",
             "| Observation | Deterministic | LLM |", "| --- | --- | --- |",
             f"| Automated consistency | {result['deterministic']['consistency']['passed']} | {result['llm']['consistency']['passed']} |",
             f"| Model cost (USD estimate) | 0 | {cost if cost is not None else 'Unknown'} |"]
    for field in ("seconds", "corrections", "verdict"):
        values = [result[name]["review"][field] if result[name]["review"] else "Unrecorded"
                  for name in ("deterministic", "llm")]
        lines.append(f"| Review {field} | {values[0]} | {values[1]} |")
    lines += ["", "## Automated issues", ""]
    lines += [f"- {issue}" for issue in result["llm"]["consistency"]["issues"]] or ["No automated issues found."]
    lines += ["", "## Check limits", ""] + [f"- {item}" for item in result["limitations"]]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kpis", type=Path, default=Path(PATHS["reports"]) / "kpis.json")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--briefing", type=Path, help="Replay an existing briefing JSON without an API call")
    source.add_argument("--generate", action="store_true", help="Call the existing model API with the fixed snapshot")
    parser.add_argument("--model", help="Explicit provider model ID required for --generate")
    parser.add_argument("--usage", type=Path, help="Recorded usage JSON bound to KPI and briefing hashes")
    parser.add_argument("--review", type=Path, help="Human observations bound to both briefing hashes")
    parser.add_argument("--input-usd-per-million", type=float)
    parser.add_argument("--output-usd-per-million", type=float)
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory; existing files are never overwritten")
    args = parser.parse_args(argv)
    if args.generate and (not args.model or args.usage):
        parser.error("--generate requires --model and cannot use --usage")
    if args.generate and args.review:
        parser.error("Record reviews by replaying the saved generated briefing with --briefing and --usage")
    if args.briefing and args.model:
        parser.error("--model is only valid with --generate; replay model IDs belong in --usage")
    try:
        if args.output_dir.exists():
            raise ValueError("Output directory already exists; choose a new directory")
        # Validate all local inputs before an optional billed request.
        kpis = _read_json(args.kpis)
        validate_kpis(kpis)
        usage = _read_json(args.usage) if args.usage else None
        review = _read_json(args.review) if args.review else None
        model_cost(usage, args.input_usd_per_million, args.output_usd_per_million)
        if args.generate:
            briefing, usage = generate_candidate(kpis, args.model)
        else:
            briefing = _read_json(args.briefing)
        result = compare(kpis, briefing, usage, review,
                         args.input_usd_per_million, args.output_usd_per_million)
        args.output_dir.mkdir(parents=True, exist_ok=False)
        artifacts = {"comparison.json": result, "kpis.json": kpis,
                     "deterministic.json": result["deterministic"]["briefing"], "llm.json": briefing}
        artifacts["review-template.json"] = {
            key: result[key] for key in ("kpi_sha256", "llm_sha256", "deterministic_sha256")
        } | {name: {"reviewer": "", "seconds": None, "corrections": None, "verdict": None}
             for name in ("deterministic", "llm")}
        if usage is not None:
            artifacts["usage.json"] = usage
        for filename, value in artifacts.items():
            (args.output_dir / filename).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        (args.output_dir / "comparison.md").write_text(_comparison_markdown(result), encoding="utf-8")
        baseline = result["deterministic"]["briefing"]
        (args.output_dir / "deterministic.md").write_text(_render_markdown(baseline, kpis), encoding="utf-8")
        if result["llm"]["consistency"]["passed"]:
            (args.output_dir / "llm.md").write_text(_render_markdown(briefing, kpis), encoding="utf-8")
        print(f"Wrote comparison to {args.output_dir / 'comparison.json'}")
        return 0 if result["llm"]["consistency"]["passed"] else 1
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(2, f"Comparison failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
