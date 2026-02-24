"""
Layer 3: LLM Novelty & Significance Scoring using Gemini 2.5 Flash-Lite.

For each candidate paper, prompts Gemini to return a JSON score (1-10) and one-sentence reason.
Validation: strict JSON parse → retry once → skip paper if still invalid.
Returns the top TARGET_PAPERS papers sorted by (layer_score + llm_score) descending.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from google import genai
from google.genai import types as genai_types

from apollo.config.settings import GEMINI_SCORER_MODEL, LLM_SCORING_PROMPT, TARGET_PAPERS

logger = logging.getLogger(__name__)


def _build_paper_context(paper: dict[str, Any]) -> str:
    authors_str = ", ".join(paper["authors"][:5])
    if len(paper["authors"]) > 5:
        authors_str += f" et al. ({len(paper['authors'])} total)"
    return (
        f"Title: {paper['title']}\n"
        f"Authors: {authors_str}\n"
        f"Abstract: {paper['abstract'][:1200]}"
    )


def _parse_score_json(text: str) -> dict[str, Any] | None:
    """
    Try to extract a valid {score, reason} JSON object from model output.
    Returns None if parsing fails or score is not an int in 1-10.
    """
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON object from surrounding text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end == 0:
            return None
        try:
            data = json.loads(text[start:end])
        except json.JSONDecodeError:
            return None

    score = data.get("score")
    reason = data.get("reason", "")

    if not isinstance(score, int) or not (1 <= score <= 10):
        try:
            score = int(score)
            if not (1 <= score <= 10):
                return None
        except (TypeError, ValueError):
            return None

    return {"score": score, "reason": str(reason)}


def _score_one(client: genai.Client, paper: dict[str, Any]) -> dict[str, Any] | None:
    """
    Call Gemini once to score the paper.
    response_mime_type="application/json" enforces valid JSON output natively.
    Returns parsed result dict or None on failure.
    """
    context = _build_paper_context(paper)
    prompt = f"{LLM_SCORING_PROMPT}\n\n{context}"

    response = client.models.generate_content(
        model=GEMINI_SCORER_MODEL,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            max_output_tokens=200,
        ),
    )
    return _parse_score_json(response.text)


def score_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Score all candidate papers with Gemini LLM.
    Each paper gets fields added: "llm_score", "llm_reason", "final_score".
    Papers that fail validation after one retry are skipped.
    Returns the top TARGET_PAPERS by final_score.
    """
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    results: list[dict[str, Any]] = []
    skipped = 0

    for i, paper in enumerate(papers, 1):
        print(f"[scorer] {i}/{len(papers)} — {paper['title'][:70]}...")

        parsed = None
        try:
            parsed = _score_one(client, paper)
            if parsed is None:
                logger.warning(f"Invalid JSON on first attempt for {paper['id']}, retrying in 10s...")
                time.sleep(10)
                parsed = _score_one(client, paper)
        except Exception as e:
            logger.warning(f"API error for {paper['id']}: {e}, retrying in 10s...")
            time.sleep(10)
            try:
                parsed = _score_one(client, paper)
            except Exception as e2:
                logger.error(f"Skipping {paper['id']} after retry failure: {e2}")

        if parsed is None:
            logger.warning(f"Skipping {paper['id']} — invalid JSON after retry")
            skipped += 1
            time.sleep(2)
            continue

        final_score = paper["layer_score"] + parsed["score"]
        results.append(
            {
                **paper,
                "llm_score": parsed["score"],
                "llm_reason": parsed["reason"],
                "final_score": final_score,
            }
        )
        time.sleep(2)  # ~30 RPM — Gemma 3 27B free-tier rate limit

    results.sort(key=lambda p: p["final_score"], reverse=True)
    top = results[:TARGET_PAPERS]

    print(
        f"[scorer] Scored {len(results)} papers, skipped {skipped}. "
        f"Selected top {len(top)}."
    )
    return top
