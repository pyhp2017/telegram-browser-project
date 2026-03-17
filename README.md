# Telegram Text Browser Bot

Browse the web as plain text inside Telegram. No images, no JavaScript, no clutter — just content and links.

## Features

- **Browse any URL** as readable text
- **Search the web** via DuckDuckGo (free, no API key required)
- **Follow links** by typing a number
- **Paginate** long pages with `/more`
- **Back navigation** with `/back`
- **Browsing history** with `/history`

## Setup

### 1. Get a Telegram bot token

1. Open Telegram and message `@BotFather`
2. Send `/newbot` and follow the prompts
3. Copy the token you receive

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` and paste your token:

```
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
```

### 3. Install dependencies

Python 3.11+ is recommended.

```bash
pip install -r requirements.txt
```

### 4. Run

```bash
python bot.py
```

The bot will start polling for messages. Press `Ctrl+C` to stop.

---

## Usage

| Action | How |
|--------|-----|
| Open a URL | Send the URL directly, or `/browse <url>` |
| Search the web | Send any text, or `/search <query>` |
| Follow a link | Type the link number (e.g. `3`) |
| Next page of content | `/more` or `/m` |
| Go back | `/back` |
| Show links again | `/links` or `/l` |
| Browsing history | `/history` |

### Short command aliases

`/b` = `/browse` · `/s` = `/search` · `/l` = `/links` · `/m` = `/more`

---

## How it works

1. **Fetching** — `requests` fetches the raw HTML with a browser-like User-Agent
2. **Parsing** — `readability-lxml` extracts the main article content (strips ads, navbars, footers)
3. **Text conversion** — `html2text` converts the cleaned HTML to readable plain text
4. **Links** — `BeautifulSoup` extracts all `<a>` tags and numbers them
5. **Search** — `duckduckgo-search` queries DuckDuckGo with no API key needed
6. **Chunking** — long pages are split into ~3500-character chunks to stay within Telegram's message size limit

## Notes

- State is stored in memory — it resets when the bot restarts
- Some sites block scrapers or require JavaScript; those pages may return little or no content
- This is intended for personal use only
