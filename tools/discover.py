"""Bufferのチャンネル一覧と投稿APIの形を調べて output/ に保存する（キー自体は保存しない）"""
import json, os, urllib.request
KEY = os.environ["BUFFER_API_KEY"]
def gql(q, v=None):
    req = urllib.request.Request("https://api.buffer.com", data=json.dumps({"query": q, "variables": v or {}}).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json", "User-Agent": "short-video-bot"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read())
    except urllib.error.HTTPError as e: return {"http_error": e.code, "body": e.read().decode()[:500]}
out = {}
orgs = gql("query{account{organizations{id name}}}")
out["orgs"] = orgs
chans = []
for o in (orgs.get("data") or {}).get("account", {}).get("organizations", []):
    c = gql('query($id:OrganizationId!){channels(input:{organizationId:$id}){id name displayName service isQueuePaused}}', {"id": o["id"]})
    if "errors" in c:
        c = gql('query($id:String!){channels(input:{organizationId:$id}){id name displayName service isQueuePaused}}', {"id": o["id"]})
    out.setdefault("channels_raw", []).append(c)
    chans += (c.get("data") or {}).get("channels") or []
out["channels"] = chans
def t(name):
    return gql('query($n:String!){__type(name:$n){name kind inputFields{name type{kind name ofType{kind name ofType{kind name}}}} enumValues{name}}}', {"n": name})
types = {}
for n in ["CreatePostInput","PostInputMetaData","AssetsInput","VideoAssetInput","VideoMetadataInput","SchedulingType","ShareMode","YoutubePostMetadataInput","TikTokPostMetadataInput","TiktokPostMetadataInput"]:
    types[n] = t(n)
out["types"] = types
open("output/buffer_discovery.json","w").write(json.dumps(out, ensure_ascii=False, indent=1))
print(json.dumps(chans, ensure_ascii=False))
