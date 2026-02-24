# Apollo — Project Memory for Claude

## What This Project Is
Biweekly CS research newsletter. Scrapes arXiv cs.AI, filters to 25 most impactful papers
via a 3-layer pipeline, stores in ZeroClaw memory, publishes HTML digest to GitHub Pages,
and runs a Telegram Q&A bot (@ApolloAIResearchBot).

## Current Status (as of Feb 2026)
- **Fully operational** — real pipeline run completed (2026-02-15 cycle), bot working
- **ZeroClaw memory**: 26 entries stored (25 papers + digest summary) in brain.db
- **GitHub Pages**: live at `https://dhruvq.github.io/Apollo-AI-Research-Analyst/`
- **Telegram bot**: @ApolloAIResearchBot running, responding correctly
- **DAILY_LIMIT**: set to `10000` for testing — restore to `10` for production

## Key Files & Paths
- **Main entry**: `run_biweekly.py` — orchestrates full pipeline
- **Pipeline**: `pipeline/arxiv_fetcher.py`, `filters.py`, `scorer.py`, `memory_writer.py`, `digest_builder.py`
- **Telegram bot**: `bot/telegram_bot.py` — standalone bot (python-telegram-bot + Gemini direct)
- **Setup verifier**: `bot/telegram_config.py` — one-time env check + test message
- **Config**: `config/settings.py` (all tuneable values), `config/authors.py` (author boost list)
- **ZeroClaw global config**: `~/.zeroclaw/config.toml` (NOT `zeroclaw/config.toml` in repo)
- **ZeroClaw config template**: `zeroclaw/config.toml` — reference for replicating the project
- **ZeroClaw memory DB**: `~/.zeroclaw/workspace/memory/brain.db` (read directly by bot)
- **HTML template**: `templates/digest.html.jinja2` (dark GitHub-style theme)
- **Pipeline state DB**: `data/pipeline.db` (gitignored SQLite — tracks cycles + bot rate limit)
- **Digests**: `digests/YYYY-MM-DD.{json,md}` (committed), `docs/YYYY-MM-DD.html` (GitHub Pages)
- **CI**: `.github/workflows/pages.yml` (auto-deploys `docs/` to Pages on push)

## Telegram Bot Architecture
`bot/telegram_bot.py` is a **standalone Python bot** (NOT ZeroClaw's Telegram channel):
1. `python-telegram-bot` receives @ApolloAIResearchBot mentions in group (or DMs)
2. Reads all stored papers directly from `~/.zeroclaw/workspace/memory/brain.db` via sqlite3
3. Calls `gemini-2.5-flash` directly with Apollo persona + all paper context
4. Returns 3-paragraph max response with arXiv citations

Why direct SQLite read instead of `zeroclaw agent --message "Recall..."`:
- ZeroClaw's LLM-based retrieval is non-deterministic — same query returns different results
- ZeroClaw sometimes calls `memory_store` instead of `memory_recall` (wrong tool selection)
- ZeroClaw's web_search (even when disabled) can block in subprocess with no stdin
- Direct SQLite read is instant, deterministic, and returns all 25 papers every time

Why not ZeroClaw's Telegram channel:
- ZeroClaw v0.1.0 ignores `system_prompt`/`persona` config fields in channel mode
- Always runs as a general-purpose agent (lists tools, reads skill files, etc.)
- Not configurable as a focused research Q&A bot

ZeroClaw's Telegram channel is **disabled** in `~/.zeroclaw/config.toml` (`bot_token = ""`).

## Announcements
`run_biweekly.py` posts digest announcements via direct Telegram Bot API (`urllib.request`).
Requires `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`.

## Schedule Logic
- Anchor dates: **1st and 15th** of each month
- `cycle_id` = anchor date ISO string (e.g. `"2026-02-15"`) — PRIMARY KEY in `runs` table
- If `cycle_id` already in DB → exit immediately (duplicate guard)
- `since_date` = last completed anchor + 1 day (covers full gap if computer was off)
- `until_date` = today (actual run date, NOT anchor date)

## Models & API Keys
- **Scorer**: `gemma-3-27b-it` via `google-genai` SDK → `GOOGLE_API_KEY` (14,400 RPD free tier)
- **Telegram bot LLM**: `gemini-2.5-flash` via `google-genai` SDK → `GOOGLE_API_KEY`
- **ZeroClaw LLM** (for memory storage CLI): `gemini-2.5-flash` → `GOOGLE_API_KEY`
- **ZeroClaw embeddings**: `text-embedding-004` via `gemini` provider → `GOOGLE_API_KEY`
- Single `GOOGLE_API_KEY` covers everything — no OpenAI account needed

## Rate Limiting
- **Scorer**: 2s sleep after every paper → ~30 RPM, within Gemma 3 27B free tier; 10s before retry
- **Bot**: `DAILY_LIMIT` in `bot/telegram_bot.py` — global queries/day tracked in `bot_rate_limit` table

## ZeroClaw
- **Global config**: `~/.zeroclaw/config.toml` (ZeroClaw ignores project-level configs)
- **Config template**: `zeroclaw/config.toml` in repo (reference for setup)
- **Provider**: `gemini` (native Google provider, reads `GOOGLE_API_KEY`)
- **Model**: `gemini-2.5-flash`
- **Embeddings**: `text-embedding-004` via `embedding_provider = "gemini"`, dimensions=768
- **Memory backend**: SQLite at `~/.zeroclaw/workspace/memory/brain.db`
- **Python stores memories via CLI**: `zeroclaw agent --message "Remember: {json}"`
- **NEVER write directly to ZeroClaw's SQLite** — always via CLI
- **Python reads memories directly from SQLite** — `brain.db` → `memories` table → `content` column
- **Web search**: DISABLED in config (`[web_search] enabled = false`)
- **Telegram channel**: DISABLED in `~/.zeroclaw/config.toml` (`bot_token = ""`)
- **auto_approve**: must include `memory_store`, `memory_write`, `memory_save`, `memory_recall`
  (without these, CLI subprocess hangs waiting for interactive Y/N approval)

## Environment Variables (.env)
```
GOOGLE_API_KEY=                  # Gemini scoring + bot LLM + ZeroClaw
TELEGRAM_BOT_TOKEN=              # from @BotFather
TELEGRAM_CHAT_ID=                # supergroup chat_id (negative integer) — for announcements
GITHUB_TOKEN=                    # optional, for non-interactive git push
```

## Pipeline DB Schema (data/pipeline.db)
```sql
CREATE TABLE runs (
    cycle_id TEXT PRIMARY KEY,  -- e.g. "2026-02-15"
    anchor_date TEXT,
    since_date TEXT,
    until_date TEXT,
    papers_fetched INTEGER,
    papers_selected INTEGER,
    completed_at TEXT,
    digest_path TEXT
);

CREATE TABLE bot_rate_limit (
    date  TEXT PRIMARY KEY,  -- ISO date, e.g. "2026-02-15"
    count INTEGER NOT NULL DEFAULT 0
);
```

## Known Issues / Decisions Made
- ZeroClaw v0.1.0: `system_prompt`/`persona` in config are silently ignored for channels
- ZeroClaw v0.1.0: `tool_dispatcher = "none"` does not hide tools from the model
- ZeroClaw v0.1.0: no `--config` flag — always reads `~/.zeroclaw/config.toml`
- ZeroClaw v0.1.0: `zeroclaw config set` command does not exist
- ZeroClaw v0.1.0: LLM-based retrieval (`zeroclaw agent --message "Recall..."`) is non-deterministic
  and unreliable — bot now reads brain.db directly
- ZeroClaw v0.1.0: web_search enabled by default — must set `[web_search] enabled = false`
  or it will search the web instead of recalling memory (and block in subprocess without stdin)
- `zeroclaw-tools` PyPI package does not exist — ZeroClaw is a brew binary, used via subprocess
- GitHub Pages must be manually enabled in repo settings before first push
- arXiv query window: cs.AI only, max 500 results
- HOW_THIS_WAS_BUILT.md at project root explains the full architecture
