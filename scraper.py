"""
Telegram scraper — fetches public channel messages and indexes them in SQLite.

Usage:
    python scraper.py add <channel_username_or_link>
    python scraper.py scrape [channel_username]
    python scraper.py list
    python scraper.py remove <channel_username>
"""

import asyncio
import re
import sys
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import (
    Channel, Chat, User,
    MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage,
)
from telethon.errors import (
    ChannelPrivateError,
    UsernameNotOccupiedError,
    FloodWaitError,
    InviteHashInvalidError,
    InviteHashExpiredError,
)

import aiosqlite
from database import get_db, init_db

load_dotenv()

API_ID   = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
PHONE    = os.getenv("TELEGRAM_PHONE", "")
INITIAL_SCRAPE_LIMIT = int(os.getenv("INITIAL_SCRAPE_LIMIT", "100"))

_BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
SESSION_PATH = os.path.join(_BASE_DIR, "telegram_session")
MEDIA_DIR    = os.path.join(_BASE_DIR, "media")
os.makedirs(MEDIA_DIR, exist_ok=True)


def make_client():
    return TelegramClient(SESSION_PATH, API_ID, API_HASH)


def normalize_input(raw: str) -> str:
    raw = raw.strip()
    # Invite link — keep full URL so Telethon resolves the hash
    m = re.match(
        r'^(?:https?://)?t\.me/(joinchat/[A-Za-z0-9_-]+|\+[A-Za-z0-9_-]+)$',
        raw, re.IGNORECASE,
    )
    if m:
        return 'https://t.me/' + m.group(1)
    # Public channel URL
    m = re.match(r'^(?:https?://)?t\.me/([A-Za-z0-9_]{3,32})$', raw, re.IGNORECASE)
    if m:
        return m.group(1)
    return raw.lstrip('@')


async def _download_photo(client, message, channel_id) -> str | None:
    """Download photo to MEDIA_DIR and return the filename, or None on failure."""
    filename = f"{channel_id}_{message.id}.jpg"
    full_path = os.path.join(MEDIA_DIR, filename)
    if os.path.exists(full_path):
        return filename
    try:
        await client.download_media(message, full_path)
        return filename
    except Exception:
        return None


async def _download_video(client, message, channel_id) -> str | None:
    """Download video if it's small enough (<= 20 MB), return filename or None."""
    doc = message.media.document if isinstance(message.media, MessageMediaDocument) else None
    if doc is None:
        return None
    size_mb = (doc.size or 0) / (1024 * 1024)
    if size_mb > 20:
        return None
    # Determine extension from mime_type
    mime = getattr(doc, "mime_type", "") or ""
    ext = mime.split("/")[-1] if "/" in mime else "mp4"
    if ext not in ("mp4", "mov", "webm", "avi", "mkv"):
        ext = "mp4"
    filename = f"{channel_id}_{message.id}.{ext}"
    full_path = os.path.join(MEDIA_DIR, filename)
    if os.path.exists(full_path):
        return filename
    try:
        await client.download_media(message, full_path)
        return filename
    except Exception:
        return None


async def _detect_media(client, message, channel_id):
    """Return (media_type, media_path) for a message."""
    if not message.media:
        return None, None

    if isinstance(message.media, MessageMediaPhoto):
        path = await _download_photo(client, message, channel_id)
        return "photo", path

    if isinstance(message.media, MessageMediaDocument):
        doc = message.media.document
        mime = (getattr(doc, "mime_type", "") or "").lower()
        if mime.startswith("video/") or mime == "video":
            path = await _download_video(client, message, channel_id)
            return "video", path
        if mime.startswith("image/"):
            path = await _download_photo(client, message, channel_id)
            return "photo", path
        if mime.startswith("audio/"):
            return "audio", None
        # Try to get a human-readable name from document attributes
        return "document", None

    if isinstance(message.media, MessageMediaWebPage):
        return "webpage", None

    return "other", None


async def add_channel(client: TelegramClient, db: aiosqlite.Connection, raw_input: str):
    identifier = normalize_input(raw_input)
    is_invite = identifier.startswith('https://t.me/')
    print(f"Resolving {'invite link' if is_invite else '@' + identifier} ...")
    try:
        entity = await client.get_entity(identifier)
    except (UsernameNotOccupiedError, ValueError,
            InviteHashInvalidError, InviteHashExpiredError, KeyError) as e:
        print(f"Error: could not find channel — {e}")
        return None

    if not isinstance(entity, (Channel, Chat)):
        print("Error: entity is not a channel or group")
        return None

    channel_id       = str(entity.id)
    channel_title    = entity.title
    channel_username = getattr(entity, 'username', None) or (
        identifier if not is_invite else str(entity.id)
    )

    try:
        from telethon.tl.functions.channels import GetFullChannelRequest
        full_ch      = await client(GetFullChannelRequest(entity))
        description  = full_ch.full_chat.about or ""
        subscribers  = full_ch.full_chat.participants_count or 0
    except Exception:
        description, subscribers = "", 0

    await db.execute(
        """
        INSERT INTO channels (channel_id, channel_username, channel_title, description, subscribers)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(channel_id) DO UPDATE SET
            channel_username=excluded.channel_username,
            channel_title=excluded.channel_title,
            description=excluded.description,
            subscribers=excluded.subscribers
        """,
        (channel_id, channel_username, channel_title, description, subscribers),
    )
    await db.commit()
    print(f"Added: {channel_title} (@{channel_username}) — {subscribers:,} subscribers")
    return channel_id, channel_username


async def scrape_channel(
    client: TelegramClient,
    db: aiosqlite.Connection,
    channel_username: str,
    limit: int = INITIAL_SCRAPE_LIMIT,
):
    channel_username = channel_username.lstrip("@")
    print(f"\nScraping @{channel_username} (up to {limit} messages) ...")

    try:
        entity = await client.get_entity(channel_username)
    except (ChannelPrivateError, UsernameNotOccupiedError) as e:
        print(f"  Skipping — {e}")
        return 0

    channel_id    = str(entity.id)
    channel_title = getattr(entity, "title", channel_username)

    async with db.execute(
        "SELECT MAX(message_id), COUNT(*) FROM messages WHERE channel_id = ?", (channel_id,)
    ) as cur:
        row = await cur.fetchone()
        min_id       = row[0] or 0
        already_have = row[1] or 0

    # Estimate how many new messages to fetch for progress reporting
    try:
        total_in_channel = (await client.get_messages(entity, limit=0)).total
    except Exception:
        total_in_channel = 0
    to_process = max(min(total_in_channel - already_have, limit), 1)
    print(f"SCRAPE_START:{to_process}")
    print(f"  Channel has {total_in_channel:,} messages total, {already_have:,} already indexed")

    inserted = 0
    skipped  = 0
    try:
        async for message in client.iter_messages(
            entity, limit=limit, min_id=min_id, reverse=False
        ):
            if not message.text and not message.media:
                continue

            sender_name = None
            if message.sender:
                s = message.sender
                if isinstance(s, User):
                    parts = [s.first_name or "", s.last_name or ""]
                    sender_name = " ".join(p for p in parts if p).strip() or None
                elif isinstance(s, (Channel, Chat)):
                    sender_name = s.title

            date_str = message.date.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            media_type, media_path = await _detect_media(client, message, channel_id)
            text = message.text or ""

            # Skip entirely if no text AND media type we can't display
            if not text and media_type not in ("photo", "video", "audio"):
                skipped += 1
                continue

            try:
                await db.execute(
                    """
                    INSERT INTO messages
                        (channel_id, channel_username, channel_title, message_id,
                         message_text, message_date, sender_name,
                         views, forwards, has_media, media_type, media_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(channel_id, message_id) DO UPDATE SET
                        media_type = COALESCE(excluded.media_type, media_type),
                        media_path = COALESCE(excluded.media_path, media_path)
                    """,
                    (
                        channel_id, channel_username, channel_title, message.id,
                        text, date_str, sender_name,
                        message.views or 0, message.forwards or 0,
                        1 if message.media else 0,
                        media_type, media_path,
                    ),
                )
                inserted += 1
            except Exception:
                skipped += 1

            processed = inserted + skipped
            if processed % 10 == 0 and processed > 0:
                print(f"SCRAPE_PROG:{processed}")
            if inserted % 100 == 0 and inserted > 0:
                await db.commit()

    except FloodWaitError as e:
        print(f"  Rate limited — waiting {e.seconds}s ...")
        await asyncio.sleep(e.seconds)
    except ChannelPrivateError:
        print("  Channel became private, skipping")

    await db.commit()
    await db.execute(
        "UPDATE channels SET last_scraped = datetime('now') WHERE channel_id = ?",
        (channel_id,),
    )
    await db.commit()
    print(f"SCRAPE_PROG:{to_process}")
    print(f"  Done: {inserted} new messages indexed, {skipped} skipped")
    return inserted


async def scrape_all(client: TelegramClient, db: aiosqlite.Connection):
    async with db.execute("SELECT channel_username FROM channels") as cur:
        channels = [row[0] for row in await cur.fetchall()]
    if not channels:
        print("No channels added yet. Use: python scraper.py add <channel>")
        return
    total = 0
    for username in channels:
        total += await scrape_channel(client, db, username)
    print(f"\nTotal new messages indexed: {total}")


async def list_channels(db: aiosqlite.Connection):
    async with db.execute(
        "SELECT channel_username, channel_title, subscribers, last_scraped FROM channels ORDER BY channel_title"
    ) as cur:
        rows = await cur.fetchall()
    if not rows:
        print("No channels indexed yet.")
        return
    print(f"\n{'Username':<25} {'Title':<35} {'Subscribers':>12} {'Last scraped'}")
    print("-" * 90)
    for row in rows:
        print(f"@{row[0]:<24} {row[1]:<35} {row[2]:>12,} {row[3] or 'never'}")


async def remove_channel(db: aiosqlite.Connection, username: str):
    username = username.lstrip("@")
    async with db.execute(
        "SELECT channel_id, channel_title FROM channels WHERE channel_username = ?", (username,)
    ) as cur:
        row = await cur.fetchone()
    if not row:
        print(f"Channel @{username} not found in database")
        return
    channel_id, title = row[0], row[1]
    await db.execute("DELETE FROM messages WHERE channel_id = ?", (channel_id,))
    await db.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
    await db.commit()
    print(f"Removed {title} and all its messages")


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]
    await init_db()
    db = await get_db()

    try:
        if cmd == "list":
            await list_channels(db)
            return
        if cmd == "remove" and len(sys.argv) >= 3:
            await remove_channel(db, sys.argv[2])
            return

        if not API_ID or not API_HASH:
            print("Error: TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env")
            return

        async with make_client() as client:
            if PHONE:
                await client.start(phone=PHONE)
            else:
                await client.start()

            if cmd == "add" and len(sys.argv) >= 3:
                result = await add_channel(client, db, sys.argv[2])
                if result:
                    _, channel_username = result
                    print("\nScraping new channel now ...")
                    await scrape_channel(client, db, channel_username)

            elif cmd == "scrape":
                if len(sys.argv) >= 3:
                    await scrape_channel(client, db, sys.argv[2])
                else:
                    await scrape_all(client, db)
            else:
                print(__doc__)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
