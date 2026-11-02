"""Send the daily digest to Telegram.

Setup: create a bot with @BotFather (it gives you a token), send your bot any message, then run
`notify --find-chat` (or the workflow with "Find Telegram chat id" ticked) to see your chat id. Store both as GitHub
secrets TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (several chats: comma-separated ids). The token is never printed.
"""

import html

import requests

API = "https://api.telegram.org/bot{token}/{method}"
LIMIT = 4096  # Telegram's maximum message length


class TelegramError(RuntimeError):
    pass


RUN_LINK_TEXT = "Dashboard and files (Artifacts → psx-yt-report)"


def message(d: dict, link: str | None = None, link_text: str = RUN_LINK_TEXT) -> str:
    """The digest as Telegram HTML: bold title and section names, bullet lists, an optional link at the end (the
    published dashboard, or the workflow run whose artifacts hold it)."""
    e = html.escape
    lines = [f"<b>{e(d['title'])}</b>", e(d["headline"])]
    for s in d["sections"]:
        lines += ["", f"<b>{e(s['title'])}</b>"] + [f"• {e(item)}" for item in s["items"]]
    if link:
        lines += ["", f'<a href="{e(link, quote=True)}">{e(link_text)}</a>']
    lines += ["", "<i>What the tracked channels said, detected from keywords; technical signals are mechanical "
                  "calculations from daily closes. Not investment advice.</i>"]
    return "\n".join(lines)


def split(text: str, limit: int = LIMIT) -> list[str]:
    """Break a long message at line ends (a single over-long line is cut) so each part fits Telegram's limit."""
    parts, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = f"{cur}\n{line}" if cur else line
        if len(candidate) > limit:
            parts.append(cur)
            cur = line
        else:
            cur = candidate
    if cur:
        parts.append(cur)
    return parts


def _call(token: str, method: str, **payload) -> dict:
    try:
        r = requests.post(API.format(token=token, method=method), json=payload or None, timeout=30)
    except requests.RequestException as e:
        # The exception text contains the URL, which holds the token: report only the kind of error.
        raise TelegramError(f"could not reach Telegram ({type(e).__name__})") from None
    try:
        body = r.json()
    except ValueError:
        body = {}
    if not body.get("ok"):
        hint = {401: " (check TELEGRAM_BOT_TOKEN)", 400: " (check TELEGRAM_CHAT_ID)",
                403: " (send your bot a message first, or add it to the group/channel)"}.get(r.status_code, "")
        raise TelegramError(f"Telegram said {r.status_code}: {body.get('description', 'no details')}{hint}")
    return body


def send(token: str, chat_ids: str, text: str) -> int:
    """Send `text` (split if needed) to each comma-separated chat id; returns the number of messages sent."""
    sent = 0
    for chat in [c.strip() for c in chat_ids.split(",") if c.strip()]:
        for part in split(text):
            _call(token, "sendMessage", chat_id=chat, text=part, parse_mode="HTML", disable_web_page_preview=True)
            sent += 1
    return sent


def find_chats(token: str) -> list[dict]:
    """Chats that recently messaged the bot (or added it): [{"id", "type", "name"}]."""
    chats = {}
    for u in _call(token, "getUpdates")["result"]:
        for key in ("message", "channel_post", "my_chat_member", "edited_message"):
            chat = (u.get(key) or {}).get("chat")
            if chat:
                name = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])) \
                    or chat.get("username") or ""
                chats[chat["id"]] = {"id": chat["id"], "type": chat.get("type", ""), "name": name}
    return list(chats.values())
