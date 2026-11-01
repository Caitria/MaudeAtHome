#!/usr/bin/env python3
"""
iss-passes.py — ISS pass predictions for your location, written to ~/briefing/iss.json.

Installed on the caster Pi (see docs/OPERATIONS.md). Runs nightly ~18:00 + at boot
(systemd iss-passes.timer). Fetches the ISS TLE from CelesTrak, propagates with
the pure-python `sgp4` package (venv ~/iss-venv), and finds every pass whose
peak elevation exceeds 10 degrees over the next 4 days.

A pass is marked visible=true only when BOTH hold at peak:
  - the satellite is sunlit (cylindrical Earth-shadow test, plain math), and
  - the sun is below -4 degrees at the observer (twilight-dark sky).
No JPL ephemeris, no API keys. All failures exit non-zero WITHOUT touching the
previous iss.json, so a stale file is detectable by its generated_at stamp
(the Tonight's Sky page refuses data older than 36 h).

Observer: YOUR_LAT / YOUR_LON below — set them to your home's coordinates.
"""
import json
import math
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LAT, LON = 0.0, 0.0  # CONFIG: your home's latitude/longitude
TZ = ZoneInfo("UTC")  # CONFIG: your timezone, e.g. ZoneInfo("Europe/London")
TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE"
OUT = os.path.expanduser("~/briefing/iss.json")
DAYS = 4
MIN_PEAK_DEG = 10.0
STEP_S = 20
EARTH_R_KM = 6371.0
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass(az_deg):
    return COMPASS[int((az_deg + 11.25) // 22.5) % 16]


def sun_ra_dec(dt_utc):
    """Low-precision solar position (~0.01 deg) -> (ra_deg, dec_deg)."""
    jd = dt_utc.timestamp() / 86400.0 + 2440587.5
    n = jd - 2451545.0
    L = (280.460 + 0.9856474 * n) % 360
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = math.radians((L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)) % 360)
    eps = math.radians(23.439 - 0.0000004 * n)
    ra = math.degrees(math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))) % 360
    dec = math.degrees(math.asin(math.sin(eps) * math.sin(lam)))
    return ra, dec


def sun_alt_deg(dt_utc):
    ra, dec = sun_ra_dec(dt_utc)
    jd = dt_utc.timestamp() / 86400.0 + 2440587.5
    n = jd - 2451545.0
    gmst = (280.46061837 + 360.98564736629 * n) % 360
    lst = (gmst + LON) % 360
    ha = math.radians((lst - ra + 540) % 360 - 180)
    alt = math.asin(math.sin(math.radians(dec)) * math.sin(math.radians(LAT)) +
                    math.cos(math.radians(dec)) * math.cos(math.radians(LAT)) * math.cos(ha))
    return math.degrees(alt)


def sun_dir_eci(dt_utc):
    ra, dec = sun_ra_dec(dt_utc)
    # GMST rotation: RA measured from vernal equinox; ECI x-axis points there.
    return (math.cos(math.radians(dec)) * math.cos(math.radians(ra)),
            math.cos(math.radians(dec)) * math.sin(math.radians(ra)),
            math.sin(math.radians(dec)))


def gmst_rad(dt_utc):
    jd = dt_utc.timestamp() / 86400.0 + 2440587.5
    return math.radians((280.46061837 + 360.98564736629 * (jd - 2451545.0)) % 360)


def observer_ecef():
    lat, lon = math.radians(LAT), math.radians(LON)
    # Spherical-earth observer position (fine at pass-prediction precision).
    return (EARTH_R_KM * math.cos(lat) * math.cos(lon),
            EARTH_R_KM * math.cos(lat) * math.sin(lon),
            EARTH_R_KM * math.sin(lat))


OBS_ECEF = observer_ecef()


def alt_az(dt_utc, sat):
    """Propagate and return (alt_deg, az_deg, eci_pos_km)."""
    from sgp4.api import jday
    jd, fr = jday(dt_utc.year, dt_utc.month, dt_utc.day,
                  dt_utc.hour, dt_utc.minute, dt_utc.second + dt_utc.microsecond / 1e6)
    err, r, _v = sat.sgp4(jd, fr)
    if err != 0:
        raise RuntimeError(f"sgp4 error {err}")
    # ECI -> ECEF
    th = gmst_rad(dt_utc)
    x = math.cos(th) * r[0] + math.sin(th) * r[1]
    y = -math.sin(th) * r[0] + math.cos(th) * r[1]
    z = r[2]
    dx, dy, dz = x - OBS_ECEF[0], y - OBS_ECEF[1], z - OBS_ECEF[2]
    lat, lon = math.radians(LAT), math.radians(LON)
    east = -math.sin(lon) * dx + math.cos(lon) * dy
    north = -math.sin(lat) * math.cos(lon) * dx - math.sin(lat) * math.sin(lon) * dy + math.cos(lat) * dz
    up = math.cos(lat) * math.cos(lon) * dx + math.cos(lat) * math.sin(lon) * dy + math.sin(lat) * dz
    rng = math.sqrt(east * east + north * north + up * up)
    alt = math.degrees(math.asin(up / rng))
    az = math.degrees(math.atan2(east, north)) % 360
    return alt, az, r


def is_sunlit(dt_utc, eci_pos):
    s = sun_dir_eci(dt_utc)
    r = math.sqrt(sum(c * c for c in eci_pos))
    dot = sum(p * si for p, si in zip(eci_pos, s))
    if dot >= 0:
        return True
    perp2 = r * r - dot * dot
    return perp2 > EARTH_R_KM ** 2


def refine_peak(sat, t_lo, t_hi):
    """Golden-section search for max altitude between two datetimes."""
    gr = (math.sqrt(5) - 1) / 2
    a, b = t_lo, t_hi
    span = (b - a).total_seconds()
    c = a + timedelta(seconds=span * (1 - gr))
    d = a + timedelta(seconds=span * gr)
    for _ in range(24):
        if alt_az(c, sat)[0] < alt_az(d, sat)[0]:
            a = c
        else:
            b = d
        span = (b - a).total_seconds()
        c = a + timedelta(seconds=span * (1 - gr))
        d = a + timedelta(seconds=span * gr)
    t = a + (b - a) / 2
    alt, az, pos = alt_az(t, sat)
    return t, alt, az, pos


def main():
    from sgp4.api import Satrec
    req = urllib.request.Request(TLE_URL, headers={"User-Agent": "iss-passes/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        tle = resp.read().decode("ascii", "replace").splitlines()
    l1 = next(l for l in tle if l.startswith("1 "))
    l2 = next(l for l in tle if l.startswith("2 "))
    sat = Satrec.twoline2rv(l1, l2)

    now = datetime.now(timezone.utc)
    end = now + timedelta(days=DAYS)
    samples = []
    t = now
    while t <= end:
        alt, az, _ = alt_az(t, sat)
        samples.append((t, alt, az))
        t += timedelta(seconds=STEP_S)

    passes = []
    i = 0
    while i < len(samples):
        if samples[i][1] > 0:
            j = i
            while j + 1 < len(samples) and samples[j + 1][1] > 0:
                j += 1
            seg = samples[i:j + 1]
            pk_t, pk_alt, pk_az, pk_pos = refine_peak(sat, seg[0][0], seg[-1][0])
            if pk_alt >= MIN_PEAK_DEG:
                # rise/set at the 10-degree crossings bracketing the peak
                rise_t = next((s[0] for s in seg if s[1] >= MIN_PEAK_DEG), seg[0][0])
                set_t = next((s[0] for s in reversed(seg) if s[1] >= MIN_PEAK_DEG), seg[-1][0])
                r_alt, r_az, _ = alt_az(rise_t, sat)
                s_alt, s_az, _ = alt_az(set_t, sat)
                lit = is_sunlit(pk_t, pk_pos)
                sun_alt = sun_alt_deg(pk_t)
                passes.append({
                    "rise": rise_t.astimezone(TZ).isoformat(),
                    "peak": pk_t.astimezone(TZ).isoformat(),
                    "set": set_t.astimezone(TZ).isoformat(),
                    "rise_dir": compass(r_az),
                    "peak_dir": compass(pk_az),
                    "set_dir": compass(s_az),
                    "peak_alt_deg": round(pk_alt),
                    "sunlit": lit,
                    "sun_alt_deg": round(sun_alt, 1),
                    "visible": bool(lit and sun_alt < -4.0),
                })
            i = j + 1
        else:
            i += 1

    doc = {
        "generated_at": now.astimezone(TZ).isoformat(),
        "observer": {"lat": LAT, "lon": LON, "tz": str(TZ)},
        "min_peak_deg": MIN_PEAK_DEG,
        "passes": passes,
    }
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=1)
    os.replace(tmp, OUT)
    vis = [p for p in passes if p["visible"]]
    print(f"iss-passes: {len(passes)} passes >10deg in {DAYS}d, {len(vis)} visible; wrote {OUT}")
    for p in vis[:3]:
        print("  next visible:", p["rise"], "peak", p["peak"], p["peak_alt_deg"])


if __name__ == "__main__":
    sys.exit(main())
