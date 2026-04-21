"""
YouTube Oracle - Outcome Backfill

Re-checks videos that are now 7+ days old and records their final stats.
This is what turns caught rows into labeled training data.

Run once daily via cron.
"""

import os
import sqlite3
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("YOUTUBE_API_KEY")
DB_PATH = Path(__file__).parent.parent / "data" / "videos.db"
VIRAL_THRESHOLD = 500_000  # views in 7 days

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("backfill")


def get_video_stats(video_ids):
    params = {
        "part": "statistics",
        "id": ",".join(video_ids),
        "key": API_KEY,
    }
    r = requests.get("https://www.googleapis.com/youtube/v3/videos", params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def backfill():
    if not API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY not set.")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Find videos that are 7+ days old and not yet outcome-checked.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    rows = cursor.execute("""
        SELECT video_id FROM videos
        WHERE published_at <= ?
          AND outcome_checked_at IS NULL
        LIMIT 500
    """, (cutoff,)).fetchall()

    pending = [r[0] for r in rows]
    log.info(f"{len(pending)} videos to backfill")
    if not pending:
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    updated = 0

    for i in range(0, len(pending), 50):
        batch = pending[i:i + 50]
        resp = get_video_stats(batch)
        found = {item["id"]: item.get("statistics", {}) for item in resp.get("items", [])}

        for vid in batch:
            s = found.get(vid)
            if s is None:
                # video deleted or private — mark checked with null stats
                cursor.execute("""
                    UPDATE videos
                    SET outcome_checked_at = ?, went_viral = 0
                    WHERE video_id = ?
                """, (now_iso, vid))
                continue

            views = int(s.get("viewCount", 0))
            likes = int(s.get("likeCount", 0))
            comments = int(s.get("commentCount", 0))
            viral = 1 if views >= VIRAL_THRESHOLD else 0

            cursor.execute("""
                UPDATE videos
                SET views_at_7d = ?, likes_at_7d = ?, comments_at_7d = ?,
                    went_viral = ?, outcome_checked_at = ?
                WHERE video_id = ?
            """, (views, likes, comments, viral, now_iso, vid))
            updated += 1

    conn.commit()

    # Quick summary
    viral_count = cursor.execute(
        "SELECT COUNT(*) FROM videos WHERE went_viral = 1"
    ).fetchone()[0]
    labeled_count = cursor.execute(
        "SELECT COUNT(*) FROM videos WHERE outcome_checked_at IS NOT NULL"
    ).fetchone()[0]

    conn.close()
    log.info(f"Updated {updated} rows. Total labeled: {labeled_count} ({viral_count} viral)")


if __name__ == "__main__":
    backfill()
