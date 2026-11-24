"""Sends pictures and files to Discord through a webhook: post, or replace in place.

Shared by the leaderboard and status jobs. Same pattern as rlgpost.py in the
Wardogs repository. A webhook can only touch messages it posted itself. The
webhook URL is a secret and is never printed.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

UA = "mc-discord-board/1.0 (GitHub Actions; Discord webhook)"
ZONE = ZoneInfo(os.environ.get("MC_TIMEZONE", "").strip() or "America/Phoenix")
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state")


def stamp(when=None, fmt="%b %-d, %Y · %-I:%M %p %Z"):
    """A date and time in the server's home time zone, for the footer of a picture."""
    return (when or datetime.now(ZONE)).astimezone(ZONE).strftime(fmt)


def load(name, default):
    """Read state/<name> as JSON. Returns default if it is missing or damaged."""
    try:
        with open(os.path.join(STATE, name), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def save(name, value):
    os.makedirs(STATE, exist_ok=True)
    with open(os.path.join(STATE, name), "w", encoding="utf-8") as f:
        json.dump(value, f, indent=1, sort_keys=True)


def _send(method, url, data, headers):
    """One request to Discord, waiting and retrying when it says to slow down."""
    for attempt in range(6):
        req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": UA, **headers})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 5:
                raise
            try:
                wait = float(json.loads(e.read()).get("retry_after", 3))
            except (ValueError, AttributeError):
                wait = 3
            time.sleep(min(wait + 0.3, 60))


def _multipart(content, blob, filename, mime):
    """payload_json plus one file, in the form Discord expects for uploads."""
    payload = {
        "content": content[:2000],
        "embeds": [],
        "attachments": [{"id": 0, "filename": filename}],
        "allowed_mentions": {"parse": []},               # nothing in a post can ping anyone
    }
    boundary = "mc" + uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
        f"Content-Type: application/json\r\n\r\n".encode() + json.dumps(payload).encode() + b"\r\n",
        f'--{boundary}\r\nContent-Disposition: form-data; name="files[0]"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n".encode() + blob + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def put_file(webhook, message_id, blob, filename, content="", mime="image/png"):
    """Replace the message if it exists, otherwise post a new one.
    Returns (message id, True if a new message was posted)."""
    webhook = webhook.split("?")[0].rstrip("/")
    data, headers = _multipart(content, blob, filename, mime)
    if message_id:
        try:
            _send("PATCH", f"{webhook}/messages/{message_id}", data, headers)
            return message_id, False
        except urllib.error.HTTPError as e:
            if e.code != 404:          # 404 = the message was deleted; post a fresh one
                raise
    return _send("POST", webhook + "?wait=true", data, headers)["id"], True


def edit_text(webhook, message_id, content):
    """Change only the text under a picture. Returns False if the message is gone."""
    webhook = webhook.split("?")[0].rstrip("/")
    body = json.dumps({"content": content[:2000], "allowed_mentions": {"parse": []}}).encode()
    try:
        _send("PATCH", f"{webhook}/messages/{message_id}", body, {"Content-Type": "application/json"})
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


def describe(error):
    """A safe one-line description of an HTTP error (host and status, never the URL)."""
    host = urllib.parse.urlparse(getattr(error, "url", "") or "").netloc or "the server"
    try:
        detail = error.read()[:300].decode(errors="replace")
    except Exception:  # noqa: BLE001
        detail = ""
    return f"Request to {host} failed with HTTP {getattr(error, 'code', '?')}: {detail}"
