"""Bufferにまだ予約中（未投稿）の動画を取り消して、作り直した動画で入れ直せるようにする。
使い方: python tools/requeue.py 004 007 008 009 010
取り消せたものは output/posted.json から外す（このあと post_buffer.py が新しい動画で予約し直す）。
"""
import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path

KEY = os.environ["BUFFER_API_KEY"]
STATE_PATH = Path("output/posted.json")


def gql(q, v=None):
    req = urllib.request.Request("https://api.buffer.com", data=json.dumps({"query": q, "variables": v or {}}).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json", "User-Agent": "short-video-bot"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode()[:500]}


def tname(t):
    while t.get("ofType"):
        t = t["ofType"]
    return t["name"]


def main(ids):
    log = []
    m = gql("{__schema{mutationType{fields{name args{name type{kind name ofType{kind name ofType{kind name}}}}}}}}")
    fields = {f["name"]: f for f in m["data"]["__schema"]["mutationType"]["fields"]}
    log.append("mutations: " + ", ".join(sorted(fields)))
    f = fields.get("deletePost")
    if not f:
        log.append("deletePost がないので取り消せません")
        Path("output/requeue_log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
        return
    arg = f["args"][0]
    itype = tname(arg["type"])
    info = gql('query($n:String!){__type(name:$n){kind inputFields{name}}}', {"n": itype})
    ty = (info.get("data") or {}).get("__type") or {}
    log.append(f"deletePost({arg['name']}: {itype}) fields={[x['name'] for x in ty.get('inputFields') or []]}")
    if ty.get("kind") == "INPUT_OBJECT":
        q = f"mutation($v:{itype}!){{deletePost({arg['name']}:$v){{__typename ... on MutationError{{message}}}}}}"
        make = lambda pid: {"id": pid}
    else:
        q = f"mutation($v:{itype}!){{deletePost({arg['name']}:$v){{__typename ... on MutationError{{message}}}}}}"
        make = lambda pid: pid
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    now = dt.datetime.now(dt.timezone.utc)
    keep = []
    for p in state["posts"]:
        future = dt.datetime.fromisoformat(p["dueAt"]) > now + dt.timedelta(minutes=20)
        if p["id"] in ids and p.get("ok") and p.get("publish") and future and p.get("post_id"):
            r = gql(q, {"v": make(p["post_id"])})
            res = (r.get("data") or {}).get("deletePost") or {}
            ok = bool(res) and "message" not in res and "errors" not in r
            log.append(f"{p['id']} {p['service']} {p['dueAt']} 取り消し{'OK' if ok else 'NG'} {json.dumps(r, ensure_ascii=False)[:200]}")
            if ok:
                continue
        keep.append(p)
    state["posts"] = keep
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    Path("output/requeue_log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    print("\n".join(log))


if __name__ == "__main__":
    main(sys.argv[1:])
