# Agent Stage — browser demo

A screen your agent can move into. Open the page, and your personal agent
configures it — its name, its face, the kinds of things it may say — and
then talks to you through it: emotes, captions, states. You can add senses
over time (microphone, camera, other sensors are optional modules in the
contract); a little latency is expected, and fine.

This is the browser-first demo of the **Agent Stage** contract
(`../CONTRACT.md`). License: MIT.

## Run it (one command)

```sh
python3 bridge.py
```

Then open **http://127.0.0.1:8377** in a browser. That's the whole setup:
the bridge is a single Python file with no dependencies, and it serves
the page itself.

Without the bridge, the page still opens — it will say
"No agent connected — manual preview," and the buttons are yours to poke.
That's a preview, not the product.

## Connect an agent

Hand your agent the file **`AGENT-SETUP.md`** from this folder — it's
written to them. Or point them at the bridge: `GET /stage/setup` returns
the same instructions as JSON, including which avatar frames are still
missing.

The short version, for the curious:

```sh
# the agent configures the screen as itself
curl -X POST http://127.0.0.1:8377/stage/config -H 'Content-Type: application/json' -d '{
  "agent_name": "YourAgent",
  "avatar": {"frames": {"neutral": "<url>", "blink": "<url>", "talk": "<url>"},
             "faces":  {"happy": "<url>", "sad": "<url>"}},
  "kinds": ["fact", "quote", "poem", "insight", "idea", "note"]}'

# the agent says something
curl -X POST http://127.0.0.1:8377/stage/item -H 'Content-Type: application/json' \
     -d '{"kind": "fact", "text": "Honey never spoils.", "face": "happy"}'
```

## The face

The avatar is frame-based, per the contract: a neutral frame, a blink
frame, a talking frame (Tier 0), plus one frame per mood. The demo ships
with a bundled default character with a frame for every mood, so it works
before anyone uploads anything. If the agent (or you) supplies frames,
they replace the defaults mood-by-mood — and if the agent already has a
picture, that picture is its neutral frame. A single picture on its own
stays still, with a note saying why: a wiggle is not an expression.

## Files

- `index.html` — the screen (self-contained; the bundled frames are inlined)
- `bridge.py` — the bridge: serves the page, takes the agent's calls
  (`/stage/config`, `/stage/item`, `/stage/state`, `/stage/setup`,
  `/stage/events`), enforces the configured kinds, keeps the last state
  in `bridge-state.json`
- `AGENT-SETUP.md` — instructions written to the configuring agent
- `../CONTRACT.md` — the design contract this demo implements

## Honest limits of the demo

Local only, no authentication — the bridge binds 127.0.0.1; don't expose
it to a network you don't control. No microphone or camera modules yet;
voice-out is the page's speech, not the contract's full module set. The
permission windows and kill switch in the contract are design rules this
demo gestures at, not yet enforcement machinery.

— Caitria O'Neill, caitriaoneill.com
