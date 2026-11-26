"""End-to-end over HTTP: the server answers, /health works, and queries never reach the logs."""

import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from personal_brain.logcheck import find_leaks, run_check

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "records"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def http_server(tmp_path):
    port = _free_port()
    log_path = tmp_path / "server.log"
    log = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "personal_brain.cli", "serve",
            "--transport", "http", "--port", str(port),
            "--records", str(EXAMPLES), "--db", str(tmp_path / "index.db"),
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(f"{base}/health", timeout=1)
            break
        except OSError:
            if proc.poll() is not None:
                raise RuntimeError(log_path.read_text(encoding="utf-8"))
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("server did not start")
    yield base, log_path
    proc.terminate()
    proc.wait(timeout=10)
    log.close()


def test_health_endpoint(http_server):
    base, _ = http_server
    with urllib.request.urlopen(f"{base}/health", timeout=3) as response:
        assert response.read() == b"ok"


def test_query_terms_never_reach_the_logs(http_server):
    base, log_path = http_server
    leaks = run_check(f"{base}/mcp", lambda: log_path.read_text(encoding="utf-8", errors="replace"))
    assert leaks == []


def test_find_leaks_detects_terms():
    assert find_leaks("GET /x canaryabc", ["canaryabc", "canaryxyz"]) == ["canaryabc"]
