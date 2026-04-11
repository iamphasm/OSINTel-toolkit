import aiosqlite
import os
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "telegram_search.db")

CREATE_MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL,
    channel_username TEXT,
    channel_title TEXT NOT NULL,
    message_id INTEGER NOT NULL,
    message_text TEXT NOT NULL,
    message_date TEXT NOT NULL,
    sender_name TEXT,
    views INTEGER DEFAULT 0,
    forwards INTEGER DEFAULT 0,
    has_media INTEGER DEFAULT 0,
    UNIQUE(channel_id, message_id)
);
"""

CREATE_CHANNELS_TABLE = """
CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT UNIQUE NOT NULL,
    channel_username TEXT,
    channel_title TEXT NOT NULL,
    description TEXT,
    subscribers INTEGER DEFAULT 0,
    last_scraped TEXT,
    added_at TEXT DEFAULT (datetime('now'))
);
"""

CREATE_FTS_TABLE = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    channel_title,
    channel_username,
    message_text,
    sender_name,
    message_date,
    channel_id UNINDEXED,
    message_id UNINDEXED,
    views UNINDEXED,
    has_media UNINDEXED,
    content='messages',
    content_rowid='id',
    tokenize='unicode61'
);
"""

CREATE_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, channel_title, channel_username, message_text, sender_name, message_date, channel_id, message_id, views, has_media)
    VALUES (new.id, new.channel_title, new.channel_username, new.message_text, new.sender_name, new.message_date, new.channel_id, new.message_id, new.views, new.has_media);
END;

CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, channel_title, channel_username, message_text, sender_name, message_date, channel_id, message_id, views, has_media)
    VALUES ('delete', old.id, old.channel_title, old.channel_username, old.message_text, old.sender_name, old.message_date, old.channel_id, old.message_id, old.views, old.has_media);
END;

CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, channel_title, channel_username, message_text, sender_name, message_date, channel_id, message_id, views, has_media)
    VALUES ('delete', old.id, old.channel_title, old.channel_username, old.message_text, old.sender_name, old.message_date, old.channel_id, old.message_id, old.views, old.has_media);
    INSERT INTO messages_fts(rowid, channel_title, channel_username, message_text, sender_name, message_date, channel_id, message_id, views, has_media)
    VALUES (new.id, new.channel_title, new.channel_username, new.message_text, new.sender_name, new.message_date, new.channel_id, new.message_id, new.views, new.has_media);
END;
"""

CREATE_TRANSLATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL,
    message_id INTEGER NOT NULL,
    target_lang TEXT NOT NULL,
    translated_text TEXT NOT NULL,
    source_lang TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(channel_id, message_id, target_lang)
);
"""

CREATE_PROJECTS_TABLE = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    tags TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);
"""

CREATE_PROJECT_DATA_TABLE = """
CREATE TABLE IF NOT EXISTS project_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_type TEXT DEFAULT 'manual',
    source_ref TEXT DEFAULT '',
    content TEXT NOT NULL,
    exported_at TEXT DEFAULT (datetime('now'))
);
"""

CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_messages_channel_id ON messages(channel_id);
CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(message_date DESC);
CREATE INDEX IF NOT EXISTS idx_channels_username ON channels(channel_username);
CREATE INDEX IF NOT EXISTS idx_translations_lookup ON translations(channel_id, message_id, target_lang);
"""


async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA synchronous=NORMAL")
    await db.execute("PRAGMA cache_size=10000")
    await db.execute("PRAGMA busy_timeout=5000")
    return db


async def init_db():
    db = await get_db()
    try:
        await db.execute(CREATE_MESSAGES_TABLE)
        await db.execute(CREATE_CHANNELS_TABLE)
        await db.execute(CREATE_TRANSLATIONS_TABLE)
        await db.execute(CREATE_PROJECTS_TABLE)
        await db.execute(CREATE_PROJECT_DATA_TABLE)
        await db.execute(CREATE_FTS_TABLE)
        for trigger in CREATE_FTS_TRIGGERS.strip().split(";\n\n"):
            t = trigger.strip()
            if t:
                await db.execute(t)
        for idx in CREATE_INDEXES.strip().split("\n"):
            i = idx.strip()
            if i:
                await db.execute(i)
        # Migrate: add media columns to existing DBs
        for col_def in [
            "ALTER TABLE messages ADD COLUMN media_type TEXT",
            "ALTER TABLE messages ADD COLUMN media_path TEXT",
        ]:
            try:
                await db.execute(col_def)
            except Exception:
                pass  # column already exists
        await db.commit()
    finally:
        await db.close()
