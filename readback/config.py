"""Paths and credentials shared across Readback."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / ".cache"
RUNS_DIR = Path(os.environ.get("READBACK_RUNS_DIR", ROOT / "runs"))
# Text-only copies of the published runs, committed so the dashboard works from a fresh clone with no API key.
SNAPSHOT_DIR = ROOT / "results"

load_dotenv(ROOT / ".env")


def api_key() -> str:
    key = os.environ.get("ASSEMBLYAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "ASSEMBLYAI_API_KEY is not set. Copy .env.example to .env and paste your key."
        )
    return key
