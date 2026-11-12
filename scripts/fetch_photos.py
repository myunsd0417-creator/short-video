"""Openverseから商用利用OK（CC0・パブリックドメイン）の写真を取ってくる。
使い方: python scripts/fetch_photos.py content/001.json
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = "short-video-bot/1.0 (personal project)"
API = "https://api.openverse.org/v1/images/"


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


BAD_WORDS = ("png", "clipart", "clip art", "transparent", "illustration", "vector", "icon", "drawing", "cartoon")


def search(query, licenses="cc0,pdm"):
    params = {
        "q": query,
        "license": licenses,
        "category": "photograph",
        "extension": "jpg",
        "page_size": "40",
        "mature": "false",
    }
    data = json.loads(get(API + "?" + urllib.parse.urlencode(params)))
    results = [
        r for r in data.get("results", [])
        if not any(w in (r.get("title") or "").lower() for w in BAD_WORDS)
        and (r.get("width") or 0) >= 800
    ]
    print(f"  search '{query}' [{licenses}]: {len(results)} usable")
    # 縦長に近いものを優先、次に大きいもの
    def score(r):
        w, h = r.get("width") or 0, r.get("height") or 0
        tall = 1 if h >= w else 0
        return (tall, w * h)
    return sorted(results, key=score, reverse=True)


def main(path):
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    outdir = Path("work") / spec["id"]
    outdir.mkdir(parents=True, exist_ok=True)
    credits = []
    used = set()
    for i, slide in enumerate(spec["slides"]):
        dest = outdir / f"bg{i}.jpg"
        results = []
        queries = [slide["query"]] + slide.get("fallback", []) + ["kitchen"]
        for q in queries:
            for lic in ("cc0,pdm", "by"):
                try:
                    results = search(q, lic)
                except Exception as e:
                    print(f"[{i}] 検索失敗 {q}: {e}")
                    results = []
                results = [r for r in results if r["url"] not in used]
                if results:
                    break
                time.sleep(1)
            if results:
                break
        ok = False
        for r in results:
            if r["url"] in used:
                continue
            try:
                blob = get(r["url"], timeout=40)
                if len(blob) < 30_000:
                    continue
                dest.write_bytes(blob)
                used.add(r["url"])
                credits.append(
                    f"slide{i}: {r.get('title','')} / {r.get('creator','')} / "
                    f"{r.get('license','')} / {r.get('foreign_landing_url','')}"
                )
                print(f"[{i}] {slide['query']} -> {r['url']}")
                ok = True
                break
            except Exception as e:
                print(f"[{i}] 取得失敗 {r.get('url')}: {e}")
        if not ok:
            print(f"[{i}] 写真なし（グラデーション背景にします）")
        time.sleep(1)
    Path("output").mkdir(exist_ok=True)
    (Path("output") / f"{spec['id']}_credits.txt").write_text(
        "\n".join(credits) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main(sys.argv[1])
