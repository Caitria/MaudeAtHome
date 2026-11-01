# House Screens — an ambient display system for a home

*The screens system of [MaudeAtHome](../README.md) — one of the systems an
agent keeps running in a house, each in its own subfolder. This folder is
the displays: what they show, what runs them, and how they stay correct.*

A house full of calm screens. Not dashboards you *use* — pages that live on
the displays already in the rooms, each one doing a single job beautifully:

- **The Morning Paper** — a twice-daily broadsheet briefing (morning and
  evening editions) composed from the day's calendar, the weather, and a
  snapshot of the house itself, and cast to the bedroom display at 7 AM / 7 PM.
  House data appears exactly once, in a single strip; the attention box is
  for personal items only. Below them sits **the Almanac** — a rotating
  delight: an on-this-day in art or science, a native plant in its season,
  a scrap of local history, every fact verified against a named source
  before it ships (the bank is `docs/ALMANAC.md`).
- **The House, Lit + House Pulse** — a TV dashboard whose hero is a glowing
  two-floor plan of the house (rooms light up with their real state), beside
  an energy rail: a sun arc and one diamond per solar inverter. The page
  speaks in **two voices**: it alternates in place between the House board
  and a full-board feed phase (below), each getting the whole screen in
  turn. Behind the TV, a pair of light bars follows its casts — warm for
  the briefing, amber for the dashboard, dark for movies.
- **Floorplan (Glow)** — the same glowing plan, full-screen, for the bedroom.
- **Tonight's Sky** — will tonight be worth going outside? A GO / WAIT / SKIP
  verdict from real cloud cover, the Moon drawn at tonight's true phase,
  constellations, the ISS's live position — and *real* ISS pass predictions,
  computed nightly on the Pi, including the honest cases ("it crosses at
  11:43 PM, but in Earth's shadow — not visible").
- **Flights Overhead** — a self-rendered radar scope of the aircraft above
  the house right now (the embedded-map version never loaded in a cast
  webview, so the page draws the sky itself from raw ADS-B data).
- **Storm Mode** — weather as theatre: animated radar, a particle wind
  field, a live satellite "planet window", and a full-screen typographic
  poster that interrupts everything when a real weather alert lands.
- **The Feed** — not a page of its own: a curated stream of short context
  items (the day, the open loops, the projects, the people), rebuilt every
  ~30 minutes and tier-split at generation so shared screens only ever
  receive the household tier. It surfaces inside the dashboard's second
  phase and as the Paper's "Since the last edition" strip — and it has no
  actuator: it can inform a screen, never interrupt one.
- **Jelly Cam** — a full-bleed aquarium livestream with one quiet facts card.
- **The Gallery** — when the TV sits idle, it becomes art: local landmarks
  and famous paintings, with small history cards that fold away so the art
  stays clear.
- **Living Mycelium** — an organism that grows from the day's house signals
  (aircraft overhead set its vigour; rain speeds its pulses). Its skeleton
  is seeded by the date, so the same organism lives all day.
- **Dream Mode — The Pleasure-Dome** — a city of light builds itself on a
  dark shore (real flights overhead "carry in" the parts), while verified
  public-domain dream poems surface as events. The dream runs on **time on
  screen**, not time of day: the first paint is already alive — nearly half
  the city standing — and four elapsed movements deepen it over ~12
  minutes, whenever it is cast.

One mode was retired: **AQI Sentinel** (the whole screen as an air-quality
reading) — the air now gets a line in the feed instead of a mode of its
own. The page file remains in `pages/` for reference; the controller no
longer offers it. The controller's twelve views are: Briefing, Dashboard,
Floorplan, Tonight's Sky, Storm Mode, Flights Overhead, Jelly Cam,
Living Mycelium, Dream Mode, and the three Galleries.

## Design principles

1. **Subject pages wear their subject.** A night-sky page *is* the night
   sky; an air page *is* the air. Full-bleed imagery with translucent
   overlay cards — no generic dashboard skin on top of a subject.
2. **Information pages get a household skin.** Briefing and dashboard use
   paper and frosted glass: calm, warm, legible from across the room.
3. **Data honesty.** Pages label what is live, what is baked, and what is a
   labelled specimen/fallback. A page never invents a number: if a feed
   fails, it says less, or shows its fallback *labelled as one*. Baked
   snapshots carry their "as of" time on screen.
4. **Calm-tech cadence.** Nothing refreshes faster than its subject
   changes; nothing moves faster than a drifting cloud unless it's an
   alert. The one loud thing in the system is a real weather warning.
5. **Events, not mush.** The dream's poems appear for 30 seconds every few
   minutes and are gone. The mycelium's blooms open over half a minute.
   Ambient ≠ continuously animated.

## Architecture

```
                 ┌───────────────────────────── caster Pi ─────────────────────────────┐
                 │  ~/briefing/  static pages served on :8080 (python http.server)     │
  free data ───► │  cast-control.py  phone controller :8081 (+ /adsb proxy, port-80    │
  APIs           │                   redirect) · keep-alive cron · gallery watcher     │
  (no keys)      │  iss-passes.py ─► iss.json (nightly systemd timer)                  │
                 │  fetch-briefing.sh ◄── briefing edition file (Drive, updated in     │
                 │                        place by the edition routine)                │
                 └──────┬───────────────────────┬──────────────────────┬───────────────┘
              catt/DashCast              catt/DashCast           catt/DashCast
                        ▼                       ▼                      ▼
                 Bedroom display        Living-room TV        Kitchen display
                 (briefing 7 AM/PM,     (dashboard, gallery    (on-demand)
                  keep-alive)            idle rule, dreams)

  Home Assistant ──(read-only snapshot, every ~2 h)──► re-renders the baked
  states in dashboard.html + floorplan.html. The credential lives with the
  agent host that runs the snapshot job — never on the Pi, never in a file.
```

- **Casting** is done with [catt](https://github.com/skorokithakis/catt)
  driving the DashCast receiver. One inviolable rule: **stop the current
  cast and wait ~10 s before every new cast**, or DashCast stalls.
- **The phone controller** (`pi/cast-control.py`) serves a tap-to-cast page
  per display, shows what each screen is currently showing, and proxies the
  ADS-B feed (the upstream sends no CORS header, so cast webviews can't
  fetch it directly). It also answers on bare port 80 with a redirect —
  because humans bookmark `http://CASTPI_LAN_IP/` without the port. Three
  companions ride on it: a **movie mode** (one toggle that darkens the TV
  light bars and vetoes the gallery watcher), the **light-bars companion**
  (`pi/govee.py` — after a successful TV cast the bars behind the TV take
  the view's light recipe over Govee's local LAN API; a stop, or movie
  mode, turns them off; brightness from the controller is hard-capped),
  and **refresh-on-cast** (a dashboard/floorplan cast whose baked data is
  stale drops a request flag; an off-Pi watcher refreshes the snapshot in
  the background and the on-screen page reloads itself — the cast never
  waits).
- **Scheduled casts** (systemd timers on the Pi): fetch the briefing
  edition at :50, cast it at :00, morning and evening. A user-cron
  keep-alive re-casts the bedroom display's last-chosen view every 8
  minutes (DashCast sessions expire), 06:00–23:00. The TV is deliberately
  *not* keep-alived — it belongs to the gallery idle rule.
- **The gallery watcher** (v2) polls every ~30 s but may take the TV only
  on *positive* proof of idleness: TV on, the Chromecast's own running app
  is exactly its Backdrop screensaver, nothing playing — sustained 5
  minutes inside 06:00–23:00, with movie mode off and no manual TV control
  in the last 3 hours. Silence is not consent: an unknown app state is a
  refusal, with the reason logged. It maintains only a gallery it started.
  **As shipped here, its timer is disabled** — v1 once cast over a movie
  playing outside the Chromecast, and v2 arms only when the owner says so
  (see `docs/OPERATIONS.md` §3).

## Refresh cadence (who owns what)

| Data | Cadence | Mechanism |
|---|---|---|
| Briefing content | 2 editions/day | an agent routine composes + publishes; Pi fetches/casts on timers |
| Dashboard/floorplan states | every ~2 h, and on cast when stale | snapshot job re-renders the baked states block; refresh-on-cast covers the gap (controller flag → off-Pi watcher → pages reload themselves) |
| Context feed | every ~30 min | off-Pi generator writes the two tier files; surfaces poll / re-read on phase entry |
| Dashboard sun arc | daily | renderer recomputes sunrise/sunset for the date |
| ISS passes | nightly | `iss-passes.py` on the Pi (fresh TLE, 4-day horizon) |
| Flights | 15 s poll (12 s proxy cache) | page + Pi proxy |
| Storm radar / GOES | 5 min | page |
| Storm alerts | 60 s | page |
| Storm wind field | hourly | page |
| Tonight's Sky weather, Mycelium signals | at load (a recast reloads; add an in-page refetch timer if a page sits for hours) | page |
| Dream Mode flights | 60 s poll; the visual arc runs on elapsed time since load | page |
| Gallery images | static | curated by hand |

## CONFIGURING — every placeholder in the tree

Nothing in this system contains a real address, coordinate, or name from
the house it was built in. Search the tree for `YOUR_` / `CASTPI_` tokens:

| Placeholder | Where | Set it to |
|---|---|---|
| `YOUR_LAT`, `YOUR_LON` | most pages + `pi/` scripts | your home's latitude/longitude (they ship as `0.0` — pages will ask the APIs about the Gulf of Guinea until you set them) |
| `CASTPI_LAN_IP` | controller, pages that call the ADS-B proxy, shell scripts | the Pi's LAN address (a private RFC-1918 address on your network) |
| `YOUR_TOWN` | page kickers/captions | your town's name, as display text |
| `HOUSE_NAME` | dashboard/floorplan/briefing mastheads | whatever your house is called (or just "Home") |
| `YOUR_TIMEZONE` | `pi/iss-passes.py` (`TZ`) | your IANA timezone |
| `YOUR_BRIEFING_FILE_ID` | `pi/fetch-briefing.sh` | the Drive file ID of *your* briefing file (or replace the fetch with your own publishing route) |
| `TV_LAN_IP` | `pi/gallery-watch.py` | your TV's LAN address (Samsung local API) |
| Display cast names | `pi/cast-control.py`, `pi/cast-briefing.sh`, `pi/cast-keepalive.py` | your displays' cast names ("Bedroom display", "Living Room TV", "Kitchen display" are the examples) |
| Home Assistant entities | dashboard/floorplan `DEVICES` + the snapshot job | your own entity IDs (see `docs/OPERATIONS.md`) |
| GOES sector | `pages/storm-mode.html` (`SAT`) | your GOES-East/West sector image |

Gallery images are **not included**: drop your own files into
`pages/img/` (places) and `pages/img-art/` (art) using the filenames the
gallery pages reference, or edit the lists in those pages.

## What you'd adapt

- **The floorplan** is data (a `ROOMS` array), not a drawing: rearrange the
  rectangles to your house, point the `DEVICES` entries at your lights.
- **The briefing routine** (calendar + weather + house snapshot → one static
  page, published to a fixed file the Pi fetches) is described as a spec in
  `docs/OPERATIONS.md`. In the original house an AI agent runs it; a cron +
  template script works too, with less charm and the same honesty rules.
- **No Home Assistant?** The dashboard/floorplan degrade to pretty static
  portraits; everything else is independent of it.
- **Displays**: any Cast-enabled display or Chromecast works. Weak webviews
  (small smart displays) will struggle with the heavy canvas pages —
  flights and mycelium are the demanding ones.

## Layout of this system

- `pages/` — the screens themselves (static HTML; `storm-assets/` is a
  vendored Leaflet for the storm page). Serve this folder from the Pi.
- `pi/` — the caster Pi's programs (controller, keep-alive, gallery
  watcher, briefing fetch/cast, ISS passes). See `pi/README.md`.
- `docs/OPERATIONS.md` — the operations pack: system map, cadence table,
  routine specs (briefing editions, health check, snapshot refresh, the
  context feed), failure runbook, and the change-a-page checklist.
- `docs/ALMANAC.md` — the briefing's almanac bank: the verified delights
  the Paper rotates through, with their sources.
- `previews/` — screenshots of two pages (Storm Mode's planet window;
  Dream Mode's inhabited city).

## A note on the poems

Dream Mode's poem fragments are public-domain texts (Coleridge, Yeats,
de la Mare, Li Bai in a 1922 translation, and friends), each verified
against a public-domain source before inclusion. If you add your own,
verify them the same way — the famous English translations of Bashō and
Issa, for instance, are *not* public domain.
