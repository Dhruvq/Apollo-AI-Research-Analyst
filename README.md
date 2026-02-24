# Apollo: Autonomous AI Research Analyst

[![Deploy docs](https://github.com/dhruvq/Apollo-AI-Research-Analyst/actions/workflows/pages.yml/badge.svg)](https://github.com/dhruvq/Apollo-AI-Research-Analyst/actions/workflows/pages.yml)

A secure, local-first autonomous research assistant that ingests cutting-edge papers in the field of AI, stores structured memory, performs hybrid retrieval, and produces biweekly research intelligence reports.

Apollo scrapes arXiv `cs.AI` submissions, filters out the noise down to the top 25 most impactful papers using a rigorous 3-layer pipeline, and stores them in [ZeroClaw](https://github.com/topoteretes/zeroclaw) (a smart local memory db). It leverages `gemma-3-27b-it` for scoring and `gemini-2.5-flash` for answering user queries via a live Telegram bot.


## 🌟 Key Features

- **Automated Research Cycle**: Fetches all arXiv papers published in the `cs.AI` category on the 1st and 15th of each month.
- **Three-Layer Filtering Pipeline**:
  1. **Keyword Scoring**: Matches abstract/title against high-signal AI terms (RAG, multi-agent, alignement, etc).
  2. **Author Boost**: Upweighs research from a curated list of ~40 top AI researchers/labs.
  3. **LLM Evaluation**: `gemma-3-27b-it` evaluates the top 150 candidates and scores them 1-10 on novelty and impact.
- **Static Website Digests**: Automatically compiles the top 25 papers into a beautiful, dark-themed GitHub Pages HTML digest.
- **ZeroClaw Memory Integration**: Persistently stores all approved papers in ZeroClaw's local SQLite DB with hybrid search capabilities (Vector + Keyword).
- **Interactive Telegram Assistant**: Query previous digest papers interactively via the standalone Python Telegram bot (@ApolloAIResearchBot).
- **Run-if-Missed Consistency**: The scheduler automatically covers gaps in dates if the machine was offline during a regularly scheduled cycle.


## Architecture

You can read the full, detailed technical breakdown of the architecture, constraints, and why certain decisions were made in [HOW_THIS_WAS_BUILT.md](HOW_THIS_WAS_BUILT.md).

At a high level:
1. `run_biweekly.py` orchestrated the full run.
2. It hits **arXiv** for the `cs.AI` window.
3. Papers pass through `filters.py` (keywords, authors) and `scorer.py` (LLM).
4. `memory_writer.py` persists the top 25 results to `~/.zeroclaw/workspace/memory/brain.db` via the CLI.
5. `digest_builder.py` produces JSON, MD, and HTML digests, pushing them directly to GitHub for GitHub Pages deployment.
6. `telegram_bot.py` monitors the Telegram supergroup and queries `brain.db` directly to answer questions using `gemini-2.5-flash`.


## Setup & Installation

### 1. Prerequisites
- Python 3.10+
- **ZeroClaw** (brew binary v0.1.0 installed locally)
- A **Single Google API Key** (powers Gemma, Gemini, and embeddings — no OpenAI required).
- A **Telegram Bot Token** (from `@BotFather`).

### 2. Environment Setup

Clone the repository and install the project locally:

```bash
git clone https://github.com/dhruvq/Apollo-AI-Research-Analyst.git
cd Apollo-AI-Research-Analyst

python -m venv venv
source venv/bin/activate
pip install -e .
```

Copy the `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```
Ensure it contains:
```env
GOOGLE_API_KEY=your_google_api_key_here
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=-123456789  # (Optional) For automated channel announcements
GITHUB_TOKEN=your_github_token # (Optional) For non-interactive git push
```

### 3. ZeroClaw Configuration

Apollo relies on ZeroClaw for its persistent memory vector database. Note that ZeroClaw ignores project-level configuration, so you must edit its global configuration located at `~/.zeroclaw/config.toml`.

Use the provided template in the repo:
```bash
mkdir -p ~/.zeroclaw
cp zeroclaw/config.toml ~/.zeroclaw/config.toml
```

**CRITICAL**: Ensure ZeroClaw's `web_search` is set to `enabled = false` and `telegram` is disabled (`bot_token = ""`), as Apollo handles the Telegram bot standalone.

---

## 💻 Usage

### Running the Biweekly Pipeline

To manually trigger a research cycle, run the orchestration script:

```bash
python run_biweekly.py
```

This will automatically calculate the missing date range, fetch papers, score them, update ZeroClaw, build the new HTML digest, and deploy it to GitHub pages.

### Running the Telegram Bot

Apollo runs a standalone polling daemon for the Telegram Q&A assistant:

```bash
python src/apollo/bot/telegram_bot.py
```

The bot will now respond to `@ApolloAIResearchBot` mentions in groups or direct private messages.

*Note: The chatbot reads directly from `~/.zeroclaw/workspace/memory/brain.db` because ZeroClaw's LLM retrieval is non-deterministic. It then passes the full context to Gemini 2.5 flash, ensuring accurate context window alignment!*

---

## Repository Structure

```text
Apollo-AI-Research-Analyst/
├── src/
│   └── apollo/
│       ├── bot/              # Standalone Telegram Q&A logic 
│       ├── config/           # App settings and high-impact author tracking
│       └── pipeline/         # ArXiv fetching, filtering, ZeroClaw integration, HTML generation
├── data/                     # Pipeline SQLite DB for tracking cycles & rate limits
├── digests/                  # Committed Markdown & JSON representations of all issues
├── docs/                     # GitHub Pages HTML output
├── templates/                # Jinja2 templates for the HTML newsletter frontends
├── tests/                    # Unit tests for the scorers and fetcher components
├── zeroclaw/                 # Boilerplate ZeroClaw configuration
├── run_biweekly.py           # The primary execution script for generating new digests
├── HOW_THIS_WAS_BUILT.md     # Deep-dive architecture and technical decisions
└── CLAUDE.md                 # Brief developer cheat-sheet
```
