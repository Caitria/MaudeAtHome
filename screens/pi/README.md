# pi/ — the caster Pi's programs

Everything here runs on the Raspberry Pi (the "caster"). In the original
house the Pi's home directory is the install location and paths below are
written home-relative (`~/…`) so they read the same anywhere.

| File | What it does |
|---|---|
| `cast-control.py` | The phone controller. Serves a tap-to-cast page on **:8081** (per-display cards, current-view status, cast confirmation), a bare port-80 redirect to it, and the **`/adsb` proxy** (adsb.lol sends no CORS header; 12 s cache). Actions are appended to `~/cast-control.log`. Casts run stop-first + 10 s settle, in a background thread. Also drives the TV light-bars companion via `govee.py`: after a successful TV cast the bars take the view's light recipe; a TV stop (or a movie-mode flag file) turns them off; the TV card carries a Bars row (Off / Auto / Warm / Dim) |
| `govee.py` | A small client for Govee light bars over Govee's LAN API (UDP; scan-based discovery, found address cached in `~/govee-device.json`, log `~/govee.log`). Needs the bars' **LAN Control** toggle on in the Govee Home app. Provides `status()` / `set_recipe()` / `off()`; every call is timeout-bounded and exception-swallowing, recipe brightness is hard-capped at 30%, and nothing the controller sends exceeds 60% — a bars failure can never break or delay a cast |
| `cast-keepalive.py` | User-cron, every 8 min (self-limits to 06:00–23:00): re-casts the bedroom display's last-chosen view, read back from `~/cast-control.log`. DashCast sessions expire; this is the leash. Bedroom only — the TV belongs to the gallery watcher |
| `gallery-watch.py` | The gallery idle rule, v2 (see the docstring): positive-idle gating — the TV is taken only when the Chromecast's own Backdrop screensaver is provably the idle screen, sustained 5 min, with movie-mode and hands-off vetoes. Polls TV power (Samsung local API) + Chromecast state (pychromecast) every ~30 s via a systemd timer. **Ships disabled in the original house** — the timer arms only on the owner's say-so |
| `fetch-briefing.sh` | Downloads the current briefing edition file and swaps it in **only if** it contains the word "Briefing" — a bad fetch never replaces a good edition |
| `cast-briefing.sh` | Stop, sleep 10, cast the briefing page to the bedroom display |
| `iss-passes.py` | Nightly: CelesTrak TLE → pure-python SGP4 → `~/briefing/iss.json` (4 days of passes > 10°; `visible` = sunlit at peak AND sun below −4° at the observer). Fails non-zero *without* touching the old file, so staleness is always detectable |

## Install shape (described, not shipped as unit files)

- **Page server**: a systemd service running `python3 -m http.server 8080`
  in the pages directory (the original serves `~/briefing/`).
- **`cast-control.service`**: a systemd service running `cast-control.py`,
  enabled at boot. One subtlety: the port-80 redirect binds a privileged
  port as an unprivileged user, so the unit needs a drop-in granting
  `AmbientCapabilities=CAP_NET_BIND_SERVICE`. If the :80 bind fails, the
  controller logs it and carries on at :8081.
- **Timers**: `briefing-fetch.timer` (06:50 + 18:50), `briefing-cast.timer`
  (07:00 + 19:00), `gallery-watch.timer` (every 30 s — **installed but
  disabled**; see `gallery-watch.py`), `iss-passes.timer` (daily ~18:00 +
  shortly after boot, `Persistent=true`).
- **Venvs on the Pi**: one for `catt` (+ pychromecast) — the scripts call
  `~/caster/bin/catt`; one for `sgp4` — `~/iss-venv/bin/python`.
- **User crontab**: `*/8 * * * * ~/cast-keepalive.py`.

## Configuration

Before anything works, set the placeholders (full table in the screens
README, `../README.md`): the Pi's LAN address (`CASTPI_LAN_IP`), your coordinates
(`YOUR_LAT`/`YOUR_LON`), your TV's address (`TV_LAN_IP`), your briefing
file's ID (`YOUR_BRIEFING_FILE_ID`), your timezone, and your displays'
cast names. The scripts log what they do; when something misbehaves, the
logs in `~` are the first place to look (see `../docs/OPERATIONS.md` §5).
