"""台所用Blueskyアカウントの自動投稿。
使い方:
  python tools/post_bluesky.py          動画を1本投稿し、自分の返信で「3行まとめ」を付ける
  python tools/post_bluesky.py weekly   その週に投稿した動画のまとめ投稿をする
  python tools/post_bluesky.py pin      自己紹介の投稿を作ってプロフィールに固定する（1回だけ）
- アカウント名は config.json の bluesky.handle、パスワードは GitHub のシークレット BSKY_APP_PASSWORD
- 投稿順は config.json の order。投稿済みは output/bluesky_posted.json に記録
- 他の人への自動いいね・フォロー・返信はしない（Blueskyのルールでスパム扱いになるため）
"""
import datetime as dt
import json
import os
import re
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


def load_state():
    s = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}
    s.setdefault("posted", [])
    s.setdefault("history", [])  # {"id", "at"}
    return s


def save_state(s):
    STATE_PATH.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


def login():
    sess = call("POST", f"{PDS}/xrpc/com.atproto.server.createSession", {"identifier": HANDLE, "password": PASSWORD})
    return sess, {"Authorization": f"Bearer {sess['accessJwt']}"}


def links_tail():
    return "".join(f"\n{l['label']}\n{l['url']}" for l in BS.get("links", []))


def facets_for(text):
    """URLとハッシュタグを押せるようにする（位置はバイトで指定）"""
    facets = []
    for m in re.finditer(r"https?://\S+", text):
        s = len(text[: m.start()].encode("utf-8"))
        e = s + len(m.group(0).encode("utf-8"))
        facets.append({"index": {"byteStart": s, "byteEnd": e},
                       "features": [{"$type": "app.bsky.richtext.facet#link", "uri": m.group(0)}]})
    for m in re.finditer(r"(?:(?<=\s)|^)#([^\s#]+)", text):
        s = len(text[: m.start()].encode("utf-8"))
        e = s + len(m.group(0).encode("utf-8"))
        facets.append({"index": {"byteStart": s, "byteEnd": e},
                       "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": m.group(1)}]})
    return facets


def fit(text, tail="", limit=295):
    """Blueskyは300文字まで。末尾（リンク）は残して本文を詰める"""
    if len(text) + len(tail) > limit:
        text = text[: limit - len(tail)]
    return text + tail


def create_post(sess, auth, text, embed=None, reply=None):
    record = {"$type": "app.bsky.feed.post", "text": text, "langs": ["ja"], "facets": facets_for(text),
              "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())}
    if embed:
        record["embed"] = embed
    if reply:
        record["reply"] = reply
    return call("POST", f"{PDS}/xrpc/com.atproto.repo.createRecord",
                {"repo": sess["did"], "collection": "app.bsky.feed.post", "record": record}, headers=auth)


def upload_video(sess, auth, path, name):
    pds_host = urllib.parse.urlparse(sess.get("didDoc", {}).get("service", [{}])[0].get("serviceEndpoint", PDS)).netloc
    svc = call("GET", f"{PDS}/xrpc/com.atproto.server.getServiceAuth?" + urllib.parse.urlencode(
        {"aud": f"did:web:{pds_host}", "lxm": "com.atproto.repo.uploadBlob", "exp": int(time.time()) + 1800}), headers=auth)
    up = call("POST", "https://video.bsky.app/xrpc/app.bsky.video.uploadVideo?" + urllib.parse.urlencode(
        {"did": sess["did"], "name": name}), raw=path.read_bytes(), ctype="video/mp4",
        headers={"Authorization": f"Bearer {svc['token']}"})
    job = up.get("jobId") or up.get("jobStatus", {}).get("jobId")
    blob = up.get("blob") or up.get("jobStatus", {}).get("blob")
    for _ in range(60):  # 動画の処理が終わるのを待つ
        if blob:
            return blob
        time.sleep(5)
        st = call("GET", "https://video.bsky.app/xrpc/app.bsky.video.getJobStatus?jobId=" + urllib.parse.quote(job), headers=auth)
        js = st.get("jobStatus", {})
        if js.get("state") == "JOB_STATE_FAILED":
            raise RuntimeError(f"動画の処理に失敗: {js.get('error')}")
        blob = js.get("blob")
    raise RuntimeError("動画の処理が時間内に終わりませんでした")


def summary_text(spec):
    """動画の要点を文字で（検索に引っかかるように）"""
    items = [s for s in spec["slides"] if s["type"] == "item"]
    lines = ["【3行まとめ】"]
    for n, s in zip("①②③", items):
        head = "".join(s["big"])
        sub = s.get("sub", "")
        lines.append(f"{n}{head}" + (f"：{sub}" if sub else ""))
    end = [s for s in spec["slides"] if s["type"] == "end"]
    if end:
        lines.append("→ " + "".join(end[0]["big"]))
    ref = [l for l in spec["caption"].splitlines() if l.startswith("参考")]
    if ref:
        lines.append(ref[0])
    return fit("\n".join(lines))


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


def post_video():
    state = load_state()
    vid = pick_video(state)
    if not vid:
        log("投稿する動画がありません")
        return
    spec = json.loads(Path(f"content/{vid}.json").read_text(encoding="utf-8"))
    sess, auth = login()
    blob = upload_video(sess, auth, Path(f"output/{vid}.mp4"), f"{vid}.mp4")
    embed = {"$type": "app.bsky.embed.video", "video": blob, "aspectRatio": {"width": 1080, "height": 1920},
             "alt": spec.get("title", "")}
    res = create_post(sess, auth, fit(spec["caption"], links_tail()), embed=embed)
    state["posted"].append(vid)
    state["history"].append({"id": vid, "at": dt.datetime.now(dt.timezone.utc).isoformat()})
    save_state(state)
    log(f"{vid} 投稿OK {res.get('uri', '')}")
    try:  # 自分の投稿への返信なので、他の人に通知は飛ばない
        ref = {"uri": res["uri"], "cid": res["cid"]}
        create_post(sess, auth, summary_text(spec), reply={"root": ref, "parent": ref})
        log(f"{vid} 3行まとめOK")
    except Exception as e:
        log(f"{vid} 3行まとめNG {e}")


def post_weekly():
    state = load_state()
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)
    ids = [h["id"] for h in state["history"] if dt.datetime.fromisoformat(h["at"]) > since]
    if not ids:
        log("今週の投稿がないので、まとめはなし")
        return
    titles = ["・" + json.loads(Path(f"content/{v}.json").read_text(encoding="utf-8"))["title"] for v in dict.fromkeys(ids)]
    head = "【今週のまとめ】めんどくさがり一人暮らしの台所\n"
    tail = "\n保存して、あとで見返してね\n#一人暮らし #自炊" + links_tail()
    sess, auth = login()
    res = create_post(sess, auth, fit(head + "\n".join(titles), tail))
    log(f"週のまとめOK {res.get('uri', '')}")


def pin_intro():
    sess, auth = login()
    text = ("めんどくさがりの一人暮らしが、台所をラクにする道具と工夫を毎日紹介しています🍳\n"
            "洗い物・自炊・保存・片付け・節約。知っているだけでラクになることを、短い動画で。\n"
            "#一人暮らし #自炊 #時短家事" + links_tail())
    res = create_post(sess, auth, fit(text))
    prof = call("GET", f"{PDS}/xrpc/com.atproto.repo.getRecord?" + urllib.parse.urlencode(
        {"repo": sess["did"], "collection": "app.bsky.actor.profile", "rkey": "self"}), headers=auth)
    record = prof.get("value", {"$type": "app.bsky.actor.profile"})
    record["pinnedPost"] = {"uri": res["uri"], "cid": res["cid"]}  # 名前・自己紹介などはそのまま残す
    body = {"repo": sess["did"], "collection": "app.bsky.actor.profile", "rkey": "self", "record": record}
    if prof.get("cid"):
        body["swapRecord"] = prof["cid"]
    call("POST", f"{PDS}/xrpc/com.atproto.repo.putRecord", body, headers=auth)
    log(f"自己紹介を固定OK {res.get('uri', '')}")


def auto():
    """1時間ごとに起動され、必要な時だけ投稿する（予約実行の取りこぼし対策）"""
    jst = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    state = load_state()
    last = max((dt.datetime.fromisoformat(h["at"]) for h in state["history"]), default=None)
    in_slot = 12 <= jst.hour < 16 or 20 <= jst.hour < 24
    if in_slot and (last is None or dt.datetime.now(dt.timezone.utc) - last > dt.timedelta(hours=5)):
        post_video()
    else:
        log(f"動画の投稿なし（{jst:%H:%M}、前回 {last}）")
    week = jst.strftime("%G-W%V")
    state = load_state()
    if jst.weekday() == 6 and jst.hour >= 20 and state.get("weekly_done") != week:
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)
        if sum(dt.datetime.fromisoformat(h["at"]) > since for h in state["history"]) >= 2:
            post_weekly()
        state = load_state()
        state["weekly_done"] = week
        save_state(state)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "post"
    try:
        if not (HANDLE and PASSWORD):
            log("Blueskyのアカウント名かアプリパスワードが未設定なので、何もしません")
        elif mode == "weekly":
            post_weekly()
        elif mode == "pin":
            pin_intro()
        elif mode == "auto":
            auto()
        else:
            post_video()
    except Exception as e:
        log(f"NG {e}")
    LOG_PATH.write_text(time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()) + f" ({mode})\n" + "\n".join(LOG) + "\n",
                        encoding="utf-8")
    sys.exit(0)
