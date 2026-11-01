#!/usr/bin/env python3
"""Gallery idle watcher — when the TV sits idle, put art on it.

Polls every ~30 s (systemd timer):
  - TV power via its local API (TV_LAN_IP:8001 — Samsung TVs report PowerState)
  - Chromecast "Living Room TV" app + player state via pychromecast

Standing rule:
  - TV on + Chromecast not playing for IDLE_SECONDS (180) continuously,
    inside active hours 06:00-23:00 -> cast the mixed gallery (gallery-all).
  - While the gallery is up, recast every RECAST_SECONDS (480) to beat the
    ~9-minute DashCast timeout.
  - TV turns off -> stop our cast.
  - Someone plays something else on the Chromecast -> gallery yields,
    watcher stands down (never stops their content).
  - Quiet hours (23:00-06:00): no new casts; stop our gallery if it is up.
Logs every transition and action to ~/gallery-watch.log.
"""
import json, os, subprocess, time, urllib.request
import pychromecast

HOME = os.path.expanduser("~")
STATE_F = os.path.join(HOME, "gallery-watch-state.json")
LOG_F = os.path.join(HOME, "gallery-watch.log")
CATT = os.path.join(HOME, "caster", "bin", "catt")
DEVICE = "Living Room TV"
GALLERY_URL = "http://CASTPI_LAN_IP:8080/gallery-all.html"  # CONFIG
TV_API = "http://TV_LAN_IP:8001/api/v2/"  # CONFIG: your TV's LAN address
IDLE_SECONDS = 180
RECAST_SECONDS = 480
DASHCAST_APP = "84912283"   # our gallery casts
BACKDROP_APP = "E8C28D3C"   # Chromecast idle screensaver

def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + msg
    with open(LOG_F, "a") as f:
        f.write(line + "\n")

def in_active_hours():
    h = time.localtime().tm_hour
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
    ccs, browser = pychromecast.get_chromecasts(tries=2, timeout=12)
    try:
        for c in ccs:
            if "Living Room" in c.name:
                c.wait(timeout=8)
                mc = c.media_controller
                ps = mc.status.player_state if mc.status else None
                return c.app_id, c.app_display_name, ps
        return None, None, None
    finally:
        pychromecast.discovery.stop_discovery(browser)

def catt(*args):
    try:
        subprocess.run([CATT, "-d", DEVICE, *args],
                       capture_output=True, timeout=60)
    except Exception as e:
        log(f"catt {args} failed: {e}")

def cast_gallery(st, why):
    catt("cast_site", GALLERY_URL)
    st["last_cast"] = time.time()
    st["idle_since"] = None
    log(f"CAST gallery-all ({why})")

def stop_gallery(st, why):
    catt("stop")
    st["last_cast"] = None
    st["idle_since"] = None
    log(f"STOP gallery ({why})")

def main():
    try:
        st = json.load(open(STATE_F))
    except Exception:
        st = {}
    st.setdefault("idle_since", None)
    st.setdefault("last_cast", None)
    st.setdefault("tv", None)
    st.setdefault("app", None)

    power = tv_power()
    app_id, app_name, player = cast_state()
    now = time.time()
    active = in_active_hours()

    if power != st.get("tv"):
        log(f"TV power: {st.get('tv')} -> {power}")
    if app_id != st.get("app"):
        log(f"Chromecast app: {st.get('app')} -> {app_name} ({app_id}), player={player}")

    playing = player in ("PLAYING", "BUFFERING")
    gallery_active = app_id == DASHCAST_APP
    other_content = (app_id not in (None, BACKDROP_APP, DASHCAST_APP))

    if gallery_active and st.get("last_cast") is None:
        # First sight of a gallery cast this watcher didn't start (e.g. manual cast)
        st["last_cast"] = now
        log("Gallery on screen (cast outside watcher) — adopting it for recast timing")

    if power != "on":
        if gallery_active:
            stop_gallery(st, f"TV power={power}")
        st["idle_since"] = None
    elif not active:
        if gallery_active:
            stop_gallery(st, "quiet hours 23:00-06:00")
        st["idle_since"] = None
    elif gallery_active:
        if now - (st.get("last_cast") or now) >= RECAST_SECONDS:
            catt("stop")
            time.sleep(5)
            cast_gallery(st, "8-minute recast")
        st["idle_since"] = None
    elif playing or other_content:
        # Someone is using the Chromecast — stand down, never touch their content
        if st.get("idle_since") is not None:
            log(f"Idle window reset (app={app_name}, player={player})")
        st["idle_since"] = None
    else:
        # TV on, Chromecast idle (backdrop or nothing), active hours
        if st.get("idle_since") is None:
            st["idle_since"] = now
            log(f"Idle window started (TV on, Chromecast app={app_name}, player={player})")
        elif now - st["idle_since"] >= IDLE_SECONDS:
            cast_gallery(st, f"idle {int(now - st['idle_since'])}s")

    st["tv"] = power; st["app"] = app_id
    json.dump(st, open(STATE_F, "w"))

if __name__ == "__main__":
    main()
