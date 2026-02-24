"""
Stores paper data into ZeroClaw memory via CLI subprocess calls.
Never writes directly to ZeroClaw's SQLite DB — always goes through the CLI.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sqlite3
from pathlib import Path
from typing import Any

from apollo.config.settings import ZEROCLAW_MEMORY_LIMIT

logger = logging.getLogger(__name__)

_ZEROCLAW_BIN = "zeroclaw"
_ZEROCLAW_BRAIN_DB = Path.home() / ".zeroclaw" / "workspace" / "memory" / "brain.db"


def _entry_already_stored(search_pattern: str) -> bool:
    """Check if a memory matching the SQLite LIKE pattern already exists in ZeroClaw."""
    if not _ZEROCLAW_BRAIN_DB.exists():
        return False
    try:
        conn = sqlite3.connect(str(_ZEROCLAW_BRAIN_DB))
        row = conn.execute(
            "SELECT 1 FROM memories WHERE content LIKE ?", (search_pattern,)
        ).fetchone()
        conn.close()
        return row is not None
    except Exception as e:
        logger.warning(f"Could not check ZeroClaw brain.db for duplicates: {e}")
        return False


def _run_zeroclaw(message: str) -> bool:
    """
    Call `zeroclaw agent --message <message>` to store a memory entry.
    Returns True on success, False on failure.
    """
    try:
        env = os.environ.copy()
        result = subprocess.run(
            [_ZEROCLAW_BIN, "agent", "--message", message],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        if result.returncode != 0:
            logger.warning(
                f"zeroclaw exited {result.returncode}: {result.stderr.strip()}"
            )
            return False
        return True
    except FileNotFoundError:
        logger.error(
            "zeroclaw not found in PATH. Install with: brew install zeroclaw"
        )
        return False
    except subprocess.TimeoutExpired:
        logger.error("zeroclaw CLI call timed out after 120s")
        return False


def _paper_memory_message(paper: dict[str, Any]) -> str:
    """Build the memory store prompt for a single paper."""
    authors_preview = ", ".join(paper["authors"][:4])
    if len(paper["authors"]) > 4:
        authors_preview += " et al."

    payload = {
        "type": "research_paper",
        "id": paper["id"],
        "title": paper["title"],
        "authors": authors_preview,
        "abstract": paper["abstract"][:800],
        "submitted": paper["submitted"],
        "url": paper["url"],
        "impact_score": paper["final_score"],
        "llm_score": paper["llm_score"],
        "llm_reason": paper["llm_reason"],
    }
    return f"Remember this research paper: {json.dumps(payload)}"


def _digest_summary_message(cycle_id: str, papers: list[dict[str, Any]], digest_url: str) -> str:
    """Build the memory store prompt for the full digest summary."""
    top_titles = [p["title"][:80] for p in papers[:5]]
    payload = {
        "type": "digest_summary",
        "cycle_id": cycle_id,
        "paper_count": len(papers),
        "top_papers": top_titles,
        "digest_url": digest_url,
    }
    return f"Remember this research digest: {json.dumps(payload)}"


def store_papers(papers: list[dict[str, Any]], cycle_id: str, digest_url: str) -> int:
    """
    Store each of the 25 papers + one digest summary into ZeroClaw memory.

    ZeroClaw manages its own memory limit internally, but we cap at
    ZEROCLAW_MEMORY_LIMIT total entries. Since ZeroClaw uses FIFO/score-based
    eviction internally with auto_save, we simply write all entries and let
    ZeroClaw handle eviction.

    Returns the number of successfully stored entries.
    """
    stored = 0
    total = len(papers) + 1  # papers + digest summary

    print(f"[memory] Storing {total} entries in ZeroClaw memory...")

    for i, paper in enumerate(papers, 1):
        # 1. Check for duplicate before storing
        paper_id = paper["id"]
        search_pattern = f'%\"id\": \"{paper_id}\"%'
        if _entry_already_stored(search_pattern):
            logger.info(f"Paper {paper_id} already exists in memory. Skipping.")
            print(f"[memory] {i}/{len(papers)} skipped (already stored)")
            continue

        # 2. Store if not found
        message = _paper_memory_message(paper)
        success = _run_zeroclaw(message)
        if success:
            stored += 1
            print(f"[memory] {i}/{len(papers)} stored")
        else:
            logger.warning(f"Failed to store paper {paper_id} in ZeroClaw")

    # Store digest summary
    summary_pattern = f'%\"type\": \"digest_summary\"%\"cycle_id\": \"{cycle_id}\"%'
    if _entry_already_stored(summary_pattern):
        logger.info(f"Digest summary for {cycle_id} already exists in memory. Skipping.")
        print("[memory] Digest summary skipped (already stored)")
    else:
        summary_msg = _digest_summary_message(cycle_id, papers, digest_url)
        if _run_zeroclaw(summary_msg):
            stored += 1
            print("[memory] Digest summary stored")
        else:
            logger.warning("Failed to store digest summary in ZeroClaw")

    print(f"[memory] Done — {stored}/{total} entries stored successfully")
    return stored
