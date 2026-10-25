"""Build one blocked-dates feed per platform from every *other* platform's iCal export.

Sources come from the CAL_SOURCES env var (a JSON secret):
  {"airbnb": {"url": "https://...ics", "drop_window_tail": true}, "vrbo": {"url": "..."}}
Consumers are listed in platforms.json. Output: feeds/<platform>.ics
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
FEEDS = os.path.join(ROOT, "feeds")
# A "not available" block ending this far out is the booking-window tail, not a real block.
WINDOW_TAIL_DAYS = 300


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 calendar-sync"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse_date(value, is_end):
    d = dt.date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
    # A timed end (e.g. 11:00 checkout) still occupies that night only if past midnight; round up to be safe.
    if is_end and "T" in value and value[9:15] != "000000":
        d += dt.timedelta(days=1)
    return d


def parse_events(text):
    text = re.sub(r"\r?\n[ \t]", "", text)  # unfold continuation lines
    events, cur = [], None
    for line in text.splitlines():
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT" and cur is not None:
            if "start" in cur:
                cur.setdefault("end", cur["start"] + dt.timedelta(days=1))
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            key, val = line.split(":", 1)
            name = key.split(";")[0]
            if name == "DTSTART":
                cur["start"] = parse_date(val, False)
            elif name == "DTEND":
                cur["end"] = parse_date(val, True)
            elif name == "SUMMARY":
                cur["summary"] = val
    return events


def merge_ranges(ranges):
    out = []
    for s, e in sorted(ranges):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def covered(rng, blocks):
    s, e = rng
    return any(bs <= s and e <= be for bs, be in blocks)


def write_ics(path, name, ranges):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//airbnb-calendars//EN",
             "CALSCALE:GREGORIAN", f"X-WR-CALNAME:Blocked for {name}"]
    for s, e in ranges:
        lines += ["BEGIN:VEVENT",
                  f"UID:{s:%Y%m%d}-{e:%Y%m%d}-{name}@airbnb-calendars",
                  f"DTSTAMP:{s:%Y%m%d}T000000Z",
                  f"DTSTART;VALUE=DATE:{s:%Y%m%d}",
                  f"DTEND;VALUE=DATE:{e:%Y%m%d}",
                  "SUMMARY:Not available",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    with open(path, "w", newline="") as f:
        f.write("\r\n".join(lines) + "\r\n")


def main():
    sources = json.loads(os.environ["CAL_SOURCES"])
    with open(os.path.join(ROOT, "platforms.json")) as f:
        platforms = json.load(f)["platforms"]
    today = dt.date.today()
    tail_cutoff = today + dt.timedelta(days=WINDOW_TAIL_DAYS)

    # What we served each platform last run: blocks it re-exports from that are echoes, not bookings.
    served = {}
    for p in platforms:
        path = os.path.join(FEEDS, f"{p}.ics")
        served[p] = [(e["start"], e["end"]) for e in parse_events(open(path).read())] if os.path.exists(path) else []

    blocks, failed = {}, []
    for name, cfg in sources.items():
        try:
            events = parse_events(fetch(cfg["url"]))
        except Exception as exc:  # keep last good feeds rather than unblocking dates
            print(f"::warning::fetch failed for {name}: {exc}")
            failed.append(name)
            continue
        kept = []
        for ev in events:
            rng = (ev["start"], ev["end"])
            if rng[1] <= today:
                continue
            if cfg.get("drop_window_tail") and "not available" in ev.get("summary", "").lower() and rng[1] >= tail_cutoff:
                continue
            if covered(rng, served.get(name, [])):
                continue
            kept.append(rng)
        blocks[name] = kept
        print(f"{name}: {len(events)} events, {len(kept)} kept")

    if failed:
        # Never publish a feed missing a source: that could open dates that are actually booked.
        sys.exit(f"aborting, sources failed: {', '.join(failed)}")

    for p in platforms:
        others = [r for name, rs in blocks.items() if name != p for r in rs]
        write_ics(os.path.join(FEEDS, f"{p}.ics"), p, merge_ranges(others))
    with open(os.path.join(FEEDS, "status.json"), "w") as f:
        json.dump({"last_success": today.isoformat(), "sources": sorted(blocks)}, f, indent=1)


if __name__ == "__main__":
    main()
