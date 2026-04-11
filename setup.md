# TelegramSearch — Setup Guide

## 1. Get Telegram API credentials

1. Go to https://my.telegram.org/apps
2. Log in with your phone number
3. Create a new application — copy the **API ID** and **API Hash**

## 2. Configure

```bash
cp .env.example .env
# Edit .env and fill in TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE
```

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

## 4. Add channels and scrape

```bash
# Add a public channel (it will be scraped immediately)
python scraper.py add durov
python scraper.py add telegram
python scraper.py add @bbcnews

# Scrape all channels again to fetch new messages
python scraper.py scrape

# List indexed channels
python scraper.py list

# Remove a channel
python scraper.py remove durov
```

The first `add` will authenticate your Telegram session interactively
(enter your phone number + the code Telegram sends you). The session is
saved in `telegram_session.session` so you only need to do this once.

## 5. Start the web server

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 in your browser.

## Keep the index fresh

Run the scraper on a cron/schedule to keep messages up to date:

```bash
# Example: scrape every hour
# crontab -e
# 0 * * * * cd /path/to/telegramscraper && python scraper.py scrape
```

## Architecture

```
telegramscraper/
├── app.py          — FastAPI server + search API
├── database.py     — SQLite schema with FTS5
├── scraper.py      — Telethon-based channel scraper
├── static/
│   ├── index.html  — Home / search page
│   ├── results.html — Search results page
│   ├── channels.html — Channel browser
│   └── style.css   — Google-inspired styles
└── .env            — Your credentials (git-ignored)
```

## API endpoints

| Endpoint | Description |
|---|---|
| `GET /api/search?q=...&page=1&sort=relevance` | Full-text search |
| `GET /api/channels` | List indexed channels |
| `GET /api/stats` | Total message/channel counts |
