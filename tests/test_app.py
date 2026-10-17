"""Render the whole dashboard headlessly. Each mode runs in a fresh interpreter, because the
runs directory is read from the environment when readback.config is first imported."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

RENDER = """
import json
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("app.py", default_timeout=120).run()
print(json.dumps({
    "exceptions": [str(e.value)[:300] for e in at.exception],
    "info": [i.value for i in at.info],
    "metrics": [m.value for m in at.metric],
}))
"""


def render(env_overrides: dict) -> dict:
    env = {**os.environ, **env_overrides}
    out = subprocess.run([sys.executable, "-c", RENDER], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not (ROOT / "results").exists(), reason="no results snapshot")
def test_fresh_clone_uses_the_snapshot(tmp_path):
    page = render({"READBACK_RUNS_DIR": str(tmp_path)})  # an empty runs/ is what a clone has
    assert page["exceptions"] == []
    assert any("published results" in i for i in page["info"])
    assert "53%" in page["metrics"] and "99%" in page["metrics"]


@pytest.mark.skipif(not any((ROOT / "runs").glob("2026*")), reason="no local runs")
def test_with_local_runs():
    page = render({})
    assert page["exceptions"] == []
    assert page["metrics"], "scorecard metrics should render"
