# OPERATIONS.md — running the house screens day to day

*The instruction pack for keeping every display correct over time. It is
written generically: every address, coordinate, and name is a placeholder
(see the CONFIGURING table in this system's README, `../README.md`).*

**How to use this pack:** §1–§3 describe the system, §4 the standing
routines, §5 what to do when something breaks, §6 the boundaries to
respect, §7 the checklist for changing any page.

---

## 1. System map

**Caster:** a Raspberry Pi on Ethernet at the router. LAN `CASTPI_LAN_IP`.
Serves the pages from a static directory at `http://CASTPI_LAN_IP:8080/`
(a systemd service running a plain static file server). Phone control at
`http://CASTPI_LAN_IP:8081` (`cast-control.py`): per-device buttons for
every view + the ADS-B proxy endpoint `GET :8081/adsb` (upstream cached
12 s, CORS open). `POST /cast {device, view}`; actions logged to
`~/cast-control.log`. The controller also answers on bare port 80 with a
redirect to :8081 (bookmarks lose ports; the controller shouldn't).

**Displays (examples — yours will differ):** a bedroom smart display
(1280×800 logical design canvas), a living-room TV via Chromecast
(1920×1080), a kitchen smart display (manual casting only; its webview is
the weakest, so heavy canvas pages may run slowly there).

**Cast discipline (load-bearing):** before every cast, STOP the current
cast and wait ~10 s, or DashCast stalls. Never cast over a screen that a
standing rule is managing (the TV's gallery, §3) without the owner's go —
a manual cast fights the rule.

**Source of truth for every page:** the copies in `pages/`. The Pi's
served directory is a deployment target, never an editing surface.
Edit local → QA → deploy → verify (§7).

| Page | What it is | Data sources |
|---|---|---|
| briefing (deployed as the server root) | **The Morning Paper** briefing (AM paper / PM Evening Edition) | Baked per edition (calendar + weather + house snapshot, frozen at compose time) — §4A |
| `dashboard.html` | TV dashboard "The House, Lit + House Pulse" | Smart-home states **baked** by the snapshot job (§4C); sun arc from the client clock with per-date sunrise/sunset constants |
| `floorplan.html` | Floorplan "Glow" | Same baked-states mechanism as the dashboard |
| `tonights-sky.html` | Tonight's Sky | Weather API at load; Moon computed in-page; ISS live position from a public ISS API; **ISS passes from `iss.json`** (§3) |
| `iss.json` | ISS pass predictions, 4 days | Generated on the Pi from CelesTrak TLE + SGP4 (`iss-passes.py`) |
| `flights-overhead.html` | Flights Overhead (self-rendered radar) | ADS-B aggregator via the Pi's `:8081/adsb` proxy, polled 15 s |
| `aqi-sentinel.html` | AQI Sentinel | Air-quality API — fetch at load |
| `storm-mode.html` | Storm Mode (radar / wind / planet scenes + alert poster) | Radar tiles (5 min), gridded wind (hourly), satellite sector image (5 min), weather-service alerts (60 s) |
| `mycelium.html` | Living Mycelium | Aircraft count + weather at load; organism skeleton seeded by date |
| `dream-mode.html` | Dream Mode "The Pleasure-Dome" | Aircraft poll 60 s; acts/phases from the clock; public-domain poem bank baked into the page |
| `jelly-cam.html` | Jelly Cam (full-bleed) | A public livestream embed; facts card baked |
| `gallery*.html` | TV art gallery (mixed / places / art) | Static local images in `img/` + `img-art/` (not shipped — supply your own); client-side rotation |

---

## 2. Refresh cadence — the table that runs the system

| Page / data | Cadence | Staleness risk | Owned by |
|---|---|---|---|
| Briefing | Baked per edition; Pi fetches at :50, casts at :00, twice daily | An edition nobody composes = yesterday's paper re-cast | Edition routine (§4A) + Pi timers |
| Dashboard / floorplan states | Snapshot re-render every ~2 h | **Highest in the system if the job stops** — the pages say "as of" honestly, but they rot | Snapshot job (§4C) |
| Dashboard sun arc | Renderer recomputes sunrise/sunset for the render date | A hard-coded pair of times is wrong by ~1 min/day and by an hour across a clock change | §4C render step |
| Tonight's Sky weather | At page load (a recast reloads) | Hours-old cloud data on a very long cast — add an hourly in-page refetch if that matters to you | Page |
| ISS passes `iss.json` | Nightly + at boot | TLE ages gracefully; the page refuses data > 36 h old and says so | Pi timer |
| Flights | 15 s poll, 12 s proxy cache | None material | Page + proxy |
| AQI / Mycelium signals | At load | Ages on long casts — same optional refetch fix | Page |
| Storm Mode | Radar 5 min · alerts 60 s · satellite 5 min · wind hourly | None material | Page |
| Dream Mode | Aircraft 60 s; everything else from the clock | None material | Page |
| Gallery images | Static | Only stale when the collection should change | Human curation |
| Jelly Cam | Live stream | Dies only if the streamer restarts it under a new ID | Human check when it breaks |

---

## 3. Automation inventory — what runs, where, and how to check it's alive

### On the caster Pi (systemd)

| Automation | Schedule | Does | Check alive | Log |
|---|---|---|---|---|
| Page server service | Always | Serves the pages directory on :8080 | `systemctl is-active <unit>` · `curl -s -o /dev/null -w "%{http_code}" localhost:8080/` | journal |
| `cast-control.service` | Always | Phone control :8081 + `/adsb` proxy + port-80 redirect | `curl localhost:8081/` → 200 · `curl localhost:8081/adsb` → JSON | `~/cast-control.log` |
| Briefing fetch timer | 06:50 + 18:50 daily | Downloads the edition file; swaps it in only if it contains "Briefing" | `systemctl list-timers` | `~/briefing-fetch.log` |
| Briefing cast timer | 07:00 + 19:00 daily | Stop, sleep 10, cast the briefing to the bedroom display | `systemctl list-timers` | `~/cast-briefing.log` |
| Gallery watch timer | Every 30 s | **The gallery idle rule:** TV on + Chromecast idle 3 min, 06:00–23:00 → cast the mixed gallery; recast every 8 min; yields to other content; stops on TV-off / quiet hours | `systemctl list-timers` · log tail shows recent polls | `~/gallery-watch.log` (+ state file). Known blind spot: the TV's own built-in apps are invisible to a Chromecast-state watcher |
| ISS passes timer | ~18:00 daily + after boot (Persistent) | CelesTrak TLE → SGP4 → writes `iss.json` (4 days, passes > 10°; visible = sunlit at peak AND sun < −4° at the observer). On failure it exits non-zero and leaves the old file — staleness is detectable, never silent | `systemctl list-timers` · read `generated_at` in `iss.json` | journal |

### On the caster Pi (user crontab)

| Automation | Schedule | Does | Log |
|---|---|---|---|
| `cast-keepalive.py` | `*/8 * * * *` (script enforces 06:00–23:00) | Re-casts the bedroom display's last-chosen view (DashCast sessions expire). Other displays excluded on purpose | `~/cast-keepalive.log` |

### Off the Pi

- The **edition routine** (§4A) and the **snapshot job** (§4C) run on a
  separate host (an always-on machine, or wherever your automation/agent
  lives). Their credentials live **there** — never on the Pi, never in a
  script file on the Pi.
- The **health check** (§4B) also runs off-Pi, so a dead Pi can't hide.

---

## 4. Standing routine specs

### Spec A — BRIEFING EDITIONS (daily, two runs)

**Schedule:** run at ~06:05 and ~18:05 local (editions finished by :30;
the Pi fetches at :50 and casts at :00 — the buffer is the point).

**Task:**
> Compose today's briefing edition and publish it to the briefing file
> **in place** (same file ID / URL every time — the Pi fetches a fixed
> address; never publish to a new file).
> - **AM run** → the Morning Edition (light paper palette). **PM run** →
>   the Evening Edition (dark palette). Format authority:
>   `pages/briefing-template.html` — masthead + full date + edition line
>   on a double rule; serif lede headline whose key phrase carries the
>   highlight; columns: Today / Weather / Needs Your Attention (boxed
>   notice) / The House (mono box score); footer "Tomorrow —" line.
> - **Data recipe, all four, every edition:** (1) **Calendar** — the day's
>   calendar (untitled busy blocks are meetings — say so, never invent
>   titles); (2) **Weather** — a public weather API for your coordinates:
>   today's high/low, condition, sunset, tonight's risk, tomorrow's
>   headline. Use a maintained public feed, not a personal weather
>   station you can't vouch for; (3) **House exceptions** — a read-only
>   smart-home snapshot (§4C's read route): lights-on count, devices
>   offline (name the vacuum plainly when it's down), batteries low,
>   anything newly unavailable vs the last edition; (4) **Day notes** —
>   clock changes, holidays, quiet-hours-relevant events.
> - **Truth rules:** every number on the page comes from one of those four
>   sources in this run. If a source fails, the edition says less — it
>   never carries yesterday's figures forward as if fresh. The box score
>   is labelled with its snapshot time.
> - **Publish + verify:** update the file in place; then **re-download it
>   and compare checksums** against the local copy. Only a matching
>   checksum counts as published. Do not cast anything yourself — the
>   Pi's timers do that.
> - **Failure:** if composition or publishing fails, leave the previous
>   edition in place (a stale paper beats a broken one) and notify the
>   owner what failed and which edition is affected.

### Spec B — DAILY HEALTH CHECK (daily ~09:00, silent when healthy)

> Health-check the screens system. Report **only on failure or anomaly**;
> complete silence when healthy.
> 1. SSH to the caster Pi. Unreachable → that's a report (see §5 first — a
>    reboot may already have fixed it; verify twice, minutes apart,
>    before declaring an outage; check more than one route if you have
>    them). **Never conclude "down" from one failed connection.**
> 2. Page server + cast-control services = active; `systemctl list-timers`
>    shows fetch, cast, gallery-watch, and ISS timers all with a NEXT time.
> 3. `curl localhost:8080/` = 200 and `curl localhost:8081/` = 200 from the Pi.
> 4. `iss.json` `generated_at` is < 36 h old (expect < 24 h).
> 5. The served briefing page's mtime is from today's or yesterday's fetch
>    window; the fetch log's last line is a successful update.
> 6. Tail the gallery-watch and keep-alive logs — recent entries, no
>    repeating error pattern.
> 7. Pi disk usage under 85%.
> Any failure = one plain-language message: what failed, since when (if
> known), what still works, and what §5 says to do about it.

### Spec C — SNAPSHOT-REFRESH for dashboard + floorplan (every ~2 hours)

**Why it exists:** two pages show smart-home state. Baking the state into
static pages is deliberate (cast webviews are weak; static pages never
hang on a live API), but baked state rots — so a job re-renders just the
states, on a cadence, and the pages label their "as of" time.

**Read route:** read states **read-only** from your smart-home platform
(e.g. Home Assistant's REST `GET /api/states`, or its websocket API) from
the off-Pi host, using a credential that lives with that host's secret
store. **Never** copy the credential to the Pi, into the renderer script,
or into an env file in this repo. If your platform offers scoped
read-only tokens, prefer one.

**Entity map:** yours to write — one row per page element: the page key,
the platform entity that feeds it, and notes (e.g. "this one is a
`switch`, not a `light`"). Keep the aggregate lists explicit too: the
dashboard's "N lights awaiting refresh" line counts `unavailable` among a
named list, recomputed every run, so the number falls on its own when
the devices are fixed.

**Mapping rules:** `on` → on; `off` → off; `unavailable`/`unknown` →
offline; a vacuum in any real state shows its state word (docked /
cleaning). Headline + box score are **computed** from the snapshot
(lights-on count, offline count, batteries-low count) — never hand-typed.

**Renderer design:** (1) read states; (2) regenerate the two pages,
replacing ONLY the states block (wrap each page's `DEVICES` object in
`/*SNAPSHOT:BEGIN*/ … /*SNAPSHOT:END*/` markers so runs replace exactly
that block), the "as of" line, and the computed headline counts;
(3) recompute the dashboard's sun-arc sunrise/sunset constants for the
render date from the weather API (this keeps the arc correct across
clock changes); (4) QA-screenshot both pages at their real sizes and
eyeball them; (5) deploy to the Pi's served directory; verify checksum +
HTTP 200; (6) **never cast anything** — the keep-alive and the phone
control pick up new files on their own cycles.

**Guardrails:** read-only — the job reads states, never calls a service.
If the read fails or returns implausibly few entities, **leave both pages
untouched** and let the health check surface it — a stale-labelled page
beats a half-rendered one. Apply sanity rules before printing any derived
figure (an energy total that equals its own 7-day sum is an integration
quirk, not a fact): when a field smells wrong, print less.

**Schedule:** every 2 hours inside waking hours is plenty.

---

## 5. Failure + recovery runbook

**Pi unreachable (SSH times out / :8080 down).** A Pi that hangs usually
reboots or gets power-cycled and *everything recovers by itself* — all
services are systemd-enabled and the keep-alive is a user cron. So:
(1) wait 10 minutes and retry — a reboot may already have fixed it;
(2) try a second route if you have one (LAN vs. overlay network);
(3) if still down, it's physical: power supply and SD card are the
suspects, in that order — someone at the house power-cycles the Pi
(unplug 10 s, replug); (4) after it returns, run §4B's checks manually
and confirm all timers show NEXT times. **Never conclude "down" from one
failed connection attempt** — a route-specific failure looks exactly like
a dead Pi from one side.

**A page shows wrong/stale data.** Find its row in §2's table and check
the owning routine before blaming the page. Baked pages are wrong by
design until their routine runs. Client-polled pages: check the upstream
from the Pi with `curl` before editing code.

**Upstream dependencies (who can break what):**
- **ADS-B aggregator** — flights page, Mycelium/Dream vigour. The Pi proxy
  caches 12 s; on failure the pages degrade to labelled fallbacks.
- **CelesTrak** — `iss.json` only. A failed nightly run leaves yesterday's
  file; the page refuses it at 36 h and says predictions are unavailable.
  TLE data stays accurate for days; a week of failures is a chore, not an
  emergency.
- **Weather / air-quality APIs** — Tonight's Sky, AQI, Storm wind,
  Mycelium, briefing weather, §4C sunrise/sunset. Pages show labelled
  specimen fallbacks on failure.
- **Radar tile provider** — Storm radar scene only; the other scenes
  carry the page.
- **National weather service alerts API** — Storm alert poster + polygons.
- **Satellite imagery (NOAA)** — Storm planet scene image.
- **ISS position API** — Tonight's Sky's live-position line only (passes
  are independent — CelesTrak).
- **Livestream host (YouTube)** — Jelly Cam; if the streamer restarts the
  stream under a new ID, update the embed ID in the page by hand.
- **Briefing file host (Drive)** — the briefing fetch. The fetch script
  fails safe: it replaces the served page only after a sanity grep
  passes, so the house keeps the previous edition.
- **Smart-home platform route** — §4C's reads. On auth failure, fix the
  credential through its normal recovery flow; do not mint ad-hoc tokens.

**Rollback.** Keep the predecessor of every replaced page (locally beside
the current file; on the Pi as a `*-backup.html` in the served directory).
Rollback = copy the backup over the live name + checksum/HTTP verify (§7).
No cast needed — keep-alive/recasts pick it up.

---

## 6. Boundaries worth adopting

- **Credentials live with the job that uses them** — on the host that runs
  the job, in its secret store. Not on the Pi, not in scripts, not in this
  repo. Smart-home admin (users, tokens, integrations, bridges) is a
  human decision, never a side effect of a page change.
- **Spending is the owner's explicit, per-purchase approval.** Nothing in
  this pack authorizes buying anything.
- **Don't credit sources you can't vouch for.** If a sensor is broken but
  still reporting, every page must stop citing it until it's repaired —
  a confident stale number is worse than an honest gap.
- **Standing display rules belong to the owner.** The gallery idle rule,
  quiet hours, and what may interrupt what are household decisions. Code
  that fights a standing rule is a bug even when it works.
- **Instance data stays home.** LAN addresses, file IDs, coordinates, and
  household specifics never go into a public repo or a shared doc — this
  pack uses placeholders for exactly that reason.

---

## 7. When you change a page — checklist

1. Edit the copy in `pages/`, never the Pi copy. Update the page's header
   comment if behaviour, data sources, or caveats changed — the next
   maintainer reads those first.
2. QA-screenshot at the page's real sizes (1920×1080 TV / 1280×800
   logical smart display); mock any fetch your sandbox can't reach with a
   realistic fixture, and say so in your report. Eyeball the shot —
   layout regressions (overlaps, clipped cards) are yours to catch.
3. Deploy: copy to the Pi's served directory under the page's live name.
4. Verify: served checksum == local checksum, and `curl
   localhost:8080/<name>` from the Pi returns 200. Both, every time —
   "deployed" without both checks is a claim, not a fact.
5. If the page is new, add it to `cast-control.py`'s view list (deploy +
   restart the service + verify the button in the served page) and add
   rows to §1–§2 of this pack.
6. Do **not** cast it to a screen "to test" — offer the preview or the
   phone-control button instead. Exception: a cast the owner explicitly
   asked for — stop-first, and restore what was showing.
7. Record durable changes (new automations, new rulings, broken things)
   in this pack the same day. A fact that lives only in a chat transcript
   is already forgotten.
