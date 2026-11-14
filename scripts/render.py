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
    if sub:
        f_sub = font(56)
        sw = d.textlength(sub, font=f_sub)
        if sw > W - 100:
            f_sub = font(int(56 * (W - 100) / sw))
            sw = d.textlength(sub, font=f_sub)
        d.text(((W - sw) / 2, y + 70), sub, font=f_sub, fill=WHITE, stroke_width=6, stroke_fill=(0, 0, 0))

    step = slide.get("_step")  # 進み具合（1/3 など）を上に表示
    if step:
        n, total = step
        gap, top, hgt = 16, 150, 16
        seg = (W - 160 - gap * (total - 1)) / total
        for k in range(total):
            x0 = 80 + k * (seg + gap)
            col = ACCENT + (255,) if k < n else (255, 255, 255, 90)
            d.rounded_rectangle((x0, top, x0 + seg, top + hgt), radius=8, fill=col)
        f_step = font(44)
        lab = f"{n}/{total}"
        d.text((W - 80 - d.textlength(lab, font=f_step), top + 30), lab, font=f_step, fill=WHITE,
               stroke_width=4, stroke_fill=(0, 0, 0))

    f_foot = font(40)
    foot = "みん｜一人暮らしの台所ラク化"
    fw = d.textlength(foot, font=f_foot)
    d.text(((W - fw) / 2, H - 230), foot, font=f_foot, fill=(255, 255, 255, 220), stroke_width=4, stroke_fill=(0, 0, 0))
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
    out = Path("output") / f"{spec['id']}.mp4"
    out.parent.mkdir(exist_ok=True)
    sh = shade()
    dfile = work / "durations.json"
    durs = json.loads(dfile.read_text())["durations"] if dfile.exists() else [None] * len(spec["slides"])
    audio = work / "audio.wav"
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
    for i, slide in enumerate(spec["slides"]):
        if i in items:
            slide["_step"] = (items.index(i) + 1, len(items))
        f = work / f"bg{i}.jpg"
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
