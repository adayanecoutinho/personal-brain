"""Retrieval evaluation (docs/adr/013-evaluation.md).

Runs a fixed set of cases through `search` and measures what the server controls:
whether the right records come back, with the right status, inside the caller's
scope. Answer quality of the client model is evaluated separately.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .search import search

TOP_K = 5


@dataclass
class CaseResult:
    id: str
    category: str
    gating: bool
    passed: bool
    reasons: list[str] = field(default_factory=list)
    reciprocal_rank: float | None = None


def load_cases(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = data["cases"]
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids")
    return cases


def run_case(db: Path, case: dict) -> CaseResult:
    scope = case.get("scope")
    results = search(db, case["query"], TOP_K, scope)
    got_ids = [r["id"] for r in results]
    reasons: list[str] = []

    # Scope is checked on every case, whatever else it expects.
    if scope is not None:
        leaked = [r["id"] for r in results if r["domain"] not in scope]
        if leaked:
            reasons.append("scope_violation")

    reciprocal_rank = None
    if case.get("expect_empty"):
        if results:
            reasons.append("expected_empty")
    else:
        expected = case.get("expected_ids", [])
        missing = [i for i in expected if i not in got_ids]
        if missing:
            reasons.append("missing_expected")
        ranks = [got_ids.index(i) + 1 for i in expected if i in got_ids]
        reciprocal_rank = 1 / min(ranks) if ranks else 0.0

        status = case.get("expected_status")
        if status:
            wrong = [r for r in results if r["id"] in expected and r["review_status"] != status]
            if wrong:
                reasons.append("wrong_status")

    forbidden = set(case.get("forbid_types", []))
    if forbidden and any(r["event_type"] in forbidden for r in results):
        reasons.append("forbidden_type")

    return CaseResult(
        id=case["id"],
        category=case["category"],
        gating=case.get("gating", True),
        passed=not reasons,
        reasons=reasons,
        reciprocal_rank=reciprocal_rank,
    )


def evaluate(db: Path, cases: list[dict]) -> dict:
    results = [run_case(db, case) for case in cases]
    by_category: dict[str, list[CaseResult]] = defaultdict(list)
    for result in results:
        by_category[result.category].append(result)

    gating = [r for r in results if r.gating]
    ranked = [r.reciprocal_rank for r in gating if r.reciprocal_rank is not None]
    return {
        "top_k": TOP_K,
        "cases": len(results),
        "gating_cases": len(gating),
        "gating_passed": sum(r.passed for r in gating),
        "scope_violations": sum("scope_violation" in r.reasons for r in results),
        "mrr": round(sum(ranked) / len(ranked), 3) if ranked else None,
        "categories": {
            name: {
                "passed": sum(r.passed for r in items),
                "total": len(items),
                "gating": all(r.gating for r in items),
            }
            for name, items in sorted(by_category.items())
        },
        "failures": [
            {"id": r.id, "category": r.category, "gating": r.gating, "reasons": r.reasons}
            for r in results
            if not r.passed
        ],
    }


def is_passing(report: dict) -> bool:
    return report["scope_violations"] == 0 and report["gating_passed"] == report["gating_cases"]


def to_markdown(report: dict) -> str:
    lines = [
        f"Cases: {report['cases']} · gating passed: "
        f"{report['gating_passed']}/{report['gating_cases']} · "
        f"scope violations: {report['scope_violations']} · MRR: {report['mrr']}",
        "",
        "| Category | Passed | Gating |",
        "|---|---|---|",
    ]
    for name, stats in report["categories"].items():
        gate = "yes" if stats["gating"] else "no (informational)"
        lines.append(f"| {name} | {stats['passed']}/{stats['total']} | {gate} |")
    return "\n".join(lines) + "\n"
