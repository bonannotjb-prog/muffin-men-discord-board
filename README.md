# Minecraft Discord posts

Keeps three messages in Discord up to date for the ATM11 server, built the same way as the Wardogs (RLG) repository: Python jobs on GitHub Actions, pictures posted through webhooks, message ids saved in `state/`.

| Channel | Message | Refreshes |
|---|---|---|
| `mc-leaderboards` | Leaderboard picture (top players, six columns) | Every 15 minutes |
| `mc-leaderboards` | Records picture (one winner per category) | Every 15 minutes |
| `mc-status` | Live status picture | Within 30 seconds of a change, and every 2 minutes |
| `mc-status` | Mod list, as an attached `mods.txt` | When the mods change |

The chat channel is separate: the Discord Integration mod on the server handles it.

Items marked `[VERIFY]` could not be confirmed from outside your accounts. They are listed again at the end.

## Files

| File | What it is |
|---|---|
| `mcdata.py` | Reads the server: Starbase panel API, game port ping, stats files |
| `mcimage.py` | Draws the three pictures |
| `mcpost.py` | Uploads pictures and files to Discord |
| `leaderboard.py` | Leaderboard and records pictures |
| `status.py` | Live status picture and the mod list message |
| `check.py` | Tests every connection and prints OK or the reason |
| `assets/` | The Muffin Men banner and icon, and the fonts. Upload the whole folder |
| `state/` | Message ids the jobs save. Leave it in place |
| `workflows/*.yml` | The schedule for each job. In the repository these go in `.github/workflows/` |

To see a picture without posting it, run a job with `DRY_RUN=1`. It saves the picture to disk instead.

## Setup (about 20 minutes)

1. **Make two Discord webhooks.** One in `mc-status`, one in `mc-leaderboards`: channel settings, Integrations, Webhooks, New Webhook. Copy each URL. Treat a URL like a password: anyone who has it can post in that channel.

2. **Make a Starbase API key.** In the panel: Account Settings, Account, API Credentials. Name it `discord-board` and create it. Copy the key. It is shown once.

3. **Make a GitHub repository.** New repository, set to **Public**, tick "Add a README file". Public matters for the same reason as the Wardogs one: scheduled jobs are free on public repositories. Nothing secret is stored in the files.

4. **Upload this folder.** Add file, Upload files, then drag in everything in this folder except `workflows`.

   Then add the three schedules, the same way as in the Wardogs repository. For each file in the `workflows` folder (`status.yml`, `leaderboard.yml`, `check.yml`): Add file, Create new file, name it `.github/workflows/status.yml` (typing the slashes makes the folders), and paste in the file's contents.

5. **Add the secrets.** Settings, Secrets and variables, Actions, New repository secret.

   | Secret | Value |
   |---|---|
   | `DISCORD_STATUS_WEBHOOK_URL` | The `mc-status` webhook URL |
   | `DISCORD_LEADERBOARD_WEBHOOK_URL` | The `mc-leaderboards` webhook URL |
   | `PANEL_API_KEY` | The Starbase API key |
   | `PANEL_HOST` | The panel address, up to and including the domain. Copy it from your browser while the panel is open `[VERIFY]` |
   | `PANEL_SERVER_ID` | The code after `/server/` in the panel address bar `[VERIFY]` |
   | `MC_ADDRESS` | The address players join with, for example `myserver.example.com:25565` |
   | `BLUEMAP_URL` | Optional. The BlueMap web address. Adds a "Live map" link under the status picture |

   The server address and panel details are secrets, not settings in the workflow file, because the repository is public. That keeps the server's address out of public view.

6. **Allow the jobs to save their message ids.** Settings, Actions, General, Workflow permissions: choose "Read and write permissions" and save.

7. **Run the check.** Actions tab, "Check connections", Run workflow. Open the run. Every line must say `OK`. If one says `FAIL`, use the table under "When something fails".

8. **Run each job once by hand.** Actions tab, "Minecraft leaderboard", Run workflow. Then "Minecraft server status", Run workflow. The messages appear in Discord and the ids appear in `state/`. From then on the schedules take over.

## Changing what it shows

Edit the `env:` block at the top of each workflow file in the repository.

| Setting | File | Options |
|---|---|---|
| `LB_SORT` | `leaderboard.yml` | `playtime`, `deaths`, `mobKills`, `playerKills`, `distance`, `mined` |
| `LB_TOP` | `leaderboard.yml` | Players shown, up to 15 |
| `LB_MIN_MINUTES` | `leaderboard.yml` | Minutes played needed to appear |
| `MC_NAME` | all three | The name in the picture headers |
| `MC_PACK` | `status.yml` | The modpack line. Add the pack version if you want it shown |
| `MC_SHOW_ADDRESS` | `status.yml` | `1` shows the join address under the status picture |
| `STATUS_INTERVAL` | `status.yml` | Seconds between checks, minimum 15 |
| `MC_WORLD_DIR` | all three | The world folder name, if it is not `world` |
| `MC_TIMEZONE` | all three | Time zone for the "Updated" line |

To change the artwork, swap `assets/banner.jpg` or `assets/icon.png` for a file of the same name. To change the colours, edit the list near the top of `mcimage.py`.

## Good to know

- **Stats run a few minutes behind.** Minecraft writes stats files when it autosaves and when a player logs out.
- **Player list.** The game port only reports a sample of who is online (about 12 names). On a small server that is everyone.
- **State is told in words.** The status tag always says ONLINE, STARTING or OFFLINE, with a different shape for each, so it does not depend on colour.
- **Deleting a message:** the next run posts a fresh one and remembers it.
- **Moving channels:** make a new webhook, update the secret, delete the matching file in `state/`, and run the job once.
- **The 60-day pause:** each job commits a small weekly heartbeat file, so the repository always has a recent commit and GitHub does not pause the schedules.
- **Pack updates:** the jobs read the server live, so a pack update needs no change here. The mod list message updates itself.
- **BlueMap:** the map needs its own port opened on the server (Starbase panel, port allocation) and its download setting accepted in the BlueMap config before the web address works. `[VERIFY]` Once the address opens in a browser, add it as the `BLUEMAP_URL` secret.

## When something fails

GitHub emails the repository owner when a run fails. Run "Check connections" to see which part broke.

| Message | Cause | Fix |
|---|---|---|
| `panel call ... answered HTTP 401` or `403` | The API key is wrong | Replace the `PANEL_API_KEY` secret |
| `panel call ... answered HTTP 404` | Wrong panel address or server id | Recheck `PANEL_HOST` and `PANEL_SERVER_ID`. If the short id fails, use the full server UUID from the panel's settings page |
| `panel could not be reached` | The panel address is wrong or the panel is down | Recheck `PANEL_HOST` |
| `no stats files found` | The world folder has another name, or nobody has played yet | Look in the panel's Files tab and set `MC_WORLD_DIR` |
| `Game port ping: FAIL` | The server is off, or `MC_ADDRESS` is wrong | Start the server, or recheck the secret |
| `Request to discord.com failed with HTTP 401` or `404` | The webhook was deleted or the URL is wrong | Replace the webhook secret |

## Open items

| # | Item | How to close it |
|---|---|---|
| 1 | `[VERIFY]` The exact Starbase panel address | Copy it from your browser |
| 2 | `[VERIFY]` Starbase accepts the short server id from the address bar | "Check connections" shows OK or HTTP 404 |
| 3 | `[VERIFY]` Starbase answers the standard resources and files calls | "Check connections" tests each one |
| 4 | `[VERIFY]` Where Minecraft 26.1.2 keeps stats files | The code tries `world/players/stats`, then `world/stats`. "Check connections" prints which it found |
| 5 | `[VERIFY]` BlueMap's port and download setting on your server | Open the map address in a browser |
