"""
Layer 1: Keyword scoring — title + abstract match against KEYWORDS list.
Layer 2: Author boost — high-impact authors add extra score.

Papers with zero keyword score are dropped entirely.
Returns papers sorted by combined score descending, capped at SCORING_CANDIDATE_LIMIT.
"""

from __future__ import annotations

import re
from typing import Any

from config.authors import get_author_lookup
from config.settings import KEYWORDS, SCORING_CANDIDATE_LIMIT


def _keyword_score(title: str, abstract: str) -> int:
    """Count how many distinct keywords appear in the title or abstract."""
    haystack = (title + " " + abstract).lower()
    score = 0
    for kw in KEYWORDS:
        # Use word-boundary aware matching to avoid partial matches
        pattern = r"\b" + re.escape(kw.lower()) + r"\b"
        if re.search(pattern, haystack):
            score += 1
    return score


def _author_boost(authors: list[str], author_lookup: dict[str, int]) -> int:
    """
    For each paper author, check if any high-impact author name is a
    case-insensitive substring of the author string.
    Returns sum of all matched author boost weights.
    """
    boost = 0
    for author in authors:
        author_lower = author.lower()
        for known_name, weight in author_lookup.items():
            if known_name in author_lower:
                boost += weight
                break  # count each paper author at most once
    return boost


def apply_filters(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Apply Layer 1 (keywords) and Layer 2 (author boost) to the full paper list.

    Adds fields to each paper dict:
        "keyword_score":  int
        "author_boost":   int
        "layer_score":    int  (keyword_score + author_boost)

    Papers with keyword_score == 0 are dropped.
    Returns top SCORING_CANDIDATE_LIMIT papers sorted by layer_score descending.
    """
    author_lookup = get_author_lookup()
    scored: list[dict[str, Any]] = []

    for paper in papers:
        kw_score = _keyword_score(paper["title"], paper["abstract"])
        if kw_score == 0:
            continue  # Layer 1 drop

        auth_boost = _author_boost(paper["authors"], author_lookup)

        paper = {
            **paper,
            "keyword_score": kw_score,
            "author_boost": auth_boost,
            "layer_score": kw_score + auth_boost,
        }
        scored.append(paper)

    scored.sort(key=lambda p: p["layer_score"], reverse=True)
    result = scored[:SCORING_CANDIDATE_LIMIT]

    print(
        f"[filters] {len(papers)} → {len(scored)} keyword-matched → "
        f"{len(result)} sent to LLM scoring"
    )
    return result
