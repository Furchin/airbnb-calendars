# airbnb-calendars

Keeps availability in sync for one rental listed on several platforms.

Every 15 minutes, `merge.py` downloads each platform's iCal export and writes `feeds/<platform>.ics`. That file holds the dates booked or blocked on **every other** platform, and each platform imports its own file.

- Export URLs live only in the `CAL_SOURCES` Actions secret. Feeds contain dates only, with no guest details.
- `drop_window_tail` drops Airbnb's "Not available" block for dates past its booking window, so long-term sites aren't blocked by it.
- Blocks a platform re-exports from its imported feed are ignored, so a cancelled booking can't get stuck as an "echo".
- If any source fails to download, nothing is published. The previous feeds stay up rather than opening dates that are actually booked.

Import URL for a platform: `https://raw.githubusercontent.com/Furchin/airbnb-calendars/main/feeds/<platform>.ics`
