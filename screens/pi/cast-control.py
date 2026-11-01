#!/usr/bin/env python3
"""Cast control — a phone-friendly tap-to-cast page for the house displays.

Serves a small control page on port 8081 and runs CATT casts on castpi.
Design rules honoured: stop-first + 10 s settle before every cast (learned
the hard way — DashCast stalls without it); casts run in a background thread so the page answers
immediately; every action is appended to ~/cast-control.log.
No authentication by design decision: it binds the home LAN / tailnet only,
same trust level as the briefing page server it sits beside.
Also listens on port 80 with a bare redirect to :8081, so the bookmarked
http://CASTPI_LAN_IP/ address lands on this controller (see RedirectHandler).
Also the companion for Govee TV light bars: after a successful TV cast
the bars behind the TV take the view's recipe via the sibling govee.py
module (Govee's LAN API, scan-based discovery — no address hardcoded),
a TV stop or the movie-mode flag turns them off, and the TV card
carries a Bars row (Off / Auto / Warm / Dim) backed by POST /bars and
the /status "bars" object. Bars failures never affect casting.
"""
import json, os, re, subprocess, threading, time, urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = os.path.expanduser("~")
CATT = os.path.join(HOME, "caster", "bin", "catt")
BASE = "http://CASTPI_LAN_IP:8080"  # CONFIG: your caster Pi's LAN address
LOG_F = os.path.join(HOME, "cast-control.log")
# Refresh-on-cast: the dashboard and floorplan bake their Home Assistant
# states at render time (see docs/OPERATIONS.md, the snapshot job), so a
# cast can bring up hours-old data. When a cast is requested for one of
# those views and its baked snapshot is > 20 min old, the controller drops
# ~/refresh-request.flag; a watcher on the machine that runs the snapshot
# job spots it and refreshes in the background. The cast itself NEVER
# waits on this — it proceeds immediately with the data that exists. The
# flag is a request, not data (no credentials ever live on the Pi).
# Idempotent: an existing flag < 10 min old is left alone.
REFRESH_FLAG_F = os.path.join(HOME, "refresh-request.flag")
BRIEFING_DIR = os.path.join(HOME, "briefing")
SNAPSHOT_VIEWS = {"dashboard": "dashboard.html", "floorplan": "floorplan.html"}
SNAPSHOT_STALE_S = 20 * 60
REFRESH_FLAG_MIN_AGE_S = 10 * 60

# Govee TV light-bars companion: the Govee light bars behind the TV
# follow TV casts over Govee's LAN API via the sibling govee.py module.
# The import is defensive: if the module is missing or the bars are
# asleep, casting proceeds exactly as before — the lights are a
# companion, never a dependency, and no bars call may block or break a
# cast. Recipes are static per view; the client hard-caps recipe
# brightness at 30% and anything from this controller at 60%. A
# movie-mode flag file (shared with the gallery watcher) means bars
# OFF, always. Bedroom/kitchen casts never touch the bars.
try:
    import govee as _govee
except Exception:
    _govee = None

MOVIE_FLAG_F = os.path.join(HOME, "movie-mode.flag")
WATCH_STATE_F = os.path.join(HOME, "gallery-watch-state.json")

# view -> (brightness %, ("kelvin", K) | ("rgb", (r, g, b))); the briefing
# brightness is time-of-day (25% before noon, 20% after) and the Feed
# follows the Dashboard recipe.
BAR_RECIPES = {
    "briefing":      (None, ("kelvin", 2700)),
    "dashboard":     (20, ("kelvin", 3000)),
    "feed":          (20, ("kelvin", 3000)),
    "tonights-sky":  (12, ("rgb", (45, 35, 130))),
    "storm-mode":    (15, ("rgb", (70, 85, 105))),
    "jelly-cam":     (18, ("rgb", (0, 128, 128))),
    "gallery-all":   (25, ("kelvin", 3750)),
    "gallery-local": (25, ("kelvin", 3750)),
    "gallery-art":   (25, ("kelvin", 3750)),
    "dream-mode":    (10, ("rgb", (88, 40, 160))),
    "mycelium":      (12, ("rgb", (120, 30, 200))),
}
bars = {"auto": True, "mode": "auto", "recipe": None, "reachable": None,
        "status": None, "updated": None}
_bars_lock = threading.Lock()

def _bars_note(mode, recipe, reachable, status):
    with _bars_lock:
        bars.update({"mode": mode, "recipe": recipe, "reachable": reachable,
                     "status": status, "updated": time.strftime("%H:%M")})

def _bars_off(reason):
    """Bars off + record it. Never raises."""
    try:
        if _govee is None:
            _bars_note("off", None, None, None)
            return
        ok, st = _govee.off()
        _bars_note("off", None, ok, st)
        log(f"BARS off ({reason}) ok={ok}")
    except Exception as e:
        log(f"BARS off failed ({reason}): {e}")

def bars_apply_recipe(view_key):
    """Companion step after a successful TV cast: put the bars into the
    view's recipe. Honours, in order: movie mode (bars off), the Auto
    gate (a manual Bars choice wins until Auto is re-selected), and the
    recipe table (a view with no recipe turns the bars off). Never
    raises — it runs inside the cast thread, after the cast itself."""
    try:
        if _govee is None:
            return
        if os.path.exists(MOVIE_FLAG_F):
            _bars_off("movie mode")
            return
        with _bars_lock:
            auto = bars["auto"]
        if not auto:
            return
        spec = BAR_RECIPES.get(view_key)
        if spec is None:
            _bars_off(f"no recipe for {view_key}")
            return
        bright, color = spec
        if view_key == "briefing":
            bright = 25 if datetime.now().hour < 12 else 20
        kw = {"brightness": bright}
        kw[color[0]] = color[1]
        ok, st = _govee.set_recipe(**kw)
        _bars_note("auto", f"{view_key} recipe", ok, st)
        log(f"BARS recipe {view_key} {kw} ok={ok}")
    except Exception as e:
        log(f"BARS recipe failed for {view_key}: {e}")

def bars_snapshot():
    with _bars_lock:
        return dict(bars)

def bars_manual(mode):
    """The controller's Bars row: off | auto | warm | dim. Manual modes
    switch Auto off (the human beats the automation until Auto is
    re-selected); warm/dim go through the client's MANUAL_CAP (60).
    Returns a human result string. Never raises."""
    try:
        if mode == "off":
            with _bars_lock:
                bars["auto"] = False
            _bars_off("controller")
            return "bars off"
        if mode == "auto":
            with _bars_lock:
                bars["auto"] = True
            _bars_note("auto", bars_snapshot()["recipe"],
                       bars_snapshot()["reachable"], bars_snapshot()["status"])
            cur = state["devices"].get("tv") or {}
            vk = cur.get("view")
            if vk and vk != "stop":
                bars_apply_recipe(vk)
            return "bars auto — following casts"
        if mode in ("warm", "dim"):
            with _bars_lock:
                bars["auto"] = False
            if _govee is None:
                return "bars unavailable (no client)"
            if os.path.exists(MOVIE_FLAG_F):
                _bars_off("movie mode")
                return "movie mode is on — bars stay off"
            if mode == "warm":
                ok, st = _govee.set_recipe(brightness=25, kelvin=2700,
                                           cap=_govee.MANUAL_CAP)
                name = "warm 2700K · 25%"
            else:
                ok, st = _govee.set_recipe(brightness=5, kelvin=2200,
                                           cap=_govee.MANUAL_CAP)
                name = "dim 2200K · 5%"
            _bars_note(mode, name, ok, st)
            log(f"BARS manual {name} ok={ok}")
            return f"bars: {name}" + ("" if ok else " (the bars didn't answer)")
        return "unknown bars mode"
    except Exception as e:
        log(f"BARS manual {mode} failed: {e}")
        return f"bars error: {e}"

DEVICES = {
    "bedroom": "Bedroom display",
    "tv": "Living Room TV",
    "kitchen": "Kitchen display",
}
VIEWS = {
    "briefing":  ("Ambient Briefing", BASE + "/"),
    "dashboard": ("Home Dashboard",   BASE + "/dashboard.html"),
    "gallery-all":  ("Gallery — Mixed (local + famous)", BASE + "/gallery-all.html"),
    "gallery-local": ("Gallery — Bay Area Landmarks",    BASE + "/gallery.html"),
    "gallery-art":   ("Gallery — Famous Paintings",      BASE + "/gallery-art.html"),
    "floorplan": ("Floorplan", BASE + "/floorplan.html"),
    "jelly-cam": ("Jelly Cam — Monterey Bay", BASE + "/jelly-cam.html"),
    "tonights-sky": ("Tonight's Sky", BASE + "/tonights-sky.html"),
    "storm-mode": ("Storm Mode", BASE + "/storm-mode.html"),
    "flights-overhead": ("Flights Overhead", BASE + "/flights-overhead.html"),
    "mycelium": ("Living Mycelium", BASE + "/mycelium.html"),
    "dream-mode": ("Dream Mode — The Day, Dreamed", BASE + "/dream-mode.html"),
}

state = {"busy": False, "last": "nothing yet",
         "devices": {"bedroom": None, "tv": None, "kitchen": None}}

# ADS-B proxy for the Flights page: adsb.lol sends no CORS header, so the cast
# webview cannot fetch it directly. The Pi fetches server-side and the page
# reads same-origin. Cached 12 s so page polls never hammer the upstream.
YOUR_LAT, YOUR_LON = 0.0, 0.0  # CONFIG: your home's latitude/longitude
ADSB_URL = "https://api.adsb.lol/v2/point/{}/{}/30".format(YOUR_LAT, YOUR_LON)
_adsb = {"body": None, "at": 0.0}
def adsb_json():
    now = time.time()
    if _adsb["body"] is None or now - _adsb["at"] > 12:
        req = urllib.request.Request(ADSB_URL, headers={"User-Agent": "castpi-flights/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            _adsb["body"] = r.read()
        _adsb["at"] = now
    return _adsb["body"]

def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + msg
    with open(LOG_F, "a") as f:
        f.write(line + "\n")

def snapshot_age_s(view_key):
    """Age in seconds of the baked HA snapshot in a snapshot page, parsed
    from its "states read …" footer line; falls back to the file's mtime.
    Returns None if the page can't be read at all."""
    path = os.path.join(BRIEFING_DIR, SNAPSHOT_VIEWS[view_key])
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception:
        text = None
    if text:
        idx = text.lower().rfind("states read")
        seg = text[idx:idx + 300] if idx >= 0 else text
        m = re.search(r"([A-Z][a-z]{2} \d{1,2}, \d{4}, \d{1,2}:\d{2} [AP]M)", seg)
        if m:
            try:
                dt = datetime.strptime(m.group(1), "%b %d, %Y, %I:%M %p")
                return time.time() - time.mktime(dt.timetuple())
            except Exception:
                pass
    try:
        return time.time() - os.path.getmtime(path)
    except Exception:
        return None

def maybe_request_refresh(view_key):
    """Write ~/refresh-request.flag when view_key is a snapshot page whose
    baked data is stale (> 20 min). Returns True only when this call wrote
    the flag. Never raises — a refresh problem must never break a cast."""
    try:
        if view_key not in SNAPSHOT_VIEWS:
            return False
        age = snapshot_age_s(view_key)
        if age is None or age <= SNAPSHOT_STALE_S:
            return False
        try:
            if time.time() - os.path.getmtime(REFRESH_FLAG_F) < REFRESH_FLAG_MIN_AGE_S:
                return False  # a fresh request is already pending
        except OSError:
            pass
        payload = {"page": view_key,
                   "requested_at": datetime.now().isoformat(timespec="seconds"),
                   "reason": "cast"}
        tmp = REFRESH_FLAG_F + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, REFRESH_FLAG_F)
        log(f"REFRESH REQUESTED {view_key} (snapshot age {int(age // 60)} min > 20 min)")
        return True
    except Exception as e:
        log(f"REFRESH CHECK FAILED {view_key}: {e}")
        return False

def status_extras():
    """Additive /status fields (existing keys untouched): movie-mode flag
    state, the gallery watcher's liveness + current gate string from its
    state file, and the TV light bars' last-known companion state. The
    watcher polls every ~30 s; a state file older than 120 s means it is
    not running (e.g. its timer is disabled)."""
    w = {"polling": False, "gate": None}
    try:
        age = time.time() - os.path.getmtime(WATCH_STATE_F)
        if age < 120:
            with open(WATCH_STATE_F) as f:
                w = {"polling": True, "gate": json.load(f).get("gate")}
    except Exception:
        pass
    return {"movie_mode": os.path.exists(MOVIE_FLAG_F), "watcher": w,
            "bars": bars_snapshot()}

def run_cast(device_key, view_key):
    state["busy"] = True
    try:
        dev = DEVICES[device_key]
        if view_key == "stop":
            subprocess.run([CATT, "-d", dev, "stop"], timeout=60,
                           capture_output=True, text=True)
            state["last"] = f"{dev}: stopped"
            log(f"STOP {dev}")
            state["devices"][device_key] = {"view": "stop", "label": "Stopped",
                                            "when": time.strftime("%H:%M")}
            if device_key == "tv":
                _bars_off("tv stop")
            return
        label, url = VIEWS[view_key]
        subprocess.run([CATT, "-d", dev, "stop"], timeout=60,
                       capture_output=True, text=True)
        time.sleep(10)
        r = subprocess.run([CATT, "-d", dev, "cast_site", url], timeout=90,
                           capture_output=True, text=True)
        ok = "Casting" in (r.stdout + r.stderr)
        state["last"] = f"{dev}: {label}" + ("" if ok else " (cast unconfirmed — check log)")
        state["devices"][device_key] = {"view": view_key, "label": label,
                                        "when": time.strftime("%H:%M"),
                                        "unconfirmed": not ok}
        log(f"CAST {dev} <- {label} {url} ok={ok} out={(r.stdout + r.stderr).strip()[:200]}")
        if device_key == "tv" and ok:
            bars_apply_recipe(view_key)
    except Exception as e:
        state["last"] = f"error: {e}"
        log(f"ERROR {device_key}/{view_key}: {e}")
    finally:
        state["busy"] = False

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>House Screens</title>
<!-- cast-control-ui v2: peach-glass redesign. The old page's
     failure mode: feedback lived in one small line at the very bottom of a
     28-button page, the /cast fetch had no error handling (a failed fetch
     left "Casting..." up forever), and nothing showed what was on a screen.
     v2: sticky header + toast, per-device now-showing, per-button pending
     state, polls /status until the cast confirms or visibly fails. -->
<style>
  :root {
    --ink: #4A2C22; --ink-soft: #86604F;
    --accent: #BC5A28; --accent-soft: rgba(224,104,60,.15);
    --teal: #1F7A6D; --teal-soft: rgba(46,140,130,.15);
    --card: rgba(255,251,245,.66); --card-line: rgba(255,255,255,.85);
    --btn: rgba(255,255,255,.68); --btn-line: rgba(176,92,56,.28);
    --shadow: 0 10px 26px rgba(146,84,44,.14);
    --danger: #A3331B; --danger-soft: rgba(200,60,30,.12);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --ink: #F6DFCE; --ink-soft: #C9A58E;
      --accent: #F09A5F; --accent-soft: rgba(240,154,95,.16);
      --teal: #5FC4B5; --teal-soft: rgba(95,196,181,.16);
      --card: rgba(64,38,54,.55); --card-line: rgba(255,190,160,.22);
      --btn: rgba(84,50,66,.55); --btn-line: rgba(240,154,95,.30);
      --shadow: 0 10px 26px rgba(0,0,0,.45);
      --danger: #FF9A80; --danger-soft: rgba(255,120,90,.16);
    }
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; color: var(--ink);
    background: linear-gradient(155deg, #FFF8EF 0%, #FDEBD7 52%, #F8D9BC 100%);
    min-height: 100vh; padding: 0 14px 44px; }
  @media (prefers-color-scheme: dark) {
    body { background: linear-gradient(155deg, #2B1830 0%, #211226 55%, #180C1E 100%); }
  }
  .topbar { position: sticky; top: 0; z-index: 20; margin: 0 -14px; padding: 14px 16px 11px;
    background: linear-gradient(180deg, rgba(253,235,215,.93), rgba(253,235,215,.80));
    backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
    border-bottom: 1px solid rgba(255,255,255,.5); }
  @media (prefers-color-scheme: dark) {
    .topbar { background: linear-gradient(180deg, rgba(33,18,38,.95), rgba(33,18,38,.85));
      border-bottom-color: rgba(255,190,160,.15); }
  }
  .titlerow { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
  h1 { font-size: 25px; font-weight: 750; letter-spacing: -.01em; }
  #clock { font-size: 17px; font-weight: 650; color: var(--ink-soft);
    font-variant-numeric: tabular-nums; white-space: nowrap; }
  .sub { color: var(--ink-soft); font-size: 14px; margin-top: 3px; }
  #banner { display: none; margin-top: 10px; padding: 11px 13px; border-radius: 12px;
    font-size: 14.5px; font-weight: 650; color: var(--danger);
    background: var(--danger-soft); border: 1px solid var(--danger); }
  #banner.show { display: block; }
  #toast { display: none; margin-top: 10px; padding: 11px 13px; border-radius: 12px;
    font-size: 15px; font-weight: 620; background: var(--card);
    border: 1px solid var(--card-line); box-shadow: var(--shadow); }
  #toast.show { display: block; }
  #toast.pending { border-color: var(--accent); color: var(--accent); }
  #toast.ok { border-color: var(--teal); color: var(--teal); background: var(--teal-soft); }
  #toast.err { border-color: var(--danger); color: var(--danger); background: var(--danger-soft); }
  .dev { background: var(--card); border: 1px solid var(--card-line); border-radius: 20px;
    box-shadow: var(--shadow); padding: 16px 14px 14px; margin-top: 16px;
    backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px); }
  .devhead { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; padding: 0 2px; }
  .dev h2 { font-size: 20px; font-weight: 720; }
  .now { font-size: 14.5px; color: var(--ink-soft); margin-top: 3px; }
  .now b { color: var(--ink); font-weight: 650; }
  .now .unc { color: var(--danger); font-weight: 650; }
  .stopbtn { flex: none; min-height: 44px; padding: 10px 16px; border-radius: 12px;
    font-size: 15px; font-weight: 700; color: var(--danger); cursor: pointer;
    background: var(--danger-soft); border: 1px solid var(--danger); }
  .group { margin-top: 14px; }
  .grouplabel { font-size: 11.5px; font-weight: 750; letter-spacing: .13em;
    text-transform: uppercase; color: var(--ink-soft); padding: 0 2px 7px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; }
  .vbtn { display: flex; align-items: center; gap: 9px; min-height: 58px; padding: 10px 12px;
    font-size: 16px; font-weight: 620; color: var(--ink); text-align: left; cursor: pointer;
    background: var(--btn); border: 1px solid var(--btn-line); border-radius: 14px; }
  .vbtn .emo { font-size: 21px; line-height: 1; flex: none; }
  .vbtn .tag { margin-left: auto; flex: none; font-size: 10px; font-weight: 800;
    letter-spacing: .05em; color: var(--teal); text-transform: uppercase; }
  .vbtn:active { background: var(--accent-soft); }
  .vbtn.current { border-color: var(--teal); background: var(--teal-soft);
    box-shadow: inset 0 0 0 1px var(--teal); }
  .vbtn.pending { border-color: var(--accent); color: var(--accent); }
  button:disabled { opacity: .5; cursor: default; }
  .vbtn.pending:disabled, .stopbtn:disabled { opacity: 1; }
  .tvbars { margin-top: 14px; display: flex; flex-direction: column; gap: 7px; }
  .barsline { font-size: 13.5px; color: var(--ink-soft); line-height: 1.35; }
  .barsrow { display: flex; gap: 7px; }
  .barsbtn { flex: 1; min-height: 46px; border-radius: 12px; padding: 8px 6px;
    border: 1px solid var(--btn-line); background: var(--btn);
    color: var(--ink); font-size: 14.5px; font-weight: 680; cursor: pointer; }
  .barsbtn.on { background: var(--accent); border-color: var(--accent); color: #FFF6EC; }
  .foot { margin-top: 18px; font-size: 13px; color: var(--ink-soft); text-align: center; }
  .spin { display: inline-block; animation: pulse 1s ease-in-out infinite; }
  @keyframes pulse { 50% { opacity: .3; } }
</style></head><body>
<div class="topbar">
  <div class="titlerow"><h1>🖋️ House Screens</h1><div id="clock">--:--</div></div>
  <div class="sub">Tap a view to put it on a screen. Casts take ~15 seconds.</div>
  <div id="banner">⚠️ Can't reach the house controller — check you're on home Wi-Fi, then try again.</div>
  <div id="toast"></div>
</div>
<div id="devices"></div>
<div class="foot">House Screens · the castpi controller</div>
<script>
  const DEVICES = [["bedroom", "🛏️", "Bedroom display"], ["tv", "📺", "Living Room TV"], ["kitchen", "🍳", "Kitchen display"]];
  const GROUPS = [
    ["Briefing & House", [
      ["briefing", "🌅", "Briefing", "Ambient Briefing"],
      ["dashboard", "🏠", "Dashboard", "Home Dashboard"],
      ["floorplan", "🗺️", "Floorplan", "Floorplan"]]],
    ["Skies & Weather", [
      ["tonights-sky", "🔭", "Tonight's Sky", "Tonight's Sky"],
      ["storm-mode", "⛈️", "Storm Mode", "Storm Mode"],
      ["flights-overhead", "✈️", "Flights", "Flights Overhead"]]],
    ["Living Things", [
      ["jelly-cam", "🪼", "Jelly Cam", "Jelly Cam — Monterey Bay"],
      ["mycelium", "🍄", "Mycelium", "Living Mycelium"],
      ["dream-mode", "🌙", "Dream Mode", "Dream Mode — The Day, Dreamed"]]],
    ["Gallery", [
      ["gallery-all", "🖼️", "Mixed", "Gallery — Mixed (local + famous)"],
      ["gallery-local", "🌉", "Bay Area", "Gallery — Bay Area Landmarks"],
      ["gallery-art", "🎨", "Paintings", "Gallery — Famous Paintings"]]]
  ];
  const FULL = {};
  GROUPS.forEach(g => g[1].forEach(v => { FULL[v[0]] = v[3]; }));

  let op = null;            // {dk, vk} while a cast WE started is in flight
  let serverBusy = false;   // server reports a cast running (ours or keep-alive's)
  let lastSeen = "";
  let refreshReq = false;   // /cast said this cast's page data was stale and a background refresh was requested
  let toastTimer = null;

  const wrap = document.getElementById('devices');
  const nowEls = {}, btnEls = {}, stopEls = {};
  const tvBars = {};
  for (const [dk, emo, dl] of DEVICES) {
    const d = document.createElement('div'); d.className = 'dev';
    const head = document.createElement('div'); head.className = 'devhead';
    const left = document.createElement('div');
    const h = document.createElement('h2'); h.textContent = emo + ' ' + dl;
    const now = document.createElement('div'); now.className = 'now'; now.textContent = 'Now showing: …';
    left.appendChild(h); left.appendChild(now); nowEls[dk] = now;
    const stop = document.createElement('button'); stop.className = 'stopbtn'; stop.textContent = '⏹ Stop';
    stop.onclick = () => send(dk, 'stop');
    head.appendChild(left); head.appendChild(stop); d.appendChild(head);
    stopEls[dk] = stop; btnEls[dk] = {};
    if (dk === 'tv') {
      const mb = document.createElement('div'); mb.className = 'tvbars';
      const bl = document.createElement('div'); bl.className = 'barsline';
      bl.textContent = '💡 TV light bars: …';
      const brow = document.createElement('div'); brow.className = 'barsrow';
      const bbtns = {};
      for (const [mode, lab] of [['off', 'Bars Off'], ['auto', 'Auto'], ['warm', 'Warm'], ['dim', 'Dim']]) {
        const bb = document.createElement('button'); bb.className = 'barsbtn'; bb.textContent = lab;
        bb.onclick = () => barsSend(mode);
        brow.appendChild(bb); bbtns[mode] = bb;
      }
      mb.appendChild(bl); mb.appendChild(brow); d.appendChild(mb);
      tvBars.line = bl; tvBars.btns = bbtns;
    }
    for (const [gname, views] of GROUPS) {
      const g = document.createElement('div'); g.className = 'group';
      const gl = document.createElement('div'); gl.className = 'grouplabel'; gl.textContent = gname;
      const grid = document.createElement('div'); grid.className = 'grid';
      for (const [vk, vemo, short] of views) {
        const b = document.createElement('button'); b.className = 'vbtn';
        const e = document.createElement('span'); e.className = 'emo'; e.textContent = vemo;
        const l = document.createElement('span'); l.className = 'lbl'; l.textContent = short;
        const t = document.createElement('span'); t.className = 'tag'; t.textContent = 'On screen'; t.hidden = true;
        b.appendChild(e); b.appendChild(l); b.appendChild(t);
        b.dataset.short = short;
        b.onclick = () => send(dk, vk);
        grid.appendChild(b); btnEls[dk][vk] = b;
      }
      g.appendChild(gl); g.appendChild(grid); d.appendChild(g);
    }
    wrap.appendChild(d);
  }

  function setToast(kind, msg, autoHide) {
    const t = document.getElementById('toast');
    t.className = 'show ' + kind; t.innerHTML = msg;
    clearTimeout(toastTimer);
    if (autoHide) toastTimer = setTimeout(() => { t.className = ''; }, 9000);
  }
  function setBanner(on) { document.getElementById('banner').className = on ? 'show' : ''; }

  function markPending() {
    const busy = !!op || serverBusy;
    for (const dk of Object.keys(btnEls)) {
      stopEls[dk].disabled = busy;
      for (const vk of Object.keys(btnEls[dk])) {
        const b = btnEls[dk][vk];
        b.disabled = busy;
        const isOp = op && op.dk === dk && op.vk === vk;
        b.classList.toggle('pending', !!isOp);
        b.querySelector('.lbl').textContent = isOp ? 'Casting…' : b.dataset.short;
      }
    }
  }

  function deviceNow(dk, s) {
    const name = (DEVICES.find(d => d[0] === dk) || [])[2] || dk;
    const dv = (s.devices || {})[dk];
    if (dv) {
      if (dv.view === 'stop') return {label: 'Stopped', when: dv.when, unc: false, key: 'stop'};
      return {label: dv.label, when: dv.when, unc: !!dv.unconfirmed, key: dv.view};
    }
    const last = s.last || '';
    if (last.indexOf(name + ': ') === 0) {
      let rest = last.slice(name.length + 2);
      if (rest === 'stopped') return {label: 'Stopped', when: null, unc: false, key: 'stop'};
      const unc = rest.indexOf(' (cast unconfirmed') >= 0;
      rest = rest.replace(' (cast unconfirmed — check log)', '');
      const key = Object.keys(FULL).find(k => FULL[k] === rest) || null;
      return {label: rest, when: null, unc: unc, key: key};
    }
    return {label: 'Nothing yet this session', when: null, unc: false, key: null};
  }

  function render(s) {
    lastSeen = s.last || '';
    serverBusy = !!s.busy;
    for (const [dk] of DEVICES) {
      const n = deviceNow(dk, s);
      nowEls[dk].innerHTML = 'Now showing: <b></b>' +
        (n.unc ? ' <span class="unc">(unconfirmed)</span>' : '') +
        (n.when ? ' · since ' + n.when : '');
      nowEls[dk].querySelector('b').textContent = n.label;
      for (const vk of Object.keys(btnEls[dk])) {
        const isCur = n.key === vk && !n.unc;
        btnEls[dk][vk].classList.toggle('current', isCur);
        btnEls[dk][vk].querySelector('.tag').hidden = !isCur;
      }
    }
    if (tvBars.line && s.bars) {
      const b = s.bars, st = b.status;
      const live = st ? (st.onOff ? 'on · ' + st.brightness + '%' : 'off')
                      : 'no reading yet';
      tvBars.line.textContent = '💡 TV light bars: ' +
        (b.mode === 'off' ? 'off' : (b.recipe || 'auto')) + ' · ' + live +
        (b.reachable === false ? " · ⚠️ didn't answer" : '') +
        (b.updated ? ' · set ' + b.updated : '');
      for (const m of Object.keys(tvBars.btns))
        tvBars.btns[m].classList.toggle('on', b.mode === m);
    }
    markPending();
  }

  async function refresh() {
    try {
      const s = await (await fetch('/status')).json();
      setBanner(false);
      render(s);
    } catch (e) { setBanner(true); }
  }

  async function barsSend(mode) {
    try {
      const r = await (await fetch('/bars', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({mode: mode})})).json();
      setToast('ok', '💡 ' + (r.result || 'bars updated'), true);
    } catch (e) { setBanner(true); }
    refresh();
  }

  async function send(dk, vk) {
    if (op || serverBusy) return;
    const dl = (DEVICES.find(d => d[0] === dk) || [])[2] || dk;
    const what = vk === 'stop' ? 'Stop' : (FULL[vk] || vk);
    op = {dk: dk, vk: vk};
    markPending();
    setToast('pending', '<span class="spin">⏳</span> ' +
      (vk === 'stop' ? 'Stopping the ' + dl + '…'
                     : 'Casting ' + what + ' → ' + dl + '… (~15 s)'), false);
    let res;
    try {
      res = await (await fetch('/cast', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({device: dk, view: vk})})).json();
    } catch (e) {
      op = null; markPending(); setBanner(true);
      setToast('err', "✗ Couldn't reach the controller — nothing was cast. Check you're on home Wi-Fi and try again.", false);
      return;
    }
    refreshReq = res.refresh === 'requested';
    if (res.result !== 'started') {
      op = null; markPending();
      setToast('err', '✗ ' + res.result, false);
      refresh();
      return;
    }
    if (refreshReq) {
      setToast('pending', '<span class="spin">⏳</span> Casting ' + what + ' → ' + dl +
        '… · its data was stale, so a refresh was requested in the background — the screen will update itself shortly.', false);
    }
    pollDone(dk, vk, dl, what);
  }

  async function pollDone(dk, vk, dl, what) {
    const t0 = Date.now();
    while (Date.now() - t0 < 80000) {
      await new Promise(r => setTimeout(r, 2000));
      let s;
      try { s = await (await fetch('/status')).json(); setBanner(false); }
      catch (e) { continue; }
      render(s);
      if (!s.busy) {
        op = null; markPending();
        const dv = (s.devices || {})[dk];
        if (vk === 'stop') {
          if ((dv && dv.view === 'stop') || (s.last || '').indexOf(dl + ': stopped') === 0)
            setToast('ok', '✓ ' + dl + ' stopped.', true);
          else
            setToast('err', "✗ Stop didn't confirm — last action: " + (s.last || 'unknown'), false);
        } else if (dv && dv.view === vk && !dv.unconfirmed) {
          setToast('ok', '✓ ' + what + ' is on the ' + dl + '.' +
            (refreshReq ? ' Data refresh requested — it will update itself in a few minutes.' : ''), true);
        } else if (dv && dv.view === vk && dv.unconfirmed) {
          setToast('err', "✗ The cast to the " + dl + " didn't confirm — the display may not have taken it. Try again, or check the screen.", false);
        } else if ((s.last || '').indexOf('error') === 0) {
          setToast('err', '✗ Cast failed — ' + s.last, false);
        } else {
          setToast('err', "✗ That cast didn't confirm — last action: " + (s.last || 'unknown'), false);
        }
        return;
      }
    }
    op = null; markPending();
    setToast('err', '✗ Still no confirmation after 80 s — check the screen. Last action: ' + lastSeen, false);
  }

  function tickClock() {
    const d = new Date();
    let h = d.getHours(); const ap = h >= 12 ? 'PM' : 'AM'; h = h % 12 || 12;
    document.getElementById('clock').textContent =
      h + ':' + String(d.getMinutes()).padStart(2, '0') + ' ' + ap;
  }
  tickClock(); setInterval(tickClock, 10000);
  refresh(); setInterval(refresh, 10000);
</script></body></html>
"""

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass
    def do_GET(self):
        if self.path == "/adsb":
            try:
                body = adsb_json()
                self.send_response(200); self.send_header("Content-Type", "application/json")
            except Exception as e:
                body = json.dumps({"ac": [], "error": str(e)}).encode()
                self.send_response(502); self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)
        elif self.path == "/status":
            # Additive extras (movie_mode / watcher / bars); existing keys
            # are untouched.
            merged = dict(state); merged.update(status_extras())
            body = json.dumps(merged).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)
        else:
            body = PAGE.encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)
    def do_POST(self):
        if self.path == "/bars":
            try:
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(n) or b"{}")
                msg = bars_manual(req.get("mode", ""))
            except Exception as e:
                msg = f"bad request: {e}"
            body = json.dumps({"result": msg}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)
            return
        if self.path != "/cast":
            self.send_response(404); self.end_headers(); return
        resp = {}
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            dk, vk = req.get("device"), req.get("view")
            if dk in DEVICES and (vk in VIEWS or vk == "stop"):
                # Refresh-on-cast: runs BEFORE the cast thread starts, and
                # regardless of whether the cast then succeeds — a stale
                # snapshot page earns a background refresh request, and the
                # cast proceeds immediately either way (see
                # maybe_request_refresh). Additive response field only.
                if maybe_request_refresh(vk):
                    resp["refresh"] = "requested"
                if state["busy"]:
                    msg = "busy — a cast is already running, try again in a few seconds"
                else:
                    threading.Thread(target=run_cast, args=(dk, vk), daemon=True).start()
                    msg = "started"
            else:
                msg = "unknown device or view"
        except Exception as e:
            msg = f"bad request: {e}"
        resp["result"] = msg
        body = json.dumps(resp).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)

class RedirectHandler(BaseHTTPRequestHandler):
    """Port 80 landing: phones bookmark http://CASTPI_LAN_IP/ (no port), where
    nothing used to listen — that dead end was the "controller stopped
    working" report. Every request here 302s to the real
    controller on :8081, path preserved. Port 80 is privileged and the
    service runs as an unprivileged user, so the bind needs CAP_NET_BIND_SERVICE from
    the systemd drop-in port80.conf; if the bind ever fails, the failure is
    logged and the :8081 controller carries on without it."""
    def log_message(self, *a):  # quiet
        pass
    def _go(self):
        self.send_response(302)
        self.send_header("Location", "http://CASTPI_LAN_IP:8081" + (self.path or "/"))
        self.send_header("Content-Length", "0")
        self.end_headers()
    do_GET = _go
    do_POST = _go
    do_HEAD = _go

if __name__ == "__main__":
    log("cast-control server starting on 8081")
    try:
        threading.Thread(
            target=ThreadingHTTPServer(("0.0.0.0", 80), RedirectHandler).serve_forever,
            daemon=True).start()
        log("port-80 redirect listener up (-> http://CASTPI_LAN_IP:8081/)")
    except Exception as e:
        log(f"port-80 redirect listener FAILED (controller unaffected): {e}")
    ThreadingHTTPServer(("0.0.0.0", 8081), Handler).serve_forever()
