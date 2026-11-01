# Changelog

Notable changes to the House Screens system, newest first. Each entry is
dated the day the change went live in the house and was published here.

## 2026-11-01

### Added

- **Two-voice TV dashboard.** The dashboard now alternates in place between
  its two voices: the house board (floor plan, house pulse, headline) for
  45 seconds, then a full-screen feed board for 30–45 seconds, with a slow
  crossfade and a small footer indicator showing which voice is up. The
  feed board re-reads its data as the phase opens; if the feed is missing
  or stale, the phase is skipped entirely and the screen stays with the
  house.
- **Context feed.** A curated feed of the household's wider context —
  today's shape, things that need a person, project pulses, the public
  numbers — regenerated every 30 minutes. Items are tier-filtered at
  generation time into a household file and a bedroom file, so shared
  surfaces never receive bedroom-tier items. The feed has exactly two
  surfaces: the dashboard's feed phase and the briefing's "Since the last
  edition" box. It has no actuator: it cannot cast, interrupt, or change
  anything.
- **The Almanac.** The Morning Paper gains a rotating layer of verified
  local colour: an on-this-day item from art or science, a native plant or
  creature of the valley in its season, or a scrap of local history. Every
  item is checked against a named source before it prints; an edition with
  no verifiable item ships with fewer, never with invented ones.
- **Light-bars companion.** The TV's light bars now follow the ambient
  casts over the local network (the manufacturer's LAN API — no cloud
  account, no key). Each view has a recipe (warm white for the briefing,
  amber for the dashboard, teal for the jellyfish cam, violet for Dream
  Mode); recipe brightness is capped at 30% in code. A stopped cast turns
  the bars off; movie mode turns them off and keeps them off. The phone
  controller gained a Bars row (Off / Auto / Warm / Dim). A bars failure
  never delays or blocks a cast.
- **Refresh-on-cast.** Casting the dashboard or the floor plan with data
  older than 20 minutes now requests a background refresh without delaying
  the cast; the pages reload themselves when the fresh snapshot lands, so
  the screen heals to current data a few minutes later on its own.

### Changed

- **The Morning Paper, v4.** House and device data now appear exactly
  once, in a single compact strip under the columns. The "Needs your
  attention" box is personal items only — decisions and callbacks, never
  device states. The Almanac (above) takes the freed space.
- **Dream Mode, v3.** The visuals are now keyed to time on screen instead
  of time of day. The scene is already alive on first paint (roughly half
  the city standing, dome glowing, a poem up), deepens noticeably over the
  first minutes, and reaches full richness at about 11 minutes, then
  breathes on a plateau. Four movements — Arrival, The Unfurling, The
  Full Dome, The Deep Dome — count elapsed screen time. The clock's only
  remaining job is choosing the opening poem.
- **Gallery watcher, v2.** The idle-gallery watcher was rebuilt around a
  stricter rule: silence is not consent. It may start its own gallery only
  after 300 continuous seconds of positive idle proof (the ambient
  backdrop app confirmed on screen, player not playing), inside waking
  hours, with no movie-mode flag and no manual TV control in the previous
  three hours. It ships **disabled**, pending the owner's review of its
  test evidence.

### Removed

- **Standalone Feed view** — retired as a castable controller option; the
  feed lives on in the dashboard's feed phase and the briefing box.
- **AQI Sentinel view** — retired as a castable controller option. Air
  quality remains available as data to other surfaces; the page stays in
  the tree as reference.

## 2026-10-31 — Initial public release

The House Screens system as first published:

- **The Morning Paper** — a twice-daily broadsheet briefing (morning and
  evening editions) with the day's calendar, weather, and the house as a
  box score.
- **The House, Lit + House Pulse** — the TV dashboard: a glowing two-floor
  plan of the house, a sun arc, one diamond per solar inverter, and a
  pulse rail of live states.
- **Floor plan "Glow"** — the plan on its own, in the dark jewel palette.
- **Flights Overhead** — a radar scope the page draws itself from raw
  ADS-B data relayed through the Pi.
- **Tonight's Sky** — real ISS pass predictions computed on the Pi from
  orbital elements, plus the night's sky notes.
- **Storm Mode** — animated radar, a particle wind field, and full-screen
  weather-alert posters.
- **Jelly Cam** — a full-bleed aquarium camera page with translucent
  overlay cards.
- **Living Mycelium** — an organism that grows from the day's house
  signals, in purples and cyans, with blooms.
- **Dream Mode, v2** — an overnight city of light that built itself
  through five clock-driven acts, with a bank of verified public-domain
  poems.
- **Art galleries** — three rotating gallery variants for idle hours.
- **AQI Sentinel** — a standalone air-quality page (retired as a castable
  view on Nov 1; see above).
- **Phone controller** — the remote for every display and view, with
  per-device now-showing state.
- **The Pi services behind it all** — the page server, the casting
  service with its stop-and-wait discipline, the twice-daily briefing
  fetch-and-cast timers, and gallery watcher v1.
