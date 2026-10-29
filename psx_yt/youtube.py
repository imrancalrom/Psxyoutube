"""Fetch videos from YouTube channels.

Two modes:
  * RSS (default, no key): the channel's public feed - latest ~15 uploads with title, description, views.
  * YouTube Data API v3 (set YOUTUBE_API_KEY): full upload history up to --max videos.
Transcripts are optional and need the `youtube-transcript-api` package.
"""

import re
import xml.etree.ElementTree as ET

import requests

API = "https://www.googleapis.com/youtube/v3"
RSS = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}
_CHANNEL_ID = re.compile(r"UC[\w-]{22}")
HEADERS = {"User-Agent": "Mozilla/5.0 (psx-yt-tracker)", "Accept-Language": "en-US,en;q=0.8"}


class YouTubeError(RuntimeError):
    pass


def _get(url: str, **params) -> requests.Response:
    r = requests.get(url, params=params or None, headers=HEADERS, timeout=30)
    if r.status_code != 200:
        raise YouTubeError(f"GET {r.url} -> HTTP {r.status_code}: {r.text[:200]}")
    return r


def resolve_channel(ref: str, api_key: str | None = None) -> tuple[str, str | None]:
    """Turn a channel ID, /channel/ URL, @handle or /@handle URL into (channel_id, title or None)."""
    ref = ref.strip()
    m = re.fullmatch(r"(?:https?://(?:www\.|m\.)?youtube\.com/channel/)?(UC[\w-]{22})/?", ref)
    if m:
        return m.group(1), None
    m = re.search(r"@([\w.\-]+)", ref)
    if not m:
        raise YouTubeError(f"Don't understand channel reference {ref!r}; use a UC... id or an @handle")
    handle = m.group(1)
    if api_key:
        data = _get(f"{API}/channels", part="snippet", forHandle=handle, key=api_key).json()
        if not data.get("items"):
            raise YouTubeError(f"No channel found for @{handle}")
        item = data["items"][0]
        return item["id"], item["snippet"]["title"]
    html = _get(f"https://www.youtube.com/@{handle}").text
    for pattern in (r'"externalId":"(UC[\w-]{22})"', r'<meta itemprop="identifier" content="(UC[\w-]{22})"',
                    r'"channelId":"(UC[\w-]{22})"'):
        found = re.search(pattern, html)
        if found:
            title = re.search(r'<meta property="og:title" content="([^"]*)"', html)
            return found.group(1), title.group(1) if title else None
    raise YouTubeError(f"Could not find the channel id on the @{handle} page")


def parse_rss(xml_text: str) -> tuple[str | None, list[dict]]:
    root = ET.fromstring(xml_text)
    channel_title = root.findtext("atom:title", namespaces=NS)
    videos = []
    for e in root.findall("atom:entry", NS):
        stats = e.find("media:group/media:community/media:statistics", NS)
        videos.append({
            "id": e.findtext("yt:videoId", namespaces=NS),
            "channel_id": e.findtext("yt:channelId", namespaces=NS),
            "title": e.findtext("atom:title", default="", namespaces=NS),
            "description": e.findtext("media:group/media:description", default="", namespaces=NS),
            "published_at": e.findtext("atom:published", namespaces=NS),
            "views": int(stats.get("views", 0)) if stats is not None else 0,
        })
    return channel_title, videos


def fetch_rss(channel_id: str) -> tuple[str | None, list[dict]]:
    return parse_rss(_get(RSS.format(channel_id)).text)


def fetch_api(channel_id: str, api_key: str, max_videos: int = 200) -> tuple[str | None, list[dict]]:
    ch = _get(f"{API}/channels", part="snippet,contentDetails", id=channel_id, key=api_key).json()
    if not ch.get("items"):
        raise YouTubeError(f"Channel {channel_id} not found")
    title = ch["items"][0]["snippet"]["title"]
    uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    videos, page = [], None
    while len(videos) < max_videos:
        params = dict(part="snippet", playlistId=uploads, maxResults=50, key=api_key)
        if page:
            params["pageToken"] = page
        data = _get(f"{API}/playlistItems", **params).json()
        for it in data.get("items", []):
            sn = it["snippet"]
            videos.append({
                "id": sn["resourceId"]["videoId"],
                "channel_id": channel_id,
                "title": sn.get("title", ""),
                "description": sn.get("description", ""),
                "published_at": sn.get("publishedAt"),
                "views": 0,
            })
        page = data.get("nextPageToken")
        if not page:
            break
    videos = videos[:max_videos]

    by_id = {v["id"]: v for v in videos}
    ids = list(by_id)
    for i in range(0, len(ids), 50):
        data = _get(f"{API}/videos", part="statistics", id=",".join(ids[i:i + 50]), key=api_key).json()
        for it in data.get("items", []):
            by_id[it["id"]]["views"] = int(it.get("statistics", {}).get("viewCount", 0))
    return title, videos


def fetch_transcript(video_id: str, languages=("ur", "en", "hi")) -> str | None:
    """Caption text for a video, or None if unavailable / library not installed."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None
    try:
        if hasattr(YouTubeTranscriptApi, "get_transcript"):  # library < 1.0
            parts = YouTubeTranscriptApi.get_transcript(video_id, languages=list(languages))
            return " ".join(p["text"] for p in parts)
        fetched = YouTubeTranscriptApi().fetch(video_id, languages=list(languages))
        return " ".join(s.text for s in fetched)
    except Exception:
        return None
