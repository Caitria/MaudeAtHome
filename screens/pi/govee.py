#!/usr/bin/env python3
"""Govee LAN client — local control of the Govee TV light bars (H6046).

Design authority: files/govee-tv-bars-pairing-2026-11-01.md. The bars
speak Govee's documented LAN API: UDP multicast scan to
239.255.255.250:4001, replies land on port 4002, control datagrams go to
the device on port 4003 as {"msg": {"cmd": ..., "data": {...}}} —
turn {value 0|1}, brightness {value 1-100}, colorwc {color {r,g,b},
colorTemInKelvin} (a non-zero Kelvin wins over the RGB triple), and
devStatus {} for a read-back. "LAN Control" must be on in the Govee app;
there is no auth and no cloud in this path.

Contract with the caller (cast-control): EVERY function here is
timeout-bounded and swallows its own exceptions, logging to
~/govee.log. A sleeping light bulb must never break or delay a cast —
the bars are a companion, never a dependency. Discovery is scan-based;
the found IP is cached in ~/govee-device.json (a Pi-side runtime value,
never source) and re-scanned once on failure, because DHCP leases move.

Brightness discipline lives here, not in the recipes: set_recipe caps at
RECIPE_CAP (30) no matter what it is asked for; callers doing manual
controller overrides pass cap=MANUAL_CAP (60). Nothing in this module
will ever ask the bars for more than 60%.
"""
import json, os, socket, time

HOME = os.path.expanduser("~")
LOG_F = os.path.join(HOME, "govee.log")
CACHE_F = os.path.join(HOME, "govee-device.json")
SCAN_ADDR = ("239.255.255.250", 4001)
REPLY_PORT = 4002
CTRL_PORT = 4003
RECIPE_CAP = 30
MANUAL_CAP = 60
GAP_S = 0.15  # small gaps between datagrams — a device can drop back-to-back commands
SETTLE_S = 0.6  # the device applies a command a beat after the datagram lands;
# an instant read-back can still show the pre-command state (seen live
# Nov 1, 2026: an off() read back onOff=1 for a command that had in fact
# taken). Confirm reads therefore wait, and re-read once on mismatch.


def _log(msg):
    try:
        line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + msg
        with open(LOG_F, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _sock(timeout):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", REPLY_PORT))
    s.settimeout(timeout)
    return s


def _send(ip, cmd, data):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.sendto(json.dumps({"msg": {"cmd": cmd, "data": data}}).encode(),
                 (ip, CTRL_PORT))
    finally:
        s.close()


def scan(timeout=4.0):
    """Multicast-scan for the bars. Returns {"ip", "sku", "device"} for
    the first responder, or None. Read-only."""
    s = _sock(timeout)
    try:
        s.sendto(json.dumps({"msg": {"cmd": "scan",
                                     "data": {"account_topic": "reserve"}}}).encode(),
                 SCAN_ADDR)
        while True:
            try:
                raw, addr = s.recvfrom(4096)
            except socket.timeout:
                return None
            try:
                d = json.loads(raw.decode()).get("msg", {}).get("data", {})
            except Exception:
                continue
            if d:
                return {"ip": d.get("ip") or addr[0],
                        "sku": d.get("sku"), "device": d.get("device")}
    finally:
        s.close()


def _cache_write(dev):
    try:
        tmp = CACHE_F + ".tmp"
        with open(tmp, "w") as f:
            json.dump(dev, f)
        os.replace(tmp, CACHE_F)
    except Exception:
        pass


def _scan_and_cache():
    dev = scan()
    if dev:
        _cache_write(dev)
        _log(f"scan found bars at {dev['ip']} (sku={dev.get('sku')})")
        return dev["ip"]
    _log("scan found no bars")
    return None


def _ensure_ip():
    """Cached IP if we have one, else scan once and cache the result."""
    try:
        with open(CACHE_F) as f:
            ip = json.load(f).get("ip")
        if ip:
            return ip
    except Exception:
        pass
    return _scan_and_cache()


def _dev_status(ip, wait=2.0):
    """One devStatus query to ip; returns the data dict or None."""
    if not ip:
        return None
    s = _sock(wait)
    try:
        s.sendto(json.dumps({"msg": {"cmd": "devStatus", "data": {}}}).encode(),
                 (ip, CTRL_PORT))
        while True:
            try:
                raw, _addr = s.recvfrom(4096)
            except socket.timeout:
                return None
            try:
                m = json.loads(raw.decode()).get("msg", {})
            except Exception:
                continue
            if m.get("cmd") == "devStatus":
                return m.get("data")
    finally:
        s.close()


def status():
    """Current bars state ({onOff, brightness, color, colorTemInKelvin})
    or None if they don't answer. Never raises."""
    try:
        st = _dev_status(_ensure_ip())
        if st is None:
            st = _dev_status(_scan_and_cache())
        return st
    except Exception as e:
        _log(f"status failed: {e}")
        return None


def _confirm(ip, want_on, tries=3):
    """Read status until it shows want_on or the tries run out; between
    tries, wait SETTLE_S for the device to finish applying. Returns the
    last status read (or None)."""
    st = None
    for i in range(tries):
        if i:
            time.sleep(SETTLE_S)
        st = _dev_status(ip)
        if st is not None and st.get("onOff") == want_on:
            break
    return st


def _patient_read(ip, want_on, current):
    """One last read, 1.5 s on, when the confirm reads answered but
    showed the pre-command state: the replies are untagged and the
    device can lag seconds behind its own change (seen live Nov 1,
    2026 — an off confirmed by a fresh read ~5 s later had read back
    onOff=1 twice at +0.6/+1.2 s). Returns the freshest status."""
    if current is not None and current.get("onOff") == want_on:
        return current
    time.sleep(1.5)
    st = _dev_status(ip)
    return st if st is not None else current


def _apply(ip, brightness, rgb, kelvin):
    """turn on → brightness → colorwc, with gaps; settle, then confirm
    by read-back. Returns (answered_on, status|None)."""
    _send(ip, "turn", {"value": 1})
    time.sleep(GAP_S)
    if brightness is not None:
        _send(ip, "brightness", {"value": brightness})
        time.sleep(GAP_S)
    if kelvin:
        _send(ip, "colorwc", {"color": {"r": 0, "g": 0, "b": 0},
                              "colorTemInKelvin": int(kelvin)})
    elif rgb:
        _send(ip, "colorwc", {"color": {"r": int(rgb[0]), "g": int(rgb[1]),
                                        "b": int(rgb[2])},
                              "colorTemInKelvin": 0})
    time.sleep(SETTLE_S)
    st = _patient_read(ip, 1, _confirm(ip, 1))
    return (st is not None and st.get("onOff") == 1), st


def set_recipe(brightness=None, rgb=None, kelvin=None, cap=RECIPE_CAP):
    """Apply a recipe: bars on at the given brightness and color/Kelvin.
    Brightness is clamped to [1, cap] HERE so no caller can blast the
    room. Returns (ok, status|None); ok means the read-back shows the
    bars on. On a silent first attempt, re-scans once and retries at the
    fresh IP. Never raises."""
    try:
        b = None
        if brightness is not None:
            b = max(1, min(int(brightness), int(cap)))
        ip = _ensure_ip()
        if not ip:
            _log("set_recipe: no bars found")
            return False, None
        ok, st = _apply(ip, b, rgb, kelvin)
        if not ok:
            ip2 = _scan_and_cache()
            if ip2 and ip2 != ip:
                ok, st = _apply(ip2, b, rgb, kelvin)
        _log(f"set_recipe brightness={b} rgb={rgb} kelvin={kelvin} ok={ok}")
        return ok, st
    except Exception as e:
        _log(f"set_recipe failed: {e}")
        return False, None


def off():
    """Bars off, confirmed by read-back where possible. Returns
    (ok, status|None); ok means the read-back shows them off (or, if no
    read-back answers at all, False — the command was still sent).
    Never raises."""
    try:
        ip = _ensure_ip()
        if not ip:
            _log("off: no bars found")
            return False, None
        _send(ip, "turn", {"value": 0})
        time.sleep(SETTLE_S)
        st = _confirm(ip, 0)
        if st is None or st.get("onOff") != 0:
            ip2 = _scan_and_cache()
            if ip2 and ip2 != ip:
                _send(ip2, "turn", {"value": 0})
                time.sleep(SETTLE_S)
                st = _confirm(ip2, 0)
        st = _patient_read(ip, 0, st)
        ok = st is not None and st.get("onOff") == 0
        _log(f"off ok={ok}")
        return ok, st
    except Exception as e:
        _log(f"off failed: {e}")
        return False, None


if __name__ == "__main__":
    # Manual smoke path (read-only unless a verb is given):
    #   govee.py            -> scan + status
    #   govee.py off        -> bars off
    print("scan:", scan())
    print("status:", status())
