#!/usr/bin/env python3
"""Gallery idle watcher v2 — LIVE mode with positive-idle gating.

WHY V2 EXISTS (the Oct 31, 2026 incident): v1 treated "Chromecast not
playing" as idle. At 18:12 that evening the household started a movie
OUTSIDE the Chromecast (a Samsung TV app / another input). The Chromecast
reported app=None, player=UNKNOWN, v1 read that as idle, counted 3
minutes, and cast the gallery over the movie. The owner ordered the watcher
disabled, then ordered it fixed. v2 inverts the core assumption:

    SILENCE IS NOT CONSENT. The watcher may take the TV only on POSITIVE
    PROOF that the Chromecast itself is the TV's current, idle screen:
    its running app must be exactly the Backdrop receiver (E8C28D3C,
    the Chromecast idle screensaver app id, observed on this device and
    carried in the code since v1). app=None, an undiscovered device, an
    unrecognized app, or a playing/paused state are all treated as
    SOMEONE MAY BE WATCHING and are refused, with the reason logged.

START gates — ALL must hold continuously for IDLE_SECONDS (300 s) before
the first cast:
  1. Samsung TV power == "on" (TV local API).
  2. Chromecast discovered AND app_id == BACKDROP_APP (positive idle).
  3. Player state is not PLAYING/BUFFERING.
  4. Active hours 06:00-23:00.
  5. Movie mode OFF (~/movie-mode.flag must not exist — toggled from the
     phone controller; while it exists the watcher never takes the TV).
  6. No hands-off window: any CAST or STOP sent to the TV from the phone
     controller (~/cast-control.log) within the last HANDSOFF_SECONDS
     (3 h) blocks starting. The log file is the shared mechanism: it
     survives restarts of both processes and needs no new state plumbing.

MAINTAINING a gallery the watcher itself started is deliberately less
strict (recast every RECAST_SECONDS to beat the DashCast timeout; stop
at quiet hours or TV-off; stop if movie mode is switched on). A gallery
cast the watcher did NOT start is never adopted, recast, or stopped —
hands off entirely.

Every poll writes a human-readable `gate` string into the state file
(the phone controller surfaces it), and any CHANGE in that string is
logged, so a future incident is diagnosable from ~/gallery-watch.log
alone.

Modes: default = live. `--dry-run` = full decision logic with catt calls
replaced by WOULD CAST / WOULD RECAST / WOULD STOP log lines (used by
the state-replay harness; safe to run any time).

AS SHIPPED IN THE ORIGINAL HOUSE: v2 passed its full state-replay
harness (19/19, including a replay of the v1 incident) and is deployed
on the Pi, but its systemd timer is DISABLED — it arms only when the
owner says so, after reviewing the harness evidence. That is the
correct state for a watcher whose v1 once interrupted a movie.
"""
import json, os, subprocess, sys, time, urllib.request
from datetime import datetime

HOME = os.path.expanduser("~")
STATE_F = os.path.join(HOME, "gallery-watch-state.json")
LOG_F = os.path.join(HOME, "gallery-watch.log")
CONTROL_LOG_F = os.path.join(HOME, "cast-control.log")
MOVIE_FLAG_F = os.path.join(HOME, "movie-mode.flag")
CATT = os.path.join(HOME, "caster", "bin", "catt")
DEVICE = "Living Room TV"
GALLERY_URL = "http://CASTPI_LAN_IP:8080/gallery-all.html"  # CONFIG
TV_API = "http://TV_LAN_IP:8001/api/v2/"  # CONFIG: your TV's LAN address
IDLE_SECONDS = 300          # v2: 5 minutes of positive idle (v1: 180 s of not-playing)
RECAST_SECONDS = 480
HANDSOFF_SECONDS = 3 * 3600
DASHCAST_APP = "84912283"   # our gallery casts (DashCast receiver)
BACKDROP_APP = "E8C28D3C"   # Chromecast idle screensaver — the ONLY positive-idle app id

DRY_RUN = "--dry-run" in sys.argv

def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + msg
    with open(LOG_F, "a") as f:
        f.write(line + "\n")

# ---------------- inputs ----------------

def in_active_hours(now=None):
    h = time.localtime(now).tm_hour
    return 6 <= h < 23

def tv_power():
    try:
        req = urllib.request.Request(TV_API, headers={"User-Agent": "gallery-watch"})
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.load(r)
        return (d.get("device") or {}).get("PowerState", "unknown")
    except Exception:
        return "unreachable"

def cast_state():
    """Returns dict(found, app_id, app_name, player). found=False means the
    Chromecast did not answer discovery — an UNKNOWN state, never idle."""
    import pychromecast
    ccs, browser = pychromecast.get_chromecasts(tries=2, timeout=12)
    try:
        for c in ccs:
            if "Living Room" in c.name:
                c.wait(timeout=8)
                mc = c.media_controller
                ps = mc.status.player_state if mc.status else None
                return {"found": True, "app_id": c.app_id,
                        "app_name": c.app_display_name, "player": ps}
        return {"found": False, "app_id": None, "app_name": None, "player": None}
    finally:
        pychromecast.discovery.stop_discovery(browser)

def movie_mode_on(flag_path=MOVIE_FLAG_F):
    return os.path.exists(flag_path)

def hands_off_until(control_log_path=CONTROL_LOG_F, now=None):
    """Epoch until which manual controller actions on the TV block the
    watcher, or None. Reads the tail of ~/cast-control.log for the most
    recent 'CAST Living Room TV' / 'STOP Living Room TV' line; that
    action + HANDSOFF_SECONDS is the window. Unreadable log -> None
    (the positive-idle gate still protects; the failure is logged)."""
    if now is None:
        now = time.time()
    try:
        with open(control_log_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 65536))
            tail = f.read().decode("utf-8", "replace")
    except Exception as e:
        log(f"hands-off check: cannot read control log ({e}) — treating as no window")
        return None
    latest = None
    for line in tail.splitlines():
        if ("CAST " + DEVICE) in line or ("STOP " + DEVICE) in line:
            try:
                ts = datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
                latest = time.mktime(ts.timetuple())
            except Exception:
                continue
    if latest is None:
        return None
    until = latest + HANDSOFF_SECONDS
    return until if until > now else None

# ---------------- decision ----------------

def decide(obs, st, now):
    """Pure decision step. obs: {power, found, app_id, app_name, player,
    movie_mode, handsoff_until, active_hours}. st: persistent watcher
    state (mutated). Returns (action, gate) where action is one of
    'cast' | 'recast' | 'stop' | None and gate is the human status line.
    STARTING a cast requires every gate; maintaining our own gallery
    only respects off-switches."""
    power = obs["power"]
    app_id = obs["app_id"]
    player = obs["player"]
    gallery_on = bool(obs["found"]) and app_id == DASHCAST_APP
    ours = bool(st.get("ours"))

    # --- our own gallery is on screen: maintain or stand down ---
    if gallery_on and ours:
        if obs["movie_mode"]:
            return "stop", "stopping our gallery — movie mode switched on"
        if power != "on":
            return "stop", f"stopping our gallery — TV power={power}"
        if not obs["active_hours"]:
            return "stop", "stopping our gallery — quiet hours 23:00-06:00"
        last = st.get("last_cast") or now
        if now - last >= RECAST_SECONDS:
            return "recast", "gallery up (ours) — 8-minute recast due"
        return None, "gallery up (ours) — standing by"
    if gallery_on and not ours:
        st["idle_since"] = None
        return None, "gallery on screen but not watcher-started — hands off"

    # --- not our gallery: the strict START gates ---
    if power != "on":
        st["idle_since"] = None
        return None, f"standby — TV power={power}"
    if not obs["active_hours"]:
        st["idle_since"] = None
        return None, "standby — quiet hours 23:00-06:00"
    if obs["movie_mode"]:
        st["idle_since"] = None
        return None, "REFUSED — movie mode is on"
    if obs["handsoff_until"] and now < obs["handsoff_until"]:
        st["idle_since"] = None
        hhmm = time.strftime("%H:%M", time.localtime(obs["handsoff_until"]))
        return None, f"REFUSED — hands-off window (manual TV control) until {hhmm}"
    if not obs["found"]:
        st["idle_since"] = None
        return None, "REFUSED — Chromecast not discovered; state unknown is not idle"
    if app_id != BACKDROP_APP:
        st["idle_since"] = None
        shown = app_id if app_id is not None else "None"
        return None, (f"REFUSED — app={shown} ({obs['app_name']}) is not positive idle; "
                      "only Backdrop proves the Chromecast is the idle screen — "
                      "someone may be watching another input")
    if player in ("PLAYING", "BUFFERING"):
        st["idle_since"] = None
        return None, f"REFUSED — player state {player}"
    # Positive idle: Backdrop app, not playing, all vetoes clear.
    if st.get("idle_since") is None:
        st["idle_since"] = now
        return None, "positive idle (Backdrop) — window started"
    held = now - st["idle_since"]
    if held >= IDLE_SECONDS:
        return "cast", f"CASTING — positive idle sustained {int(held)}s, all gates green"
    return None, f"positive idle (Backdrop) — {int(held)}s of {IDLE_SECONDS}s"

# ---------------- actions ----------------

def catt(*args):
    try:
        subprocess.run([CATT, "-d", DEVICE, *args],
                       capture_output=True, timeout=60)
    except Exception as e:
        log(f"catt {args} failed: {e}")

def do_cast(st, now, why):
    if DRY_RUN:
        log(f"WOULD CAST gallery-all ({why})")
    else:
        catt("cast_site", GALLERY_URL)
        log(f"CAST gallery-all ({why})")
    st["last_cast"] = now
    st["ours"] = True
    st["idle_since"] = None

def do_recast(st, now):
    if DRY_RUN:
        log("WOULD RECAST gallery-all (8-minute recast)")
    else:
        catt("stop")
        time.sleep(5)
        catt("cast_site", GALLERY_URL)
        log("RECAST gallery-all (8-minute recast)")
    st["last_cast"] = now
    st["ours"] = True

def do_stop(st, why):
    if DRY_RUN:
        log(f"WOULD STOP gallery ({why})")
    else:
        catt("stop")
        log(f"STOP gallery ({why})")
    st["last_cast"] = None
    st["ours"] = False
    st["idle_since"] = None

# ---------------- main ----------------

def main():
    try:
        st = json.load(open(STATE_F))
    except Exception:
        st = {}
    st.setdefault("idle_since", None)
    st.setdefault("last_cast", None)
    st.setdefault("ours", False)
    st.setdefault("tv", None)
    st.setdefault("app", None)
    st.setdefault("gate", None)

    now = time.time()
    cs = cast_state()
    obs = {
        "power": tv_power(),
        "found": cs["found"],
        "app_id": cs["app_id"],
        "app_name": cs["app_name"],
        "player": cs["player"],
        "movie_mode": movie_mode_on(),
        "handsoff_until": hands_off_until(now=now),
        "active_hours": in_active_hours(now),
    }

    if obs["power"] != st.get("tv"):
        log(f"TV power: {st.get('tv')} -> {obs['power']}")
    if obs["app_id"] != st.get("app"):
        log(f"Chromecast app: {st.get('app')} -> {obs['app_name']} ({obs['app_id']}), "
            f"player={obs['player']}, found={obs['found']}")

    action, gate = decide(obs, st, now)
    if gate != st.get("gate"):
        log(f"GATE {gate}")
    if action == "cast":
        do_cast(st, now, gate)
    elif action == "recast":
        do_recast(st, now)
    elif action == "stop":
        do_stop(st, gate)

    st["tv"] = obs["power"]; st["app"] = obs["app_id"]
    st["gate"] = gate
    st["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    json.dump(st, open(STATE_F, "w"))

if __name__ == "__main__":
    main()
