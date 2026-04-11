"""
Translation helpers using deep-translator (Google Translate free tier)
and langdetect for language identification.
All results are cached in the `translations` SQLite table.
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from langdetect import detect, LangDetectException
    LANGDETECT_OK = True
except ImportError:
    LANGDETECT_OK = False
    logger.warning("langdetect not installed — language detection disabled")

try:
    from deep_translator import GoogleTranslator
    TRANSLATOR_OK = True
except ImportError:
    TRANSLATOR_OK = False
    logger.warning("deep-translator not installed — translation disabled")


def _lang_base(code: str) -> str:
    """Return the base language code (e.g. 'zh-cn' → 'zh', 'nb' → 'nb')."""
    return (code or "").lower().split("-")[0]


def detect_lang(text: str) -> Optional[str]:
    """Return ISO 639-1 code or None. Only tries for texts >= 15 chars."""
    if not LANGDETECT_OK or not text or len(text.strip()) < 15:
        return None
    try:
        return detect(text[:400])
    except Exception:
        return None


def _needs_translation(source_lang: Optional[str], target_lang: str) -> bool:
    if not source_lang:
        return True  # Unknown — attempt translation
    return _lang_base(source_lang) != _lang_base(target_lang)


def _translate_batch_sync(texts: list, target_lang: str) -> list:
    """Translate a list of strings. Returns same-length list (None on failure)."""
    if not TRANSLATOR_OK or not texts:
        return [None] * len(texts)
    # deep-translator has a per-text limit of ~5000 chars; truncate safely
    safe = [t[:4500] if t else "" for t in texts]
    # Split into chunks of 10 to stay well under rate limits
    results = []
    for i in range(0, len(safe), 10):
        chunk = safe[i:i + 10]
        try:
            translator = GoogleTranslator(source="auto", target=target_lang)
            batch = translator.translate_batch(chunk)
            results.extend(batch if batch else [None] * len(chunk))
        except Exception as exc:
            logger.warning("Translation batch failed: %s", exc)
            results.extend([None] * len(chunk))
    return results


async def translate_batch(texts: list, target_lang: str) -> list:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _translate_batch_sync, texts, target_lang)


async def enrich_messages(messages: list, target_lang: str, db) -> list:
    """
    Given a list of message dicts (must have channel_id, message_id, message_text),
    add 'translated_text' and 'source_lang' fields.
    Reads/writes the translations cache table.
    """
    if not messages or target_lang == "original":
        for m in messages:
            m["translated_text"] = None
            m["source_lang"] = None
        return messages

    # 1. Detect source language for each message
    for m in messages:
        m["source_lang"] = detect_lang(m["message_text"])

    # 2. Split into "needs translation" vs "already in target lang"
    to_translate: list = []
    skip_set: set = set()
    for m in messages:
        key = (m["channel_id"], m["message_id"])
        if _needs_translation(m["source_lang"], target_lang):
            to_translate.append(m)
        else:
            skip_set.add(key)

    # 3. Check DB cache for messages that need translation
    cache: dict = {}
    need_api: list = []
    for m in to_translate:
        cid, mid = m["channel_id"], m["message_id"]
        async with db.execute(
            "SELECT translated_text FROM translations WHERE channel_id=? AND message_id=? AND target_lang=?",
            (cid, mid, target_lang),
        ) as cur:
            row = await cur.fetchone()
        if row:
            cache[(cid, mid)] = row[0]
        else:
            need_api.append(m)

    # 4. Translate uncached messages via API
    if need_api:
        texts = [m["message_text"] for m in need_api]
        translated = await translate_batch(texts, target_lang)
        for m, trans in zip(need_api, translated):
            cid, mid = m["channel_id"], m["message_id"]
            if trans:
                cache[(cid, mid)] = trans
                try:
                    await db.execute(
                        """INSERT OR REPLACE INTO translations
                           (channel_id, message_id, target_lang, translated_text, source_lang)
                           VALUES (?, ?, ?, ?, ?)""",
                        (cid, mid, target_lang, trans, m.get("source_lang")),
                    )
                except Exception as exc:
                    logger.warning("Failed to cache translation: %s", exc)
        try:
            await db.commit()
        except Exception:
            pass

    # 5. Assign results back
    for m in messages:
        key = (m["channel_id"], m["message_id"])
        if key in skip_set:
            m["translated_text"] = None
        else:
            m["translated_text"] = cache.get(key)

    return messages
