"""作った動画をBufferに予約する。
config.json の publish が false のあいだは、公開されない「下書き」として入れるだけ。
投稿済みの記録は output/posted.json に残す。
"""
import datetime as dt
import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

KEY = os.environ["BUFFER_API_KEY"]
REPO = os.environ.get("GITHUB_REPOSITORY", "myunsd0417-creator/short-video")
JST = dt.timezone(dt.timedelta(hours=9))
CFG = json.loads(Path("config.json").read_text(encoding="utf-8"))
STATE_PATH = Path("output/posted.json")
STATE = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {"posts": []}
LOG = []


def log(msg):
    print(msg)
    LOG.append(msg)


def gql(query, variables):
    req = urllib.request.Request(
        "https://api.buffer.com",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json", "User-Agent": "short-video-bot"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode()[:800]}


MUTATION = """
mutation($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess { post { id dueAt } }
    ... on MutationError { message }
  }
}"""


def credits_line(vid):
    p = Path(f"output/{vid}_credits.txt")
    if not p.exists():
        return ""
    names = []
    for line in p.read_text(encoding="utf-8").splitlines():
        parts = [x.strip() for x in line.split(" / ")]
        if len(parts) >= 3 and parts[2].upper().startswith("CC BY"):
            names.append(f"{parts[1][:40]}（{parts[2]}）")
    return ("写真: Wikimedia Commons " + "、".join(names)) if names else ""


def video_url(vid, service="tiktok", notify=False):
    name = f"{vid}.mp4"
    if service == "youtube" and Path(f"output/{vid}_yt.mp4").exists():
        name = f"{vid}_yt.mp4"
    if service == "tiktok" and notify and Path(f"output/{vid}_tn.mp4").exists():
        name = f"{vid}_tn.mp4"  # 手動で音源を付ける枠はBGMなし版
    sha = subprocess.check_output(["git", "log", "-1", "--format=%H", "--", f"output/{name}"]).decode().strip()
    return f"https://cdn.jsdelivr.net/gh/{REPO}@{sha}/output/{name}"


def next_slots(n, taken, service="tiktok", history=()):
    """空いている枠を早い順に n 個。
    YouTubeはBufferの「24時間で2本まで」の制限があるので、2本前の投稿から24時間＋余裕を空ける。"""
    now = dt.datetime.now(JST) + dt.timedelta(minutes=30)
    slots = CFG["slots_jst"]
    gap = None
    if service == "youtube" and CFG.get("youtube_slots_jst"):
        slots = CFG["youtube_slots_jst"]
        gap = dt.timedelta(minutes=CFG.get("youtube_gap_min", 1480))
    hist = sorted(history)
    out, day = [], now.date()
    while len(out) < n:
        for s in slots:
            h, m = map(int, s.split(":"))
            t = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=JST)
            if t <= now or t.isoformat() in taken:
                continue
            per_day = sum(1 for x in list(taken) + [o.isoformat() for o in out] if x[:10] == t.date().isoformat())
            if gap is None and per_day >= len(slots):  # 時刻を変えた日でも1日の本数は増やさない
                continue
            if gap is not None:
                before = [x for x in hist if x < t]
                after = [x for x in hist if x > t]
                if before and t - before[-1] < dt.timedelta(hours=5):
                    continue
                if len(before) >= 2 and t - before[-2] < gap:
                    continue
                if after:  # 先の予約とぶつかる枠は使わない
                    continue
                hist = sorted(hist + [t])
            out.append(t)
            if len(out) == n:
                break
        day += dt.timedelta(days=1)
    return out


ERRQ = """query($org:OrganizationId!,$ch:[ChannelId!]){posts(first:50,input:{organizationId:$org,filter:{status:[error],channelIds:$ch}}){edges{node{id error{message rawError}}}}}"""


def mark_failed():
    """Bufferで投稿に失敗した予約を見つけて、入れ直せるように記録から外す"""
    res = gql(ERRQ, {"org": CFG.get("org", "6715160d6ebd9c191c9ccab2"), "ch": list(CFG["channels"].values())})
    edges = ((res.get("data") or {}).get("posts") or {}).get("edges") or []
    bad = {e["node"]["id"]: (e["node"].get("error") or {}) for e in edges}
    for p in STATE["posts"]:
        if p.get("ok") and p.get("post_id") in bad:
            p["ok"] = False
            p["failed"] = (bad[p["post_id"]].get("rawError") or bad[p["post_id"]].get("message") or "")[:200]
            log(f"{p['id']} {p['service']} {p['dueAt']} NG(投稿失敗→入れ直し) {p['failed']}")


def existing_posts():
    """Bufferにすでにある予約・投稿済みの中身（同じ動画を2回出さないため）"""
    q = """query($org: OrganizationId!, $ch: [ChannelId!], $after: String) {
      posts(first: 100, after: $after, input: {organizationId: $org, filter: {status: [scheduled, sent], channelIds: $ch}}) {
        edges { node { channelId text assets { source } } }
        pageInfo { endCursor hasNextPage }
      }
    }"""
    seen, after = [], None
    try:
        for _ in range(10):
            res = gql(q, {"org": "6715160d6ebd9c191c9ccab2", "ch": list(CFG["channels"].values()), "after": after})
            data = (res.get("data") or {}).get("posts")
            if not data:
                log(f"既存の投稿を読めませんでした: {json.dumps(res, ensure_ascii=False)[:200]}")
                break
            for e in data["edges"]:
                n = e["node"]
                srcs = " ".join(a.get("source") or "" for a in (n.get("assets") or []))
                seen.append((n["channelId"], (n.get("text") or ""), srcs))
            if not data["pageInfo"]["hasNextPage"]:
                break
            after = data["pageInfo"]["endCursor"]
    except Exception as e:
        log(f"既存の投稿の確認に失敗: {e}")
    return seen


def already_there(seen, channel, vid, spec):
    key = spec["caption"].splitlines()[0].strip()
    for ch, text, srcs in seen:
        if ch != channel:
            continue
        if f"/output/{vid}." in srcs or f"/output/{vid}_" in srcs or (key and key in text):
            return True
    return False


def main():
    publish = CFG.get("publish", False)
    now = dt.datetime.now(JST)
    if publish:
        mark_failed()
    done = {(p["id"], p["service"]) for p in STATE["posts"] if p.get("ok") and p.get("publish") == publish}
    vids = sorted(f.stem for f in Path("output").glob("*.mp4") if not f.stem.endswith(("_yt", "_tn")))
    vids = [v for v in vids if v not in CFG.get("skip", [])]
    order = CFG.get("order", [])  # 並び順の指定（知識系と商品紹介を混ぜるため）
    vids.sort(key=lambda v: (order.index(v) if v in order else len(order), v))
    if not publish:
        vids = vids[:1]  # 下書きテストは1本だけ
    for service, channel in CFG["channels"].items():
        future = [p for p in STATE["posts"] if p["service"] == service and p.get("ok") and p.get("publish")
                  and dt.datetime.fromisoformat(p["dueAt"]) > now]
        room = CFG["max_queued_per_channel"] - len(future) if publish else 1
        todo = [v for v in vids if (v, service) not in done][:max(room, 0)]
        taken = {p["dueAt"] for p in future}
        history = [dt.datetime.fromisoformat(p["dueAt"]) for p in STATE["posts"]
                   if p["service"] == service and p.get("ok") and p.get("publish")]
        blocked = []  # Bufferに「1日の上限」で断られた時刻（次の枠へずらす）
        seen = existing_posts() if publish else []
        for v in [v for v in todo if already_there(seen, channel, v, json.loads(Path(f"content/{v}.json").read_text(encoding="utf-8")))]:
            log(f"{v} {service} はBufferに既にあるので追加しません")  # 記録だけ合わせて二重投稿を防ぐ
            STATE["posts"].append({"id": v, "service": service, "dueAt": now.isoformat(), "ok": True,
                                   "publish": publish, "post_id": None, "note": "already in buffer"})
            todo.remove(v)
        queue = list(todo)
        while queue:
            vid = queue.pop(0)
            slots = next_slots(1, taken | {b.isoformat() for b in blocked}, service, history + blocked)
            if not slots:
                break
            when = slots[0]
            notify = service == "tiktok" and when.strftime("%H:%M") in CFG.get("tiktok_notify_slots", [])
            spec = json.loads(Path(f"content/{vid}.json").read_text(encoding="utf-8"))
            text = "【めんどくさがり一人暮らしの台所】\n" + spec["caption"]  # シリーズ名でフォローする理由を作る
            # 写真・声のクレジットは動画の最後に小さく表示している（説明文はハッシュタグまで）
            inp = {
                "channelId": channel,
                "text": text,
                "schedulingType": "notification" if notify else "automatic",
                "mode": "customScheduled",
                "dueAt": when.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                "assets": [{"video": {"url": video_url(vid, service, notify), "metadata": {"thumbnailOffset": 1200, "title": spec["title"]}}}],
                "metadata": {},
            }
            if service == "youtube":
                inp["text"] = text + "\n#shorts"
                inp["metadata"]["youtube"] = {"title": spec["title"][:95], "categoryId": "26",
                                              "madeForKids": False, "notifySubscribers": True}
            if service == "tiktok":
                inp["metadata"]["tiktok"] = {"title": spec["title"][:90]}
            if not publish:
                inp["saveToDraft"] = True
            url = inp["assets"][0]["video"]["url"]
            for attempt in range(7):
                try:  # 先にCDNへ取りに行って、Bufferが読めるようにしておく
                    urllib.request.urlopen(urllib.request.Request(url, headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                        "Accept": "video/mp4,*/*"}), timeout=90).read()
                except Exception as e:
                    log(f"warmup {vid}: {e}")
                if attempt >= 3:  # CDNがだめならGitHubの直接リンクで試す
                    url = url.replace("https://cdn.jsdelivr.net/gh/" + REPO + "@", "https://raw.githubusercontent.com/" + REPO + "/")
                    inp["assets"][0]["video"]["url"] = url
                res = gql(MUTATION, {"input": inp})
                msg = json.dumps(res, ensure_ascii=False)
                if "could not be read" not in msg:
                    break
                time.sleep(30)
            log(f"{vid} {service} url={url}")
            post = ((res.get("data") or {}).get("createPost") or {}).get("post")
            ok = bool(post)
            log(f"{vid} {service} {when.isoformat()} {'OK' if ok else 'NG'} {json.dumps(res, ensure_ascii=False)[:400]}")
            if not ok and service == "youtube" and re.search(r"maximum number of posts|limit of 2", msg) and len(blocked) < 4:
                blocked.append(when)  # 同じ動画を次の枠で入れ直す（記録はしない）
                queue.insert(0, vid)
                log(f"{vid} youtube 上限のため次の枠で再試行")
                continue
            if ok:
                taken.add(when.isoformat())
                history.append(when)
            STATE["posts"].append({"id": vid, "service": service, "dueAt": when.isoformat(), "ok": ok,
                                   "publish": publish, "post_id": post and post.get("id")})
    STATE_PATH.write_text(json.dumps(STATE, ensure_ascii=False, indent=1), encoding="utf-8")
    Path("output/post_log.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
