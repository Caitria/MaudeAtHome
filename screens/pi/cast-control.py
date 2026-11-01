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
"""
import json, os, subprocess, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = os.path.expanduser("~")
CATT = os.path.join(HOME, "caster", "bin", "catt")
BASE = "http://CASTPI_LAN_IP:8080"  # CONFIG: your caster Pi's LAN address
LOG_F = os.path.join(HOME, "cast-control.log")

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
    "aqi-sentinel": ("AQI Sentinel", BASE + "/aqi-sentinel.html"),
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
      ["aqi-sentinel", "🌫️", "AQI", "AQI Sentinel"],
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
  let toastTimer = null;

  const wrap = document.getElementById('devices');
  const nowEls = {}, btnEls = {}, stopEls = {};
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
    markPending();
  }

  async function refresh() {
    try {
      const s = await (await fetch('/status')).json();
      setBanner(false);
      render(s);
    } catch (e) { setBanner(true); }
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
    if (res.result !== 'started') {
      op = null; markPending();
      setToast('err', '✗ ' + res.result, false);
      refresh();
      return;
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
          setToast('ok', '✓ ' + what + ' is on the ' + dl + '.', true);
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
            body = json.dumps(state).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)
        else:
            body = PAGE.encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)
    def do_POST(self):
        if self.path != "/cast":
            self.send_response(404); self.end_headers(); return
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            dk, vk = req.get("device"), req.get("view")
            if dk in DEVICES and (vk in VIEWS or vk == "stop"):
                if state["busy"]:
                    msg = "busy — a cast is already running, try again in a few seconds"
                else:
                    threading.Thread(target=run_cast, args=(dk, vk), daemon=True).start()
                    msg = "started"
            else:
                msg = "unknown device or view"
        except Exception as e:
            msg = f"bad request: {e}"
        body = json.dumps({"result": msg}).encode()
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
