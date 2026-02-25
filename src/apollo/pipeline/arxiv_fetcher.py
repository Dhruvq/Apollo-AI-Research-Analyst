"""
Fetches papers from arXiv cs.AI submitted within the given date window.
Returns a list of paper dicts ready for the filter pipeline.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any

import arxiv

from apollo.config.settings import ARXIV_CATEGORY, MAX_FETCH_RESULTS


def fetch_papers(since_date: date, until_date: date) -> list[dict[str, Any]]:
    """
    Fetch all cs.AI papers submitted between since_date and until_date (inclusive).

    Returns a list of dicts:
        {
            "id":        str,    # e.g. "2502.12345"
            "title":     str,
            "abstract":  str,
            "authors":   list[str],
            "submitted": str,    # ISO date string "YYYY-MM-DD"
            "url":       str,    # https://arxiv.org/abs/<id>
        }
    """
    since_str = since_date.strftime("%Y%m%d")
    until_str = until_date.strftime("%Y%m%d")

    query = (
        f"cat:{ARXIV_CATEGORY} AND "
        f"submittedDate:[{since_str}0000 TO {until_str}2359]"
    )

    print(f"[arxiv] Querying: {query}")

    client = arxiv.Client(
        page_size=100,
        delay_seconds=3.0,      # be polite to arXiv
        num_retries=3,
    )

    search = arxiv.Search(
        query=query,
        max_results=MAX_FETCH_RESULTS,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    papers: list[dict[str, Any]] = []
    for result in client.results(search):
        paper_id = result.entry_id.split("/abs/")[-1]
        papers.append(
            {
                "id": paper_id,
                "title": result.title.strip(),
                "abstract": result.summary.strip(),
                "authors": [str(a) for a in result.authors],
                "submitted": result.published.date().isoformat(),
                "url": f"https://arxiv.org/abs/{paper_id}",
            }
        )

    print(f"[arxiv] Fetched {len(papers)} papers from {since_date} to {until_date}")
    return papers
