"""
YouTube Oracle - Ingestion Script (v2)

Pulls YouTube's most-popular (trending) videos per category, snapshots their
state, and stores a row per (video, snapshot_time). Videos we see multiple
times get multiple snapshots — letting us reconstruct their growth trajectory.

Videos aged 2-24 hours at snapshot time become our scorable candidates.

Quota cost per run: ~100 units (9 categories x ~10 units each).
Free tier: 10,000 units/day. Plenty of room.
"""

import os
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("YOUTUBE_API_KEY")
DB_PATH = Path(__file__).parent.parent / "data" / "videos.db"

CATEGORIES = {
    "10": "Music",
    "20": "Gaming",
    "22": "People & Blogs",
    "23": "Comedy",
    "24": "Entertainment",
    "25": "News & Politics",
    "26": "Howto & Style",
    "27": "Education",
    "28": "Science & Technology",
}
REGION = "US"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("collect")


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    # One row per video (stable metadata + latest-known channel stats)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            video_id TEXT PRIMARY KEY,
            channel_id TEXT,
            channel_title TEXT,
            title TEXT,
            description TEXT,
            category_id TEXT,
            category_name TEXT,
            published_at TEXT,
            first_seen_at TEXT,
            duration_seconds INTEGER,
            tags_count INTEGER,
            title_length INTEGER,

            -- channel features (updated on each sighting)
            channel_subs INTEGER,
            channel_total_views INTEGER,
            channel_video_count INTEGER,

            -- 7-day outcome (backfilled later)
            views_at_7d INTEGER,
            likes_at_7d INTEGER,
            comments_at_7d INTEGER,
            outcome_checked_at TEXT,
            went_viral INTEGER
        )
    """)

    # Time-series snapshots — we append every run, building growth curves
    conn.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT NOT NULL,
            snapshot_at TEXT NOT NULL,
            age_hours REAL NOT NULL,
            views INTEGER,
            likes INTEGER,
            comments INTEGER,
            FOREIGN KEY (video_id) REFERENCES videos (video_id)
        )
    """)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_snap_video ON snapshots(video_id, snapshot_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_outcome_pending ON videos(outcome_checked_at, published_at)")
    conn.commit()
    return conn


def api_get(endpoint, params):
    params["key"] = API_KEY
    url = f"https://www.googleapis.com/youtube/v3/{endpoint}"
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def get_most_popular(category_id):
    """Fetch YouTube's trending videos for a category. Returns full video objects."""
    return api_get("videos", {
        "part": "snippet,statistics,contentDetails",
        "chart": "mostPopular",
        "videoCategoryId": category_id,
        "regionCode": REGION,
        "maxResults": 50,
    })


def get_channel_stats(channel_ids):
    """Batch fetch channel stats. Up to 50 IDs per call."""
    if not channel_ids:
        return {}
    result = {}
    ids = list(channel_ids)
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        resp = api_get("channels", {"part": "statistics", "id": ",".join(batch)})
        for item in resp.get("items", []):
            s = item.get("statistics", {})
            result[item["id"]] = {
                "subs": int(s.get("subscriberCount", 0)),
                "total_views": int(s.get("viewCount", 0)),
                "video_count": int(s.get("videoCount", 0)),
            }
    return result


def parse_iso_duration(iso_dur: str) -> int:
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_dur or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def collect():
    if not API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY not set. See README.")

    conn = init_db()
    cursor = conn.cursor()
    now = datetime.now(timezone.utc)

    # 1) Pull most-popular per category
    all_items = []
    for cat_id, cat_name in CATEGORIES.items():
        try:
            resp = get_most_popular(cat_id)
            items = resp.get("items", [])
            log.info(f"  {cat_name}: {len(items)} trending videos")
            for item in items:
                item["_our_category"] = cat_id
            all_items.extend(items)
        except requests.HTTPError as e:
            log.error(f"  {cat_name}: API error {e}")
            continue

    if not all_items:
        log.warning("No videos fetched this run.")
        return

    # Deduplicate — a video can appear in multiple categories
    seen = {}
    for item in all_items:
        vid = item["id"]
        if vid not in seen:
            seen[vid] = item
    all_items = list(seen.values())
    log.info(f"{len(all_items)} unique trending videos this run")

    # 2) Fetch channel stats
    channel_ids = {item["snippet"]["channelId"] for item in all_items}
    channel_stats = get_channel_stats(channel_ids)

    # 3) Insert / update videos and append snapshots
    new_videos = 0
    new_snapshots = 0

    for v in all_items:
        vid = v["id"]
        snippet = v["snippet"]
        stats = v.get("statistics", {})
        content = v.get("contentDetails", {})
        ch_id = snippet["channelId"]
        ch = channel_stats.get(ch_id, {})

        published_at_str = snippet.get("publishedAt")
        try:
            published_at = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
            age_hours = (now - published_at).total_seconds() / 3600
        except (ValueError, AttributeError):
            age_hours = -1

        views = int(stats.get("viewCount", 0))
        likes = int(stats.get("likeCount", 0))
        comments = int(stats.get("commentCount", 0))

        # Upsert into videos table
        cursor.execute("SELECT video_id FROM videos WHERE video_id = ?", (vid,))
        if cursor.fetchone() is None:
            cursor.execute("""
                INSERT INTO videos (
                    video_id, channel_id, channel_title, title, description,
                    category_id, category_name, published_at, first_seen_at,
                    duration_seconds, tags_count, title_length,
                    channel_subs, channel_total_views, channel_video_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                vid, ch_id, snippet.get("channelTitle"),
                snippet.get("title"), snippet.get("description", "")[:5000],
                snippet.get("categoryId"),
                CATEGORIES.get(snippet.get("categoryId"), "Other"),
                published_at_str, now.isoformat(),
                parse_iso_duration(content.get("duration", "")),
                len(snippet.get("tags", [])),
                len(snippet.get("title", "")),
                ch.get("subs", 0), ch.get("total_views", 0), ch.get("video_count", 0),
            ))
            new_videos += 1
        else:
            # Refresh channel stats (they change over time)
            cursor.execute("""
                UPDATE videos
                SET channel_subs = ?, channel_total_views = ?, channel_video_count = ?
                WHERE video_id = ?
            """, (ch.get("subs", 0), ch.get("total_views", 0), ch.get("video_count", 0), vid))

        # Always append a snapshot
        cursor.execute("""
            INSERT INTO snapshots (video_id, snapshot_at, age_hours, views, likes, comments)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (vid, now.isoformat(), age_hours, views, likes, comments))
        new_snapshots += 1

    conn.commit()

    # Summary
    total_videos = cursor.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    total_snaps = cursor.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    young = cursor.execute("""
        SELECT COUNT(DISTINCT video_id) FROM snapshots
        WHERE age_hours BETWEEN 2 AND 24
    """).fetchone()[0]

    conn.close()
    log.info(f"+{new_videos} videos, +{new_snapshots} snapshots")
    log.info(f"Totals: {total_videos} videos, {total_snaps} snapshots, {young} in 2-24h window")


if __name__ == "__main__":
    collect()
