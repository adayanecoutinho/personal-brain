"""CLI behaviour around invalid records: no file names by default, no outage on a bad rebuild."""

import shutil
import subprocess
import sys
from pathlib import Path

from personal_brain.cli import main
from personal_brain.search import search

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "records"
SENSITIVE_NAME = "health/encounters/very-private-name.md"


def _records_with_one_invalid(tmp_path: Path) -> Path:
    records = tmp_path / "records"
    shutil.copytree(EXAMPLES, records)
    bad = records / SENSITIVE_NAME
    bad.write_text("no front matter here", encoding="utf-8")
    return records


def test_validate_reports_codes_without_file_names(tmp_path, capsys):
    records = _records_with_one_invalid(tmp_path)
    assert main(["validate", "--records", str(records)]) == 1
    err = capsys.readouterr().err
    assert "valid: 15  invalid: 1" in err
    assert "missing_front_matter: 1" in err
    assert "very-private-name" not in err


def test_show_paths_names_the_file(tmp_path, capsys):
    records = _records_with_one_invalid(tmp_path)
    main(["validate", "--records", str(records), "--show-paths"])
    assert "very-private-name" in capsys.readouterr().err


def test_build_failure_keeps_the_index_and_hides_names(tmp_path, capsys):
    db = tmp_path / "index.db"
    assert main(["build", "--records", str(EXAMPLES), "--db", str(db)]) == 0
    records = _records_with_one_invalid(tmp_path)
    assert main(["build", "--records", str(records), "--db", str(db)]) == 1
    err = capsys.readouterr().err
    assert "BUILD_FAILED" in err and "very-private-name" not in err
    assert search(db, "moisturizer")  # previous index untouched


def test_serve_falls_back_to_previous_index(tmp_path):
    db = tmp_path / "index.db"
    assert main(["build", "--records", str(EXAMPLES), "--db", str(db)]) == 0
    records = _records_with_one_invalid(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, "-m", "personal_brain.cli", "serve",
         "--records", str(records), "--db", str(db)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    _, err = proc.communicate(input="", timeout=30)  # stdio server exits when stdin closes
    assert "SERVING_PREVIOUS_INDEX" in err
    assert "very-private-name" not in err


def test_serve_without_any_index_refuses_to_start(tmp_path):
    records = _records_with_one_invalid(tmp_path)
    code = main(["serve", "--records", str(records), "--db", str(tmp_path / "none.db")])
    assert code == 1
