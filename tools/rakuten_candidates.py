"""商品紹介の動画ごとに、楽天市場の商品の候補を集めておく（YouTubeショッピングの条件を満たしたらすぐタグ付けできるように）。
必要なGitHubシークレット: RAKUTEN_APP_ID, RAKUTEN_ACCESS_KEY（任意: RAKUTEN_AFFILIATE_ID）
楽天ウェブサービスのアプリ設定で「WebサイトURL」に config.json の rakuten.referer を登録しておく
出力: output/rakuten/<id>.json と output/rakuten/README.md
"""
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

CFG = json.loads(Path("config.json").read_text(encoding="utf-8"))
APP = os.environ.get("RAKUTEN_APP_ID", "")
KEY = os.environ.get("RAKUTEN_ACCESS_KEY", "")
AFF = os.environ.get("RAKUTEN_AFFILIATE_ID", "")
REFERER = CFG.get("rakuten", {}).get("referer", "https://github.com/myunsd0417-creator/short-video")
ENDPOINT = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20220601"
OUT = Path("output/rakuten")


def search(keyword):
    p = {"applicationId": APP, "keyword": keyword, "format": "json", "formatVersion": 2,
         "hits": 10, "sort": "-reviewCount", "availability": 1}
    if AFF:
        p["affiliateId"] = AFF
    req = urllib.request.Request(f"{ENDPOINT}?{urllib.parse.urlencode(p)}",
                                 headers={"accessKey": KEY, "Referer": REFERER, "Origin": REFERER.split("/", 3)[0] + "//" + REFERER.split("/")[2]})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("Items", [])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if not (APP and KEY):
        (OUT / "README.md").write_text("楽天のアプリIDとアクセスキーが未登録のため、まだ候補を集めていません。\n", encoding="utf-8")
        print("skip: no rakuten keys")
        return
    lines = ["# 商品の候補（楽天市場・レビューの多い順）", "", "YouTubeショッピングの条件を満たしたら、ここから商品タグを付ける。", ""]
    for f in sorted(Path("content").glob("*.json")):
        spec = json.loads(f.read_text(encoding="utf-8"))
        if spec.get("kind", "product") != "product":
            continue
        result = {"id": spec["id"], "title": spec["title"], "items": []}
        for s in spec["slides"]:
            if s["type"] != "item":
                continue
            kw = "".join(s["big"]).replace("→", " ").replace("の", " ").strip()
            try:
                items = search(kw)
            except Exception as e:
                print(spec["id"], kw, "NG", e)
                items = []
            top = [{"name": i.get("itemName", "")[:80], "price": i.get("itemPrice"), "reviews": i.get("reviewCount"),
                    "rating": i.get("reviewAverage"), "url": i.get("affiliateUrl") or i.get("itemUrl")} for i in items[:3]]
            result["items"].append({"keyword": kw, "candidates": top})
            time.sleep(1.6)
        (OUT / f"{spec['id']}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        lines.append(f"## {spec['id']} {spec['title']}")
        for it in result["items"]:
            lines.append(f"- {it['keyword']}")
            for c in it["candidates"]:
                lines.append(f"  - {c['name']}（{c['price']}円・レビュー{c['reviews']}件）")
        lines.append("")
    (OUT / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
