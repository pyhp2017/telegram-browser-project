import os
import logging
from html import escape

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from browser import fetch_page, search_web, chunk_text

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# In-memory session store: {user_id: {...}}
sessions: dict[int, dict] = {}

MAX_LINKS_SHOWN = 20


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def get_session(user_id: int) -> dict:
    if user_id not in sessions:
        sessions[user_id] = {
            "links": [],       # list of (label, url)
            "chunks": [],      # current page text chunks
            "chunk_idx": 0,
            "history": [],     # list of URLs visited
            "mode": None,      # "browse" | "search"
        }
    return sessions[user_id]


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_page_header(title: str, url: str, page: int, total: int) -> str:
    paging = f"  [page {page}/{total}]" if total > 1 else ""
    return (
        f"<b>{escape(title)}</b>{escape(paging)}\n"
        f"<a href=\"{url}\">{escape(url[:80])}</a>\n"
        f"{'─' * 30}\n"
    )


def fmt_links(links: list[tuple[str, str]]) -> str:
    if not links:
        return "No links on this page."
    lines = ["<b>Links</b> — type a number to open:\n"]
    for i, (label, url) in enumerate(links[:MAX_LINKS_SHOWN], 1):
        lines.append(f"  <code>{i:2}.</code> {escape(label)}")
    return "\n".join(lines)


def fmt_search_results(results: list[dict], links: list[tuple]) -> str:
    if not results:
        return "No results found."
    lines = ["<b>Search results</b> — type a number to open:\n"]
    for i, r in enumerate(results, 1):
        lines.append(
            f"<code>{i:2}.</code> <b>{escape(r['title'])}</b>\n"
            f"       {escape(r['snippet'])}\n"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core actions
# ---------------------------------------------------------------------------

async def open_url(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    user_id = update.effective_user.id
    session = get_session(user_id)

    msg = await update.effective_message.reply_text("⏳ Fetching page…")
    try:
        result = fetch_page(url)
    except Exception as e:
        await msg.edit_text(f"❌ <b>Error:</b> {escape(str(e))}", parse_mode="HTML")
        return

    session["chunks"] = chunk_text(result["text"])
    session["chunk_idx"] = 0
    session["links"] = result["links"]
    session["mode"] = "browse"
    # push to history (avoid duplicate consecutive entries)
    if not session["history"] or session["history"][-1] != result["url"]:
        session["history"].append(result["url"])

    total = len(session["chunks"])
    header = fmt_page_header(result["title"], result["url"], 1, total)
    body = header + escape(session["chunks"][0])

    await msg.edit_text(body, parse_mode="HTML", disable_web_page_preview=True)

    # Send links as a separate message
    links_text = fmt_links(result["links"])
    nav_hint = "\n\n<i>Use /more for next page • /links to re-show links • /back to go back</i>"
    await update.effective_message.reply_text(
        links_text + nav_hint, parse_mode="HTML", disable_web_page_preview=True
    )


async def do_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    user_id = update.effective_user.id
    session = get_session(user_id)

    msg = await update.effective_message.reply_text(f"🔍 Searching: <i>{escape(query)}</i>…", parse_mode="HTML")
    try:
        results = search_web(query)
    except Exception as e:
        await msg.edit_text(f"❌ <b>Search error:</b> {escape(str(e))}", parse_mode="HTML")
        return

    session["links"] = [(r["title"], r["url"]) for r in results]
    session["chunks"] = []
    session["chunk_idx"] = 0
    session["mode"] = "search"

    text = fmt_search_results(results, session["links"])
    await msg.edit_text(text, parse_mode="HTML", disable_web_page_preview=True)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>🌐 Text Browser Bot</b>\n\n"
        "Browse the entire web as plain text, right here in Telegram.\n\n"
        "<b>How to use:</b>\n"
        "• Send any URL to open it\n"
        "• Send any text to search the web\n"
        "• Type a <b>number</b> to follow a link from the current page/results\n\n"
        "<b>Commands:</b>\n"
        "/browse &lt;url&gt; — open a specific page\n"
        "/search &lt;query&gt; — search DuckDuckGo\n"
        "/links — re-show current page links\n"
        "/more — load next chunk of page content\n"
        "/back — go to previous page\n"
        "/history — show browsing history",
        parse_mode="HTML",
    )


async def cmd_browse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /browse &lt;url&gt;", parse_mode="HTML")
        return
    url = context.args[0]
    await open_url(update, context, url)


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /search &lt;query&gt;", parse_mode="HTML")
        return
    query = " ".join(context.args)
    await do_search(update, context, query)


async def cmd_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_user.id)
    if not session["links"]:
        await update.message.reply_text("No links available yet. Browse a page first.")
        return
    await update.message.reply_text(
        fmt_links(session["links"]), parse_mode="HTML", disable_web_page_preview=True
    )


async def cmd_more(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_user.id)
    chunks = session["chunks"]
    idx = session["chunk_idx"] + 1

    if not chunks or idx >= len(chunks):
        await update.message.reply_text("No more content on this page.")
        return

    session["chunk_idx"] = idx
    total = len(chunks)
    url = session["history"][-1] if session["history"] else ""
    header = f"<b>[page {idx + 1}/{total}]</b>  <a href=\"{url}\">{escape(url[:60])}</a>\n{'─' * 30}\n"
    await update.message.reply_text(
        header + escape(chunks[idx]), parse_mode="HTML", disable_web_page_preview=True
    )


async def cmd_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_user.id)
    history = session["history"]
    if len(history) < 2:
        await update.message.reply_text("No previous page in history.")
        return
    history.pop()  # discard current
    prev_url = history.pop()  # will be re-added by open_url
    await open_url(update, context, prev_url)


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_user.id)
    history = session["history"]
    if not history:
        await update.message.reply_text("History is empty.")
        return
    lines = ["<b>Browsing history:</b>\n"]
    for i, url in enumerate(reversed(history[-15:]), 1):
        lines.append(f"  {i}. <a href=\"{url}\">{escape(url[:70])}</a>")
    await update.message.reply_text(
        "\n".join(lines), parse_mode="HTML", disable_web_page_preview=True
    )


# ---------------------------------------------------------------------------
# Free-text message handler
# ---------------------------------------------------------------------------

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    session = get_session(update.effective_user.id)

    # Number → follow link
    if text.isdigit():
        num = int(text)
        links = session["links"]
        if not links:
            await update.message.reply_text("No links available. Browse a page or search first.")
            return
        if not (1 <= num <= len(links)):
            await update.message.reply_text(f"Enter a number between 1 and {len(links)}.")
            return
        _, url = links[num - 1]
        await open_url(update, context, url)
        return

    # URL → browse directly
    lower = text.lower()
    if lower.startswith("http://") or lower.startswith("https://") or (
        "." in text and " " not in text and len(text) < 256
    ):
        await open_url(update, context, text)
        return

    # Anything else → search
    await do_search(update, context, text)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("browse", cmd_browse))
    app.add_handler(CommandHandler("b", cmd_browse))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("s", cmd_search))
    app.add_handler(CommandHandler("links", cmd_links))
    app.add_handler(CommandHandler("l", cmd_links))
    app.add_handler(CommandHandler("more", cmd_more))
    app.add_handler(CommandHandler("m", cmd_more))
    app.add_handler(CommandHandler("back", cmd_back))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot started. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
