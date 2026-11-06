#!/usr/bin/env python3
"""
Agent Stage — demo bridge.

One file, no dependencies (Python 3 standard library only). It serves the
demo page, and it is the thing an agent actually talks to:

  python3 bridge.py            # then open http://127.0.0.1:8377

An agent configures the screen and talks through it with plain HTTP:

  # the agent sets itself up on the screen
  curl -X POST http://127.0.0.1:8377/stage/config -H 'Content-Type: application/json' -d '{
    "agent_name": "Maude",
    "avatar": {"tier": 0, "frames": {"neutral": "https://…/frame-0.webp",
                                     "blink":   "https://…/frame-1.webp",
                                     "talk":    "https://…/frame-2.webp"},
               "faces":  {"happy": "https://…/happy.webp", "sad": "https://…/sad.webp"}},
    "kinds": ["fact", "quote", "poem", "insight", "idea", "note"]
  }'

  # an agent that has just arrived can ask what setup is wanted and what is missing
  curl http://127.0.0.1:8377/stage/setup

  # the agent says something
  curl -X POST http://127.0.0.1:8377/stage/item -H 'Content-Type: application/json' -d '{
    "kind": "fact", "text": "Honey never spoils.", "face": "happy"
  }'

  # the agent just changes state
  curl -X POST http://127.0.0.1:8377/stage/state -H 'Content-Type: application/json' \
       -d '{"state": "listening"}'

  # anyone can ask what is on screen
  curl http://127.0.0.1:8377/stage/state

The page receives everything over a same-origin event stream (/stream).
State and config persist to bridge-state.json next to this script, so a
page reload restores the screen the agent left.

Local only: the bridge binds 127.0.0.1 and has no authentication, by
design, for a demo running on your own machine. Do not expose it to a
network you do not control. Contract: ../CONTRACT.md (Agent Stage v0).
MIT License — Caitria O'Neill.
"""

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "bridge-state.json"
HOST, PORT = "127.0.0.1", 8377

DEFAULT_STATE = {
    "config": {
        "agent_name": None,
        "avatar": None,  # {"tier":0, "frames":{"neutral":…,"blink":…,"talk":…}, "faces":{…}}
        "kinds": ["fact", "quote", "poem", "insight", "idea", "note"],
    },
    "state": "idle",
    "item": None,      # the headline item
    "earlier": [],     # up to 4 previous items
}

_lock = threading.Lock()
_clients = []  # list[queue.Queue]


def load_state():
    if STATE_FILE.exists():
        try:
            saved = json.loads(STATE_FILE.read_text())
            merged = json.loads(json.dumps(DEFAULT_STATE))
            merged.update({k: saved[k] for k in saved if k in merged})
            return merged
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_STATE))


STATE = load_state()

# The face vocabulary of the contract (CONTRACT.md §3), and the Tier 0
# frames every avatar needs before per-mood frames even come up.
FACES = ["neutral", "happy", "sad", "surprised", "thinking", "sleepy"]
TIER0_FRAMES = ["neutral", "blink", "talk"]


def setup_instructions(config):
    """What a configuring agent reads first: how to set this screen up,
    and exactly which avatar frames are still missing."""
    avatar = config.get("avatar") or {}
    frames = avatar.get("frames") or {}
    faces = avatar.get("faces") or {}
    return {
        "what_this_is": (
            "An Agent Stage demo screen. You (an agent) configure it once, "
            "then talk to your human through it. Full contract: CONTRACT.md."
        ),
        "steps": [
            "1. GET /stage/state to see what is on the screen now.",
            "2. POST /stage/config with your name, your avatar, and the "
            "content kinds you will use (see 'config_fields').",
            "3. POST /stage/item to say something; POST /stage/state to "
            "change state without speaking.",
        ],
        "config_fields": {
            "agent_name": "your name, shown on the screen",
            "avatar.frames": "Tier 0 frame image URLs: neutral, blink, talk",
            "avatar.faces": "per-mood frame image URLs, keyed by mood name",
            "kinds": "the content kinds you may post (the stage rejects others)",
        },
        "avatar_rules": [
            "If your human already has a picture of you, that picture is "
            "your neutral frame — start from it.",
            "Per-mood frames should be the same character in the same "
            "style, one per mood. Derive them from the neutral picture "
            "(image generation/editing) or choose them together with "
            "your human.",
            "Any mood you do not supply falls back to the screen's "
            "bundled default frame for that mood — the face still works; "
            "it just is not you yet.",
            "The artwork's license/credit belong in avatar art metadata "
            "when you know them (CONTRACT.md §4).",
        ],
        "moods": FACES,
        "tier0_frames": TIER0_FRAMES,
        "missing": {
            "frames": [f for f in TIER0_FRAMES if f not in frames],
            # the neutral mood is satisfied by the Tier 0 neutral frame
            "faces": [f for f in FACES
                      if f not in faces and not (f == "neutral" and "neutral" in frames)],
        },
        "endpoints": {
            "configure": "POST /stage/config",
            "post_item": "POST /stage/item {kind, text, face?, state?, hold_seconds?}",
            "set_state": "POST /stage/state {state}",
            "read_state": "GET /stage/state",
        },
    }


def save_state():
    STATE_FILE.write_text(json.dumps(STATE, indent=2))


def broadcast(event, payload):
    msg = json.dumps({"event": event, "data": payload})
    with _lock:
        dead = []
        for q in _clients:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _clients.remove(q)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # -- plumbing ---------------------------------------------------------
    def log_message(self, fmt, *args):  # keep the terminal friendly
        print(f"  {self.address_string()} {fmt % args}")

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return {}

    # -- routes ------------------------------------------------------------
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            page = HERE / "index.html"
            if page.exists():
                self._send(200, page.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(200, "<h1>Agent Stage bridge is running.</h1>"
                                "<p>Put the demo page next to bridge.py as index.html.</p>",
                           "text/html; charset=utf-8")
        elif self.path in ("/stream", "/stage/events"):
            self._stream()
        elif self.path == "/stage/state":
            with _lock:
                self._send(200, json.dumps(STATE))
        elif self.path == "/stage/config":
            with _lock:
                self._send(200, json.dumps(STATE["config"]))
        elif self.path == "/stage/setup":
            with _lock:
                self._send(200, json.dumps(setup_instructions(STATE["config"])))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        body = self._json_body()
        if self.path == "/stage/config":
            with _lock:
                for key in ("agent_name", "avatar", "kinds"):
                    if key in body:
                        STATE["config"][key] = body[key]
                save_state()
                config = json.loads(json.dumps(STATE["config"]))
            broadcast("config", config)
            self._send(200, json.dumps({"ok": True, "config": config}))
        elif self.path == "/stage/item":
            text = (body.get("text") or "").strip()
            if not text:
                self._send(400, json.dumps({"error": "item needs non-empty text"}))
                return
            item = {
                "kind": body.get("kind", "note"),
                "text": text[:700],
                "face": body.get("face"),
                "hold_seconds": body.get("hold_seconds"),
            }
            with _lock:
                kinds = STATE["config"].get("kinds") or []
                if kinds and item["kind"] not in kinds:
                    self._send(400, json.dumps(
                        {"error": f"kind {item['kind']!r} not in configured kinds {kinds}"}))
                    return
                if STATE["item"]:
                    STATE["earlier"] = [STATE["item"]] + STATE["earlier"][:3]
                STATE["item"] = item
                STATE["state"] = body.get("state", "speaking")
                save_state()
                snapshot = json.loads(json.dumps(STATE))
            broadcast("item", snapshot)
            self._send(200, json.dumps({"ok": True}))
        elif self.path == "/stage/state":
            state = body.get("state")
            if not state:
                self._send(400, json.dumps({"error": "state required"}))
                return
            with _lock:
                STATE["state"] = state
                save_state()
                snapshot = json.loads(json.dumps(STATE))
            broadcast("state", snapshot)
            self._send(200, json.dumps({"ok": True}))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # -- the event stream the page listens to ------------------------------
    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        q = queue.Queue(maxsize=100)
        with _lock:
            _clients.append(q)
            snapshot = json.dumps({"event": "state", "data": STATE})
        try:
            self.wfile.write(f"data: {snapshot}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=20)
                    self.wfile.write(f"data: {msg}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with _lock:
                if q in _clients:
                    _clients.remove(q)


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Agent Stage bridge on http://{HOST}:{PORT}")
    print("Open that address in a browser. An agent configures and talks via")
    print(f"POST /stage/config, POST /stage/item, POST /stage/state (see the header of this file).")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
