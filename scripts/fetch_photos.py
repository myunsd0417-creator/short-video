"""Wikimedia Commonsから、商用利用OK（CC0・パブリックドメイン・CC BY）の写真を取ってくる。
CC BY-SA など条件が重いものは使わない。出典は output/<id>_credits.txt に残す。
使い方: python scripts/fetch_photos.py content/001.json
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = "short-video-bot/1.0 (https://github.com/myunsd0417-creator/short-video)"
API = "https://commons.wikimedia.org/w/api.php"
BAD_WORDS = ("logo", "icon", "drawing", "diagram", "map", "clipart", "illustration", "svg", "patent",
             "advertisement", "advert", "poster", "page", "book", "scan", "newspaper", "magazine", "text", "sign",
             "catalog", "label", "document", "letter", "postcard", "scale")


def get(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def license_ok(name):
    n = (name or "").lower()
    if "sa" in re.split(r"[\s\-]+", n):
        return False
    return n.startswith("cc0") or "public domain" in n or n == "pd" or n.startswith("cc by")


def search(query):
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap",
        "gsrnamespace": "6",
        "gsrlimit": "30",
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": "1400",
    }
    data = json.loads(get(API + "?" + urllib.parse.urlencode(params)))
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    out = []
    for p in pages:
        ii = (p.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata", {})
        lic = meta.get("LicenseShortName", {}).get("value", "")
        title = p.get("title", "")
        if ii.get("mime") != "image/jpeg":
            continue
        if any(w in title.lower() for w in BAD_WORDS):
            continue
        if re.search(r"\b1[89]\d\d\b", title) or "wellcome" in title.lower() or " by " in title.lower():
            continue  # 古い広告・絵画・肖像を避ける
        if (ii.get("width") or 0) < 900 or not license_ok(lic):
            continue
        artist = re.sub("<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip()
        out.append({
            "url": ii.get("thumburl") or ii.get("url"),
            "title": title,
            "license": lic,
            "artist": artist,
            "page": ii.get("descriptionurl", ""),
            "tall": ii.get("height", 0) >= ii.get("width", 1),
        })
    print(f"  search '{query}': {len(out)} usable")
    # 検索順位を保ちつつ、縦長を少し優先
    return sorted(out, key=lambda r: not r["tall"])[:10] if out else []


def main(path):
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    outdir = Path("work") / spec["id"]
    outdir.mkdir(parents=True, exist_ok=True)
    credits, used = [], set()
    for i, slide in enumerate(spec["slides"]):
        dest = outdir / f"bg{i}.jpg"
        ok = False
        for q in [slide["query"]] + slide.get("fallback", []):
            try:
                results = [r for r in search(q) if r["url"] not in used]
            except Exception as e:
                print(f"[{i}] 検索失敗 {q}: {e}")
                results = []
            for r in results:
                try:
                    blob = get(r["url"])
                    if len(blob) < 40_000:
                        continue
                    dest.write_bytes(blob)
                    used.add(r["url"])
                    credits.append(f"slide{i}: {r['title']} / {r['artist']} / {r['license']} / {r['page']}")
                    print(f"[{i}] OK {q} -> {r['title']} ({r['license']})")
                    ok = True
                    break
                except Exception as e:
                    print(f"[{i}] 取得失敗 {r['url']}: {e}")
            time.sleep(1)
            if ok:
                break
        if not ok:
            print(f"[{i}] 写真なし（グラデーション背景にします）")
    Path("output").mkdir(exist_ok=True)
    (Path("output") / f"{spec['id']}_credits.txt").write_text("\n".join(credits) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
