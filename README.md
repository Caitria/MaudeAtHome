# MaudeAtHome

An agent-kept home. This repository collects the ambient systems one agent
runs in a house — the pages that live on its displays, and (separately, in
its own place) a voice in its rooms. Each system is self-contained in its
own subfolder, with its own description, parts list, and operations pack,
so any one of them can be read, borrowed, or rebuilt on its own.

Nothing here is a product. It's a working household, written down: what the
screens show at 7 AM, how the house knows tonight's ISS pass is in shadow,
why the TV is never allowed to interrupt a movie.

## Systems

### [`screens/`](screens/) — House Screens

A house full of calm screens: a twice-daily broadsheet briefing (the
Morning Paper — house data stated once, personal items up front, and a
rotating verified Almanac of local plants, local history, and
on-this-days in art and science) cast to the bedroom at 7 AM / 7 PM; a
TV dashboard whose hero is a glowing two-floor plan of the house with a
sun arc and one diamond per solar inverter, alternating in place with a
full-board feed of the household's context — and light bars behind the
TV that take each cast's colours; a live flight-radar scope the page
draws itself from raw ADS-B data; storm theatre (animated radar, a
particle wind field, a live satellite window, full-screen weather-alert
posters); a night-sky page with real, locally computed ISS pass
predictions; an organism that grows from the day's house signals; and a
dream in which a city of light builds itself — on time-on-screen, not
time of day — while public-domain dream poems surface. A small
Raspberry Pi serves the pages and casts them; a phone page is the
remote. Start with [`screens/README.md`](screens/README.md);
hardware is in [`screens/PARTS.md`](screens/PARTS.md) and day-to-day
operations in [`screens/docs/OPERATIONS.md`](screens/docs/OPERATIONS.md).

### voice — a separate system, not in this repo yet

The household voice (speaking through the house's displays, hearing a wake
word, answering) is a separate system with its own design and its own
safeguards. It will get its own subfolder when it's ready to share; it is
deliberately not part of the screens system.

## Privacy

Everything published here is scrubbed. The code and docs were written for
one real house, but every address, coordinate, name, account identifier,
and credential-shaped value was replaced with a clearly marked placeholder
(`YOUR_LAT`, `CASTPI_LAN_IP`, `HOUSE_NAME`, …) before publication, and the
tree was swept for personal data — names, emails, phone numbers, network
addresses, file IDs — with zero hits. Each system's README carries the
table of its placeholders and what to set them to. If you adopt a system,
your house's data stays yours: it only ever enters through those
placeholders, on your own machines.
