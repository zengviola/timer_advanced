"""Hail alerts for Kangaroo Point (Brisbane) and Bundall (Gold Coast), plus rain alerts for
Kangaroo Point, via Bark.

Data: Bureau of Meteorology public feeds.
  - QLD warnings RSS: severe thunderstorm warnings that mention hail
  - QLD precis forecast: a once-a-day heads-up when storms are forecast
Rain: Open-Meteo (free, no key) 15-minute precipitation forecast — BoM's own JSON API forbids
third-party use, so it isn't used here.
  - rain expected within the next hour while it's still dry -> push (once per rain spell)
  - once a day after 5am: heads-up if today's rain chance is high

Env: BARK_KEY (no key -> dry run, prints instead of pushing). State in state.json.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

WARNINGS_URL = "https://www.bom.gov.au/fwo/IDZ00056.warnings_qld.xml"
FORECAST_URL = "ftp://ftp.bom.gov.au/anon/gen/fwo/IDQ11295.xml"
BRISBANE_TZ = timezone(timedelta(hours=10))  # QLD has no daylight saving
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

# Warnings name councils/suburbs, not every suburb, so match the surrounding area too.
PLACES = {
    "袋鼠角": ["Kangaroo Point", "Brisbane"],
    "Bundall": ["Bundall", "Gold Coast", "Surfers Paradise", "Southport"],
}
# Nearest BoM forecast locations.
FORECAST_LOCATIONS = {"袋鼠角": "Brisbane", "Bundall": "Surfers Paradise"}

# Rain: Kangaroo Point only.
RAIN_PLACE, RAIN_LAT, RAIN_LON = "袋鼠角", -27.476, 153.036
RAIN_URL = (
    "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
    "&minutely_15=precipitation&past_minutely_15=2&forecast_minutely_15=4"
    "&hourly=precipitation_probability,precipitation&forecast_days=1"
    "&daily=precipitation_probability_max,precipitation_sum&timezone=Australia%2FBrisbane"
).format(lat=RAIN_LAT, lon=RAIN_LON)
RAIN_MM = 0.2          # per 15 min; below this it's a few drops at most
RAIN_QUIET_HOURS = 3   # one alert per rain spell, not one every 10 minutes
RAIN_DAY_PROB = 50     # % for the morning heads-up

UA = {"User-Agent": "Mozilla/5.0 (hail-alert personal script)"}


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def page_text(html):
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def warning_text(html):
    """Only the warning itself: the page's menus link to "Brisbane Forecast" etc., so matching the
    whole page flagged every hail warning in QLD. The tail after "The next warning" lists other
    districts' warnings and is cut off too."""
    m = re.search(r'(?is)<div id="main">(.*?)(?:The next warning|</div>)', html)
    return page_text(m.group(1) if m else "")


def push(title, body, url=None, critical=False, group="冰雹提醒"):
    key = os.environ.get("BARK_KEY", "").strip()
    # Accept the whole "https://api.day.app/<key>/..." URL Bark shows, not just the key.
    m = re.search(r"day\.app/([^/\s]+)", key)
    if m:
        key = m.group(1)
    if not key:
        print(f"[dry run] {title} | {body} | {url or ''}")
        return
    payload = {"device_key": key, "title": title, "body": body, "group": group}
    if url:
        payload["url"] = url
    if critical:
        payload.update(level="critical", volume=8, sound="alarm")
    else:
        payload["level"] = "timeSensitive"
    req = urllib.request.Request(
        "https://api.day.app/push",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print("Bark:", r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Bark HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from None


def check_warnings(state):
    seen = state.setdefault("seen", [])
    root = ET.fromstring(fetch(WARNINGS_URL))
    for item in root.iter("item"):
        title = item.findtext("title", "")
        link = item.findtext("link", "")
        guid = item.findtext("guid", link)
        if "thunderstorm" not in title.lower():
            continue
        text = warning_text(fetch(link.replace("http://", "https://")))
        if not re.search(r"\bhail", text, re.I):
            continue
        for place, needles in PLACES.items():
            hit = next((n for n in needles if n.lower() in text.lower()), None)
            seen_key = f"{guid}|{place}"
            if not hit or seen_key in seen:
                continue
            push(f"⚠️ {place} 冰雹预警", f"BoM 强雷暴预警提到冰雹，影响 {hit}。\n{title}", link, critical=True)
            seen.append(seen_key)
    state["seen"] = seen[-300:]


def check_forecast(state):
    now = datetime.now(BRISBANE_TZ)
    today = now.strftime("%Y-%m-%d")
    if now.hour < 5 or state.get("forecast_date") == today:
        return
    root = ET.fromstring(fetch(FORECAST_URL))
    lines = []
    for place, loc in FORECAST_LOCATIONS.items():
        area = root.find(f".//area[@description='{loc}']")
        period = area.find("forecast-period[@index='0']") if area is not None else None
        if period is None:
            continue
        precis = period.findtext("text[@type='precis']", "")
        icon = period.findtext("element[@type='forecast_icon_code']", "")
        if "storm" in precis.lower() or icon == "16":
            lines.append(f"{place}（{loc}）：{precis}")
    if lines:
        push("⛈️ 今天有雷暴预报", "\n".join(lines) + "\n留意冰雹预警，车尽量停室内。")
    state["forecast_date"] = today


def check_rain(state):
    now = datetime.now(BRISBANE_TZ)
    data = json.loads(fetch(RAIN_URL))
    m15 = data["minutely_15"]
    slots = [(datetime.fromisoformat(t).replace(tzinfo=BRISBANE_TZ), mm or 0.0)
             for t, mm in zip(m15["time"], m15["precipitation"])]
    past = [mm for t, mm in slots if t + timedelta(minutes=15) <= now]
    coming = [(t, mm) for t, mm in slots if t + timedelta(minutes=15) > now]
    wet = [(t, mm) for t, mm in coming if mm >= RAIN_MM]

    last = state.get("rain_alerted_at")
    quiet = last and now - datetime.fromisoformat(last) < timedelta(hours=RAIN_QUIET_HOURS)
    already_raining = any(mm >= RAIN_MM for mm in past[-1:])
    if wet and not quiet and not already_raining:
        start = wet[0][0]
        mins = max(0, round((start - now).total_seconds() / 60))
        total = sum(mm for _, mm in coming)
        when = "马上" if mins <= 5 else f"约 {mins} 分钟后（{start:%H:%M}）"
        push(f"🌧️ {RAIN_PLACE} {when}下雨",
             f"未来一小时预计降雨约 {total:.1f} mm。收衣服、带伞。", group="下雨提醒")
        state["rain_alerted_at"] = now.isoformat()
    elif already_raining and not quiet:
        state["rain_alerted_at"] = now.isoformat()  # started without warning: don't alert mid-spell

    today = now.strftime("%Y-%m-%d")
    if now.hour >= 5 and state.get("rain_day_date") != today:
        prob = (data["daily"]["precipitation_probability_max"] or [0])[0] or 0
        mm = (data["daily"]["precipitation_sum"] or [0])[0] or 0
        if prob >= RAIN_DAY_PROB:
            h = data["hourly"]
            hours = [t[11:13] for t, p in zip(h["time"], h["precipitation_probability"])
                     if (p or 0) >= RAIN_DAY_PROB and t[11:13] >= f"{now.hour:02d}"]
            span = f"，主要在 {hours[0]}–{int(hours[-1]) + 1:02d} 点" if hours else ""
            push(f"☔ {RAIN_PLACE}今天可能下雨", f"降雨概率 {prob}%，预计 {mm:.1f} mm{span}。",
                 group="下雨提醒")
        state["rain_day_date"] = today


def main():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    failed = False
    for check in (check_warnings, check_forecast, check_rain):
        try:
            check(state)
        except Exception as e:  # one feed down shouldn't block the other
            # ::error:: shows up as a run annotation, readable without opening the log.
            print(f"::error::{check.__name__} failed: {e!r}")
            failed = True
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    if "--test" in sys.argv:
        try:
            push("✅ 冰雹提醒测试", "收到这条说明 Bark 连通了。", critical=True)
        except Exception as e:
            print(f"::error::test push failed: {e!r}")
            sys.exit(1)
    else:
        main()
