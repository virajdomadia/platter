"""Fetch one CC-licensed dish photo per `photo` key in area.json from Wikimedia Commons.

    uv run python -m app.seed.fetch_photos            # fills web/public/dishes/, skips existing
    uv run python -m app.seed.fetch_photos --refresh  # re-picks every photo

Licence filter: CC0 / public domain / CC BY / CC BY-SA only. Each file is a Commons thumbnail
(480 px wide), credited in web/public/dishes/CREDITS.md (title, author, licence, link). Polite: a
descriptive User-Agent, one request at a time, exponential backoff on 429 / 5xx. A key with no
acceptable result falls back to one of the hand-picked mockup photos (mockups/img/).
"""

import argparse
import html
import json
import re
import shutil
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
AREA = Path(__file__).with_name("area.json")
OUT = ROOT / "web" / "public" / "dishes"
MOCKUP_IMG = ROOT / "mockups" / "img"
API = "https://commons.wikimedia.org/w/api.php"
UA = "platter-seed/1.0 (portfolio demo; https://github.com/virajdomadia/platter)"
# No brands on a fictional menu.
DENY = re.compile(r"starbucks|mcdonald|burger king|bk|kfc|pizza hut|domino|subway|logo", re.I)
OK_LICENCES = re.compile(r"^(cc0|public domain|pd|cc by(-sa)? [0-9.]+)$", re.I)

# Search terms per photo key (the key alone when missing).
QUERIES = {
    "dosa": "masala dosa",
    "ghee-roast": "ghee roast dosa",
    "paneer-dosa": "dosa paneer",
    "rava-dosa": "rava dosa",
    "idli": "idli sambar",
    "vada": "medu vada",
    "south-thali": "south indian meals banana leaf",
    "coffee": "filter coffee dabara",
    "kesari": "kesari bath",
    "biryani": "chicken biryani",
    "mutton-biryani": "mutton biryani",
    "veg-biryani": "vegetable biryani",
    "egg-biryani": "egg biryani",
    "seekh": "seekh kebab",
    "tandoori": "tandoori chicken",
    "salan": "mirchi ka salan",
    "double-ka-meetha": "double ka meetha",
    "thali": "veg thali",
    "rajasthani-thali": "rajasthani thali",
    "gujarati-thali": "gujarati thali",
    "paneer": "paneer butter masala",
    "dal-makhani": "dal makhani",
    "paratha": "aloo paratha",
    "gulab-jamun": "gulab jamun",
    "lassi": "lassi glass",
    "momos": "momo dumplings",
    "veg-momos": "steamed momos",
    "fried-momos": "fried momos",
    "jhol-momo": "jhol momo",
    "thukpa": "thukpa",
    "noodles": "hakka noodles",
    "chilli-chicken": "chilli chicken",
    "pizza": "pizza margherita",
    "veg-pizza": "vegetable pizza",
    "pepperoni": "pepperoni pizza",
    "paneer-pizza": "paneer pizza",
    "garlic-bread": "garlic bread",
    "salad": "caesar salad",
    "tiramisu": "tiramisu",
    "burger": "veggie burger",
    "chicken-burger": "chicken burger sandwich",
    "lamb-burger": "cheeseburger",
    "paneer-burger": "aloo tikki burger",
    "fries": "chips fries ketchup",
    "onion-rings": "onion rings",
    "milkshake": "milkshake",
    "podi-idli": "podi idli",
    "rava-idli": "rava idli",
    "pongal": "ven pongal",
    "upma": "upma",
    "buns": "mangalore buns",
    "badam-milk": "badam milk",
    "rasmalai": "rasmalai",
    "kaju-katli": "kaju katli",
    "mysore-pak": "mysore pak",
    "halwa": "gajar halwa",
    "falooda": "falooda",
    "brownie": "chocolate brownie",
    "chai": "masala chai",
    "iced-tea": "iced tea lemon",
    "samosa": "samosa",
    "vada-pav": "vada pav",
    "bun-maska": "bun maska",
    "poha": "poha",
    "chole": "chole bhature",
    "butter-chicken": "butter chicken",
    "saag": "sarson da saag",
    "rajma": "rajma chawal",
    "naan": "naan bread tandoor",
    "kulcha": "amritsari kulcha",
    "pavbhaji": "pav bhaji",
    "cheese-pavbhaji": "pav bhaji cheese",
    "masala-pav": "masala pav",
    "pani-puri": "pani puri",
    "dahi-puri": "dahi puri",
    "bhel": "bhel puri",
    "gola": "gola ice",
    "mango-lassi": "mango lassi",
    "wings": "chicken wings",
    "paneer-tikka": "paneer tikka",
    "nachos": "nachos cheese salsa",
    "pasta": "penne arrabbiata",
    "cold-coffee": "iced coffee",
    "lime-soda": "lime soda",
    "kitchen": "indian restaurant kitchen",
}

# Keys that always use the hand-picked mockup photo.
FORCE_MOCKUP = {"kitchen"}

# Hand-picked mockup photos (mockups/img/CREDITS.md) used when Commons has nothing acceptable.
MOCKUP = {
    "dosa": "dish-dosa",
    "biryani": "dish-biryani",
    "paneer": "dish-paneer",
    "momos": "dish-momos",
    "thali": "dish-thali",
    "chole": "dish-chole",
    "pavbhaji": "dish-pavbhaji",
    "coffee": "dish-coffee",
    "rasmalai": "dish-rasmalai",
    "idli": "dish-idli",
    "pizza": "dish-pizza",
    "burger": "dish-burger",
    "kitchen": "kitchen",
    "chai": "dish-coffee",
}


def photo_keys() -> list[str]:
    area = json.loads(AREA.read_text(encoding="utf-8"))
    keys: set[str] = set()
    for r in area["restaurants"]:
        keys.add(r["cover"])
        for items in r["menu"].values():
            keys.update(item[3] for item in items)
    return sorted(keys)


def strip_tags(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value or "")).strip()


def get(client: httpx.Client, params: dict) -> dict:
    delay = 2.0
    for _ in range(6):
        r = client.get(API, params=params)
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(delay)
            delay *= 2
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Commons kept refusing; try again later")


def search(client: httpx.Client, query: str) -> dict | None:
    data = get(
        client,
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"filetype:bitmap {query}",
            "gsrnamespace": 6,
            "gsrlimit": 12,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size",
            "iiurlwidth": 480,
        },
    )
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        licence = strip_tags(meta.get("LicenseShortName", {}).get("value", ""))
        if not OK_LICENCES.match(licence) or DENY.search(page["title"]):
            continue
        if info.get("width", 0) < 480 or info.get("height", 0) < 400:
            continue
        if info.get("width", 1) / max(1, info.get("height", 1)) > 2.2:
            continue
        return {
            "title": page["title"].removeprefix("File:"),
            "page": info.get("descriptionurl"),
            "thumb": info.get("thumburl"),
            "author": strip_tags(meta.get("Artist", {}).get("value", "")) or "unknown",
            "licence": licence,
        }
    return None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--only", default="", help="comma-separated keys to re-pick")
    args = parser.parse_args()
    only = {k for k in args.only.split(",") if k}
    OUT.mkdir(parents=True, exist_ok=True)
    credits_path = OUT / "credits.json"
    credits: dict[str, dict] = (
        json.loads(credits_path.read_text(encoding="utf-8")) if credits_path.exists() else {}
    )
    with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
        for key in photo_keys():
            target = OUT / f"{key}.jpg"
            if only and key not in only:
                continue
            if target.exists() and key in credits and not args.refresh and not only:
                continue
            found = None
            try:
                if key in FORCE_MOCKUP:
                    raise RuntimeError("mockup photo by choice")
                found = search(client, QUERIES.get(key, key.replace("-", " ")))
            except (httpx.HTTPError, RuntimeError) as exc:
                print(f"  {key}: search failed ({exc})", file=sys.stderr)
            if found and found["thumb"]:
                try:
                    r = client.get(found["thumb"])
                    r.raise_for_status()
                    target.write_bytes(r.content)
                    credits[key] = {k: v for k, v in found.items() if k != "thumb"}
                    print(f"  {key}: {found['title']} ({found['licence']})")
                    time.sleep(0.5)
                    continue
                except httpx.HTTPError as exc:
                    print(f"  {key}: download failed ({exc})", file=sys.stderr)
            fallback = MOCKUP.get(key) or MOCKUP.get(key.split("-")[-1]) or "dish-thali"
            shutil.copyfile(MOCKUP_IMG / f"{fallback}.jpg", target)
            credits[key] = {"mockup": fallback}
            print(f"  {key}: mockup photo {fallback}")
    credits_path.write_text(json.dumps(credits, indent=1, sort_keys=True), encoding="utf-8")
    write_credits(credits)
    return 0


def write_credits(credits: dict[str, dict]) -> None:
    mockup_credits = (MOCKUP_IMG / "CREDITS.md").read_text(encoding="utf-8")
    lines = [
        "# Dish photo credits",
        "",
        "Photos from Wikimedia Commons under the licence listed (CC0 / public domain / CC BY /"
        " CC BY-SA), served as 480-px thumbnails. Fetched by `api/app/seed/fetch_photos.py`.",
        "",
    ]
    for key, c in sorted(credits.items()):
        if "mockup" in c:
            m = re.search(rf"`{re.escape(c['mockup'])}\.jpg` — (.+)", mockup_credits)
            lines.append(f"- `{key}.jpg` — {m.group(1) if m else 'see mockups/img/CREDITS.md'}")
        else:
            lines.append(
                f"- `{key}.jpg` — [{c['title']}]({c['page']}) · {c['author']} · {c['licence']}"
            )
    (OUT / "CREDITS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
