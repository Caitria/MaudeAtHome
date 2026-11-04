# The Agent Stage — a screen any agent can occupy

**Contract draft v0 — November 4, 2026. Caitria O'Neill.**
Status: design draft. The reference implementation ("MaudeMode") runs today
on a Raspberry Pi driving a TV; this document describes the generalized
form, so that any agent — Muse, OpenClaw, a local model, a shell script —
can appear on a screen it does not own, under rules its owner sets.

The seam, in one sentence: **share the stage, not the agent.** The stage
owns the screen, the face, and the safety rules. The agent owns what it
says. Neither reaches inside the other.

---

## 1. Roles

- **Stage** — the program that owns a display (TV, monitor, tablet, e-ink
  panel). Renders the avatar, the content, and the permission indicators.
  Enforces every rule in §6 whether the agent likes it or not.
- **Agent** — anything that can make an HTTP request. Posts state and
  content; never touches the screen directly.
- **Owner** — the human. Chooses the avatar, the content kinds, the
  optional hardware, and the permission windows. The owner's configuration
  outranks anything an agent sends.

## 2. The core contract (all of it)

An agent talks to the stage with three small calls. Everything else in
this document is configuration or optional modules.

### POST /stage/item — "show this"
```json
{
  "kind": "fact",
  "text": "Honey never spoils. Archaeologists have tasted 3,000-year-old honey and found it edible.",
  "state": "speaking",
  "face": "happy",
  "hold_seconds": 600
}
```
- `kind` — one of the owner's configured content kinds (§4). Unknown kinds
  are rejected, not improvised.
- `text` — the item itself. The newest item is the headline; the stage
  keeps a short "earlier" list (the reference build keeps 4) and then
  forgets. The stage is not an archive.
- `state` — optional; one of the state vocabulary (§3). Defaults to
  `speaking` while an item is fresh, then the stage returns to `idle`
  on its own (§5).
- `face` — optional; a name from the avatar's declared expressions (§4).
  Unknown faces are ignored, not errored — an agent guessing wrong about a
  face should look neutral, not broken.
- `hold_seconds` — optional; how long this item may stay headline before
  the stage demotes it. The owner sets a maximum; requests above it are
  clamped.

### POST /stage/state — "I am doing this"
```json
{ "state": "listening" }
```
State without content: thinking, listening, needs-you. Same vocabulary,
same return-to-idle behaviour.

### GET /stage/state — "what is on screen now"
Returns the current state, the headline item, the earlier list, which
optional modules are live, and whether a permission window (§6) is open.
Agents that post blind are fine; agents that check first are better.

An MCP adapter may expose the same three operations as tools
(`stage_post_item`, `stage_set_state`, `stage_get_state`) for agents that
speak MCP — copying the tool shapes already proven by PHOS and
stackchan-mcp. The HTTP contract stays the core: cron jobs and shell
scripts are agents too, and they do not speak MCP.

## 3. State and face vocabulary

Deliberately small, and deliberately the vocabulary independent projects
keep converging on:

- **States:** `idle`, `speaking`, `listening`, `thinking`, `needs-you`,
  `asleep`
- **Faces (expressions):** `neutral`, `happy`, `sad`, `surprised`,
  `thinking`, `sleepy`

An avatar (§4) declares which faces it can actually draw. A stage must
never fake a face the avatar does not have.

Inline directives are a permitted convenience path for conversational
agents — a reply containing `[[face:happy]]` or `[emotion]` tags may be
translated by an adapter into the calls above (precedent: agent-faces,
ChatdollKit, Open-LLM-VTuber). The calls remain the contract; tags are
sugar.

## 4. The avatar plug-in

The avatar is data, not code: a folder of images plus a manifest.

**Frame tiers** (a stage must support Tier 0; higher tiers are additive):

- **Tier 0 — three frames:** eyes open / mouth closed, eyes closed
  (blink), mouth open. Blink is derived by the stage from frame 2, talk
  flapping from frame 3. *This is the reference build's current face.*
- **Tier 1 — the 4-frame matrix:** eyes {open, closed} × mouth {closed,
  open}, one canvas, one anchor point. Blink and speech derive cleanly.
- **Tier 2 — expression sets:** a folder per face name
  (`faces/happy/…`), stills or short sequences (precedent: Be More Agent,
  stackchan-mcp, SillyTavern sprite folders).

**Manifest** (`avatar.json`) — the one idea worth taking from VRM, without
VRM: the file declares its own terms.

```json
{
  "name": "Newsprint Editor",
  "canvas": [760, 687],
  "anchor": "center",
  "tier": 0,
  "frames": { "neutral": "frame-0.webp", "blink": "frame-1.webp", "talk": "frame-2.webp" },
  "faces": ["neutral"],
  "emotion_map": { "happy": "neutral" },
  "artwork": { "by": "…", "license": "…", "credit": "…" }
}
```
- `emotion_map` translates an agent's requested face to the nearest frame
  this avatar actually has — the owner's mapping, not the agent's hope.
- `artwork` is mandatory. A face is someone's art; its license and credit
  travel with it, the way VRM embeds license metadata in the model file.

**Not in the kit:** Live2D (its runtime cannot legally be bundled in an
open-source repo) and VRM/WebGPU rendering as a default (too heavy for
the small computers stages actually run on, and humanoid-only). A stage
may add them as local extras; the kit never requires them.

## 5. Content kinds are configuration

Kinds are declared by the owner, in the MagicMirror shape
`{kind, position, config}` — but as **data schemas rendered by the stage**,
not per-kind code (MagicMirror's module rot is what happens otherwise):

```json
{ "kind": "fact",  "label": "THE LATEST", "max_chars": 700, "default_hold_seconds": 900 }
{ "kind": "quote", "label": "THE LATEST", "max_chars": 700 }
{ "kind": "poem",  "label": "THE LATEST", "max_chars": 700 }
```
The reference build's kinds — fact, quote, poem, insight, idea, note —
are a starting set, not a standard. An owner who wants `score`,
`verse-of-the-day`, or `build-status` declares them; the stage renders
any kind the same way: label, timestamp, text, earlier list.

Display discipline borrowed from View Assist and Anthias: every item has
a duration, every screen has a **return-to-idle timeout**, and playlists
are `{asset, duration, schedule}` data — never code an agent can push.

## 6. Permission, presence, and the owner's rules

This section is the difference between a stage and a surveillance device,
and it is enforced by the stage, never by the agent's good behaviour.

- **Grant windows.** An agent may only initiate (speak unprompted, open a
  microphone) inside a window the owner granted — a start, an end, and
  what is allowed inside it. The reference build's model: the owner
  grants two hours; inside it, the agent may interrupt at will; when it
  closes, the agent goes back to speaking only when spoken to.
  **Expiry is the stage's job, enforced outside the agent's discretion.**
- **A ping arms the reply.** If the agent initiates, the same act opens
  the listening window for an answer. Making a human use a wake word to
  reply to a message the agent just sent is a design defect.
- **Indicators are physical truths, not UI promises.** Microphone live,
  camera live, and window-open each have a visible indicator rendered by
  the stage from the module's actual state — a light the software cannot
  fake because it *is* the software path.
- **Kill switch.** One action — a button, a word, a switch — ends all
  agent presence immediately: screen to idle, mic and camera closed,
  window revoked. It works while the agent is mid-sentence.
- **A log the owner can read.** Every initiation, every mic/camera open
  and close, every item posted, timestamped, in plain language. If it
  isn't in the log, it didn't happen; if it happened, it's in the log.
- **Bystanders.** A stage in a shared room shows its state to the room:
  who is present (which agent), whether it can hear, whether it can see.
  Consent of the people in the room is the owner's to arrange; the
  stage's job is to never make the room guess.

## 7. Optional hardware modules

Modules are adapters behind the stage's interfaces — never baked in —
because adapters survive and hard-wiring doesn't (see §8).

- **Speaker out.** The agent posts an item; the stage speaks it with its
  configured voice. The reference build's pipeline (synthesize to a file,
  play the file) is Tier 0: ugly, robust, replaceable.
- **Microphone in.** Behind a voice-assistant adapter. Rule: audio is
  captured **only inside an open window** (§6) — unarmed audio is
  discarded on arrival, never recorded, never transcribed. The reference
  build implements this today.
- **Camera.** Permission-gated stills before streams (precedent: PHOS's
  snapshot resource). First use is presence — *someone is here* — not
  recognition. Streams, when they exist at all, are a separate, explicit
  owner grant.

## 8. Known fault lines (from the prior-art survey, November 2026)

- **wyoming-satellite, the reference build's current voice-in component,
  is deprecated and archived**; its successor is Linux Voice Assistant.
  This is why §7 puts voice-in behind an adapter.
- Single-maintainer avatar libraries freeze (m5stack-avatar); the frame
  spec in §4 is therefore a file format, not a library.
- Platform modules rot when the core owns no minimal contract
  (MagicMirror) — §2 and §5 are the whole contract, on purpose.
- Projects die and survive by forkability (Mycroft → OpenVoiceOS). The
  kit is MIT-licensed so the fork is never in question.

## 9. What the reference build has, and what it doesn't (honest state)

Running today on the Pi: the page, the 3-frame face, the states, the
latest-item model with an earlier list, the speak pipeline, armed-window
listening with discard-when-unarmed, and a two-hour grant window used in
practice.

Not yet: the avatar as a plug-in (the face is baked into the page), kinds
as configuration (they are a fixed list in code), the MCP adapter, a
second agent ever having occupied the stage, and the camera as a stage
module (it exists separately, experimentally). The contract above is
written so each of those is a separable build step, in roughly that
order.

---

*Draft v0. Written to be argued with.*
