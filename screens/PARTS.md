# Parts list

Everything the system runs on. Prices are stated only where they're
generic facts ("free"); hardware prices move and vary by region, so
they're deliberately not quoted.

## Hardware

| Part | Role | Notes |
|---|---|---|
| Raspberry Pi (4 or 5 class), on Ethernet | The caster: serves the pages, runs the controller, the watchers, the timers, and all casting | Ethernet strongly preferred over WiFi — it casts all day. A Pi 3 will do the job; the ISS math and page serving are light. Needs a decent power supply and a decent SD card (or USB boot): an unhappy PSU/SD is the #1 cause of "the Pi vanished" |
| Lenovo Smart Display 10 | Bedroom display (briefing, floorplan, sky) | **Discontinued** — used market only. Any Cast-enabled display works in its place; this one's 1920×1200 panel is why the bedroom pages are designed on a 1280×800 logical canvas |
| Google Nest Hub Max | Kitchen display (on-demand casting) | Its webview is the weakest of the three displays — fine for briefing/sky/AQI/gallery-class pages, slower on heavy canvas |
| Chromecast / Google TV (on the living-room TV) | TV target (dashboard, gallery, storm, dream) | 1920×1080. A TV with built-in Cast works the same |
| The network | — | Pi and all displays must share one LAN (casting is local discovery). The controller page is LAN-only by design |

Optional, not required: a rooftop SDR receiver if you want a local ADS-B
feed instead of the public aggregator.

## Software & services

| Piece | Role | Cost/keys |
|---|---|---|
| Home Assistant | The house's state (lights, vacuums, sensors, solar) — read by the snapshot job | Free, self-hosted. Its optional cloud remote route is one way for an off-Pi job to read states; a LAN route works too |
| catt + DashCast | The casting mechanism (`catt cast_site` loads a URL on a Cast device) | Free, open source |
| Python 3 + `sgp4` (pure-python) | ISS pass prediction on the Pi — no ephemeris downloads, no keys | Free |
| pychromecast | Gallery watcher's view of Chromecast state | Free, open source |
| Leaflet (vendored, in `pages/storm-assets/`) | Storm Mode's radar map | Free, open source (BSD) |
| A static file host for one briefing file | The edition routine publishes a single HTML file to a fixed address; the Pi fetches it on a timer | The original uses a Google Drive file updated in place; any stable URL works |

## Free data APIs (no keys anywhere in this system)

| API | Feeds |
|---|---|
| Open-Meteo (forecast + air-quality) | Weather for the briefing, Tonight's Sky, AQI Sentinel, Storm wind field, Mycelium vigor, sunrise/sunset for the dashboard's sun arc |
| RainViewer | Storm Mode's animated radar tiles |
| NWS — api.weather.gov | Storm Mode's alert poster + warning polygons (US only) |
| NOAA NESDIS (GOES GeoColor sectors) | Storm Mode's planet window |
| CelesTrak (TLE) | ISS orbital elements for `iss-passes.py` |
| adsb.lol | Aircraft positions for Flights Overhead, Mycelium, Dream Mode (via the Pi's proxy — the API sends no CORS header) |
| wheretheiss.at | The ISS's live position line on Tonight's Sky |
| YouTube (public livestream embed) | Jelly Cam — any public aquarium/nature cam ID works |
