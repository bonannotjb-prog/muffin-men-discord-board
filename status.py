"""Keep one Discord picture showing live Minecraft server status, replaced in place.

Reads the panel (running or not, CPU, memory, disk, uptime) and pings the game
port (players online, version), draws the picture with mcimage.py and posts it
through a Discord webhook. A second message carries the mod list as a file.

The picture is redrawn straight away when the state or the players change, and
every STATUS_REDRAW_SECONDS otherwise so the resource figures stay fresh.

Modes:
  python status.py --once   update the messages one time and exit
  python status.py          keep checking every STATUS_INTERVAL seconds until
                            STATUS_RUN_MINUTES have passed, then exit

Settings come from environment variables (set in .github/workflows/status.yml):
  DISCORD_STATUS_WEBHOOK_URL  required, kept as a GitHub secret
  PANEL_HOST, PANEL_SERVER_ID, PANEL_API_KEY, MC_ADDRESS   see mcdata.py
  MC_NAME                 name in the picture header (default: the panel's server name)
  MC_PACK                 modpack name and version to show, optional
  BLUEMAP_URL             address of the BlueMap web map, optional (adds a link)
  MC_SHOW_ADDRESS         1 = show the join address under the picture (default 0)
  STATUS_INTERVAL         seconds between checks, minimum 15 (default 30)
  STATUS_REDRAW_SECONDS   longest gap between redraws (default 120)
  STATUS_RUN_MINUTES      how long the loop runs before exiting (default 330)
  DRY_RUN                 set to 1 to save the picture to disk instead of sending it
"""
import hashlib
import json
import os
import sys
import time
import urllib.error

import mcdata
import mcimage
import mcpost

WEBHOOK = os.environ.get("DISCORD_STATUS_WEBHOOK_URL", "").strip()
NAME = os.environ.get("MC_NAME", "").strip()
PACK = os.environ.get("MC_PACK", "").strip()
BLUEMAP = os.environ.get("BLUEMAP_URL", "").strip()
SHOW_ADDRESS = os.environ.get("MC_SHOW_ADDRESS") == "1"
INTERVAL = max(15, int(os.environ.get("STATUS_INTERVAL", "") or 30))
REDRAW = max(60, int(os.environ.get("STATUS_REDRAW_SECONDS", "") or 120))
RUN_MINUTES = float(os.environ.get("STATUS_RUN_MINUTES", "") or 330)
DRY_RUN = os.environ.get("DRY_RUN") == "1"
IDS_FILE = "status_messages.json"       # {"status": message id, "mods": message id, "mods_hash": ...}
SLOW = 3600                             # seconds between reads of things that rarely change

_slow = {"at": 0, "info": {"name": "", "limits": {}}, "mods": None}


def refresh_slow():
    """Server name, plan limits and the mod list change rarely: read them hourly."""
    if time.time() - _slow["at"] < SLOW:
        return
    _slow["at"] = time.time()
    try:
        _slow["info"] = mcdata.server_info()
    except mcdata.PanelError as e:
        print(f"Server details not read ({e}).", flush=True)
    try:
        _slow["mods"] = mcdata.mod_files()
    except mcdata.PanelError as e:
        print(f"Mod list not read ({e}).", flush=True)


def gb(n_bytes):
    return n_bytes / 1073741824


def uptime(seconds):
    m = seconds // 60
    d, h = m // 1440, (m % 1440) // 60
    return (f"{d}d " if d else "") + f"{h}h {m % 60:02d}m"


def build():
    """Returns (panel for the picture, key): the key changes only when something
    a reader would notice at once has changed (state, players, version)."""
    refresh_slow()
    res = hit = None
    try:
        res = mcdata.resources()
    except mcdata.PanelError as e:
        print(f"Resources not read ({e}).", flush=True)
    try:
        hit = mcdata.ping()
    except (OSError, ValueError):
        pass   # not answering: the panel state decides between STARTING and OFFLINE

    if hit:
        state, note, detail = "ONLINE", "Open to players", ""
    elif res and res["state"] in ("running", "starting"):
        state, note, detail = "STARTING", "", "The server is running but not taking players yet"
    else:
        state, note = "OFFLINE", ""
        detail = "The server is stopped" if res else "The server could not be reached"

    limits = _slow["info"]["limits"]
    mods = _slow["mods"]
    facts = [("Version", hit["version"])] if hit and hit.get("version") else []
    if PACK:
        facts.append(("Modpack", PACK))
    if mods is not None:
        facts.append(("Mods", f"{len(mods)} files"))

    gauges = []
    if res and res["state"] != "offline":
        cpu_cap, mem_cap, disk_cap = limits.get("cpu") or 0, limits.get("memory") or 0, limits.get("disk") or 0
        gauges = [
            ("CPU", f"{res['cpu']:.0f}%" + (f" of {cpu_cap}%" if cpu_cap else ""),
             res["cpu"] / cpu_cap if cpu_cap else None),
            ("Memory", f"{gb(res['memory']):.1f}" + (f" / {mem_cap / 1024:.0f} GB" if mem_cap else " GB"),
             res["memory"] / (mem_cap * 1048576) if mem_cap else None),
            ("Disk", f"{gb(res['disk']):.1f}" + (f" / {disk_cap / 1024:.0f} GB" if disk_cap else " GB"),
             res["disk"] / (disk_cap * 1048576) if disk_cap else None),
            ("Uptime", uptime(res["uptime"]), None),
        ]

    panel = {"name": NAME or _slow["info"]["name"] or "Minecraft server", "state": state, "note": note,
             "detail": detail, "players": (hit or {}).get("players", 0), "max": (hit or {}).get("max", 0),
             "names": (hit or {}).get("names", []), "facts": facts, "gauges": gauges}
    key = json.dumps([state, panel["players"], panel["max"], panel["names"], facts], sort_keys=True)
    return panel, key


def caption(panel):
    """The text under the picture. The Discord time chip keeps counting between updates."""
    parts = [f"**{panel['name']}**"]
    if BLUEMAP:
        # <...> around an address stops Discord adding a link preview under the picture.
        parts.append(f"[Live map](<{BLUEMAP}>)")
    if SHOW_ADDRESS and mcdata.ADDRESS:
        parts.append(f"Join: `{mcdata.ADDRESS}`")
    parts.append(f"Checked <t:{int(time.time())}:R>")
    return " · ".join(parts)


def post_mods(ids):
    """Keep the mod list message current. It is only uploaded when the list changes."""
    mods = _slow["mods"]
    if mods is None or DRY_RUN:
        return
    digest = hashlib.sha256("\n".join(mods).encode()).hexdigest()[:16]
    if ids.get("mods") and ids.get("mods_hash") == digest:
        return
    text = f"**Mod list** · {len(mods)} mod files. Open the attached file for the full list."
    ids["mods"], _ = mcpost.put_file(WEBHOOK, ids.get("mods"), ("\n".join(mods) + "\n").encode(),
                                     "mods.txt", text, mime="text/plain")
    ids["mods_hash"] = digest
    mcpost.save(IDS_FILE, ids)
    print("Mod list message updated.", flush=True)


def update(last):
    """Check the server once. last is (key of the picture on show, when it was drawn)."""
    panel, key = build()
    old_key, drawn = last
    if key == old_key and time.time() - drawn < REDRAW:
        return last
    png = mcimage.status(panel, footer_left=PACK or "Minecraft", footer_right="Updated " + mcpost.stamp())
    if DRY_RUN:
        out = os.path.join(os.environ.get("DRY_RUN_DIR", "."), "mc-status.png")
        with open(out, "wb") as f:
            f.write(png)
        print(f"{caption(panel)}\n  picture saved to {out} ({len(png) // 1024} KB)")
        return key, time.time()
    ids = mcpost.load(IDS_FILE, {})
    ids["status"], new = mcpost.put_file(WEBHOOK, ids.get("status"), png, "mc-status.png", caption(panel))
    if new:
        mcpost.save(IDS_FILE, ids)
    if key != old_key:
        print(time.strftime("%H:%M:%S"), panel["state"], f"{panel['players']}/{panel['max']}",
              "posted new" if new else "picture updated", flush=True)
    post_mods(ids)
    return key, time.time()


def main():
    if not WEBHOOK and not DRY_RUN:
        sys.exit("DISCORD_STATUS_WEBHOOK_URL is not set. Add it as a repository secret.")
    if "--once" in sys.argv:
        update((None, 0))
        return

    deadline = time.time() + RUN_MINUTES * 60
    last, failures = (None, 0), 0
    while time.time() < deadline:
        started = time.time()
        try:
            last = update(last)
            failures = 0
        except urllib.error.HTTPError as e:
            failures += 1
            print(f"Discord answered HTTP {e.code}; retrying.", flush=True)
        except (urllib.error.URLError, TimeoutError) as e:
            failures += 1
            print(f"Network error ({getattr(e, 'reason', e)}); retrying.", flush=True)
        if failures >= 30:
            sys.exit("Giving up after 30 failed updates in a row.")
        time.sleep(max(1, INTERVAL - (time.time() - started)))


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        sys.exit(mcpost.describe(e))       # never prints the webhook URL
    except urllib.error.URLError as e:
        sys.exit(f"Network error: {e.reason}")
