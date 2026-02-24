"""
Central configuration for the Apollo pipeline.
Edit this file to tune keywords, model, and thresholds.
"""

# ── arXiv ─────────────────────────────────────────────────────────────────────
ARXIV_CATEGORY = "cs.AI"
MAX_FETCH_RESULTS = 2000         # Hard cap per arXiv query call (pagination handled automatically)

# ── Layer 1: keyword filter ───────────────────────────────────────────────────
KEYWORDS = [
    "multi-agent",
    "diffusion",
    "alignment",
    "llm",
    "rlhf",
    "reasoning",
    "rag",
    "transformer",
    "memory",
    "retrieval",
]

# ── Layer 2: author boost ─────────────────────────────────────────────────────
AUTHOR_BOOST_PER_MATCH = 3       # Score added per high-impact author in paper

# ── Layer 3: LLM scoring ──────────────────────────────────────────────────────
GEMINI_SCORER_MODEL = "gemma-3-27b-it"   # 14,400 RPD free tier vs 20 RPD for Flash Lite
SCORING_CANDIDATE_LIMIT = 150    # Max papers sent to model for scoring
TARGET_PAPERS = 25               # Final papers in digest

LLM_SCORING_PROMPT = (
    "Rate this paper from 1–10 for potential research impact based on novelty, "
    "scope, methodological rigor, and broader implications. "
    'Return JSON only, no other text: {"score": <int 1-10>, "reason": "<one sentence>"}'
)

# ── Scheduling ────────────────────────────────────────────────────────────────
ANCHOR_DAYS = [1, 15]            # Day-of-month anchor dates for biweekly schedule

# ── Paths ─────────────────────────────────────────────────────────────────────
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
DATA_DIR = ROOT_DIR / "data"
DIGESTS_DIR = ROOT_DIR / "digests"
DOCS_DIR = ROOT_DIR / "docs"
TEMPLATES_DIR = ROOT_DIR / "templates"

PIPELINE_DB = DATA_DIR / "pipeline.db"

# ── ZeroClaw ──────────────────────────────────────────────────────────────────
ZEROCLAW_CONFIG = ROOT_DIR / "zeroclaw" / "config.toml"
ZEROCLAW_MEMORY_LIMIT = 100      # Max paper chunks stored in ZeroClaw memory
