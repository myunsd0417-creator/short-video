"""作った動画をBufferに予約する。
config.json の publish が false のあいだは、公開されない「下書き」として入れるだけ。
投稿済みの記録は output/posted.json に残す。
"""
import datetime as dt
import json
import os
import re
import subprocess
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


def video_url(vid):
    sha = subprocess.check_output(["git", "log", "-1", "--format=%H", "--", f"output/{vid}.mp4"]).decode().strip()
    return f"https://cdn.jsdelivr.net/gh/{REPO}@{sha}/output/{vid}.mp4"


def next_slots(n, taken):
    now = dt.datetime.now(JST) + dt.timedelta(minutes=30)
    out, day = [], now.date()
    while len(out) < n:
        for s in CFG["slots_jst"]:
            h, m = map(int, s.split(":"))
            t = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=JST)
            if t > now and t.isoformat() not in taken:
                out.append(t)
                if len(out) == n:
                    break
        day += dt.timedelta(days=1)
    return out


def main():
    publish = CFG.get("publish", False)
    now = dt.datetime.now(JST)
    done = {(p["id"], p["service"]) for p in STATE["posts"] if p.get("ok") and p.get("publish") == publish}
    vids = sorted(f.stem for f in Path("output").glob("*.mp4"))
    vids = [v for v in vids if v not in CFG.get("skip", [])]
    if not publish:
        vids = vids[:1]  # 下書きテストは1本だけ
    for service, channel in CFG["channels"].items():
        future = [p for p in STATE["posts"] if p["service"] == service and p.get("ok") and p.get("publish")
                  and dt.datetime.fromisoformat(p["dueAt"]) > now]
        room = CFG["max_queued_per_channel"] - len(future) if publish else 1
        todo = [v for v in vids if (v, service) not in done][:max(room, 0)]
        taken = {p["dueAt"] for p in future}
        slots = next_slots(len(todo), taken)
        for vid, when in zip(todo, slots):
            spec = json.loads(Path(f"content/{vid}.json").read_text(encoding="utf-8"))
            text = spec["caption"]
            cl = credits_line(vid)
            if cl:
                text += "\n\n" + cl
            inp = {
                "channelId": channel,
                "text": text,
                "schedulingType": "automatic",
                "mode": "customScheduled",
                "dueAt": when.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                "assets": [{"video": {"url": video_url(vid), "metadata": {"thumbnailOffset": 1200, "title": spec["title"]}}}],
                "metadata": {},
            }
            if service == "youtube":
                inp["metadata"]["youtube"] = {"title": spec["title"][:95], "categoryId": "26",
                                              "madeForKids": False, "notifySubscribers": True}
            if service == "tiktok":
                inp["metadata"]["tiktok"] = {"title": spec["title"][:90]}
            if not publish:
                inp["saveToDraft"] = True
            res = gql(MUTATION, {"input": inp})
            post = ((res.get("data") or {}).get("createPost") or {}).get("post")
            ok = bool(post)
            log(f"{vid} {service} {when.isoformat()} {'OK' if ok else 'NG'} {json.dumps(res, ensure_ascii=False)[:400]}")
            STATE["posts"].append({"id": vid, "service": service, "dueAt": when.isoformat(), "ok": ok,
                                   "publish": publish, "post_id": post and post.get("id")})
    STATE_PATH.write_text(json.dumps(STATE, ensure_ascii=False, indent=1), encoding="utf-8")
    Path("output/post_log.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
