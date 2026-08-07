"""Evaluation harness (spec §34.x, OS-034).

Runs fixture cases through agent rubrics, compares lineages, scores
composer editions, and produces a cost report.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
RUBRICS_PATH = REPO_ROOT / "infra" / "eval" / "rubrics.yaml"
CASES_DIR = REPO_ROOT / "fixtures" / "eval_cases"

# guardrail patterns shared with security/hardening
_GUARDRAIL_PATTERNS = [
    re.compile(r"(建议|推荐).{0,6}(买入|卖出|持有|加仓|减仓)"),
    re.compile(r"(恐慌|贪婪|信心不足|情绪低落|情绪高涨)"),
]


class EvalError(Exception):
    pass


# ------------------------------------------------------------- fixture cases
def load_cases(cases_dir: Path | str | None = None) -> list[dict[str, Any]]:
    base = Path(cases_dir) if cases_dir else CASES_DIR
    cases: list[dict[str, Any]] = []
    for path in sorted(base.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        cases.extend(data.get("cases", []))
    return cases


def load_rubrics(path: Path | str | None = None) -> dict[str, Any]:
    with (Path(path) if path else RUBRICS_PATH).open(encoding="utf-8") as f:
        return yaml.safe_load(f)


# ----------------------------------------------------------- agent scoring
def score_agent_output(
    output: dict[str, Any],
    case: dict[str, Any],
    rubrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score one agent output against a fixture case using the rubrics."""
    rubrics = rubrics or load_rubrics()
    rubric_defs = rubrics.get("rubrics", [])
    expected = case.get("golden_output", {})

    scores: dict[str, float] = {}
    for rubric in rubric_defs:
        key = rubric["score_key"]
        if key == "evidence_grounding":
            scores[key] = _score_evidence_grounding(output, case)
        elif key == "guardrail_compliance":
            scores[key] = _score_guardrails(output)
        elif key == "numerical_accuracy":
            scores[key] = _score_numerical(output, case)
        elif key == "conciseness":
            scores[key] = _score_conciseness(output)
        else:
            scores[key] = 0.0

    weighted = sum(scores[k] * r["weight"] for r in rubric_defs for k in [r["score_key"]])
    total_weight = sum(r["weight"] for r in rubric_defs)
    final = weighted / total_weight if total_weight else 0.0
    threshold = rubrics.get("threshold_pass", 0.7)

    return {
        "case_id": case.get("id"),
        "scores": {k: round(v, 4) for k, v in scores.items()},
        "weighted_score": round(final, 4),
        "passed": final >= threshold,
    }


def _score_evidence_grounding(output: dict[str, Any], case: dict[str, Any]) -> float:
    # abstaining with a reason is evidence-grounded by definition
    if output.get("persistence") == "abstain" or output.get("verdict") == "abstain":
        return 0.8 if output.get("reason") else 0.2
    text = json.dumps(output, ensure_ascii=False)
    bundle = case.get("input", {}).get("evidence_bundle_id")
    if bundle and bundle in text:
        return 1.0
    metrics = case.get("input", {}).get("metrics", {})
    # observable probabilities cited in the observation anchor the output
    for key in ("start_probability", "current_probability", "delta_24h"):
        value = metrics.get(key)
        if value is not None and str(value) in text:
            return 1.0
    return 0.0


def _score_guardrails(output: dict[str, Any]) -> float:
    text = json.dumps(output, ensure_ascii=False)
    if any(p.search(text) for p in _GUARDRAIL_PATTERNS):
        return 0.0
    return 1.0


def _score_numerical(output: dict[str, Any], case: dict[str, Any]) -> float:
    """Output values must match the fixture's expected outcome labels."""
    expected = case.get("golden_output", {})
    for field in ("persistence", "noise_check"):
        if field in expected and output.get(field) != expected[field]:
            return 0.0
    return 1.0


def _score_conciseness(output: dict[str, Any]) -> float:
    observation = output.get("observation") or ""
    if len(observation) > 300:
        return 0.3
    if len(observation) > 150:
        return 0.7
    return 1.0


# ---------------------------------------------------------- lineage comparison
def compare_lineages(
    lineage_a: dict[str, Any],
    lineage_b: dict[str, Any],
    case: dict[str, Any],
) -> dict[str, Any]:
    """Compare two lineages' outputs on one case."""
    rubrics = load_rubrics()
    score_a = score_agent_output(lineage_a, case, rubrics)
    score_b = score_agent_output(lineage_b, case, rubrics)
    return {
        "case_id": case.get("id"),
        "lineage_a": score_a,
        "lineage_b": score_b,
        "winner": "a" if score_a["weighted_score"] > score_b["weighted_score"] else (
            "b" if score_b["weighted_score"] > score_a["weighted_score"] else "tie"
        ),
    }


# --------------------------------------------------------- composer scoring
def score_edition(edition_payload: dict[str, Any]) -> dict[str, Any]:
    """Score a composer edition: component presence, slot coverage, diversity."""
    slots = edition_payload.get("slots", {}) or {}
    lead = edition_payload.get("lead")
    sections = edition_payload.get("sections", []) or []

    score_component = 1.0 if slots else 0.0
    score_lead = 1.0 if lead else 0.0
    score_slots = min(1.0, len(slots) / 3.0)
    score_diversity = min(1.0, len(sections) / 2.0)

    final = 0.3 * score_component + 0.3 * score_lead + 0.2 * score_slots + 0.2 * score_diversity
    return {
        "component_score": round(score_component, 4),
        "lead_score": round(score_lead, 4),
        "slot_coverage": round(score_slots, 4),
        "section_diversity": round(score_diversity, 4),
        "edition_score": round(final, 4),
    }


# ------------------------------------------------------------ cost report
def cost_report(engine: Any, days: int = 30) -> dict[str, Any]:
    """Cost report from investigation_runs spend."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import text

    since = datetime.now(timezone.utc) - timedelta(days=days)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT desk_id, model_version, count(*), "
                "coalesce(sum(estimated_cost_usd), 0), "
                "coalesce(sum(total_input_tokens), 0), coalesce(sum(total_output_tokens), 0) "
                "FROM investigation_runs WHERE started_at >= :since "
                "GROUP BY desk_id, model_version ORDER BY desk_id"
            ),
            {"since": since},
        ).fetchall()

    by_desk: dict[str, dict[str, Any]] = {}
    total_cost = 0.0
    for desk, model, count, cost, in_tokens, out_tokens in rows:
        entry = by_desk.setdefault(
            desk,
            {"runs": 0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "by_model": {}},
        )
        entry["runs"] += count
        entry["cost_usd"] += float(cost)
        entry["input_tokens"] += in_tokens or 0
        entry["output_tokens"] += out_tokens or 0
        entry["by_model"][model] = {"runs": count, "cost_usd": round(float(cost), 4)}
        total_cost += float(cost)

    return {
        "window_days": days,
        "total_cost_usd": round(total_cost, 4),
        "by_desk": {
            desk: {**v, "cost_usd": round(v["cost_usd"], 4)} for desk, v in by_desk.items()
        },
    }
