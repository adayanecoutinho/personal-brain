from pathlib import Path

import pytest

from personal_brain.index import build_index

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "records"


@pytest.fixture
def examples_dir() -> Path:
    return EXAMPLES


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "index.db"
    build_index(EXAMPLES, path)
    return path
