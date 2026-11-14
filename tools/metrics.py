"""投稿済み動画の数字（再生数など）をBufferから集めて output/metrics.json と output/metrics.md に保存する。"""
import json
import os
import urllib.request
from pathlib import Path

KEY = os.environ["BUFFER_API_KEY"]
ORG = "6715160d6ebd9c191c9ccab2"
CFG = json.loads(Path("config.json").read_text(encoding="utf-8"))


def gql(q, v):
    req = urllib.request.Request("https://api.buffer.com", data=json.dumps({"query": q, "variables": v}).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json", "User-Agent": "short-video-bot"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


Q = """query($org: OrganizationId!, $ch: [ChannelId!], $after: String) {
  posts(first: 50, after: $after, input: {organizationId: $org, filter: {status: [sent], channelIds: $ch}}) {
    edges { node { id dueAt channelId metrics { type name value unit } metricsUpdatedAt } }
    pageInfo { endCursor hasNextPage }
  }
}"""

state = json.loads(Path("output/posted.json").read_text(encoding="utf-8")) if Path("output/posted.json").exists() else {"posts": []}
pid2vid = {p["post_id"]: p["id"] for p in state["posts"] if p.get("post_id")}
svc = {v: k for k, v in CFG["channels"].items()}
rows, after = [], None
try:
    while True:
        res = gql(Q, {"org": ORG, "ch": list(CFG["channels"].values()), "after": after})
        if "errors" in res:
            print("errors:", json.dumps(res["errors"], ensure_ascii=False)[:500])
            break
        data = res["data"]["posts"]
        for e in data["edges"]:
            n = e["node"]
            rows.append({"video": pid2vid.get(n["id"], "?"), "service": svc.get(n["channelId"], n["channelId"]),
                         "dueAt": n["dueAt"], "updated": n.get("metricsUpdatedAt"),
                         "metrics": {m["name"]: m["value"] for m in (n.get("metrics") or [])}})
        if not data["pageInfo"]["hasNextPage"]:
            break
        after = data["pageInfo"]["endCursor"]
except Exception as ex:
    print("metrics failed:", ex)

Path("output/metrics.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
titles = {f.stem: json.loads(f.read_text(encoding="utf-8"))["title"] for f in Path("content").glob("*.json")}
old = [r for r in rows if r["video"] == "?"]
ours = [r for r in rows if r["video"] != "?"]
def avg(rs, k):
    vals = [float(r["metrics"].get(k, 0) or 0) for r in rs]
    return round(sum(vals) / len(vals), 1) if vals else 0
lines = ["# 投稿の数字（自動更新）", "",
         f"比較用（ジャンル変更前の過去投稿 {len(old)}本の平均）: 再生 {avg(old, 'Video Views')}、平均視聴秒数 {avg(old, 'Avg. Watch Time (sec)')}",
         f"新ジャンル {len(ours)}本の平均: 再生 {avg(ours, 'Video Views')}、平均視聴秒数 {avg(ours, 'Avg. Watch Time (sec)')}",
         "", "| 動画 | 媒体 | 投稿日時 | 数字 |", "|---|---|---|---|"]
for r in sorted(ours, key=lambda r: r["dueAt"] or ""):
    m = "、".join(f"{k}: {v}" for k, v in r["metrics"].items()) or "まだ集計なし"
    lines.append(f"| {r['video']} {titles.get(r['video'], '')} | {r['service']} | {r['dueAt']} | {m} |")
# 冒頭の型ごとの平均（TikTok）
types = {f.stem: json.loads(f.read_text(encoding="utf-8")).get("hook_type", "question") for f in Path("content").glob("*.json")}
groups = {}
for r in ours:
    if r["service"] == "tiktok":
        groups.setdefault(types.get(r["video"], "?"), []).append(r)
lines += ["", "## 冒頭の型ごとの平均（TikTok）", "", "| 型 | 本数 | 平均再生 | 平均視聴秒数 |", "|---|---|---|---|"]
for k, rs in sorted(groups.items()):
    lines.append(f"| {k} | {len(rs)} | {avg(rs, 'Video Views')} | {avg(rs, 'Avg. Watch Time (sec)')} |")
Path("output/metrics.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"{len(rows)} posts")
