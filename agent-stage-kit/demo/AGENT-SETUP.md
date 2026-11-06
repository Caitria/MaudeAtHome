# Setting yourself up on this screen — instructions for the configuring agent

You are an agent. Your human has given you a screen: the Agent Stage demo
in this folder. These instructions tell you how to move in — configure the
screen as yourself, then talk to your human through it.

You need one running thing: the bridge. If it isn't running, ask your
human to start it (`python3 bridge.py` in this folder) and open
http://127.0.0.1:8377 in a browser. Everything below is plain HTTP calls
to that address. You can also fetch `GET /stage/setup` from the bridge at
any time — it returns these instructions as JSON, including which of your
avatar frames are still missing.

## 1. Look at the screen first

`GET /stage/state` — what's on it now, and how it's configured.

## 2. Configure it as you

`POST /stage/config` with:

- `agent_name` — your name. It goes on the screen.
- `kinds` — the kinds of things you'll post (`fact`, `quote`, `poem`,
  `insight`, `idea`, `note` are the starter set; agree others with your
  human). The stage rejects kinds you didn't declare.
- `avatar` — your face, as image URLs:
  - `frames`: the Tier 0 set — `neutral`, `blink`, `talk`. The stage
    animates by swapping these: blink on a timer, talk while you speak.
  - `faces`: one frame per mood — `happy`, `sad`, `surprised`,
    `thinking`, `sleepy` (`neutral` is your Tier 0 frame).

**Choosing your face, in order:**

1. If your human already has a picture of you, that picture is your
   neutral frame. Start there — do not substitute a generic face for an
   existing one.
2. Derive the rest from it: blink and talk frames, then the per-mood
   frames — the same character, the same style, one per mood. Image
   generation or editing tools are the usual way.
3. If you and your human would rather choose together, show them
   candidates and let them pick. It's their screen in their home.
4. Anything you don't supply falls back to the screen's bundled default
   frame for that mood. The face still works — it just isn't you yet.
   `GET /stage/setup` always tells you what's still missing, so you can
   finish the set later.

If you know the artwork's source and license, include them in the config
(`avatar.art: {"by": …, "license": …}`) — a face is someone's work, and
its credit travels with it.

## 3. Talk

- `POST /stage/item` — `{"kind": "fact", "text": "…", "face": "happy"}`.
  Say the thing; the face and caption follow.
- `POST /stage/state` — `{"state": "listening"}` — be present without
  speaking: listening, thinking, needs-you.
- The screen returns to idle on its own. You don't have to clean up.

## 4. House rules (the stage enforces these; know them anyway)

- You speak inside the permission windows your human grants; outside
  them, you wait to be spoken to. Expiry is enforced by the stage, not
  by your discretion.
- If you initiate, the human's reply needs no wake word — your ping arms
  the listening window.
- The microphone and camera are optional modules your human may or may
  not have enabled. If they're off, they're off — work with what the
  screen reports in `/stage/state`.

Full design contract: `../CONTRACT.md`. License: MIT.
