"""
FastAPI search server for the Telegram index.
Run with: uvicorn app:app --host 0.0.0.0 --port 8000 --reload
"""

import os
import sys
import math
import asyncio
import time as _time
from contextlib import asynccontextmanager
from typing import Optional

import re
import httpx
from urllib.parse import urljoin, urlparse

import io
import mimetypes
import struct

from fastapi import FastAPI, Query, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import pypdf
import mutagen
from dotenv import load_dotenv
from bs4 import BeautifulSoup

from database import get_db, init_db
from translate import enrich_messages

load_dotenv()

PAGE_SIZE = 10
CHANNEL_PAGE_SIZE = 20

# Path to scraper script
_SCRAPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scraper.py")

# ── In-memory job tracker (one job at a time) ─────────────────────────────────
_job: dict = {
    "status": "idle",
    "operation": None,
    "target": None,
    "log": [],
    "started_at": None,
    "finished_at": None,
}
_job_running: bool = False


async def _run_scraper(args: list) -> None:
    global _job, _job_running
    _job["log"] = []
    _job["started_at"] = _time.time()
    try:
        # Use subprocess_exec (not shell) — safe against injection
        launcher = getattr(asyncio, "create_subprocess_exec")
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        proc = await launcher(
            sys.executable, _SCRAPER, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=os.path.dirname(os.path.abspath(__file__)),
            env=env,
        )
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            _job["log"].append(line)
        await proc.wait()
        _job["status"] = "done" if proc.returncode == 0 else "error"
    except Exception as exc:
        _job["log"].append(f"Error: {exc}")
        _job["status"] = "error"
    finally:
        _job["finished_at"] = _time.time()
        _job_running = False


# ─── Pydantic models ──────────────────────────────────────────────────────────

class AddChannelBody(BaseModel):
    channel: str

class ScrapeBody(BaseModel):
    channel: str = ""

class WebLinksBody(BaseModel):
    url: str
    deep_scrape: bool = False
    selector: str = ""

class ProjectBody(BaseModel):
    name: str
    tags: str = ""
    notes: str = ""

class ProjectDataBody(BaseModel):
    source_type: str = "manual"
    source_ref: str = ""
    content: str


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Telegram Search", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Serve downloaded media files
_MEDIA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media")
os.makedirs(_MEDIA_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory=_MEDIA_DIR), name="media")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def make_snippet(text: str, query: str, length: int = 220) -> str:
    lower_text = text.lower()
    lower_query = query.lower().split()[0] if query.strip() else ""
    pos = lower_text.find(lower_query) if lower_query else -1
    if pos == -1:
        return text[:length] + ("..." if len(text) > length else "")
    start = max(0, pos - length // 2)
    end = min(len(text), start + length)
    return ("..." if start > 0 else "") + text[start:end] + ("..." if end < len(text) else "")


def channel_url(username: str, message_id: int) -> str:
    return f"https://t.me/{username}/{message_id}" if username else ""


def channel_link(username: str) -> str:
    return f"https://t.me/{username}" if username else ""


# ─── Job endpoints ────────────────────────────────────────────────────────────

@app.post("/api/channel/add")
async def api_add_channel(body: AddChannelBody):
    global _job, _job_running
    if _job_running:
        raise HTTPException(status_code=409, detail="A job is already running")
    channel = body.channel.strip()
    if not channel:
        raise HTTPException(status_code=400, detail="channel is required")
    if not os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_session.session")):
        raise HTTPException(
            status_code=400,
            detail=(
                "No Telegram session found. "
                "Run 'python scraper.py add @channel' once in the terminal "
                "to authenticate, then use this button."
            ),
        )
    _job_running = True
    _job.update({"status": "running", "operation": "add", "target": channel,
                 "log": [], "started_at": None, "finished_at": None})
    asyncio.create_task(_run_scraper(["add", channel]))
    return {"status": "started", "operation": "add", "target": channel}


@app.post("/api/scrape")
async def api_scrape(body: ScrapeBody = None):
    global _job, _job_running
    if _job_running:
        raise HTTPException(status_code=409, detail="A job is already running")
    if not os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_session.session")):
        raise HTTPException(
            status_code=400,
            detail=(
                "No Telegram session found. "
                "Run 'python scraper.py add @channel' once in the terminal to authenticate."
            ),
        )
    channel = (body.channel.strip() if body and body.channel else "")
    args = ["scrape"] + ([channel] if channel else [])
    _job_running = True
    _job.update({"status": "running", "operation": "scrape",
                 "target": channel or "all channels",
                 "log": [], "started_at": None, "finished_at": None})
    asyncio.create_task(_run_scraper(args))
    return {"status": "started", "operation": "scrape", "target": channel or "all"}


@app.get("/api/scrape/status")
async def api_scrape_status():
    return _job


# ─── Search & data endpoints ──────────────────────────────────────────────────

@app.get("/api/search")
async def search(
    q: str = Query(..., min_length=1, max_length=500),
    page: int = Query(1, ge=1),
    channel: Optional[str] = Query(None),
    sort: str = Query("relevance", pattern="^(relevance|date|views)$"),
):
    offset = (page - 1) * PAGE_SIZE
    db = await get_db()
    try:
        safe_q = q.replace('"', '""')
        fts_query = f'"{safe_q}"'
        channel_filter = ""
        params_count: list = [fts_query]
        params_results: list = [fts_query]
        if channel:
            channel_filter = "AND m.channel_username = ?"
            params_count.append(channel)
            params_results.append(channel)

        count_sql = f"""
            SELECT COUNT(*) FROM messages_fts f
            JOIN messages m ON m.id = f.rowid
            WHERE messages_fts MATCH ?
            {channel_filter}
        """
        async with db.execute(count_sql, params_count) as cur:
            total = (await cur.fetchone())[0]

        if sort == "date":
            order = "m.message_date DESC"
        elif sort == "views":
            order = "m.views DESC"
        else:
            order = "rank"

        results_sql = f"""
            SELECT m.channel_id, m.channel_username, m.channel_title, m.message_id,
                   m.message_text, m.message_date, m.sender_name, m.views, m.has_media, rank
            FROM messages_fts f
            JOIN messages m ON m.id = f.rowid
            WHERE messages_fts MATCH ?
            {channel_filter}
            ORDER BY {order}
            LIMIT {PAGE_SIZE} OFFSET {offset}
        """
        async with db.execute(results_sql, params_results) as cur:
            rows = await cur.fetchall()

        results = [
            {
                "channel_id": r["channel_id"],
                "channel_username": r["channel_username"],
                "channel_title": r["channel_title"],
                "message_id": r["message_id"],
                "snippet": make_snippet(r["message_text"], q),
                "date": r["message_date"],
                "sender_name": r["sender_name"],
                "views": r["views"],
                "has_media": bool(r["has_media"]),
                "message_url": channel_url(r["channel_username"], r["message_id"]),
                "channel_url": channel_link(r["channel_username"]),
            }
            for r in rows
        ]
        return {"query": q, "total": total, "page": page,
                "pages": math.ceil(total / PAGE_SIZE), "results": results}
    except Exception as e:
        if "fts5" in str(e).lower() or "syntax" in str(e).lower():
            return {"query": q, "total": 0, "page": 1, "pages": 0, "results": []}
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await db.close()


@app.get("/api/channels")
async def list_channels():
    db = await get_db()
    try:
        async with db.execute(
            """
            SELECT c.channel_id, c.channel_username, c.channel_title,
                   c.description, c.subscribers, c.last_scraped,
                   COUNT(m.id) as message_count
            FROM channels c
            LEFT JOIN messages m ON m.channel_id = c.channel_id
            GROUP BY c.channel_id
            ORDER BY message_count DESC
            """
        ) as cur:
            rows = await cur.fetchall()
        return [
            {
                "channel_id": r["channel_id"],
                "username": r["channel_username"],
                "title": r["channel_title"],
                "description": r["description"],
                "subscribers": r["subscribers"],
                "last_scraped": r["last_scraped"],
                "message_count": r["message_count"],
                "channel_url": channel_link(r["channel_username"]),
            }
            for r in rows
        ]
    finally:
        await db.close()


@app.get("/api/stats")
async def stats():
    db = await get_db()
    try:
        async with db.execute("SELECT COUNT(*) FROM messages") as cur:
            total_messages = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM channels") as cur:
            total_channels = (await cur.fetchone())[0]
        async with db.execute("SELECT MAX(message_date) FROM messages") as cur:
            latest = (await cur.fetchone())[0]
        return {"total_messages": total_messages,
                "total_channels": total_channels, "latest_message": latest}
    finally:
        await db.close()


@app.delete("/api/channel/{username}")
async def api_remove_channel(username: str):
    username = username.lstrip("@")
    db = await get_db()
    try:
        async with db.execute(
            "SELECT channel_id, channel_title FROM channels WHERE channel_username = ?", (username,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Channel not found")
        channel_id, title = row["channel_id"], row["channel_title"]
        await db.execute("PRAGMA busy_timeout=5000")
        # Delete messages (FTS triggers fire here), then channel record
        await db.execute("DELETE FROM messages WHERE channel_id = ?", (channel_id,))
        await db.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
        await db.execute("INSERT INTO messages_fts(messages_fts) VALUES('optimize')")
        await db.commit()
        return {"status": "removed", "title": title}
    finally:
        await db.close()


@app.get("/api/channel/{username}/messages")
async def channel_messages(
    username: str,
    page: int = Query(1, ge=1),
    lang: str = Query("en", max_length=10),
):
    username = username.lstrip("@")
    offset = (page - 1) * CHANNEL_PAGE_SIZE
    db = await get_db()
    try:
        async with db.execute(
            "SELECT * FROM channels WHERE channel_username = ?", (username,)
        ) as cur:
            ch = await cur.fetchone()
        if not ch:
            raise HTTPException(status_code=404, detail="Channel not found")

        async with db.execute(
            "SELECT COUNT(*) FROM messages WHERE channel_id = ?", (ch["channel_id"],)
        ) as cur:
            total = (await cur.fetchone())[0]

        async with db.execute(
            """SELECT channel_id, channel_username, channel_title, message_id,
                      message_text, message_date, sender_name, views, forwards, has_media,
                      media_type, media_path
               FROM messages WHERE channel_id = ?
               ORDER BY message_date DESC, message_id DESC
               LIMIT ? OFFSET ?""",
            (ch["channel_id"], CHANNEL_PAGE_SIZE, offset),
        ) as cur:
            rows = await cur.fetchall()

        messages = [dict(r) for r in rows]
        messages = await enrich_messages(messages, lang, db)

        return {
            "channel": {
                "username": ch["channel_username"],
                "title": ch["channel_title"],
                "description": ch["description"],
                "subscribers": ch["subscribers"],
                "last_scraped": ch["last_scraped"],
                "message_count": total,
                "channel_url": channel_link(ch["channel_username"]),
            },
            "messages": [
                {
                    "message_id": m["message_id"],
                    "text": m["message_text"],
                    "translated_text": m.get("translated_text"),
                    "source_lang": m.get("source_lang"),
                    "date": m["message_date"],
                    "sender_name": m.get("sender_name"),
                    "views": m["views"],
                    "forwards": m["forwards"],
                    "has_media": bool(m["has_media"]),
                    "media_type": m.get("media_type"),
                    "media_url": ("/media/" + m["media_path"]) if m.get("media_path") else None,
                    "message_url": channel_url(m["channel_username"], m["message_id"]),
                }
                for m in messages
            ],
            "page": page,
            "pages": math.ceil(total / CHANNEL_PAGE_SIZE) if total else 1,
            "total": total,
        }
    finally:
        await db.close()


# ─── Projects ────────────────────────────────────────────────────────────────

@app.post("/api/projects")
async def api_create_project(body: ProjectBody):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    db = await get_db()
    try:
        async with db.execute(
            "INSERT INTO projects (name, tags, notes) VALUES (?, ?, ?)",
            (name, body.tags.strip(), body.notes.strip()),
        ) as cur:
            project_id = cur.lastrowid
        await db.commit()
        return {"id": project_id, "name": name, "tags": body.tags.strip(), "notes": body.notes.strip()}
    finally:
        await db.close()


@app.get("/api/projects")
async def api_list_projects():
    db = await get_db()
    try:
        async with db.execute(
            """SELECT p.id, p.name, p.tags, p.notes, p.created_at,
                      COUNT(pd.id) as data_count
               FROM projects p
               LEFT JOIN project_data pd ON pd.project_id = p.id
               GROUP BY p.id ORDER BY p.created_at DESC"""
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


@app.get("/api/projects/{project_id}")
async def api_get_project(project_id: int):
    db = await get_db()
    try:
        async with db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
        async with db.execute(
            "SELECT * FROM project_data WHERE project_id = ? ORDER BY exported_at DESC",
            (project_id,),
        ) as cur:
            data_rows = await cur.fetchall()
        return {"project": dict(row), "data": [dict(r) for r in data_rows]}
    finally:
        await db.close()


@app.delete("/api/projects/{project_id}")
async def api_delete_project(project_id: int):
    db = await get_db()
    try:
        async with db.execute("SELECT name FROM projects WHERE id = ?", (project_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
        await db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        await db.commit()
        return {"status": "deleted"}
    finally:
        await db.close()


@app.delete("/api/projects/{project_id}/data/{data_id}")
async def api_delete_project_data(project_id: int, data_id: int):
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM project_data WHERE id = ? AND project_id = ?", (data_id, project_id)
        )
        await db.commit()
        return {"status": "deleted"}
    finally:
        await db.close()


@app.post("/api/projects/{project_id}/data")
async def api_add_project_data(project_id: int, body: ProjectDataBody):
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="content is required")
    db = await get_db()
    try:
        async with db.execute("SELECT id FROM projects WHERE id = ?", (project_id,)) as cur:
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="Project not found")
        async with db.execute(
            "INSERT INTO project_data (project_id, source_type, source_ref, content) VALUES (?, ?, ?, ?)",
            (project_id, body.source_type, body.source_ref, body.content.strip()),
        ) as cur:
            data_id = cur.lastrowid
        await db.commit()
        return {"id": data_id, "project_id": project_id}
    finally:
        await db.close()


class ProjectFileBody(BaseModel):
    source_type: str
    source_ref: str   # used as filename stem
    content: str      # text to append


@app.post("/api/projects/{project_id}/file")
async def api_upsert_project_file(project_id: int, body: ProjectFileBody):
    """Append content to an existing file entry, or create it if missing."""
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="content is required")
    db = await get_db()
    try:
        async with db.execute("SELECT id FROM projects WHERE id = ?", (project_id,)) as cur:
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="Project not found")
        async with db.execute(
            "SELECT id, content FROM project_data WHERE project_id = ? AND source_type = ? AND source_ref = ?",
            (project_id, body.source_type, body.source_ref),
        ) as cur:
            existing = await cur.fetchone()
        if existing:
            new_content = existing["content"] + "\n\n" + body.content.strip()
            await db.execute(
                "UPDATE project_data SET content = ?, exported_at = datetime('now') WHERE id = ?",
                (new_content, existing["id"]),
            )
            await db.commit()
            return {"id": existing["id"], "project_id": project_id, "action": "appended"}
        else:
            async with db.execute(
                "INSERT INTO project_data (project_id, source_type, source_ref, content) VALUES (?, ?, ?, ?)",
                (project_id, body.source_type, body.source_ref, body.content.strip()),
            ) as cur:
                data_id = cur.lastrowid
            await db.commit()
            return {"id": data_id, "project_id": project_id, "action": "created"}
    finally:
        await db.close()


class ProjectDataUpdateBody(BaseModel):
    content: str


@app.put("/api/projects/{project_id}/data/{data_id}")
async def api_update_project_data(project_id: int, data_id: int, body: ProjectDataUpdateBody):
    db = await get_db()
    try:
        async with db.execute(
            "SELECT id FROM project_data WHERE id = ? AND project_id = ?", (data_id, project_id)
        ) as cur:
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="Not found")
        await db.execute(
            "UPDATE project_data SET content = ? WHERE id = ?",
            (body.content, data_id),
        )
        await db.commit()
        return {"status": "updated"}
    finally:
        await db.close()


# ─── Web Link Scraper ────────────────────────────────────────────────────────

_SCRAPER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
}

_DEEP_SCRAPE_LIMIT = 50
_DEEP_SCRAPE_CONCURRENCY = 8


def _extract_tld(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
        parts = host.split(".")
        return "." + parts[-1] if len(parts) >= 2 else host
    except Exception:
        return ""


def _parse_links(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    seen_urls: set[str] = set()
    links = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue
        text = tag.get_text(" ", strip=True) or ""
        links.append({
            "text": text[:200],
            "url": absolute,
            "tld": _extract_tld(absolute),
            "is_duplicate": absolute in seen_urls,
        })
        seen_urls.add(absolute)
    return links


def _parse_meta(html: str, selector: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    description = ""
    selector_data = ""

    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)[:200]

    for attr in [
        {"name": "description"},
        {"property": "og:description"},
        {"name": "og:description"},
    ]:
        tag = soup.find("meta", attrs=attr)
        if tag and tag.get("content"):
            description = tag["content"].strip()[:300]
            break

    if selector:
        try:
            el = soup.select_one(selector)
            if el:
                selector_data = el.get_text(" ", strip=True)[:300]
        except Exception:
            pass

    return {"title": title, "description": description, "selector_data": selector_data}


async def _fetch_page(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await client.get(url, timeout=10, follow_redirects=True)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return None


@app.post("/api/weblinks/extract")
async def api_weblinks_extract(body: WebLinksBody):
    raw_url = body.url.strip()
    if not raw_url:
        raise HTTPException(status_code=400, detail="url is required")
    if not raw_url.startswith(("http://", "https://")):
        raw_url = "https://" + raw_url

    parsed = urlparse(raw_url)
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="Invalid URL")

    async with httpx.AsyncClient(headers=_SCRAPER_HEADERS, follow_redirects=True) as client:
        html = await _fetch_page(client, raw_url)
        if html is None:
            raise HTTPException(status_code=502, detail="Could not fetch the URL")

        links = _parse_links(html, raw_url)

        if body.deep_scrape and links:
            sem = asyncio.Semaphore(_DEEP_SCRAPE_CONCURRENCY)

            async def enrich(link: dict) -> dict:
                async with sem:
                    page_html = await _fetch_page(client, link["url"])
                    if page_html:
                        meta = _parse_meta(page_html, body.selector)
                        link.update(meta)
                    else:
                        link.update({"title": "", "description": "", "selector_data": ""})
                return link

            targets = links[:_DEEP_SCRAPE_LIMIT]
            enriched = await asyncio.gather(*[enrich(lnk) for lnk in targets])
            links = list(enriched) + [
                dict(lnk, title="", description="", selector_data="")
                for lnk in links[_DEEP_SCRAPE_LIMIT:]
            ]
        else:
            for lnk in links:
                lnk.update({"title": "", "description": "", "selector_data": ""})

    return {"url": raw_url, "total": len(links), "links": links}


# ─── Metadata extractor ───────────────────────────────────────────────────────

METADATA_MAX_BYTES = 50 * 1024 * 1024  # 50 MB

class MetadataUrlBody(BaseModel):
    url: str

def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} GB"

def _rational_to_float(v) -> float:
    try:
        if hasattr(v, 'numerator'):
            return v.numerator / v.denominator
        if isinstance(v, tuple) and len(v) == 2:
            return v[0] / v[1]
        return float(v)
    except Exception:
        return 0.0

def _dms_to_decimal(dms, ref: str) -> Optional[float]:
    try:
        d = _rational_to_float(dms[0])
        m = _rational_to_float(dms[1])
        s = _rational_to_float(dms[2])
        dec = d + m / 60 + s / 3600
        if ref in ("S", "W"):
            dec = -dec
        return round(dec, 7)
    except Exception:
        return None

def _fmt_exif_value(tag: str, value) -> str:
    try:
        if tag == "FNumber":
            return f"f/{_rational_to_float(value):.1f}"
        if tag == "ExposureTime":
            v = _rational_to_float(value)
            return f"1/{round(1/v)}s" if v < 1 else f"{v}s"
        if tag == "FocalLength":
            return f"{_rational_to_float(value):.0f} mm"
        if tag in ("ISOSpeedRatings", "PhotographicSensitivity"):
            return str(value)
        if tag == "ExposureBiasValue":
            return f"{_rational_to_float(value):+.1f} EV"
        if tag == "Flash":
            return "Yes" if int(value) & 1 else "No"
        if tag == "MeteringMode":
            modes = {0:"Unknown",1:"Average",2:"Center-weighted",3:"Spot",4:"Multi-spot",5:"Multi-segment",6:"Partial"}
            return modes.get(int(value), str(value))
        if tag == "WhiteBalance":
            return "Manual" if int(value) == 1 else "Auto"
    except Exception:
        pass
    return str(value)

def _extract_image(file_bytes: bytes, result: dict):
    try:
        img = Image.open(io.BytesIO(file_bytes))
        result["categories"].append({"name": "Image", "fields": [
            {"key": "Format",     "value": img.format or "Unknown"},
            {"key": "Mode",       "value": img.mode},
            {"key": "Dimensions", "value": f"{img.width} × {img.height} px"},
        ]})
        exif_raw = img._getexif() if hasattr(img, "_getexif") else None
        if not exif_raw:
            return
        camera, settings, gps_raw = [], [], {}
        CAMERA_TAGS = {"Make","Model","Software","LensModel","LensMake","HostComputer",
                       "DateTime","DateTimeOriginal","DateTimeDigitized","Artist","Copyright"}
        SETTINGS_TAGS = {"FNumber","ExposureTime","ISOSpeedRatings","PhotographicSensitivity",
                         "FocalLength","ExposureBiasValue","MeteringMode","Flash","WhiteBalance",
                         "ExposureProgram","SceneCaptureType"}
        for tag_id, val in exif_raw.items():
            tag = TAGS.get(tag_id, str(tag_id))
            if tag == "GPSInfo":
                for gid, gval in val.items():
                    gps_raw[GPSTAGS.get(gid, str(gid))] = gval
            elif tag in CAMERA_TAGS:
                camera.append({"key": tag.replace("DateTime","Date/Time"), "value": str(val).strip()})
            elif tag in SETTINGS_TAGS:
                settings.append({"key": tag, "value": _fmt_exif_value(tag, val)})
        if camera:
            result["categories"].append({"name": "Camera", "fields": camera})
        if settings:
            result["categories"].append({"name": "Camera Settings", "fields": settings})
        if gps_raw:
            lat = _dms_to_decimal(gps_raw.get("GPSLatitude"), gps_raw.get("GPSLatitudeRef",""))
            lon = _dms_to_decimal(gps_raw.get("GPSLongitude"), gps_raw.get("GPSLongitudeRef",""))
            gps_fields = []
            if lat is not None:
                gps_fields.append({"key": "Latitude",  "value": f"{abs(lat):.6f}° {gps_raw.get('GPSLatitudeRef','')}"})
            if lon is not None:
                gps_fields.append({"key": "Longitude", "value": f"{abs(lon):.6f}° {gps_raw.get('GPSLongitudeRef','')}"})
            if "GPSAltitude" in gps_raw:
                gps_fields.append({"key": "Altitude", "value": f"{_rational_to_float(gps_raw['GPSAltitude']):.1f} m"})
            if "GPSSpeed" in gps_raw:
                gps_fields.append({"key": "Speed", "value": f"{_rational_to_float(gps_raw['GPSSpeed']):.1f} km/h"})
            if "GPSImgDirection" in gps_raw:
                gps_fields.append({"key": "Direction", "value": f"{_rational_to_float(gps_raw['GPSImgDirection']):.1f}°"})
            if "GPSDateStamp" in gps_raw:
                gps_fields.append({"key": "GPS Date", "value": str(gps_raw["GPSDateStamp"])})
            if lat is not None and lon is not None:
                result["gps"] = {"lat": lat, "lon": lon}
                gps_fields.append({"key": "Google Maps", "value": f"https://maps.google.com/?q={lat},{lon}"})
                gps_fields.append({"key": "OpenStreetMap", "value": f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}&zoom=15"})
            if gps_fields:
                result["categories"].append({"name": "GPS", "fields": gps_fields})
    except Exception as e:
        result["categories"].append({"name": "Image", "fields": [{"key": "Parse Error", "value": str(e)}]})

def _extract_pdf(file_bytes: bytes, result: dict):
    try:
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        fields = [{"key": "Pages", "value": str(len(reader.pages))}]
        meta = reader.metadata
        if meta:
            mapping = {
                "/Title": "Title", "/Author": "Author", "/Subject": "Subject",
                "/Creator": "Creator", "/Producer": "Producer",
                "/CreationDate": "Created", "/ModDate": "Modified",
                "/Keywords": "Keywords",
            }
            for k, label in mapping.items():
                v = meta.get(k)
                if v:
                    s = str(v)
                    if s.startswith("D:") and len(s) >= 10:
                        s = f"{s[2:6]}-{s[6:8]}-{s[8:10]} {s[10:12]}:{s[12:14]}:{s[14:16]}" if len(s) >= 16 else s[2:]
                    fields.append({"key": label, "value": s.strip()})
        if reader.is_encrypted:
            fields.append({"key": "Encrypted", "value": "Yes"})
        result["categories"].append({"name": "PDF", "fields": fields})
    except Exception as e:
        result["categories"].append({"name": "PDF", "fields": [{"key": "Parse Error", "value": str(e)}]})

def _extract_docx(file_bytes: bytes, result: dict):
    try:
        import docx
        doc = docx.Document(io.BytesIO(file_bytes))
        cp = doc.core_properties
        fields = []
        for attr, label in [("title","Title"),("author","Author"),("last_modified_by","Last Modified By"),
                             ("subject","Subject"),("description","Description"),("keywords","Keywords"),
                             ("created","Created"),("modified","Modified"),("revision","Revision"),
                             ("category","Category"),("content_status","Status")]:
            v = getattr(cp, attr, None)
            if v:
                fields.append({"key": label, "value": str(v).strip()})
        if fields:
            result["categories"].append({"name": "Document", "fields": fields})
    except Exception as e:
        result["categories"].append({"name": "Document", "fields": [{"key": "Parse Error", "value": str(e)}]})

def _extract_audio_video(file_bytes: bytes, filename: str, result: dict):
    try:
        f = mutagen.File(io.BytesIO(file_bytes), filename=filename, easy=False)
        if f is None:
            return
        fields = []
        if hasattr(f, "info"):
            info = f.info
            if hasattr(info, "length"):
                s = int(info.length)
                fields.append({"key": "Duration", "value": f"{s//60}:{s%60:02d}"})
            if hasattr(info, "bitrate"):
                fields.append({"key": "Bitrate", "value": f"{info.bitrate} kbps"})
            if hasattr(info, "sample_rate"):
                fields.append({"key": "Sample Rate", "value": f"{info.sample_rate} Hz"})
            if hasattr(info, "channels"):
                fields.append({"key": "Channels", "value": str(info.channels)})
            if hasattr(info, "width") and hasattr(info, "height"):
                fields.append({"key": "Dimensions", "value": f"{info.width} × {info.height} px"})
            if hasattr(info, "codec"):
                fields.append({"key": "Codec", "value": str(info.codec)})
        tag_map = {
            "TIT2":"Title", "TPE1":"Artist", "TALB":"Album", "TDRC":"Year",
            "TCOM":"Composer", "TCON":"Genre", "TRCK":"Track", "COMM:":"Comment",
            "©nam":"Title", "©ART":"Artist", "©alb":"Album", "©day":"Year",
            "title":"Title", "artist":"Artist", "album":"Album", "date":"Year",
            "genre":"Genre", "tracknumber":"Track",
        }
        for key, val in f.tags.items() if f.tags else []:
            label = next((v for k, v in tag_map.items() if key.startswith(k)), None)
            if label:
                try:
                    text = str(val.text[0]) if hasattr(val, "text") else str(val)
                    fields.append({"key": label, "value": text.strip()})
                except Exception:
                    pass
        if fields:
            result["categories"].append({"name": "Audio/Video", "fields": fields})
    except Exception as e:
        result["categories"].append({"name": "Audio/Video", "fields": [{"key": "Parse Error", "value": str(e)}]})

def extract_file_metadata(file_bytes: bytes, filename: str) -> dict:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    result: dict = {
        "filename": filename,
        "file_size": len(file_bytes),
        "mime_type": mime_type,
        "categories": [],
        "gps": None,
    }
    result["categories"].append({"name": "File", "fields": [
        {"key": "Filename",  "value": filename},
        {"key": "File Size", "value": _fmt_size(len(file_bytes))},
        {"key": "MIME Type", "value": mime_type},
        {"key": "Extension", "value": ext.upper() if ext else "Unknown"},
    ]})
    if mime_type.startswith("image/"):
        _extract_image(file_bytes, result)
    elif mime_type == "application/pdf":
        _extract_pdf(file_bytes, result)
    elif ext in ("docx",):
        _extract_docx(file_bytes, result)
    elif mime_type.startswith("audio/") or mime_type.startswith("video/") or ext in ("mp3","flac","ogg","wav","m4a","mp4","mkv","avi","mov"):
        _extract_audio_video(file_bytes, filename, result)
    return result


@app.post("/api/metadata/upload")
async def api_metadata_upload(file: UploadFile = File(...)):
    data = await file.read(METADATA_MAX_BYTES + 1)
    if len(data) > METADATA_MAX_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 50 MB limit")
    return extract_file_metadata(data, file.filename or "upload")


@app.post("/api/metadata/url")
async def api_metadata_url(body: MetadataUrlBody):
    parsed = urlparse(body.url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only http/https URLs are supported")
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            async with client.stream("GET", body.url) as resp:
                resp.raise_for_status()
                chunks = []
                total = 0
                async for chunk in resp.aiter_bytes(65536):
                    total += len(chunk)
                    if total > METADATA_MAX_BYTES:
                        raise HTTPException(status_code=413, detail="Remote file exceeds 50 MB limit")
                    chunks.append(chunk)
                data = b"".join(chunks)
        filename = parsed.path.rsplit("/", 1)[-1] or "download"
        if not filename or "." not in filename:
            ct = resp.headers.get("content-type", "")
            ext = mimetypes.guess_extension(ct.split(";")[0].strip()) or ""
            filename = "download" + ext
        return extract_file_metadata(data, filename)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ─── Frontend routes ──────────────────────────────────────────────────────────

@app.get("/", response_class=FileResponse)
async def index():
    return FileResponse("static/index.html")


@app.get("/channel/{username}", response_class=FileResponse)
async def channel_page(username: str):
    return FileResponse("static/channel.html")


@app.get("/results", response_class=FileResponse)
async def results_page():
    return FileResponse("static/results.html")


@app.get("/channels", response_class=FileResponse)
async def channels_page():
    return FileResponse("static/channels.html")


@app.get("/weblinks", response_class=FileResponse)
async def weblinks_page():
    return FileResponse("static/weblinks.html")


@app.get("/shadowmap", response_class=FileResponse)
async def shadowmap_page():
    return FileResponse("static/shadowmap.html")


@app.get("/metadata", response_class=FileResponse)
async def metadata_page():
    return FileResponse("static/metadata.html")
