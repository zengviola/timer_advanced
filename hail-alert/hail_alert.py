"""Hail alerts for Kangaroo Point (Brisbane) and Bundall (Gold Coast) via Bark.

Data: Bureau of Meteorology public feeds.
  - QLD warnings RSS: severe thunderstorm warnings that mention hail
  - QLD precis forecast: a once-a-day heads-up when storms are forecast

Env: BARK_KEY (no key -> dry run, prints instead of pushing). State in state.json.
"""
import json
import os
import re
import sys
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

UA = {"User-Agent": "Mozilla/5.0 (hail-alert personal script)"}


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def page_text(html):
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def push(title, body, url=None, critical=False):
    key = os.environ.get("BARK_KEY", "").strip()
    if not key:
        print(f"[dry run] {title} | {body} | {url or ''}")
        return
    payload = {"device_key": key, "title": title, "body": body, "group": "冰雹提醒"}
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
    with urllib.request.urlopen(req, timeout=30) as r:
        print("Bark:", r.read().decode())


def check_warnings(state):
    seen = state.setdefault("seen", [])
    root = ET.fromstring(fetch(WARNINGS_URL))
    for item in root.iter("item"):
        title = item.findtext("title", "")
        link = item.findtext("link", "")
        guid = item.findtext("guid", link)
        if "thunderstorm" not in title.lower():
            continue
        text = page_text(fetch(link.replace("http://", "https://")))
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


def main():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    failed = False
    for check in (check_warnings, check_forecast):
        try:
            check(state)
        except Exception as e:  # one feed down shouldn't block the other
            print(f"{check.__name__} failed: {e}", file=sys.stderr)
            failed = True
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    if "--test" in sys.argv:
        push("✅ 冰雹提醒测试", "收到这条说明 Bark 连通了。", critical=True)
    else:
        main()
