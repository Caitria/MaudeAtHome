#!/usr/bin/env python3
"""Bedroom-display keep-alive (display cast names in the log regexes
below — "Bedroom display" — are CONFIG: use your own displays' cast names).

Bedroom-display keep-alive: DashCast sessions expire; re-cast whatever view
the phone control last put on the Bedroom display, every timer tick.
Bedroom only - the TV belongs to gallery-watch. Quiet hours 23:00-06:00."""
import json, re, subprocess, sys, urllib.request
from datetime import datetime
from pathlib import Path

LOG = Path.home() / "cast-control.log"
BASE = "http://CASTPI_LAN_IP:8080/"  # CONFIG: your caster Pi's LAN address
FILE2VIEW = {
    "index.html": "briefing", "dashboard.html": "dashboard",
    "floorplan.html": "floorplan", "gallery-all.html": "gallery-all",
    "gallery.html": "gallery-bay", "gallery-art.html": "gallery-art",
    "jelly-cam.html": "jelly-cam", "tonights-sky.html": "tonights-sky",
    "storm-mode.html": "storm-mode", "aqi-sentinel.html": "aqi-sentinel",
    "flights-overhead.html": "flights-overhead",
}

def last_bedroom_view():
    try:
        lines = LOG.read_text().splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        m = re.search(r"CAST Bedroom display <- .*? (https?://\S+?) ok=True", line)
        if m:
            fn = m.group(1).rsplit("/", 1)[-1] or "index.html"
            return FILE2VIEW.get(fn)
        if "STOP Bedroom display" in line:
            return None
    return None

def main():
    if not (6 <= datetime.now().hour < 23):
        return
    view = last_bedroom_view()
    if not view:
        return
    req = urllib.request.Request(
        "http://localhost:8081/cast",
        data=json.dumps({"device": "bedroom", "view": view}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        print(datetime.now().isoformat(), "keepalive recast bedroom:", view, r.read().decode()[:60])

if __name__ == "__main__":
    main()
