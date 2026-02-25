#!/usr/bin/env python3
"""
Apollo — Biweekly AI Research Newsletter Runner
================================================
Entry point. Run this file on or after the 1st or 15th of each month.

Implements:
  - cycle_id guard  → exits immediately if this period was already run
  - run-if-missed   → if computer was off on the anchor date, the arXiv
                      query window expands to cover the full gap
  - Full pipeline   → fetch → filter → score → memory → digest → announce

Usage:
    python run_biweekly.py           # Normal run
    python run_biweekly.py --dry-run # Fetch + score but skip git push & memory storage
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import urllib.request
from datetime import date, timedelta

from dotenv import load_dotenv

load_dotenv()

from apollo.config.settings import ANCHOR_DAYS, DATA_DIR, PIPELINE_DB
from apollo.pipeline.arxiv_fetcher import fetch_papers
from apollo.pipeline.digest_builder import build_and_publish
from apollo.pipeline.filters import apply_filters
from apollo.pipeline.memory_writer import store_papers
from apollo.pipeline.scorer import score_papers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("apollo")


# ── DB helpers ────────────────────────────────────────────────────────────────

def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            cycle_id          TEXT PRIMARY KEY,
            anchor_date       TEXT NOT NULL,
            since_date        TEXT NOT NULL,
            until_date        TEXT NOT NULL,
            papers_fetched    INTEGER,
            papers_selected   INTEGER,
            completed_at      TEXT,
            digest_path       TEXT
        )
    """)
    conn.commit()


def _already_ran(conn: sqlite3.Connection, cycle_id: str) -> bool:
    row = conn.execute(
        "SELECT completed_at FROM runs WHERE cycle_id = ?", (cycle_id,)
    ).fetchone()
    return row is not None and row[0] is not None


def _get_last_anchor(conn: sqlite3.Connection) -> date | None:
    """Return the anchor_date of the most recently completed run, or None."""
    row = conn.execute(
        "SELECT anchor_date FROM runs WHERE completed_at IS NOT NULL "
        "ORDER BY anchor_date DESC LIMIT 1"
    ).fetchone()
    if row:
        return date.fromisoformat(row[0])
    return None


def _record_run(
    conn: sqlite3.Connection,
    cycle_id: str,
    anchor: date,
    since: date,
    until: date,
    fetched: int,
    selected: int,
    digest_path: str,
) -> None:
    from datetime import datetime
    conn.execute(
        """
        INSERT INTO runs
            (cycle_id, anchor_date, since_date, until_date,
             papers_fetched, papers_selected, completed_at, digest_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(cycle_id) DO UPDATE SET
            papers_fetched  = excluded.papers_fetched,
            papers_selected = excluded.papers_selected,
            completed_at    = excluded.completed_at,
            digest_path     = excluded.digest_path
        """,
        (
            cycle_id,
            anchor.isoformat(),
            since.isoformat(),
            until.isoformat(),
            fetched,
            selected,
            datetime.utcnow().isoformat(),
            digest_path,
        ),
    )
    conn.commit()


# ── Schedule helpers ──────────────────────────────────────────────────────────

def _current_anchor(today: date) -> date:
    """
    Return the most recent anchor date (1st or 15th) on or before today.
    Examples:
      Feb 17 → Feb 15
      Feb  3 → Feb  1
      Feb  1 → Feb  1
    """
    for day in sorted(ANCHOR_DAYS, reverse=True):
        if today.day >= day:
            return today.replace(day=day)
    # Edge case: today is before the first anchor of the month → go to previous month's last anchor
    prev_month = (today.replace(day=1) - timedelta(days=1))
    last_anchor_day = max(d for d in ANCHOR_DAYS if d <= prev_month.day)
    return prev_month.replace(day=last_anchor_day)


def _previous_anchor(anchor: date) -> date:
    """
    Return the anchor date immediately before the given anchor.
    Examples:
      Feb 15 → Feb  1
      Feb  1 → Jan 15
    """
    anchor_days_sorted = sorted(ANCHOR_DAYS)
    idx = anchor_days_sorted.index(anchor.day)
    if idx > 0:
        return anchor.replace(day=anchor_days_sorted[idx - 1])
    # Roll back to previous month's last anchor
    prev_month = (anchor.replace(day=1) - timedelta(days=1))
    return prev_month.replace(day=max(anchor_days_sorted))


def _determine_since_date(
    conn: sqlite3.Connection,
    anchor: date,
) -> date:
    """
    Determine the start of the arXiv fetch window.

    If we have a previous completed run, start from the day AFTER its anchor
    (covering the full gap if the computer was off).
    Otherwise default to the day after the previous anchor.
    """
    last_anchor = _get_last_anchor(conn)
    if last_anchor:
        # Cover everything since the day after the last completed anchor
        return last_anchor + timedelta(days=1)
    # First ever run: cover since the day after the previous anchor
    prev = _previous_anchor(anchor)
    return prev + timedelta(days=1)


# ── Telegram announcement via Bot API ────────────────────────────────────────

def _send_telegram_announcement(digest_url: str, top_paper: dict, since: date, until: date) -> None:
    """
    Post a digest announcement directly to the Telegram supergroup via the Bot API.
    Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in the environment.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.warning(
            "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — skipping announcement"
        )
        return

    headline = top_paper.get("llm_reason") or top_paper["title"]
    # Lowercase first char so it flows naturally after "the top paper"
    headline_lc = headline[0].lower() + headline[1:] if headline else headline
    # Ensure headline ends with a period so the next sentence doesn't run on
    if headline_lc and not headline_lc.endswith("."):
        headline_lc += "."
    message = (
        f"New Apollo AI Research Digest is live!\n"
        f"Papers: {since.isoformat()} to {until.isoformat()}\n\n"
        f"In the past 2 weeks, the top paper {headline_lc} "
        f"Explore this and 24 other high-impact papers in this digest.\n\n"
        f"Read more: {digest_url}"
    )
    payload = json.dumps({"chat_id": chat_id, "text": message}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=15)
        print("[telegram] Announcement sent")
    except Exception as e:
        logger.warning(f"Telegram announcement failed: {e}")


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run(dry_run: bool = False) -> None:
    today = date.today()
    anchor = _current_anchor(today)
    cycle_id = anchor.isoformat()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(PIPELINE_DB))
    _init_db(conn)

    # ── Cycle guard ────────────────────────────────────────────────────────
    if _already_ran(conn, cycle_id):
        print(
            f"[apollo] Cycle {cycle_id} already completed. "
            "Nothing to do. Exiting."
        )
        conn.close()
        return

    since = _determine_since_date(conn, anchor)
    until = today

    print(
        f"[apollo] Starting cycle {cycle_id} | "
        f"Window: {since} → {until} | "
        f"{'DRY RUN' if dry_run else 'LIVE RUN'}"
    )

    # ── Fetch ──────────────────────────────────────────────────────────────
    papers = fetch_papers(since, until)
    if not papers:
        logger.warning("No papers fetched — possibly arXiv was unreachable.")
        conn.close()
        return

    # ── Filter (Layer 1 + 2) ───────────────────────────────────────────────
    candidates = apply_filters(papers)
    if not candidates:
        logger.warning("All papers filtered out — adjust KEYWORDS or date window.")
        conn.close()
        return

    # ── Score (Layer 3) ────────────────────────────────────────────────────
    top_papers = score_papers(candidates)
    if not top_papers:
        logger.error("LLM scoring returned no valid papers.")
        conn.close()
        return

    if dry_run:
        print("\n[apollo] DRY RUN complete — skipping memory storage, digest, and git push.")
        print(f"  Papers fetched:   {len(papers)}")
        print(f"  After filtering:  {len(candidates)}")
        print(f"  Top selected:     {len(top_papers)}")
        for i, p in enumerate(top_papers[:5], 1):
            print(f"  {i}. [{p['final_score']}] {p['title'][:70]}")
        conn.close()
        return

    # ── Store in ZeroClaw memory ───────────────────────────────────────────
    digest_url_placeholder = (
        f"https://dhruvq.github.io/Apollo-AI-Research-Analyst/{cycle_id}.html"
    )
    store_papers(top_papers, cycle_id, digest_url_placeholder)

    # ── Build & publish digest ─────────────────────────────────────────────
    digest_url, push_ok = build_and_publish(cycle_id, top_papers, since.isoformat(), until.isoformat())

    if not push_ok:
        logger.warning(
            "Git push failed — digest files are written locally but not pushed. "
            "Resolve manually and push, or re-run (cycle_id guard will be skipped "
            "until _record_run is called)."
        )

    # ── Record completed run ───────────────────────────────────────────────
    _record_run(
        conn,
        cycle_id=cycle_id,
        anchor=anchor,
        since=since,
        until=until,
        fetched=len(papers),
        selected=len(top_papers),
        digest_path=str(digest_url),
    )

    # ── Telegram announcement ──────────────────────────────────────────────
    if push_ok:
        _send_telegram_announcement(digest_url, top_papers[0], since, until)

    conn.close()
    print(
        f"\n[apollo] Cycle {cycle_id} complete! "
        f"{len(top_papers)} papers. Digest: {digest_url}"
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apollo biweekly AI research digest runner")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and score papers but skip memory storage, git push, and Telegram.",
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run)
