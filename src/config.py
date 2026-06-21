"""Central config — loads settings and the Claude API key from .env or environment."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Project paths
ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_DIR = ROOT / "candidates"
DATA_DIR = ROOT / "data"
CONFIG_DIR = ROOT / "config"

load_dotenv(ROOT / ".env")  # optional; env vars also work without a .env file


# ----- Claude model tiers (per master plan §14 cost strategy) -----
# Cheap extraction/scoring -> Haiku;  quality writing/answers -> Sonnet;  premium -> Opus.
MODEL_CHEAP = os.getenv("MODEL_CHEAP", "claude-haiku-4-5-20251001")
MODEL_SMART = os.getenv("MODEL_SMART", "claude-sonnet-4-6")
MODEL_PREMIUM = os.getenv("MODEL_PREMIUM", "claude-opus-4-8")


# Live-apply safety switch. While testing (default) real submissions are DISABLED so we
# never fire a real application with dummy test contact. Set APPLYPILOT_LIVE=1 to go live.
LIVE_APPLY = os.getenv("APPLYPILOT_LIVE", "").strip().lower() in ("1", "true", "yes", "on")


def get_api_key() -> str:
    """Return the Anthropic API key or raise a clear error."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not found. Set it in your environment or in a .env file "
            "at the project root (ANTHROPIC_API_KEY=sk-ant-...)."
        )
    return key


def candidate_dir(name: str) -> Path:
    """Per-candidate folder (git-ignored). Slugifies the name."""
    slug = "".join(c if c.isalnum() else "_" for c in name).strip("_").lower()
    d = CANDIDATES_DIR / slug
    d.mkdir(parents=True, exist_ok=True)
    return d
