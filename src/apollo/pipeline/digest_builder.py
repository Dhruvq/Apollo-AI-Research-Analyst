"""
Builds and publishes the biweekly digest:
  - digests/YYYY-MM-DD.json  — structured data (archived in repo)
  - digests/YYYY-MM-DD.md    — human-readable markdown (archived in repo)
  - docs/YYYY-MM-DD.html     — rendered newsletter page (GitHub Pages)
  - docs/index.html           — updated homepage listing all issues
Then commits and pushes everything to GitHub.
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from apollo.config.settings import DIGESTS_DIR, DOCS_DIR, ROOT_DIR, TEMPLATES_DIR

logger = logging.getLogger(__name__)


# ── JSON digest ───────────────────────────────────────────────────────────────

def _write_json_digest(cycle_id: str, papers: list[dict[str, Any]], since_date: str, until_date: str) -> Path:
    DIGESTS_DIR.mkdir(parents=True, exist_ok=True)
    path = DIGESTS_DIR / f"{cycle_id}.json"
    data = {
        "cycle_id": cycle_id,
        "since_date": since_date,
        "until_date": until_date,
        "generated": date.today().isoformat(),
        "paper_count": len(papers),
        "papers": papers,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"[digest] Written {path}")
    return path


# ── Markdown digest ───────────────────────────────────────────────────────────

def _write_md_digest(cycle_id: str, papers: list[dict[str, Any]]) -> Path:
    DIGESTS_DIR.mkdir(parents=True, exist_ok=True)
    path = DIGESTS_DIR / f"{cycle_id}.md"
    lines = [
        f"# Apollo AI Research Digest — {cycle_id}",
        "",
        f"*{len(papers)} most impactful cs.AI papers*",
        "",
    ]
    for i, p in enumerate(papers, 1):
        authors_str = ", ".join(p["authors"][:3])
        if len(p["authors"]) > 3:
            authors_str += " et al."
        lines += [
            f"## {i}. {p['title']}",
            "",
            f"**Authors:** {authors_str}  ",
            f"**Submitted:** {p['submitted']}  ",
            f"**Impact Score:** {p['final_score']} (LLM: {p['llm_score']}/10)  ",
            f"**arXiv:** [{p['url']}]({p['url']})",
            "",
            f"> {p['llm_reason']}",
            "",
            p["abstract"][:500] + ("..." if len(p["abstract"]) > 500 else ""),
            "",
            "---",
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[digest] Written {path}")
    return path


# ── HTML digest ───────────────────────────────────────────────────────────────

def _write_html_digest(cycle_id: str, papers: list[dict[str, Any]], since_date: str, until_date: str, all_issues: list[str]) -> Path:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    template = env.get_template("digest.html.jinja2")
    html = template.render(
        cycle_id=cycle_id,
        papers=papers,
        generated=date.today().isoformat(),
        since_date=since_date,
        until_date=until_date,
        all_issues=all_issues,
    )
    path = DOCS_DIR / f"{cycle_id}.html"
    path.write_text(html, encoding="utf-8")
    print(f"[digest] Written {path}")
    return path


# ── Index page ────────────────────────────────────────────────────────────────

def _update_index(cycle_id: str, papers: list[dict[str, Any]], since_date: str, until_date: str, all_issues: list[str]) -> None:
    """Regenerate docs/index.html to show the latest digest and link all past issues."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    template = env.get_template("digest.html.jinja2")

    # Re-render index with latest papers + issue list
    html = template.render(
        cycle_id=cycle_id,
        papers=papers,
        generated=date.today().isoformat(),
        since_date=since_date,
        until_date=until_date,
        all_issues=all_issues,
        is_index=True,
    )
    index_path = DOCS_DIR / "index.html"
    index_path.write_text(html, encoding="utf-8")
    print(f"[digest] Updated {index_path}")


# ── Git push ──────────────────────────────────────────────────────────────────

def _git_push(cycle_id: str) -> bool:
    """Commit all new digest files and push to GitHub."""
    try:
        subprocess.run(
            ["git", "-C", str(ROOT_DIR), "add",
             "digests/", "docs/"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(ROOT_DIR), "commit", "-m", f"Digest: {cycle_id}"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(ROOT_DIR), "push"],
            check=True,
        )
        print(f"[digest] Pushed to GitHub for cycle {cycle_id}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Git push failed: {e}")
        return False


# ── Public API ────────────────────────────────────────────────────────────────

def build_and_publish(
    cycle_id: str,
    papers: list[dict[str, Any]],
    since_date: str,
    until_date: str,
) -> tuple[str, bool]:
    """
    Generate all digest outputs and push to GitHub.

    Returns:
        (digest_url, push_success)
        digest_url — GitHub Pages URL for the new digest HTML page
    """
    _write_json_digest(cycle_id, papers, since_date, until_date)
    _write_md_digest(cycle_id, papers)

    # Compute all issues from JSON files since the current issue was just written
    all_issues = sorted([p.stem for p in DIGESTS_DIR.glob("*.json")], reverse=True)

    # Re-render ALL past html files so their sidebars contain the updated `all_issues`.
    for issue_id in all_issues:
        issue_json_path = DIGESTS_DIR / f"{issue_id}.json"
        try:
            with open(issue_json_path, "r", encoding="utf-8") as f:
                issue_data = json.load(f)
            i_papers = issue_data.get("papers", [])
            i_since_date = issue_data.get("since_date", issue_id)
            i_until_date = issue_data.get("until_date", issue_id)
            _write_html_digest(issue_id, i_papers, i_since_date, i_until_date, all_issues)
        except Exception as e:
            logger.error(f"Failed to regenerate HTML for {issue_id}: {e}")

    _update_index(cycle_id, papers, since_date, until_date, all_issues)

    # Derive the GitHub Pages URL from git remote
    digest_url = _get_pages_url(cycle_id)

    push_ok = _git_push(cycle_id)
    return digest_url, push_ok


def _get_pages_url(cycle_id: str) -> str:
    """
    Derive the GitHub Pages URL from the git remote URL.
    e.g. https://github.com/Dhruvq/Apollo-AI-Research-Analyst.git
      → https://dhruvq.github.io/Apollo-AI-Research-Analyst/YYYY-MM-DD.html
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT_DIR), "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True,
        )
        remote = result.stdout.strip()
        # Handle both HTTPS and SSH remotes
        if remote.startswith("https://github.com/"):
            path = remote.replace("https://github.com/", "").removesuffix(".git")
        elif remote.startswith("git@github.com:"):
            path = remote.replace("git@github.com:", "").removesuffix(".git")
        else:
            return f"https://github.com — {cycle_id}"

        user, repo = path.split("/", 1)
        return f"https://{user.lower()}.github.io/{repo}/{cycle_id}.html"
    except Exception:
        return f"https://dhruvq.github.io/Apollo-AI-Research-Analyst/{cycle_id}.html"
