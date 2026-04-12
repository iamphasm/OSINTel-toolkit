# OSIntelligence Toolkit

**Developed by [Phasm](https://phasm.io)**

OSIntelligence Toolkit is a self-hosted open-source intelligence (OSINT) web application. It provides a suite of tools for collecting, searching, and exporting data from public sources. The interface runs entirely in the browser against a local FastAPI backend with a SQLite database.

---

## Tools

### Telegram Scraper
The core tool. Connects to the Telegram API via [Telethon](https://github.com/LonamiWebs/Telethon) to index public channel messages into a local SQLite FTS5 (full-text search) database.

- Add public Telegram channels by username
- Scrapes up to a configurable number of messages on first add (default: 100)
- Full-text search across all indexed channels with pagination
- Per-channel feed view with message text, photos, videos, and links
- Automatic translation to 20+ languages via Google Translate
- Progress bar tracking during scraping
- Remove channels and all their messages
- Select individual messages and export them as a formatted PDF (with images and clickable links)
- PDF exports are saved into the active Project for later viewing

### Web Link Scraper
A standalone web scraper that extracts all hyperlinks from any public URL.

- Paste any URL and extract all links from the page
- Optional deep scrape mode: visits each extracted link to fetch page title and description (first 50 links)
- Optional CSS selector to extract specific element text alongside each link
- Sort results by link text, URL, TLD, or page title
- Filter results by TLD using a dropdown
- Exclude specific domains from results (comma-separated, supports subdomains)
- Auto-excludes GitHub noise domains when scraping a GitHub URL
- Duplicate link detection with visual highlighting
- Export results as CSV with a column picker modal
- Export results as PDF with a column picker modal (opens print dialog)

### Metadata Extractor *(GEOSINT)*
Extracts embedded metadata from digital files — either by uploading a file or providing a direct URL.

- Supports photos (JPEG, PNG, TIFF, HEIC), PDFs, Word documents (.docx), audio (MP3, FLAC, OGG, WAV, M4A), and video files
- Image EXIF data: camera make/model, lens, focal length, aperture, shutter speed, ISO
- GPS extraction: latitude, longitude, altitude, speed, and direction — with direct links to Google Maps and OpenStreetMap
- PDF metadata: title, author, creator, producer, creation and modification dates
- Document metadata: author, revision, last modified by, keywords
- Audio/video: duration, bitrate, sample rate, codec, embedded tags
- Copy-to-clipboard button on every field
- Export full metadata report as PDF
- File upload (drag & drop) or remote URL (max 50 MB)

### Image Reverse Search *(GEOSINT)*
Helps locate the origin or context of an image using reverse image search engines, combined with EXIF GPS extraction.

- Upload an image or provide a direct URL
- Immediate image preview
- Extracts EXIF data: camera, date, focal length, aperture, ISO
- GPS extraction with an embedded OpenStreetMap, plus links to Google Maps, OpenStreetMap, and Google Street View
- One-click search buttons for six engines: Google Lens, Yandex Images, Bing Images, TinEye, Karma Decay, Baidu Images
- Uploaded images are temporarily served from the local server for 30 minutes (URL-based search links)
- Add to Project saves a full HTML report with image, GPS map links, EXIF data, and search engine links

### ShadowMap *(GEOSINT)*
An embedded viewer for [ShadowMap](https://app.shadowmap.org/), a geospatial tool for analysing sun position, shadows, and lighting conditions at any location and time. Useful for verifying the time or date of photos based on shadow direction.

---

## Projects
A persistent project management sidebar available on all pages. Projects act as containers for exported data.

- **Create Project** — give it a name, tags, and notes
- **Choose Project** — set an active project from a list
- **View Project** — browse saved files in a folder/file tree grouped by source tool
  - Telegram Scraper exports appear as `YYYY-MM-DD_channelname.html`
  - Clicking a file opens it in a full-page overlay
  - HTML files (Telegram exports) render in an iframe with a **Print to PDF** button
  - Plain text files open in an editable text editor with a **Save** button
  - Files can be deleted from the overlay or from the tree

---

## Installation

### Requirements
- Python 3.10+
- A Telegram account with API credentials from [my.telegram.org/apps](https://my.telegram.org/apps)

### 1. Clone the repository

```bash
git clone <repo-url>
cd telegramscraper
```

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in your Telegram credentials:

```env
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=+1234567890
INITIAL_SCRAPE_LIMIT=100
```

### 5. Authenticate with Telegram (first run only)

```bash
python scraper.py add <any_public_channel>
```

Follow the interactive prompt to enter the code Telegram sends to your phone. The session is saved to `telegram_session.session` — you will not be asked again.

### 6. Start the server

```bash
bash up.sh
```

Or manually:

```bash
source .venv/bin/activate
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

### 7. (Optional) Keep channels fresh with a cron job

```bash
# crontab -e
0 * * * * cd /path/to/telegramscraper && source .venv/bin/activate && python scraper.py scrape
```

---

## Project structure

```
telegramscraper/
├── app.py              FastAPI server, all API endpoints
├── database.py         SQLite schema (FTS5, projects, project_data)
├── scraper.py          Telethon scraper CLI
├── translate.py        Google Translate wrapper
├── static/
│   ├── index.html      Home / search page
│   ├── channel.html    Per-channel message feed
│   ├── channels.html   Channel browser
│   ├── results.html    Search results
│   ├── weblinks.html   Web Link Scraper
│   ├── shadowmap.html  ShadowMap GEOSINT viewer
│   ├── nav.js          Shared top navigation (dropdown menus)
│   ├── sidebar.js      Projects sidebar + export functions
│   └── style.css       All styles
├── .env                Local credentials (git-ignored)
├── .env.example        Credential template
├── requirements.txt    Python dependencies
└── up.sh               Startup script
```

---

## API reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/channel/add` | Add a channel by username |
| `POST` | `/api/scrape` | Start scraping a channel |
| `GET`  | `/api/scrape/status` | Poll scrape job status / progress |
| `GET`  | `/api/channels` | List all indexed channels |
| `GET`  | `/api/channel/{username}/messages` | Paginated messages with optional translation |
| `DELETE` | `/api/channel/{username}` | Remove a channel and all its messages |
| `GET`  | `/api/search` | Full-text search |
| `GET`  | `/api/stats` | Total message and channel counts |
| `POST` | `/api/weblinks/extract` | Scrape links from a URL |
| `POST` | `/api/projects` | Create a project |
| `GET`  | `/api/projects` | List all projects |
| `GET`  | `/api/projects/{id}` | Get project with all data files |
| `DELETE` | `/api/projects/{id}` | Delete a project |
| `POST` | `/api/projects/{id}/file` | Upsert a file in a project (append if exists) |
| `PUT`  | `/api/projects/{id}/data/{data_id}` | Update file content |
| `DELETE` | `/api/projects/{id}/data/{data_id}` | Delete a file from a project |
