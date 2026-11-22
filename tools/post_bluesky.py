"""台所用のBlueskyアカウントに、動画を1本投稿する（GitHub Actionsから1日2回動かす）。
- アカウント名は config.json の bluesky.handle、パスワードは GitHub のシークレット BSKY_APP_PASSWORD
- 投稿順は config.json の order（TikTok・YouTubeと同じ並び）。投稿済みは output/bluesky_posted.json に記録
- 動画は TikTok 版（<id>.mp4）を使う。説明文はハッシュタグまで
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

CFG = json.loads(Path("config.json").read_text(encoding="utf-8"))
BS = CFG.get("bluesky", {})
HANDLE = BS.get("handle", "")
PASSWORD = os.environ.get("BSKY_APP_PASSWORD", "")
PDS = BS.get("pds", "https://bsky.social")
STATE_PATH = Path("output/bluesky_posted.json")
LOG_PATH = Path("output/bluesky_log.txt")
LOG = []


def log(m):
    print(m)
    LOG.append(m)


def call(method, url, body=None, headers=None, raw=None, ctype="application/json"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"Content-Type": ctype} if data is not None else {}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            t = r.read()
            return json.loads(t) if t else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} {url.split('?')[0]}: {e.read().decode()[:300]}")


def pick_video(state):
    done = set(state["posted"])
    skip = set(CFG.get("skip", []))
    vids = sorted(f.stem for f in Path("output").glob("*.mp4") if not f.stem.endswith(("_yt", "_tn")))
    order = CFG.get("order", [])
    vids.sort(key=lambda v: (order.index(v) if v in order else len(order), v))
    for v in vids:
        if v not in done and v not in skip:
            return v
    return None


def main():
    if not (HANDLE and PASSWORD):
        log("Blueskyのアカウント名かアプリパスワードが未設定なので、何もしません")
        return
    state = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {"posted": []}
    vid = pick_video(state)
    if not vid:
        log("投稿する動画がありません")
        return
    spec = json.loads(Path(f"content/{vid}.json").read_text(encoding="utf-8"))
    text = spec["caption"]
    links = BS.get("links", [])
    tail = "".join(f"\n{l['label']}\n{l['url']}" for l in links)
    if len(text) + len(tail) > 295:  # Blueskyは300文字まで
        text = text[: 295 - len(tail)]
    text += tail
    # URLをタップできるようにする（バイト位置で指定）
    facets = []
    b = text.encode("utf-8")
    for l in links:
        u = l["url"].encode("utf-8")
        i = b.find(u)
        if i >= 0:
            facets.append({"index": {"byteStart": i, "byteEnd": i + len(u)},
                           "features": [{"$type": "app.bsky.richtext.facet#link", "uri": l["url"]}]})

    sess = call("POST", f"{PDS}/xrpc/com.atproto.server.createSession", {"identifier": HANDLE, "password": PASSWORD})
    did, jwt = sess["did"], sess["accessJwt"]
    auth = {"Authorization": f"Bearer {jwt}"}

    # 動画サービスに上げるための一時的な許可をもらう
    pds_host = urllib.parse.urlparse(sess.get("didDoc", {}).get("service", [{}])[0].get("serviceEndpoint", PDS)).netloc
    svc = call("GET", f"{PDS}/xrpc/com.atproto.server.getServiceAuth?" + urllib.parse.urlencode(
        {"aud": f"did:web:{pds_host}", "lxm": "com.atproto.repo.uploadBlob", "exp": int(time.time()) + 1800}), headers=auth)
    video = Path(f"output/{vid}.mp4").read_bytes()
    up = call("POST", "https://video.bsky.app/xrpc/app.bsky.video.uploadVideo?" + urllib.parse.urlencode(
        {"did": did, "name": f"{vid}.mp4"}), raw=video, ctype="video/mp4", headers={"Authorization": f"Bearer {svc['token']}"})
    job = up.get("jobId") or up.get("jobStatus", {}).get("jobId")
    blob = up.get("blob") or up.get("jobStatus", {}).get("blob")
    for _ in range(60):  # 動画の処理が終わるのを待つ
        if blob:
            break
        time.sleep(5)
        st = call("GET", "https://video.bsky.app/xrpc/app.bsky.video.getJobStatus?jobId=" + urllib.parse.quote(job), headers=auth)
        js = st.get("jobStatus", {})
        if js.get("state") == "JOB_STATE_FAILED":
            raise RuntimeError(f"動画の処理に失敗: {js.get('error')}")
        blob = js.get("blob")
    if not blob:
        raise RuntimeError("動画の処理が時間内に終わりませんでした")

    record = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        "langs": ["ja"],
        "facets": facets,
        "embed": {"$type": "app.bsky.embed.video", "video": blob, "aspectRatio": {"width": 1080, "height": 1920},
                  "alt": spec.get("title", "")},
    }
    res = call("POST", f"{PDS}/xrpc/com.atproto.repo.createRecord",
               {"repo": did, "collection": "app.bsky.feed.post", "record": record}, headers=auth)
    state["posted"].append(vid)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"{vid} 投稿OK {res.get('uri', '')}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"NG {e}")
    LOG_PATH.write_text(time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()) + "\n" + "\n".join(LOG) + "\n", encoding="utf-8")
    sys.exit(0)
