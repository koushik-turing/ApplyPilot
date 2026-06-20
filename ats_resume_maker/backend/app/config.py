"""App settings, read from environment with sane local defaults.

Loads a .env file (if present) so secrets like ANTHROPIC_API_KEY don't have to be
exported manually each session. Never hardcode the key here.
"""
from __future__ import annotations
import os

try:  # optional — lets a local .env populate the environment (.env wins if present)
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass


class Settings:
    # Where the browser app is served from (used for CORS). The backend also
    # serves the frontend itself, so same-origin requests need no CORS at all.
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:8000")

    # --- Claude API (best quality; paid, optional) ---
    # The API key itself is read by the SDK from the ANTHROPIC_API_KEY env var.
    # CLAUDE_MODEL is the general default; the two AI tasks can each override it
    # to run a cheaper tier (the ATS score itself is offline/deterministic and
    # uses no model). Tiered default = Sonnet for tailoring (quality writing),
    # Haiku for the review card (lighter analysis) — ~balanced cost vs quality.
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-opus-4-8")
    # Tailoring is the deliverable — default to Opus for top quality (the critic->refine
    # loop makes the extra cost worth it). Set CLAUDE_TAILOR_MODEL=claude-sonnet-4-6 to save cost.
    claude_tailor_model: str = os.getenv(
        "CLAUDE_TAILOR_MODEL", os.getenv("CLAUDE_MODEL", "claude-opus-4-8")
    )
    claude_review_model: str = os.getenv(
        "CLAUDE_REVIEW_MODEL", os.getenv("CLAUDE_MODEL", "claude-haiku-4-5")
    )

    # --- Local Ollama (free, optional fallback) ---
    llm_model: str = os.getenv("LLM_MODEL", "llama3.1")
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")


settings = Settings()
