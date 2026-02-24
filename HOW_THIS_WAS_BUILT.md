## How the project was built

### 1. arXiv Fetcher (`pipeline/arxiv_fetcher.py`)

The newsletter needs to pull every cs.AI paper submitted in a variable-length window (defined by the run-if-missed scheduler). Rather than scraping the arXiv website, the system uses the official `arxiv` Python client, which queries the arXiv API with a structured search expression:

```
cat:cs.AI AND submittedDate:[YYYYMMDD0000 TO YYYYMMDD2359]
```

The client paginates automatically in batches of 100, up to a hard cap of 500 results. Each result is normalised into a flat dict (`id`, `title`, `abstract`, `authors`, `submitted`, `url`) so the rest of the pipeline never has to touch the raw `arxiv` SDK objects.

**Output**: Up to 500 raw paper dicts for the date window.

---

### 2. Three-Layer Filter Pipeline (`pipeline/filters.py` + `pipeline/scorer.py`)

Returning 500 papers every two weeks is too many to summarise. The pipeline applies three successive layers to identify the 25 most impactful.

#### Layer 1 — Keyword Scoring
Each paper's title and abstract are matched (case-insensitive, word-boundary regex) against 10 domain keywords: `multi-agent`, `diffusion`, `alignment`, `llm`, `rlhf`, `reasoning`, `rag`, `transformer`, `memory`, `retrieval`. Each match adds +1 to the paper's score. Papers with zero matches are dropped entirely — they are off-topic for the newsletter's focus.

#### Layer 2 — High-Impact Author Boost
A curated list of ~40 researchers (`config/authors.py`) is maintained. For each paper, if any known author name is a case-insensitive substring of a paper's author string, +3 is added to the score. This surfaces work from established AI labs before the LLM sees it. The boost is intentionally modest so a single famous author cannot override a genuinely weak paper.

**Combined score after Layers 1+2**: Top 150 papers are passed to the LLM.

#### Layer 3 — Gemini LLM Scoring
Each of the 150 candidates is scored by `gemma-3-27b-it` using this prompt:

> *"Rate this paper from 1–10 for potential research impact based on novelty, scope, methodological rigor, and broader implications. Return JSON only: `{"score": <int 1-10>, "reason": "<one sentence>"}`"*

`gemma-3-27b-it` was chosen over `gemini-2.5-flash-lite` because the Flash Lite free tier caps at 20 RPD — far too few for 150 papers. Gemma 3 27B allows 14,400 RPD. It does not support `response_mime_type="application/json"` (a Gemini-only feature), so the validation layer handles raw text output:
- Parse JSON strictly → if fail, wait 10s and retry once
- If still invalid after retry → skip paper (logged as warning)
- Final score = `layer_score + llm_score`; top 25 selected

**Rate limiting**: The Gemma 3 27B free tier allows ~30 RPM. The scorer sleeps 2 seconds between every paper and 10 seconds before each retry.

---

### 3. ZeroClaw Memory Integration (`pipeline/memory_writer.py`)

After selecting the top 25 papers, their structured data is stored in ZeroClaw — a Rust-based AI assistant framework with native SQLite memory and hybrid retrieval (vector + keyword). The key constraint from the design spec: **Python never writes directly to ZeroClaw's SQLite DB**. All storage goes through the ZeroClaw CLI via `subprocess`:

```bash
zeroclaw agent --message "Remember this research paper: {json_payload}"
```

Each paper is stored as a chunk containing its id, title, authors, abstract excerpt (800 chars), submission date, arXiv URL, final impact score, LLM score, and LLM reason. A separate digest summary entry is stored for cross-period queries like *"What changed in AI research compared to last month?"*.

ZeroClaw is configured in `~/.zeroclaw/config.toml` (the global config — ZeroClaw has no per-project config path) with:
- **Provider**: native `gemini` provider reading `GOOGLE_API_KEY` directly
- **LLM**: `gemini-2.5-flash`
- **Embeddings**: `text-embedding-004` via `embedding_provider = "gemini"` (768 dimensions)
- **Hybrid retrieval**: `vector_weight = 0.7`, `keyword_weight = 0.3`, `top_k = 5`
- **Memory hygiene**: entries archived after 7 days, purged after 30

---

### 4. Digest Generation (`pipeline/digest_builder.py`)

Three output formats are generated per cycle:

| File | Purpose |
|------|---------|
| `digests/YYYY-MM-DD.json` | Structured data — full paper metadata, scores, reasons. Committed to repo for programmatic access. |
| `digests/YYYY-MM-DD.md` | Human-readable markdown — authors, scores, abstract excerpts. Viewable directly on GitHub. |
| `docs/YYYY-MM-DD.html` | Full newsletter page rendered via Jinja2 template for GitHub Pages. |
| `docs/index.html` | Homepage — always points to the latest digest with a linked archive of all past issues. |

The HTML template (`templates/digest.html.jinja2`) uses a GitHub-dark colour scheme with score badges colour-coded by impact level (green ≥8, amber ≥6, red <6). Each paper card shows rank, layer scores, LLM reason, abstract, and clickable arXiv link.

After generating files, `digest_builder.py` derives the GitHub Pages URL from the git remote, commits all new files with message `Digest: YYYY-MM-DD`, and pushes to `main`. GitHub Actions (`.github/workflows/pages.yml`) then auto-deploys the `docs/` folder to Pages.

---

### 5. Scheduler with Run-If-Missed Logic (`run_biweekly.py`)

The newsletter publishes on the **1st and 15th of each month**. Because this runs locally on a personal machine, it can't rely on a cloud cron job that fires exactly on schedule.

**Cycle ID guard**: The anchor date (e.g. `"2026-02-15"`) is used as a `cycle_id` primary key in `data/pipeline.db`. If the script is run again for the same period, it detects the existing record and exits immediately — no duplicate digests.

**Run-if-missed logic**: If the computer was off on the 15th and the script runs on the 17th, it would be wrong to fetch only papers from Feb 15–17. Instead:
- `since_date` = day after the **last completed anchor** (not today's anchor)
- `until_date` = today (the actual run date)

This means the 17th run fetches Feb 2–17, covering the full gap. The `anchor_date` stored in the DB prevents double-counting papers in the next cycle.

---

### 6. Telegram Bot (`bot/telegram_bot.py`)

The initial design used ZeroClaw's built-in Telegram channel to handle the bot entirely within the daemon. In practice, ZeroClaw v0.1.0's channel proved too opinionated: it runs as a full autonomous agent (exposing shell, file, and git tools to the model), ignores `system_prompt` and `persona` config fields, and responds with generic agent behaviour regardless of configuration. Switching providers, disabling tool dispatch, and setting custom personas — none of it changed the output. This is a v0.1.0 limitation.

**Redesign**: a thin standalone Python bot (`bot/telegram_bot.py`) replaces the ZeroClaw channel entirely. It uses three components in sequence:

1. **`python-telegram-bot`** (polling) — receives `@ApolloAIResearchBot` mentions in the supergroup, or any direct message. Only the mention-stripped query text is forwarded.

2. **Direct SQLite read from ZeroClaw's memory** — the bot reads `~/.zeroclaw/workspace/memory/brain.db` directly via Python's `sqlite3`, querying all rows where `content LIKE 'Remember this research paper:%'`. This returns all 25 stored papers as raw context for Gemini.

   The original approach used `zeroclaw agent --message "Recall research papers relevant to: {question}"` via subprocess. This proved unreliable in production: ZeroClaw's LLM-based retrieval is non-deterministic (same query returning different results across calls), occasionally selects the wrong tool (`memory_store` instead of `memory_recall`), and with `capture_output=True` blocks waiting for stdin-based tool approval even when `auto_approve` is configured. Direct SQLite read is instant, deterministic, and requires no network calls.

3. **Gemini 2.5 Flash for response generation** — all 25 paper records and the user's question are passed to `gemini-2.5-flash` via the `google-genai` SDK, with the Apollo persona as a system instruction. Gemini handles relevance filtering: the persona instructs it to cite only papers relevant to the question and to respond with "No relevant research found" if nothing matches. Calling Gemini directly means no agent scaffolding interferes — the model sees exactly the context and instructions intended.

**Rate limiting**: a `bot_rate_limit` table in `data/pipeline.db` tracks a global daily query count. The limit is set in `DAILY_LIMIT` at the top of `telegram_bot.py`.

**Announcements**: `run_biweekly.py` posts digest announcements via a direct `urllib.request` POST to the Telegram Bot API (`sendMessage`). The message contains the top paper's LLM reason as a headline, the date window, and the GitHub Pages URL. Requires `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the environment.

---

### 7. Key Design Decisions

**Single API key**: All LLM calls (scoring, Telegram Q&A, embeddings) go through one `GOOGLE_API_KEY`. ZeroClaw uses its native `gemini` provider, which reads `GOOGLE_API_KEY` directly — no OpenAI account or endpoint workaround needed.

**Two SQLite databases**: `data/pipeline.db` tracks run history, cycle IDs, date windows, and bot rate limiting — it's owned by Python. ZeroClaw manages its own internal SQLite (`~/.zeroclaw/workspace/memory/brain.db`) for vector + keyword memory — Python never *writes* to it directly (CLI only for storage), but *reads* it directly for bot retrieval. ZeroClaw's LLM-based retrieval proved non-deterministic in production; direct SQL reads are reliable.

**No cloud infrastructure**: The entire pipeline runs locally. GitHub Pages hosts the static HTML. ZeroClaw daemon runs persistently on the local machine. The only external services are the arXiv API (free, no key), Google Gemini API, and Telegram Bot API.
