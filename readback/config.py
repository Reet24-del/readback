"""Paths and credentials shared across Readback."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / ".cache"
RUNS_DIR = ROOT / "runs"

load_dotenv(ROOT / ".env")


def api_key() -> str:
    key = os.environ.get("ASSEMBLYAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "ASSEMBLYAI_API_KEY is not set. Copy .env.example to .env and paste your key."
        )
    return key
