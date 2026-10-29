"""SQLite storage for channels, videos and detected stock mentions."""

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,
    title TEXT,
    ref TEXT
);
CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL REFERENCES channels(id),
    title TEXT NOT NULL,
    description TEXT,
    published_at TEXT NOT NULL,
    views INTEGER DEFAULT 0,
    transcript TEXT
);
CREATE TABLE IF NOT EXISTS mentions (
    video_id TEXT NOT NULL REFERENCES videos(id),
    symbol TEXT NOT NULL,
    in_title INTEGER NOT NULL,
    in_description INTEGER NOT NULL,
    in_transcript INTEGER NOT NULL,
    sentiment INTEGER NOT NULL,
    holds INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (video_id, symbol)
);
CREATE TABLE IF NOT EXISTS sector_mentions (
    video_id TEXT NOT NULL REFERENCES videos(id),
    sector TEXT NOT NULL,
    in_title INTEGER NOT NULL,
    in_description INTEGER NOT NULL,
    in_transcript INTEGER NOT NULL,
    sentiment INTEGER NOT NULL,
    holds INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (video_id, sector)
);
CREATE INDEX IF NOT EXISTS idx_videos_published ON videos(published_at);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for table in ("mentions", "sector_mentions"):  # databases made before hold calls were tracked
        if "holds" not in {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN holds INTEGER NOT NULL DEFAULT 0")
    return conn


def upsert_channel(conn, channel_id: str, title: str | None, ref: str | None = None):
    conn.execute(
        """INSERT INTO channels (id, title, ref) VALUES (?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET title = COALESCE(excluded.title, channels.title),
                                         ref = COALESCE(excluded.ref, channels.ref)""",
        (channel_id, title, ref),
    )


def upsert_video(conn, v: dict):
    conn.execute(
        """INSERT INTO videos (id, channel_id, title, description, published_at, views, transcript)
           VALUES (:id, :channel_id, :title, :description, :published_at, :views, :transcript)
           ON CONFLICT(id) DO UPDATE SET title = excluded.title, description = excluded.description,
               views = MAX(excluded.views, videos.views),
               transcript = COALESCE(excluded.transcript, videos.transcript)""",
        {"transcript": None, "views": 0, "description": "", **v},
    )


def videos_without_transcript(conn) -> list[sqlite3.Row]:
    """Videos whose captions have not been fetched yet (transcript NULL; "" means the video has none), newest first."""
    return conn.execute(
        "SELECT id, published_at FROM videos WHERE transcript IS NULL ORDER BY published_at DESC"
    ).fetchall()


def reset_empty_transcripts(conn) -> int:
    """Mark videos recorded as caption-less for another try; returns how many."""
    return conn.execute("UPDATE videos SET transcript = NULL WHERE transcript = ''").rowcount
