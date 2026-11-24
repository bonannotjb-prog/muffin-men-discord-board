"""Reads the Minecraft server three ways: the BisectHosting Starbase panel API,
a direct ping of the game port, and the stats files in the world folder.

Shared by the leaderboard, status and check jobs. Nothing here prints a secret:
errors name the call and the HTTP code, never the panel address or the key.

Settings come from environment variables (set as GitHub secrets):
  PANEL_HOST        the panel address, for example https://games.example.com
  PANEL_SERVER_ID   the server id from the panel address bar
  PANEL_API_KEY     an API key made on the panel's API Credentials page
  MC_ADDRESS        the address players join with, host or host:port
  MC_WORLD_DIR      the world folder name (default world)
"""
import json
import os
import re
import socket
import struct
import urllib.error
import urllib.parse
import urllib.request

PANEL_HOST = os.environ.get("PANEL_HOST", "").strip().rstrip("/")
SERVER_ID = os.environ.get("PANEL_SERVER_ID", "").strip()
API_KEY = os.environ.get("PANEL_API_KEY", "").strip()
ADDRESS = os.environ.get("MC_ADDRESS", "").strip()
WORLD = "/" + (os.environ.get("MC_WORLD_DIR", "").strip().strip("/") or "world")
UA = "mc-discord-board/1.0 (GitHub Actions)"

if PANEL_HOST and "://" not in PANEL_HOST:
    PANEL_HOST = "https://" + PANEL_HOST
if PANEL_HOST:
    # Keep only the site itself, so a pasted page address (…/server/abc123) still works.
    _parts = urllib.parse.urlparse(PANEL_HOST)
    PANEL_HOST = f"{_parts.scheme}://{_parts.netloc}"
# The id is the last piece of whatever was pasted, so a whole page address works here too.
SERVER_ID = SERVER_ID.rstrip("/").split("/")[-1].split("?")[0]


class PanelError(Exception):
    """The panel could not be read. The message is safe to print."""
    code = 0    # the HTTP status, when the panel answered with one


# ------------------------------------------------------------------- panel API
def panel(path="", text=False):
    """One GET against /api/client/servers/<id><path>. Returns JSON, or text."""
    if not (PANEL_HOST and SERVER_ID and API_KEY):
        raise PanelError("PANEL_HOST, PANEL_SERVER_ID or PANEL_API_KEY is not set")
    label = path.split("?")[0] or "/"
    req = urllib.request.Request(
        f"{PANEL_HOST}/api/client/servers/{SERVER_ID}{path}",
        headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json",
                 "Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        err = PanelError(f"panel call {label} answered HTTP {e.code}")
        err.code = e.code
        raise err from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise PanelError(f"panel could not be reached for {label} ({type(e).__name__})") from None
    if text:
        return raw.decode("utf-8", errors="replace")
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        # A web page came back instead of data. Its title says which page, without
        # showing the address: a login page, a "checking your browser" page, or the
        # wrong site altogether.
        page = raw[:20000].decode("utf-8", errors="replace")
        title = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
        what = f'a web page titled "{" ".join(title.group(1).split())[:80]}"' if title else "something that is not data"
        raise PanelError(f"panel call {label} answered with {what} instead of data") from None


def list_dir(folder):
    """Files and folders in one server folder: dicts with name, is_file, size."""
    data = panel("/files/list?directory=" + urllib.parse.quote(folder, safe=""))
    return [f.get("attributes", {}) for f in data.get("data", [])]


def read_file(path):
    """The text of one file on the server. Tries the direct read first; if the
    panel refuses that, asks it for a one-time download link and uses that."""
    quoted = urllib.parse.quote(path, safe="")
    try:
        return panel("/files/contents?file=" + quoted, text=True)
    except PanelError as first:
        if first.code in (401, 403, 404):
            raise
        try:
            link = panel("/files/download?file=" + quoted).get("attributes", {}).get("url")
            if not link:
                raise first
            req = urllib.request.Request(link, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError):
            raise first from None


def server_info():
    """Name and plan limits. limits: memory and disk in MB, cpu in percent (0 = no limit)."""
    a = panel("").get("attributes", {})
    return {"name": a.get("name") or "", "limits": a.get("limits") or {}}


def resources():
    """Live usage: state (running, starting, stopping, offline), cpu percent,
    memory and disk in bytes, uptime in seconds."""
    a = panel("/resources").get("attributes", {})
    r = a.get("resources") or {}
    return {"state": a.get("current_state") or "offline", "cpu": float(r.get("cpu_absolute") or 0),
            "memory": int(r.get("memory_bytes") or 0), "disk": int(r.get("disk_bytes") or 0),
            "uptime": int(r.get("uptime") or 0) // 1000}


def mod_files():
    """Names of the .jar files in the mods folder, sorted."""
    names = [f["name"] for f in list_dir("/mods") if f.get("is_file") and str(f.get("name", "")).lower().endswith(".jar")]
    return sorted(names, key=str.lower)


# ------------------------------------------------------------------ game ping
def _varint(n):
    n &= 0xFFFFFFFF
    out = b""
    while True:
        b = n & 0x7F
        n >>= 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def _read_varint(sock):
    n = 0
    for i in range(5):
        b = sock.recv(1)
        if not b:
            raise ConnectionError("server closed the connection")
        n |= (b[0] & 0x7F) << (7 * i)
        if not b[0] & 0x80:
            return n
    raise ValueError("bad number from server")


def ping(address=None, timeout=6):
    """Ask the game port what the multiplayer screen asks. Returns a dict with
    online (always True), players, max, names (may be a partial list) and version.
    Raises OSError or ValueError if the server does not answer."""
    address = address or ADDRESS
    if not address:
        raise ValueError("MC_ADDRESS is not set")
    host, _, port = address.rpartition(":")
    if not host or not port.isdigit():
        host, port = address, "25565"
    with socket.create_connection((host, int(port)), timeout=timeout) as sock:
        sock.settimeout(timeout)
        name = host.encode()
        hello = _varint(0) + _varint(-1) + _varint(len(name)) + name + struct.pack(">H", int(port)) + _varint(1)
        sock.sendall(_varint(len(hello)) + hello + b"\x01\x00")
        _read_varint(sock)                 # packet length
        _read_varint(sock)                 # packet id
        size = _read_varint(sock)
        if size > 4_000_000:
            raise ValueError("answer too large")
        raw = b""
        while len(raw) < size:
            chunk = sock.recv(min(65536, size - len(raw)))
            if not chunk:
                raise ConnectionError("server closed the connection")
            raw += chunk
    data = json.loads(raw.decode("utf-8", errors="replace"))
    p = data.get("players") or {}
    names = sorted((s.get("name") for s in p.get("sample") or [] if s.get("name")), key=str.lower)
    return {"online": True, "players": int(p.get("online") or 0), "max": int(p.get("max") or 0),
            "names": names, "version": (data.get("version") or {}).get("name") or ""}


# ---------------------------------------------------------------- stats files
def world_names():
    """Folder names to try for the world, best guess first: the MC_WORLD_DIR
    setting, the level-name line in server.properties, then every top-level
    folder that looks like a world."""
    names = [WORLD.strip("/")]
    try:
        for line in read_file("/server.properties").splitlines():
            if line.strip().startswith("level-name"):
                names.append(line.split("=", 1)[1].strip().strip("/"))
    except (PanelError, IndexError):
        pass
    try:
        skip = {"mods", "config", "logs", "libraries", "crash-reports", "defaultconfigs", "kubejs", "scripts"}
        names += [f["name"] for f in list_dir("/") if not f.get("is_file") and f.get("name") not in skip
                  and not str(f.get("name", "")).startswith(".")]
    except PanelError:
        pass
    seen = []
    for n in names:
        if n and n not in seen:
            seen.append(n)
    return seen[:25]


def stats_folder():
    """(folder, [player uuid]) for the folder that holds the stats files. Newer
    Minecraft versions keep them in players/stats, older ones in stats."""
    tried = []
    for world in world_names():
        for folder in (f"/{world}/players/stats", f"/{world}/stats"):
            try:
                ids = [f["name"][:-5] for f in list_dir(folder)
                       if f.get("is_file") and str(f.get("name", "")).endswith(".json")]
            except PanelError:
                tried.append(folder)
                continue
            if ids:
                return folder, sorted(ids)
            tried.append(folder + " (empty)")
    raise PanelError("no stats files found. Looked in: " + ", ".join(tried[:8]))


def player_names(ids=()):
    """{uuid: name}. Reads usercache.json on the server; any player still
    missing is looked up with Mojang's public profile service."""
    names = {}
    try:
        names = {u["uuid"]: u["name"] for u in json.loads(read_file("/usercache.json")) if u.get("uuid") and u.get("name")}
    except (PanelError, ValueError, TypeError, KeyError):
        pass
    for uuid in ids:
        if uuid in names:
            continue
        try:
            req = urllib.request.Request(
                "https://sessionserver.mojang.com/session/minecraft/profile/" + uuid.replace("-", ""),
                headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=15) as resp:
                names[uuid] = json.loads(resp.read()).get("name") or uuid[:8]
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            pass    # the board shows a short id for this player
    return names


def summarize(stats_json):
    """The figures the boards use, from one player's stats file."""
    s = stats_json.get("stats") or {}
    c = s.get("minecraft:custom") or {}

    def g(key):
        return c.get("minecraft:" + key) or 0

    def top(group):
        group = s.get(group) or {}
        if not group:
            return None
        key = max(group, key=group.get)
        return [key.split(":")[-1].replace("_", " "), group[key]]

    return {
        "minutes": g("play_time") // 1200,                 # 20 ticks a second
        "deaths": g("deaths"),
        "mobKills": g("mob_kills"),
        "playerKills": g("player_kills"),
        "km": round(sum(v for k, v in c.items() if k.endswith("_one_cm")) / 100000, 1),
        "mined": sum((s.get("minecraft:mined") or {}).values()),
        "crafted": sum((s.get("minecraft:crafted") or {}).values()),
        "dealt": g("damage_dealt") // 10,                  # stored in tenths of a point
        "taken": g("damage_taken") // 10,
        "jumps": g("jump"),
        "topMob": top("minecraft:killed"),
        "nemesis": top("minecraft:killed_by"),
        "topBlock": top("minecraft:mined"),
    }


def all_players():
    """One dict per player: name plus the summarize() figures. A stats file that
    cannot be read is skipped, so one bad file never empties the board."""
    folder, ids = stats_folder()
    names = player_names(ids)
    rows = []
    for uuid in ids:
        try:
            row = summarize(json.loads(read_file(f"{folder}/{uuid}.json")))
        except (PanelError, ValueError) as e:
            print(f"Skipped one stats file ({e}).", flush=True)
            continue
        row["name"] = names.get(uuid) or uuid[:8]
        rows.append(row)
    return rows
