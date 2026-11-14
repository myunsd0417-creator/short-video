"""ナレーション（VOICEVOX）とBGMを作り、スライドごとの長さを決める。
出力: work/<id>/durations.json（各スライドの秒数）, work/<id>/audio.wav（完成した音声）
VOICEVOXが動いていなければ、BGMだけの音声を作る。
使い方: python scripts/audio.py content/001.json
"""
import io
import json
import os
import sys
import urllib.parse
import urllib.request
import wave
from pathlib import Path

import numpy as np

SR = 24000
ENGINE = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021")
SPEAKER = int(os.environ.get("VOICEVOX_SPEAKER", "8"))  # 8 = 春日部つむぎ（ノーマル）
DEFAULT = {"hook": 2.2, "item": 2.8, "end": 2.6}
MIN_PAD = 0.35  # 声のあとに残す間（秒）


def narration_text(s):
    if s.get("say"):
        return s["say"]
    big = "".join(s["big"])
    if s["type"] == "hook":
        return big
    if s["type"] == "item":
        return f"{s.get('tag', '')}、{big}。{s.get('sub', '')}"
    return f"{big}。{s.get('sub', '')}"


def tts(text):
    q = urllib.request.urlopen(urllib.request.Request(
        f"{ENGINE}/audio_query?" + urllib.parse.urlencode({"text": text, "speaker": SPEAKER}), method="POST"), timeout=60)
    query = json.loads(q.read())
    query["speedScale"] = 1.2
    query["intonationScale"] = 1.2
    query["prePhonemeLength"] = 0.05
    query["postPhonemeLength"] = 0.05
    query["outputSamplingRate"] = SR
    r = urllib.request.urlopen(urllib.request.Request(
        f"{ENGINE}/synthesis?speaker={SPEAKER}", data=json.dumps(query).encode(),
        headers={"Content-Type": "application/json"}, method="POST"), timeout=120)
    with wave.open(io.BytesIO(r.read())) as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        if w.getnchannels() == 2:
            data = data.reshape(-1, 2).mean(axis=1)
    return data


def engine_ok():
    try:
        urllib.request.urlopen(f"{ENGINE}/version", timeout=5)
        return True
    except Exception:
        return False


def bgm(seconds, seed=0):
    """やわらかい和音＋軽いリズムの、権利の心配がないBGM"""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.zeros(n, dtype=np.float32)
    bpm = 100
    beat = 60 / bpm
    # I - V - vi - IV（Cメジャー）を明るめのキーに移調
    root = 261.63 * 2 ** (rng.integers(0, 5) / 12)
    prog = [[0, 4, 7], [7, 11, 14], [9, 12, 16], [5, 9, 12]]
    bar = beat * 4
    for k in range(int(seconds / bar) + 1):
        chord = prog[k % 4]
        st = int(k * bar * SR)
        for b in range(4):  # 1拍ごとに和音をやさしく鳴らす
            s0 = st + int(b * beat * SR)
            ln = min(int(beat * SR * 1.6), n - s0)
            if ln <= 0:
                continue
            tt = np.arange(ln) / SR
            env = np.exp(-tt * 3.0) * (0.9 if b == 0 else 0.55)
            for semi in chord:
                f = root * 2 ** (semi / 12)
                out[s0:s0 + ln] += 0.06 * env * (np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(4 * np.pi * f * tt))
            # ベース
            fb = root / 2 * 2 ** (chord[0] / 12)
            out[s0:s0 + ln] += 0.07 * np.exp(-tt * 4) * np.sin(2 * np.pi * fb * tt)
        for b in range(8):  # 8分のハイハット風
            s0 = st + int(b * beat / 2 * SR)
            ln = min(int(0.04 * SR), n - s0)
            if ln > 0:
                out[s0:s0 + ln] += 0.02 * rng.standard_normal(ln) * np.exp(-np.arange(ln) / SR * 80)
        for b in (0, 2):  # キック
            s0 = st + int(b * beat * SR)
            ln = min(int(0.15 * SR), n - s0)
            if ln > 0:
                tt = np.arange(ln) / SR
                out[s0:s0 + ln] += 0.12 * np.sin(2 * np.pi * (60 + 60 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 18)
    fade = int(0.4 * SR)
    out[:fade] *= np.linspace(0, 1, fade)
    out[-fade:] *= np.linspace(1, 0, fade)
    return out


def write_wav(path, data):
    data = np.clip(data, -1, 1)
    pcm = (data * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main(path):
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    work = Path("work") / spec["id"]
    work.mkdir(parents=True, exist_ok=True)
    use_voice = engine_ok()
    print("VOICEVOX:", "OK" if use_voice else "なし（BGMのみ）")
    voices, durs = [], []
    for s in spec["slides"]:
        v = None
        if use_voice:
            try:
                v = tts(narration_text(s))
            except Exception as e:
                print("TTS失敗:", e)
        d = DEFAULT[s["type"]]
        if v is not None:
            d = max(d * 0.8, len(v) / SR + MIN_PAD)
        voices.append(v)
        durs.append(round(d, 2))
    total = sum(durs)
    music = bgm(total + 0.1, seed=int(spec["id"]) if spec["id"].isdigit() else 0)
    voice_track = np.zeros_like(music)
    pos = 0.0
    for v, d in zip(voices, durs):
        if v is not None:
            st = int((pos + 0.12) * SR)
            ln = min(len(v), len(voice_track) - st)
            voice_track[st:st + ln] += v[:ln]
        pos += d
    # 声がある時はBGMを下げる（ダッキング）
    env = np.convolve(np.abs(voice_track), np.ones(int(0.2 * SR)) / int(0.2 * SR), mode="same")
    duck = 1 - 0.55 * np.clip(env * 12, 0, 1)
    mix = music * (0.9 if any(v is not None for v in voices) else 1.4) * duck + voice_track * 1.1
    peak = np.max(np.abs(mix)) or 1
    mix = mix / peak * 0.9
    write_wav(work / "audio.wav", mix)
    (work / "durations.json").write_text(json.dumps({"durations": durs, "voice": use_voice}), encoding="utf-8")
    print("durations:", durs, "total:", round(total, 2))


if __name__ == "__main__":
    main(sys.argv[1])
