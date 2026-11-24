"""Tests every connection the jobs depend on and prints OK or the reason for each.

Run it from the Actions tab ("Check connections") after adding the secrets, and
again whenever a job fails. It posts nothing to Discord and prints no secrets.
"""
import sys

import mcdata


def check(label, job):
    try:
        print(f"OK    {label}: {job()}", flush=True)
        return True
    except mcdata.PanelError as e:
        print(f"FAIL  {label}: {e}", flush=True)
    except (OSError, ValueError) as e:
        print(f"FAIL  {label}: {type(e).__name__}: {e}", flush=True)
    return False


def stats():
    folder, ids = mcdata.stats_folder()
    return f"{len(ids)} stats files in {folder}"


def ping():
    p = mcdata.ping()
    return f"{p['players']}/{p['max']} players, version {p['version'] or 'unknown'}"


results = [
    check("Panel: server details", lambda: "name and limits read" if mcdata.server_info() else ""),
    check("Panel: live resources", lambda: "state is " + mcdata.resources()["state"]),
    check("Panel: mods folder", lambda: f"{len(mcdata.mod_files())} mod files"),
    check("Panel: stats files", stats),
    check("Panel: player names", lambda: f"{len(mcdata.player_names())} names in usercache.json"),
    check("Game port ping", ping),
]
print()
print("Everything works." if all(results) else "Fix the FAIL lines above. The README has a table of causes.")
sys.exit(0 if all(results) else 1)
