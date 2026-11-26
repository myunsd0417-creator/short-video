"""写真背景＋大きな文字の縦型ショート動画を作る。
使い方: python scripts/render.py content/001.json
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1080, 1920, 30
FONT = os.environ.get(
    "JP_FONT", "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
)
YELLOW = (255, 214, 0)
ACCENT = (240, 84, 60)
WHITE = (255, 255, 255)
DUR = {"hook": 2.2, "item": 2.8, "end": 2.6}


def font(size):
    return ImageFont.truetype(FONT, size, index=0)


def cover(img):
    img = img.convert("RGB")
    s = max(W / img.width, H / img.height) * 1.08
    img = img.resize((int(img.width * s) + 1, int(img.height * s) + 1), Image.LANCZOS)
    x, y = (img.width - int(W * 1.08)) // 2, (img.height - int(H * 1.08)) // 2
    return img.crop((x, y, x + int(W * 1.08), y + int(H * 1.08)))


def gradient_bg():
    img = Image.new("RGB", (int(W * 1.08), int(H * 1.08)))
    d = ImageDraw.Draw(img)
    for y in range(img.height):
        t = y / img.height
        d.line([(0, y), (img.width, y)], fill=(int(70 + 90 * t), int(40 + 30 * t), int(30 + 10 * t)))
    return img


def shade():
    """写真の上に重ねる暗いグラデーション（文字を読みやすくする）"""
    s = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(s)
    for y in range(H):
        t = y / H
        a = int(110 + 90 * abs(t - 0.5) * 2)  # 中央110、上下200
        d.line([(0, y), (W, y)], fill=(0, 0, 0, min(a, 200)))
    return s


RAW = sys.argv[2] if len(sys.argv) > 2 else "tt"  # tt=TikTok / yt=YouTube / tn=TikTok・BGMなし
VARIANT = "tt" if RAW == "tn" else RAW
CTA = {"tt": ("＋ フォロー", "毎日2本、ラクする台所を更新中"),
       "yt": ("チャンネル登録", "チャンネル登録＆保存してね")}


def text_layer(slide):
    layer = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(layer)
    big_lines = slide["big"]
    size = 150 if max(len(l) for l in big_lines) <= 6 else 128
    widest = max(d.textlength(l, font=font(size)) for l in big_lines)
    if widest > W - 90:
        size = int(size * (W - 90) / widest)
    f_big = font(size)
    line_h = int(size * 1.3)
    total = line_h * len(big_lines)
    y = (H - total) // 2 - 60
    if slide["type"] == "end" and VARIANT == "yt":
        y = 430  # 下と右に「ここを押してね」の矢印を出すので上に寄せる
    mark = slide.get("mark", "")

    # タグ（その1 など）
    tag = slide.get("tag") or slide.get("small")
    if tag:
        f_tag = font(64)
        tw = d.textlength(tag, font=f_tag)
        pad = 44
        bx0 = (W - tw) / 2 - pad
        by0 = y - 170
        d.rounded_rectangle((bx0, by0, bx0 + tw + pad * 2, by0 + 110), radius=55, fill=ACCENT)
        d.text(((W - tw) / 2, by0 + 14), tag, font=f_tag, fill=WHITE)

    for line in big_lines:
        lw = d.textlength(line, font=f_big)
        x = (W - lw) / 2
        if mark and mark in line:
            pre = line[: line.index(mark)]
            mx = x + d.textlength(pre, font=f_big)
            mw = d.textlength(mark, font=f_big)
            d.rectangle((mx - 10, y + size * 0.62, mx + mw + 10, y + size * 1.18), fill=YELLOW)
        d.text((x, y), line, font=f_big, fill=WHITE, stroke_width=10, stroke_fill=(0, 0, 0))
        y += line_h

    sub = slide.get("sub")
    if slide["type"] == "end":
        sub = CTA[VARIANT][1] if VARIANT == "tt" else None  # YouTubeは矢印で示す
    if sub:
        f_sub = font(64)
        sw = d.textlength(sub, font=f_sub)
        if sw > W - 100:
            f_sub = font(int(64 * (W - 100) / sw))
            sw = d.textlength(sub, font=f_sub)
        d.text(((W - sw) / 2, y + 70), sub, font=f_sub, fill=WHITE, stroke_width=6, stroke_fill=(0, 0, 0))

    topic = slide.get("_topic")  # どのコマが一覧の表紙になっても、何の動画かわかるように
    if topic and slide["type"] != "hook":
        f_t = font(54)
        tw = d.textlength(topic, font=f_t)
        bx0, by0 = (W - tw) / 2 - 42, 372
        d.rounded_rectangle((bx0, by0, bx0 + tw + 84, by0 + 82), radius=41, fill=(0, 0, 0, 175))
        d.rectangle((bx0 + 22, by0 + 20, bx0 + 32, by0 + 62), fill=YELLOW)
        d.text((bx0 + 48, by0 + 6), topic, font=f_t, fill=WHITE)

    step = slide.get("_step")  # 進み具合（1/3 など）を上に表示
    if step:
        n, total = step
        gap, top, hgt = 16, 330, 16
        seg = (W - 160 - gap * (total - 1)) / total
        for k in range(total):
            x0 = 80 + k * (seg + gap)
            col = ACCENT + (255,) if k < n else (255, 255, 255, 90)
            d.rounded_rectangle((x0, top, x0 + seg, top + hgt), radius=8, fill=col)
        f_step = font(44)
        lab = f"{n}/{total}"
        d.text((W - 80 - d.textlength(lab, font=f_step), top - 58), lab, font=f_step, fill=WHITE,
               stroke_width=4, stroke_fill=(0, 0, 0))

    if slide["type"] == "end" and slide.get("_credits"):  # 写真・声のクレジット（利用ルールで表示が必要）
        f_c = font(26)
        cy = 340
        for text in slide["_credits"]:
            line = ""
            for ch in text:  # 省略せずに折り返す（作者名を全部出す）
                if d.textlength(line + ch, font=f_c) > W - 200:
                    d.text((40, cy), line, font=f_c, fill=(255, 255, 255, 200), stroke_width=2, stroke_fill=(0, 0, 0))
                    cy += 34
                    line = ch
                else:
                    line += ch
            d.text((40, cy), line, font=f_c, fill=(255, 255, 255, 200), stroke_width=2, stroke_fill=(0, 0, 0))
            cy += 34
    if slide["type"] == "end" and VARIANT == "tt":  # 最後にボタン風の呼びかけ
        label = CTA[VARIANT][0]
        f_btn = font(72)
        bw = d.textlength(label, font=f_btn) + 120
        bx, by = (W - bw) / 2, H - 620
        d.rounded_rectangle((bx, by, bx + bw, by + 140), radius=70, fill=(230, 33, 23))
        d.text((bx + 60, by + 22), label, font=f_btn, fill=WHITE)
    if slide["type"] == "end" and VARIANT == "yt":  # YouTubeのボタンの位置を矢印で示す
        f_p = font(66)

        def pointer(text, tx, ty, ax0, ay0, ax1, ay1, color):
            tw = d.textlength(text, font=f_p)
            d.rounded_rectangle((tx - 24, ty - 12, tx + tw + 24, ty + 90), radius=46, fill=color)
            d.text((tx, ty), text, font=f_p, fill=WHITE)
            d.line((ax0, ay0, ax1, ay1), fill=YELLOW, width=20)
            import math
            ang = math.atan2(ay1 - ay0, ax1 - ax0)
            L = 62
            p1 = (ax1 - L * math.cos(ang - 0.5), ay1 - L * math.sin(ang - 0.5))
            p2 = (ax1 - L * math.cos(ang + 0.5), ay1 - L * math.sin(ang + 0.5))
            d.polygon([(ax1, ay1), p1, p2], fill=YELLOW)

        pointer("いいね", 440, 905, 690, 950, 860, 950, ACCENT)
        pointer("保存", 500, 1185, 650, 1230, 860, 1230, ACCENT)
        pointer("チャンネル登録はここ", 140, 1360, 470, 1470, 560, 1575, (230, 33, 23))
    return layer


def frames_for(slide, bg, sh, seconds=None):
    n = int((seconds or DUR[slide["type"]]) * FPS)
    txt = text_layer(slide)
    bw, bh = bg.size
    for k in range(n):
        t = k / max(n - 1, 1)
        # 背景はゆっくりズーム
        z = 1.0 + 0.06 * t
        cw, ch = int(bw / z), int(bh / z)
        x0, y0 = (bw - cw) // 2, (bh - ch) // 2
        frame = bg.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.BILINEAR).convert("RGBA")
        frame.alpha_composite(sh)
        # 冒頭は1コマ目から文字を全部見せる。2枚目以降は4コマで飛び出す
        if k < 4 and slide["type"] != "hook":
            p = (k + 1) / 4
            s = 1.15 - 0.15 * p
            tw, th = int(W * s), int(H * s)
            big = txt.resize((tw, th), Image.BILINEAR)
            big = big.crop(((tw - W) // 2, (th - H) // 2, (tw - W) // 2 + W, (th - H) // 2 + H))
            if p < 1:
                a = big.getchannel("A").point(lambda v: int(v * p))
                big.putalpha(a)
            frame.alpha_composite(big)
        else:
            frame.alpha_composite(txt)
        yield frame.convert("RGB")


def main(path):
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    work = Path("work") / spec["id"]
    out = Path("output") / {"tt": f"{spec['id']}.mp4", "yt": f"{spec['id']}_yt.mp4", "tn": f"{spec['id']}_tn.mp4"}[RAW]
    out.parent.mkdir(exist_ok=True)
    sh = shade()
    dfile = work / f"durations_{RAW}.json"
    durs = json.loads(dfile.read_text())["durations"] if dfile.exists() else [None] * len(spec["slides"])
    audio = work / f"audio_{RAW}.wav"
    ain = ["-i", str(audio)] if audio.exists() else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        *ain, "-map", "0:v", "-map", "1:a",
        "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart", str(out),
    ]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    items = [i for i, sl in enumerate(spec["slides"]) if sl["type"] == "item"]
    credits = []
    cfile = Path("output") / f"{spec['id']}_credits.txt"
    if cfile.exists() and not spec.get("plain_bg"):
        names = []
        for line in cfile.read_text(encoding="utf-8").splitlines():
            parts = [x.strip() for x in line.split(" / ")]
            if len(parts) >= 3 and parts[2].upper().startswith("CC BY"):
                names.append(f"{parts[1][:30]}（{parts[2]}）")
        if names:
            credits.append("写真: Wikimedia Commons " + "、".join(dict.fromkeys(names)))
    if (work / f"durations_{RAW}.json").exists() and json.loads((work / f"durations_{RAW}.json").read_text()).get("voice"):
        credits.append("VOICEVOX:春日部つむぎ")
    for sl in spec["slides"]:
        if sl["type"] == "end":
            sl["_credits"] = credits
    for i, slide in enumerate(spec["slides"]):
        words = spec["title"].split()
        slide["_topic"] = spec.get("topic") or (words[0] if len(words[0]) > 5 or len(words) == 1 else " ".join(words[:2]))[:13]
        if i in items:
            slide["_step"] = (items.index(i) + 1, len(items))
        f = work / f"bg{i}.jpg"
        if spec.get("plain_bg") or slide.get("plain_bg"):
            f = Path("__none__")  # 写真が合わない時は無地の背景にする
        try:
            bg = cover(Image.open(f)) if f.exists() else gradient_bg()
        except Exception:
            bg = gradient_bg()
        bg = bg.filter(ImageFilter.GaussianBlur(1))
        for fr in frames_for(slide, bg, sh, durs[i]):
            p.stdin.write(fr.tobytes())
    p.stdin.close()
    p.wait()
    print("done:", out)


if __name__ == "__main__":
    main(sys.argv[1])
