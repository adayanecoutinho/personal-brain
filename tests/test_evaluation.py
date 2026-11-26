from pathlib import Path

from personal_brain.cli import main
from personal_brain.evaluation import evaluate, is_passing, load_cases, run_case
from personal_brain.search import search

CASES = Path(__file__).resolve().parent.parent / "eval" / "cases.fictional.yaml"


def test_fictional_set_passes_every_gating_case(db):
    report = evaluate(db, load_cases(CASES))
    assert report["scope_violations"] == 0
    assert report["gating_passed"] == report["gating_cases"]
    assert is_passing(report)


def test_paraphrases_are_informational_and_currently_fail(db):
    report = evaluate(db, load_cases(CASES))
    paraphrase = report["categories"]["paraphrase"]
    assert paraphrase["gating"] is False
    assert paraphrase["passed"] == 0  # documents the limit of keyword search (ADR 003)


def test_a_missing_expected_record_fails_the_case(db):
    case = {
        "id": "x", "category": "scope", "query": "blood count",
        "scope": ["training"], "expected_ids": ["exam-2026-04-02-blood"],
    }
    result = run_case(db, case)
    assert not result.passed and "missing_expected" in result.reasons


def test_eval_cli_exit_code(tmp_path, examples_dir):
    out = tmp_path / "results.md"
    code = main(["eval", "--cases", str(CASES), "--records", str(examples_dir), "--markdown", str(out)])
    assert code == 0
    assert "scope violations: 0" in out.read_text(encoding="utf-8")


def test_search_releases_the_database_file(db):
    search(db, "blood")
    db.unlink()  # fails on Windows if a connection were left open
