"""Keep two Discord pictures up to date: the player leaderboard and the records board.

Reads every player's stats file from the server through the Starbase panel API,
draws the pictures with mcimage.py and posts them through a Discord webhook. The
first run posts the two messages and saves their ids in state/; every later run
swaps the pictures in place.

Settings come from environment variables (set in .github/workflows/leaderboard.yml):
  DISCORD_LEADERBOARD_WEBHOOK_URL  required, kept as a GitHub secret
  PANEL_HOST, PANEL_SERVER_ID, PANEL_API_KEY, MC_WORLD_DIR   see mcdata.py
  MC_NAME            the name shown in the picture header (default Minecraft)
  LB_SORT            playtime | deaths | mobKills | playerKills | distance | mined
                     (default playtime)
  LB_TOP             players shown, 1-15 (default 10)
  LB_MIN_MINUTES     playtime floor to appear on the board (default 0)
  DRY_RUN            set to 1 to save the pictures to disk instead of posting
"""
import os
import sys
import time
import urllib.error

import mcdata
import mcimage
import mcpost

WEBHOOK = os.environ.get("DISCORD_LEADERBOARD_WEBHOOK_URL", "").strip()
NAME = os.environ.get("MC_NAME", "").strip() or "Minecraft"
SORT = os.environ.get("LB_SORT", "").strip() or "playtime"
TOP = max(1, min(15, int(os.environ.get("LB_TOP", "") or 10)))
MIN_MINUTES = int(os.environ.get("LB_MIN_MINUTES", "") or 0)
DRY_RUN = os.environ.get("DRY_RUN") == "1"
IDS_FILE = "leaderboard_messages.json"


def hours(minutes):
    return f"{minutes / 60:,.1f}"


def number(n):
    return f"{n:,}"


# (heading, key in the player row, how to write the value). LB_SORT uses the same names
# except playtime -> minutes and distance -> km.
COLUMNS = [("Hours", "minutes", hours), ("Deaths", "deaths", number), ("Mob kills", "mobKills", number),
           ("PvP kills", "playerKills", number), ("Km", "km", lambda v: f"{v:,.0f}"), ("Mined", "mined", number)]
SORT_KEY = {"playtime": "minutes", "distance": "km"}.get(SORT, SORT)
SORT_LABEL = {"minutes": "playtime", "deaths": "deaths", "mobKills": "mob kills",
              "playerKills": "PvP kills", "km": "distance", "mined": "blocks mined"}


def record_cards(players):
    """One winner per category. A category nobody has scored in is left out."""
    def best(key, label, fmt):
        p = max(players, key=lambda r: r.get(key) or 0, default=None)
        return (label, p["name"], fmt(p[key])) if p and p.get(key) else None

    def best_pair(key, label, fmt):
        p = max((r for r in players if r.get(key)), key=lambda r: r[key][1], default=None)
        return (label, p["name"], fmt(*p[key])) if p else None

    cards = [
        best("minutes", "Most time played", lambda v: f"{v / 60:,.1f} hours"),
        best("deaths", "Most deaths", lambda v: f"{v:,} deaths"),
        best("mobKills", "Top hunter", lambda v: f"{v:,} mob kills"),
        best("km", "Furthest travelled", lambda v: f"{v:,.0f} km"),
        best("mined", "Top miner", lambda v: f"{v:,} blocks"),
        best("crafted", "Top crafter", lambda v: f"{v:,} items"),
        best("dealt", "Most damage dealt", lambda v: f"{v:,} points"),
        best("taken", "Most damage taken", lambda v: f"{v:,} points"),
        best_pair("topMob", "Favourite target", lambda what, n: f"{n:,} x {what}"),
        best_pair("nemesis", "Worst enemy", lambda what, n: f"killed {n:,} times by {what}"),
    ]
    return [c for c in cards if c]


def build():
    """Returns [(slot, picture as PNG bytes, text under it, file name)]."""
    everyone = mcdata.all_players()
    ranked = sorted((p for p in everyone if p["minutes"] >= MIN_MINUTES),
                    key=lambda p: p.get(SORT_KEY) or 0, reverse=True)
    rows = ranked[:TOP]
    updated = "Updated " + mcpost.stamp()
    floor = f" · {MIN_MINUTES}+ minutes played" if MIN_MINUTES else ""
    board = mcimage.leaderboard(
        f"{NAME} · Top {len(rows) or TOP}", f"All time · Ranked by {SORT_LABEL.get(SORT_KEY, SORT_KEY)}{floor}",
        COLUMNS, rows, SORT_KEY, right=f"{len(ranked)} players",
        footer_left="Stats save when the server autosaves", footer_right=updated)
    rec = mcimage.records(f"{NAME} · Records", "All time · One winner per category", record_cards(everyone),
                          right=f"{len(everyone)} players", footer_left="Stats save when the server autosaves",
                          footer_right=updated)
    chip = f"Updated <t:{int(time.time())}:R>"
    return [("board", board, f"**{NAME} leaderboard** · {chip}", "mc-leaderboard.png"),
            ("records", rec, f"**{NAME} records** · {chip}", "mc-records.png")]


def main():
    if SORT_KEY not in SORT_LABEL:
        sys.exit(f"LB_SORT '{SORT}' is not one of: playtime, deaths, mobKills, playerKills, distance, mined.")
    if not WEBHOOK and not DRY_RUN:
        sys.exit("DISCORD_LEADERBOARD_WEBHOOK_URL is not set. Add it as a repository secret.")
    ids = mcpost.load(IDS_FILE, {})
    for slot, png, caption, filename in build():
        if DRY_RUN:
            out = os.path.join(os.environ.get("DRY_RUN_DIR", "."), filename)
            with open(out, "wb") as f:
                f.write(png)
            print(f"{caption}\n  picture saved to {out} ({len(png) // 1024} KB)")
            continue
        ids[slot], new = mcpost.put_file(WEBHOOK, ids.get(slot), png, filename, caption)
        print(("Posted a new" if new else "Updated the") + f" {slot} picture.")
    if not DRY_RUN:
        mcpost.save(IDS_FILE, ids)


if __name__ == "__main__":
    try:
        main()
    except mcdata.PanelError as e:
        sys.exit(f"Could not read the server: {e}")
    except urllib.error.HTTPError as e:
        sys.exit(mcpost.describe(e))       # never prints the webhook URL
    except urllib.error.URLError as e:
        sys.exit(f"Network error: {e.reason}")
