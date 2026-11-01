# House Screens — an ambient display system for a home

*The screens system of [MaudeAtHome](../README.md) — one of the systems an
agent keeps running in a house, each in its own subfolder. This folder is
the displays: what they show, what runs them, and how they stay correct.*

A house full of calm screens. Not dashboards you *use* — pages that live on
the displays already in the rooms, each one doing a single job beautifully:

- **The Morning Paper** — a twice-daily broadsheet briefing (morning and
  evening editions) composed from the day's calendar, the weather, and a
  snapshot of the house itself, and cast to the bedroom display at 7 AM / 7 PM.
- **The House, Lit + House Pulse** — a TV dashboard whose hero is a glowing
  two-floor plan of the house (rooms light up with their real state), beside
  an energy rail: a sun arc and one diamond per solar inverter.
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
- **AQI Sentinel** — the page *is* the air-quality reading: the whole screen
  takes the colour of the current AQI category.
- **Jelly Cam** — a full-bleed aquarium livestream with one quiet facts card.
- **The Gallery** — when the TV sits idle, it becomes art: local landmarks
  and famous paintings, with small history cards that fold away so the art
  stays clear.
- **Living Mycelium** — an organism that grows from the day's house signals
  (aircraft overhead set its vigour; rain speeds its pulses). Its skeleton
  is seeded by the date, so the same organism lives all day.
- **Dream Mode — The Pleasure-Dome** — overnight, a city of light builds
  itself on a dark shore in five acts (real flights overhead "carry in" the
  parts), while verified public-domain dream poems surface as events; before
  dawn the city dissolves and the briefing takes the screen.

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
  because humans bookmark `http://CASTPI_LAN_IP/` without the port.
- **Scheduled casts** (systemd timers on the Pi): fetch the briefing
  edition at :50, cast it at :00, morning and evening. A user-cron
  keep-alive re-casts the bedroom display's last-chosen view every 8
  minutes (DashCast sessions expire), 06:00–23:00. The TV is deliberately
  *not* keep-alived — it belongs to the gallery idle rule.
- **The gallery watcher** polls every ~30 s: TV on + Chromecast idle for
  3 minutes inside 06:00–23:00 → cast the gallery; recast every 8 minutes;
  yield instantly and silently when someone plays something else; stop on
  TV-off or quiet hours.

## Refresh cadence (who owns what)

| Data | Cadence | Mechanism |
|---|---|---|
| Briefing content | 2 editions/day | an agent routine composes + publishes; Pi fetches/casts on timers |
| Dashboard/floorplan states | every ~2 h | snapshot job re-renders the baked states block |
| Dashboard sun arc | daily | renderer recomputes sunrise/sunset for the date |
| ISS passes | nightly | `iss-passes.py` on the Pi (fresh TLE, 4-day horizon) |
| Flights | 15 s poll (12 s proxy cache) | page + Pi proxy |
| Storm radar / GOES | 5 min | page |
| Storm alerts | 60 s | page |
| Storm wind field | hourly | page |
| Tonight's Sky weather, AQI, Mycelium signals | at load (a recast reloads; add an in-page refetch timer if a page sits for hours) | page |
| Dream Mode flights | 60 s poll | page |
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
  routine specs, failure runbook, and the change-a-page checklist.
- `previews/` — screenshots of two pages (Storm Mode's planet window;
  Dream Mode's inhabited city).

## A note on the poems

Dream Mode's poem fragments are public-domain texts (Coleridge, Yeats,
de la Mare, Li Bai in a 1922 translation, and friends), each verified
against a public-domain source before inclusion. If you add your own,
verify them the same way — the famous English translations of Bashō and
Issa, for instance, are *not* public domain.
