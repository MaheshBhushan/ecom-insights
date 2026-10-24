"""
Grounded executive briefing (T5).

The model is sent ONLY reports/kpis.json -- never raw rows, never the CSVs --
and must answer with strict JSON. The response is validated before anything
is written: any numeric literal in the prose that doesn't trace back to
kpis.json, any recommendation missing evidence, or any evidence citing a
KPI field that doesn't exist causes a loud, non-zero-exit rejection.
"""
import json
import os
import re
import sys

import anthropic
from dotenv import load_dotenv

from src.config import PATHS

MODEL = "claude-sonnet-5"

BRIEFING_JSON_PATH = os.path.join(PATHS['reports'], 'executive_briefing.json')
BRIEFING_MD_PATH = os.path.join(PATHS['reports'], 'executive_briefing.md')

REQUIRED_KEYS = {"summary", "risks", "recommendations", "evidence"}

_NUMBER_RE = re.compile(r'\$?\d[\d,]*(?:\.\d+)?%?')
_ORDINAL_SUFFIX_RE = re.compile(r'^(st|nd|rd|th)\b', re.IGNORECASE)
_DATE_RE = re.compile(r'^(\d{4})-\d{2}-\d{2}$')


class GroundingError(Exception):
    """Raised when the model's response can't be traced back to kpis.json."""


# --------------------------------------------------------------------------
# KPI flattening / field-name vocabulary
# --------------------------------------------------------------------------

def _flatten(value, prefix=""):
    """Flatten a KPI dict into dotted field-name -> leaf-value pairs."""
    flat = {}
    if isinstance(value, dict):
        for k, v in value.items():
            key = f"{prefix}.{k}" if prefix else k
            flat.update(_flatten(v, key))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            flat.update(_flatten(v, f"{prefix}[{i}]"))
    else:
        flat[prefix] = value
    return flat


def _valid_fields(kpis):
    flat = _flatten(kpis)
    return set(flat.keys()) | set(kpis.keys())


# --------------------------------------------------------------------------
# Numeric grounding
# --------------------------------------------------------------------------

def _numeric_variants(value):
    """Plausible textual renderings of a number a model might use in prose."""
    variants = set()
    try:
        f = float(value)
    except (TypeError, ValueError):
        return variants
    for nd in range(0, 4):
        variants.add(f"{f:.{nd}f}")
    if f == int(f):
        variants.add(str(int(f)))
    if abs(f) >= 1000:
        variants.add(f"{f:,.0f}")
        variants.add(f"{f:,.2f}")
    # KPI fractions (e.g. a rate stored as 0.084) are often narrated as a
    # percentage (8.4%) -- accept both scales.
    if -1.0 <= f <= 1.0:
        pct = f * 100
        for nd in range(0, 3):
            variants.add(f"{pct:.{nd}f}")
    return variants


def build_grounding_set(kpis):
    """
    Collect every number that legitimately appears in kpis.json, in every
    reasonable formatting. Free-prose string fields are not scanned for
    digit substrings; the sole exception is a whole-string ISO date field
    (period_start / period_end):
      - its year alone is grounded, so a model can reference the year in
        prose without tripping the check;
      - the exact date token itself (e.g. "2025-06-30") is also tracked
        separately in `grounded_date_tokens`, so a model that repeats the
        whole date verbatim doesn't get its day/month flagged as stray
        numbers -- but "30" or "06" appearing on their own (not as part of
        that exact date token) are NOT grounded, since those are date
        components, not data points.
    """
    flat = _flatten(kpis)
    grounded_strings = set()
    grounded_floats = []
    grounded_date_tokens = set()
    for value in flat.values():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            grounded_strings |= _numeric_variants(value)
            grounded_floats.append(float(value))
        elif isinstance(value, str):
            date_match = _DATE_RE.match(value.strip())
            if date_match:
                year = date_match.group(1)
                grounded_strings.add(year)
                grounded_floats.append(float(year))
                grounded_date_tokens.add(value.strip())
    return grounded_strings, grounded_floats, grounded_date_tokens


def _is_grounded(literal, grounded_strings, grounded_floats):
    had_percent = literal.endswith('%')
    core = literal.lstrip('$').rstrip('%').replace(',', '')
    if core == '':
        return True
    try:
        val = float(core)
    except ValueError:
        return True  # not actually numeric (e.g. a stray '$'); not our concern here

    if core in grounded_strings:
        return True
    if had_percent:
        for nd in range(0, 3):
            if f"{val:.{nd}f}" in grounded_strings:
                return True

    # Absolute epsilon only. A relative tolerance scales with the value, so on a
    # figure like 253080 a 0.5% band would silently accept 254000 -- exactly the
    # kind of drift this validator exists to catch. Legitimate rounding is
    # already covered by the 0-3 decimal string variants.
    tolerance_targets = [val]
    if had_percent:
        tolerance_targets.append(val / 100.0)
    for target in tolerance_targets:
        for g in grounded_floats:
            if abs(target - g) <= 0.01:
                return True
    return False


def find_ungrounded_numbers(text, grounded_strings, grounded_floats, grounded_date_tokens=()):
    """Return the list of numeric literals in `text` that aren't backed by kpis.json."""
    # Blank out exact reproductions of grounded date tokens first, so a model
    # writing the literal period_start/period_end date verbatim doesn't have
    # its day/month components flagged as stray numbers. A "30" that appears
    # outside of one of these exact date tokens is untouched and still checked.
    scrubbed = text
    for token in grounded_date_tokens:
        scrubbed = scrubbed.replace(token, '')

    ungrounded = []
    for m in _NUMBER_RE.finditer(scrubbed):
        literal = m.group(0)
        tail = scrubbed[m.end():m.end() + 2]
        if _ORDINAL_SUFFIX_RE.match(tail):
            continue  # "1st", "2nd", "3rd", "4th" -- ranking language, not a data claim
        if not _is_grounded(literal, grounded_strings, grounded_floats):
            ungrounded.append(literal)
    return ungrounded


# --------------------------------------------------------------------------
# Response validation
# --------------------------------------------------------------------------

def validate_briefing(response, kpis):
    """
    Validate a parsed model response against kpis.json. Raises GroundingError
    with a specific reason on any failure; returns True if the response is
    fully grounded.
    """
    if not isinstance(response, dict):
        raise GroundingError("response is not a JSON object")

    if set(response.keys()) != REQUIRED_KEYS:
        missing = REQUIRED_KEYS - set(response.keys())
        extra = set(response.keys()) - REQUIRED_KEYS
        raise GroundingError(
            f"response must have exactly the keys {sorted(REQUIRED_KEYS)}; "
            f"missing={sorted(missing)} extra={sorted(extra)}"
        )

    summary = response["summary"]
    risks = response["risks"]
    recommendations = response["recommendations"]
    evidence = response["evidence"]

    if not isinstance(summary, str) or not summary.strip():
        raise GroundingError("'summary' must be a non-empty string")
    if not isinstance(risks, list) or not all(isinstance(r, str) for r in risks):
        raise GroundingError("'risks' must be a list of strings")
    if not isinstance(evidence, list) or not all(isinstance(e, str) for e in evidence):
        raise GroundingError("'evidence' must be a list of strings")
    if not isinstance(recommendations, list) or not recommendations:
        raise GroundingError("'recommendations' must be a non-empty list")

    valid_fields = _valid_fields(kpis)

    for e in evidence:
        if e not in valid_fields:
            raise GroundingError(f"'evidence' cites unknown KPI field: {e!r}")

    for i, rec in enumerate(recommendations):
        if not isinstance(rec, dict) or "text" not in rec or "evidence" not in rec:
            raise GroundingError(f"recommendations[{i}] must be an object with 'text' and 'evidence'")
        if not isinstance(rec["text"], str) or not rec["text"].strip():
            raise GroundingError(f"recommendations[{i}].text must be a non-empty string")
        rec_evidence = rec["evidence"]
        if not isinstance(rec_evidence, list) or not rec_evidence:
            raise GroundingError(f"recommendations[{i}] has no evidence entry")
        for field in rec_evidence:
            if not isinstance(field, str) or field not in valid_fields:
                raise GroundingError(f"recommendations[{i}] cites unknown KPI field: {field!r}")

    grounded_strings, grounded_floats, grounded_date_tokens = build_grounding_set(kpis)
    prose_blocks = [summary] + risks + [rec["text"] for rec in recommendations]
    for block in prose_blocks:
        bad = find_ungrounded_numbers(block, grounded_strings, grounded_floats, grounded_date_tokens)
        if bad:
            raise GroundingError(f"ungrounded numeric literal(s) {bad} in: {block!r}")

    return True


# --------------------------------------------------------------------------
# Model call
# --------------------------------------------------------------------------

def _build_prompt(kpis):
    field_names = sorted(_valid_fields(kpis))
    return (
        "You are writing a short executive briefing for an e-commerce analytics team.\n\n"
        "You may use ONLY the figures in KPI_DATA below. Do not use, compute, or estimate "
        "any number, percentage, or figure that is not already present in KPI_DATA. Every "
        "recommendation must cite the KPI field name(s) (from AVAILABLE_FIELDS) that support it.\n\n"
        f"AVAILABLE_FIELDS:\n{json.dumps(field_names)}\n\n"
        f"KPI_DATA:\n{json.dumps(kpis, sort_keys=True)}\n\n"
        "Respond with ONLY a JSON object (no markdown fences, no commentary) with exactly "
        "these top-level keys:\n"
        '- "summary": a short string overview\n'
        '- "risks": a list of strings\n'
        '- "recommendations": a list of objects, each '
        '{"text": string, "evidence": [field names from AVAILABLE_FIELDS cited]}\n'
        '- "evidence": a list of field names from AVAILABLE_FIELDS that ground the summary/risks\n\n'
        "Every number you write in \"summary\", \"risks\", or a recommendation's \"text\" must "
        "already appear in KPI_DATA (any reasonable formatting -- rounding, %, $, thousands "
        "separators are fine). Do not invent a figure that isn't in KPI_DATA.\n\n"
        "Write the prose for a business reader. Do NOT put raw field names such as "
        "\"gross_revenue_total\" or \"repeat_customer_rate_pct\" into \"summary\", \"risks\" or "
        "a recommendation's \"text\" -- say \"gross revenue\" or \"repeat-customer rate\" "
        "instead. Field names belong only in the \"evidence\" lists, which is where the "
        "citation is recorded.\n"
        "State what a figure implies rather than restating it. If a figure looks "
        "implausible for a real business, say so plainly instead of building a "
        "recommendation on it."
    )


def _parse_json_response(raw_text):
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?", "", text).strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    return json.loads(text)  # a malformed response raises json.JSONDecodeError


def request_briefing(kpis, client=None, model=MODEL):
    """Request a briefing and retain the provider's response and usage metadata."""
    if client is None:
        load_dotenv()
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set (checked the environment and .env). "
                "Refusing to fabricate or stub a briefing."
            )
        client = anthropic.Anthropic(api_key=api_key)

    return client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": _build_prompt(kpis)}],
    )


def generate_briefing(kpis, client=None):
    """Request, parse, and validate a briefing against the supplied KPIs."""
    response = request_briefing(kpis, client=client)
    raw_text = "".join(block.text for block in response.content if block.type == "text")
    parsed = _parse_json_response(raw_text)
    validate_briefing(parsed, kpis)
    return parsed


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def _render_markdown(briefing, kpis):
    flat = _flatten(kpis)
    lines = [
        "# Executive Briefing",
        "",
        f"_Period: {kpis['period_start']} to {kpis['period_end']}_",
        "",
        "## Summary",
        "",
        briefing["summary"],
        "",
        "## Risks",
        "",
    ]
    for r in briefing["risks"]:
        lines.append(f"- {r}")
    lines += ["", "## Recommendations", ""]
    for rec in briefing["recommendations"]:
        cited = ", ".join(rec["evidence"])
        lines.append(f"- {rec['text']} (evidence: {cited})")
    lines += ["", "## Evidence", ""]
    for e in briefing["evidence"]:
        value = flat.get(e, kpis.get(e))
        lines.append(f"- `{e}` = {json.dumps(value)}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# CLI entry point
# --------------------------------------------------------------------------

def main():
    # Serving an already-validated report does not need warehouse dependencies.
    from src.insights.kpis import write_kpis

    kpis = write_kpis()

    try:
        briefing = generate_briefing(kpis)
    except GroundingError as e:
        print(f"REJECTED (grounding validation failed): {e}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"REJECTED (model response was not valid JSON): {e}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(PATHS['reports'], exist_ok=True)
    with open(BRIEFING_JSON_PATH, 'w') as f:
        json.dump(briefing, f, indent=2)
        f.write('\n')
    with open(BRIEFING_MD_PATH, 'w') as f:
        f.write(_render_markdown(briefing, kpis))

    print(f"Wrote {BRIEFING_JSON_PATH} and {BRIEFING_MD_PATH}")


if __name__ == '__main__':
    main()
