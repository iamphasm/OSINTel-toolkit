# CHANGES — OSIntelligence Toolkit

Developed by Phasm. All notable changes are recorded here, newest first.
Current version: v1.0.1

---

## v1.0.0

### Rename to OSIntelligence Toolkit
- All page titles, alt text, and document titles updated from "PHASM" to "OSIntelligence Toolkit"
- README.md updated with new product name and Phasm attribution
- VERSION file introduced; CHANGES.md now tracks version numbers
- Git pre-commit hook installed to auto-increment patch version on every commit

### Web Link Scraper — Domain exclusion auto-rules
- Auto-exclude rule: scraping any `github.com` URL pre-fills the exclude field with `github.com, github.blog, githubstatus.com, github.community`
- Rule system extensible via `AUTO_EXCLUDE_RULES` array in `weblinks.html`
- Auto-fill is overridden if the user manually edits the exclude field

### Web Link Scraper — Domain exclusion filter
- Added "Exclude domains" input field below the options row
- Comma-separated list of domains to hide from results (e.g. `google.com, t.co`)
- Subdomain-aware: excluding `google.com` also removes `maps.google.com`
- Filter updates the table live as you type
- Excluded links are also removed from CSV and PDF exports

### Web Link Scraper — Export PDF
- Added green "Export PDF" button next to "Export CSV" in the toolbar
- Opens column picker modal (same pattern as CSV export)
- Generates formatted HTML table and opens browser print dialog
- URL column renders as clickable links; duplicate rows highlighted in yellow

### Telegram Scraper — Export as PDF (project file)
- "Export to Project" renamed to "Export as PDF"
- Selected messages built into a full HTML document (images, links, metadata)
- HTML saved to active Project under `Telegram Scraper/YYYY-MM-DD_channelname.html`
- Stored HTML opens in an iframe overlay when clicked in the Project sidebar
- Overlay has Print to PDF (green), Delete (red), and Close buttons

### Projects sidebar — HTML viewer overlay
- HTML project files open in a full-page iframe overlay instead of the text editor
- Print to PDF button calls `iframe.contentWindow.print()`
- Delete button removes the file and refreshes the sidebar tree

### Projects sidebar — file tree
- Project data grouped as folder/file tree in the View Project panel
- `source_type` is the folder name (e.g. "Telegram Scraper")
- `source_ref` becomes the filename stem; extension auto-detected (`.html` or `.txt`)
- Each file row has a delete button; clicking a file opens editor or viewer

### Projects sidebar — initial implementation
- Right-side collapsible sidebar via PROJECTS nav menu or `❮` tab button
- Create Project: name, tags, notes; saves and sets as active
- Choose Project: list all projects, click Select to activate
- View Project: folder/file tree of all exported data
- `window.phasmSidebar.open(mode)` API for nav menu integration
- `window.phasmExportHtmlToProject(htmlContent, sourceType, sourceRef)` for HTML exports
- `window.phasmExportToProject(messages, sourceType, sourceRef)` for plain text exports
- Active project persisted in `localStorage`
- Toast notifications throughout

### Backend — Projects API
- `POST /api/projects` — create project
- `GET /api/projects` — list all with data_count
- `GET /api/projects/{id}` — detail with all data entries
- `DELETE /api/projects/{id}` — delete project (cascades to data)
- `POST /api/projects/{id}/file` — upsert file by (source_type, source_ref)
- `PUT /api/projects/{id}/data/{data_id}` — update file content
- `DELETE /api/projects/{id}/data/{data_id}` — delete a file entry

### Top navigation — PROJECTS + GEOSINT menus
- PROJECTS dropdown: Create Project, Choose Project, View Project
- GEOSINT dropdown: ShadowMap (embedded iframe viewer)
- TOOLS dropdown: Telegram Scraper, Web Link Scraper

### Web Link Scraper — initial implementation
- URL input, deep scrape mode, CSS selector input
- Results table: sortable columns, TLD filter, duplicate detection
- Export CSV and Export PDF with column picker modals
- Backend: `POST /api/weblinks/extract` using httpx + BeautifulSoup4, async semaphore

### Telegram Scraper — message selection and PDF export
- Checkboxes on each message post (absolutely positioned inside CSS grid)
- Selection bar: count, Export as PDF, Deselect All
- PDF export generates full HTML with images and clickable links

### Telegram Scraper — Remove Channel
- Red "Remove Channel" button in channel subheader with confirmation
- `DELETE /api/channel/{username}` removes messages, channel row, runs FTS optimize

### Telegram Scraper — scrape progress bar
- Progress bar on home page job card
- Scraper emits `SCRAPE_START:{total}` and `SCRAPE_PROG:{n}` markers to stdout
- Fixed subprocess stdout buffering with `PYTHONUNBUFFERED=1`
- Default `INITIAL_SCRAPE_LIMIT` changed from 1000 to 100

### Sidebar tab arrow fix
- `❮` when closed (open), `❯` when open (close)
- Clicking the tab defaults to View Project if no prior mode was set

### Backend — database locked fix
- Added `PRAGMA busy_timeout=5000` to all DB connections

### App-wide branding
- All pages use consistent `app-header` / `app-logo` layout
- Navigation bar with expandable dropdown menus
- Nav group buttons: black, ALL CAPS, bold
