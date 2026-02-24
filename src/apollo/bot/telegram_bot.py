"""
Apollo Telegram Bot
===================
Standalone Telegram bot for the Apollo AI Research Newsletter.

Architecture:
  1. python-telegram-bot receives @ApolloAIResearchBot mentions in the supergroup (or DMs)
  2. ZeroClaw CLI recalls relevant paper chunks from memory
  3. Gemini 2.5 Flash generates the response using the Apollo persona + retrieved context

Run:
    python bot/telegram_bot.py

Requires .env with: GOOGLE_API_KEY, TELEGRAM_BOT_TOKEN
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv()

from config.settings import PIPELINE_DB

logger = logging.getLogger("apollo.bot")

# ── Apollo identity ────────────────────────────────────────────────────────────

APOLLO_PERSONA = (
    "You are Apollo, an academic AI research analyst. "
    "Your role is to answer questions about cutting-edge CS research using "
    "the information provided in the context below from your research memory. "
    "Use precise, neutral, academic language. "
    "Always cite papers by title and include their arXiv URL after each point. "
    "If the context contains a paper that directly matches the question, summarise "
    "it using the stored abstract and metadata. "
    "If there is no exact match, share the most thematically related papers from "
    "the context and note that the specific topic may not be covered in the current digest. "
    "Only respond with 'No relevant research found in my memory for this query.' "
    "if the question has absolutely no connection to any stored paper. "
    "Never introduce facts beyond what the context provides. "
    "Keep your response to 3 paragraphs maximum."
)

DAILY_LIMIT = 10000  # global queries per day across all users
#DAILY_LIMIT = 10  # <-- UNCOMMENT AFTER TESTING (low limit to trigger rate limit quickly)

# ── Rate limiting (stored in pipeline.db) ────────────────────────────────────

def _init_rate_limit_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_rate_limit (
            date  TEXT PRIMARY KEY,
            count INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()


def _check_and_increment(conn: sqlite3.Connection) -> bool:
    """Return True (and increment counter) if under the daily limit."""
    today = date.today().isoformat()
    row = conn.execute(
        "SELECT count FROM bot_rate_limit WHERE date = ?", (today,)
    ).fetchone()
    count = row[0] if row else 0
    if count >= DAILY_LIMIT:
        return False
    conn.execute(
        """INSERT INTO bot_rate_limit (date, count) VALUES (?, 1)
           ON CONFLICT(date) DO UPDATE SET count = count + 1""",
        (today,),
    )
    conn.commit()
    return True



_ZEROCLAW_BRAIN_DB = Path.home() / ".zeroclaw" / "workspace" / "memory" / "brain.db"


# ── Memory retrieval (direct SQLite read from ZeroClaw's brain.db) ─────────────

def _recall_papers(query: str) -> str:
    """
    Read all stored research papers directly from ZeroClaw's SQLite memory.
    Bypasses ZeroClaw's LLM-based semantic retrieval (which is unreliable for
    listing all papers). Returns the raw memory content for Gemini to filter.
    """
    try:
        conn = sqlite3.connect(str(_ZEROCLAW_BRAIN_DB))
        rows = conn.execute(
            "SELECT content FROM memories "
            "WHERE content LIKE 'Remember this research paper:%' "
            "ORDER BY created_at DESC"
        ).fetchall()
        conn.close()
        if not rows:
            logger.warning("No research paper memories found in ZeroClaw brain.db")
            return ""
        papers_text = "\n\n".join(row[0] for row in rows)
        logger.info(f"Direct DB recall: {len(rows)} papers, {len(papers_text)} chars")
        return papers_text
    except Exception as e:
        logger.error(f"Failed to read ZeroClaw brain.db: {e}")
        return ""


# ── Gemini response generation ─────────────────────────────────────────────────

def _generate_response(query: str, context: str) -> str:
    """
    Call Gemini 2.5 Flash with the Apollo persona and the recalled context.
    The persona instructs the model to cite papers from context and to say
    'No relevant research found' if context is empty or irrelevant.
    """
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

    if context:
        user_message = f"Context from research memory:\n\n{context}\n\nQuestion: {query}"
    else:
        user_message = f"Question: {query}"

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=user_message,
        config=genai_types.GenerateContentConfig(
            system_instruction=APOLLO_PERSONA,
            max_output_tokens=1200,
        ),
    )
    finish_reason = response.candidates[0].finish_reason if response.candidates else "unknown"
    token_count = response.usage_metadata.candidates_token_count if response.usage_metadata else "unknown"
    logger.info(f"Gemini finish_reason={finish_reason} tokens_used={token_count}")
    return response.text.strip()


# ── Telegram message handler ───────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Respond to:
      - @ApolloAIResearchBot mentions in groups/supergroups
      - Any message in direct (private) chats
    """
    msg = update.message
    if not msg or not msg.text:
        return

    bot_username = (await context.bot.get_me()).username  # e.g. "ApolloAIResearchBot"
    text = msg.text
    mention = f"@{bot_username}"

    if msg.chat.type in ("group", "supergroup"):
        # Only respond when explicitly @mentioned
        if mention.lower() not in text.lower():
            return
        query = text.replace(mention, "").replace(f"@{bot_username.lower()}", "").strip()
    else:
        # DM — respond to everything
        query = text.strip()

    if not query:
        await msg.reply_text(f"Please include a research question after mentioning @{bot_username}.")
        return

    # ── Rate limit ───────────────────────────────────────────────────────────
    PIPELINE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(PIPELINE_DB))
    _init_rate_limit_db(conn)
    allowed = _check_and_increment(conn)
    conn.close()

    if not allowed:
        await msg.reply_text(
            f"Apollo has reached its daily limit of {DAILY_LIMIT} questions. "
            "Please try again tomorrow."
        )
        return

    # ── Retrieve + generate ──────────────────────────────────────────────────
    await context.bot.send_chat_action(chat_id=msg.chat_id, action="typing")

    recalled = await asyncio.to_thread(_recall_papers, query)

    try:
        reply = await asyncio.to_thread(_generate_response, query, recalled)
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        await msg.reply_text(
            "Sorry, I encountered an error generating a response. Please try again."
        )
        return

    await msg.reply_text(reply)


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in environment.")
    if not os.environ.get("GOOGLE_API_KEY"):
        raise RuntimeError("GOOGLE_API_KEY not set in environment.")

    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Apollo Telegram bot starting (polling)...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    main()
