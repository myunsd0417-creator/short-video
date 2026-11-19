"""YouTube/TikTokの投稿が止まった時の調査用。Bufferのチャンネル状態と、最近の投稿の状態・エラーを output/channel_check.json に保存（キーは保存しない）"""
import json, os, urllib.request
KEY = os.environ["BUFFER_API_KEY"]
ORG = "6715160d6ebd9c191c9ccab2"
CFG = json.load(open("config.json", encoding="utf-8"))
def gql(q, v=None):
    req = urllib.request.Request("https://api.buffer.com", data=json.dumps({"query": q, "variables": v or {}}).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json", "User-Agent": "short-video-bot"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r: return json.loads(r.read())
    except urllib.error.HTTPError as e: return {"http_error": e.code, "body": e.read().decode()[:800]}
def fields(name):
    r = gql('query($n:String!){__type(name:$n){fields{name type{kind name ofType{kind name ofType{kind name}}}} enumValues{name}}}', {"n": name})
    return ((r.get("data") or {}).get("__type") or {})
def base(t):
    while t and t.get("ofType"): t = t["ofType"]
    return t or {}
def scalars(name):
    out = []
    for f in fields(name).get("fields") or []:
        b = base(f["type"])
        if b.get("kind") in ("SCALAR", "ENUM"): out.append(f["name"])
    return out
out = {"types": {n: fields(n) for n in ["Channel", "Post", "PostStatus", "PostError", "PostNotice"]}}
chf = scalars("Channel")
out["channels"] = gql('query($id:OrganizationId!){channels(input:{organizationId:$id}){%s}}' % " ".join(chf), {"id": ORG})
pf = scalars("Post")
# エラー関連のオブジェクト項目も取る
extra = []
for f in fields("Post").get("fields") or []:
    b = base(f["type"])
    if b.get("kind") == "OBJECT" and any(k in f["name"].lower() for k in ("error", "notice", "warning")):
        sub = scalars(b["name"])
        if sub: extra.append("%s{%s}" % (f["name"], " ".join(sub)))
statuses = [e["name"] for e in (fields("PostStatus").get("enumValues") or [])]
out["statuses"] = statuses
yt = CFG["channels"]["youtube"]
res = {}
for st in statuses:
    q = 'query($org:OrganizationId!,$ch:[ChannelId!]){posts(first:20,input:{organizationId:$org,filter:{status:[%s],channelIds:$ch}}){edges{node{%s}}}}' % (st, " ".join(pf + extra))
    res[st] = gql(q, {"org": ORG, "ch": [yt]})
out["youtube_posts_by_status"] = res
open("output/channel_check.json", "w").write(json.dumps(out, ensure_ascii=False, indent=1))
print(json.dumps(out["channels"], ensure_ascii=False)[:2000])
for st, r in res.items():
    edges = ((r.get("data") or {}).get("posts") or {}).get("edges") or []
    print(st, len(edges), json.dumps(r.get("errors") or [e["node"] for e in edges[:3]], ensure_ascii=False)[:1500])
