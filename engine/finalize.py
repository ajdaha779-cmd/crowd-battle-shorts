"""Сборка ролика из кадров: чёрные полосы с заголовком, счётчик, звук (удары по симуляции).

    python3 engine/finalize.py fights/<id>.json <папка кадров> <video.mp4>

Нужны numpy и ffmpeg (с libass). Звук синтезируется здесь же — без чужих сэмплов и музыки.
"""
import json
import math
import os
import subprocess
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import sim as S  # noqa: E402

SR = 44100
W, H = 1080, 1920
VIDEO_Y = 420          # квадрат 1080×1080 по центру, сверху и снизу полосы с текстом
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")


# ---------------------------------------------------------------- звук
def band(x, lo, hi):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(X, len(x))


def env(n, attack, decay):
    t = np.arange(n) / SR
    return np.minimum(1, t / max(attack, 1e-4)) * np.exp(-t / decay)


def thump(f0=95, f1=42, dur=0.35, rng=None):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = f1 + (f0 - f1) * np.exp(-t * 18)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.002, 0.09)
    noise = band((rng or np.random).standard_normal(n), 800, 6000) * env(n, 0.0005, 0.02)
    return body * 0.9 + noise * 0.6


def add(buf, sig, t, gain=1.0):
    i = int(t * SR)
    if i >= len(buf):
        return
    j = min(len(buf), i + len(sig))
    buf[i:j] += sig[: j - i] * gain


def soundtrack(spec, hits, left):
    rng = np.random.default_rng(spec.get("seed", 1))
    fps = spec.get("fps", 30)
    T = len(hits) / fps
    n = int(T * SR) + SR
    mix = np.zeros(n)

    # барабаны: тяжёлый ритм ~100 bpm, вступает с атакой толпы
    bpm = spec.get("bpm", 100)
    beat = 60 / bpm
    start = spec["crowd"].get("charge_at", 1.0)
    k = 0
    t = start
    while t < T:
        pat = k % 8
        if pat in (0, 3, 4, 6):
            add(mix, thump(70, 38, 0.6, rng), t, 0.9 if pat == 0 else 0.6)
        if pat in (2, 6):
            add(mix, band(rng.standard_normal(int(0.25 * SR)), 150, 2500) * env(int(0.25 * SR), 0.001, 0.06), t, 0.35)
        if pat == 7:
            add(mix, thump(140, 70, 0.3, rng), t, 0.4)
            add(mix, thump(120, 60, 0.3, rng), t + beat / 2, 0.4)
        k += 1
        t += beat

    # гул: квинта на низах, медленно нарастает
    tt = np.arange(n) / SR
    drone = sum(np.sign(np.sin(2 * np.pi * f * tt)) * a for f, a in ((55, 0.5), (82.4, 0.3), (110, 0.2)))
    drone = band(drone, 30, 400) * np.clip(tt / max(1, T * 0.6), 0.15, 1.0) * 0.18
    mix += drone

    # рёв толпы ~ число бегущих
    roar = band(rng.standard_normal(n), 250, 1600)
    roar = roar / (np.abs(roar).max() + 1e-9)
    total = max(left[0], 1)
    lvl = np.interp(tt, np.arange(len(left)) / fps, np.array(left) / total)
    lvl = lvl * (tt > start - 0.3)
    mix += roar * (0.05 + 0.18 * lvl)

    # удары: по кадрам симуляции
    hits_arr = np.array(hits)
    for f in np.flatnonzero(hits_arr):
        g = min(1.0, 0.35 + 0.22 * math.log1p(hits_arr[f]))
        add(mix, thump(rng.uniform(85, 120), rng.uniform(38, 50), 0.3, rng), f / fps, g * 0.8)

    # свист на склейках планов
    for s in spec["shots"][1:]:
        m = int(0.35 * SR)
        sw = band(rng.standard_normal(m), 1500, 7000) * np.sin(np.linspace(0, np.pi, m)) ** 2
        add(mix, sw, s["t"] - 0.15, 0.25)

    mix = np.tanh(mix * 1.2)
    mix /= np.abs(mix).max() + 1e-9
    mix *= 0.89
    return mix[: int(T * SR)]


def write_wav(path, x):
    st = np.stack([x, x], 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((st * 32767).astype(np.int16).tobytes())


# ---------------------------------------------------------------- текст
def ass_t(t):
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def fmt_n(v):
    return f"{v:,}"


def overlay(spec, left, path):
    fps = spec.get("fps", 30)
    T = len(left) / fps
    top = spec.get("title_top", "").replace("\n", r"\N")
    bottom = spec.get("title_bottom", "").replace("\n", r"\N")
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Top,Montserrat Black,{spec.get("title_size", 96)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,1,0,0,100,100,0,0,1,0,0,2,30,30,{H - VIDEO_Y + 40},1
Style: Bottom,Montserrat Black,{spec.get("title_size", 96)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,1,0,0,100,100,0,0,1,0,0,8,30,30,{VIDEO_Y + 1080 + 40},1
Style: Count,Montserrat Black,64,&H003DD8FF,&H003DD8FF,&H00000000,&H64000000,0,1,0,0,100,100,0,0,1,6,2,8,30,30,{VIDEO_Y + 30},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = [f"Dialogue: 1,{ass_t(0)},{ass_t(T)},Top,,0,0,0,,{top}",
          f"Dialogue: 1,{ass_t(0)},{ass_t(T)},Bottom,,0,0,0,,{bottom}"]
    label = spec.get("counter")
    if label:
        step = 3
        for f in range(0, len(left), step):
            a, b = f / fps, min(T, (f + step) / fps)
            ev.append(f"Dialogue: 2,{ass_t(a)},{ass_t(b)},Count,,0,0,0,,{label}: {fmt_n(left[f])}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(head + "\n".join(ev) + "\n")


# ---------------------------------------------------------------- сборка
def main(spec_path, frames, out):
    spec = json.load(open(spec_path, encoding="utf-8"))
    fps = spec.get("fps", 30)
    hits, left = S.hit_track(spec)
    work = os.path.dirname(os.path.abspath(out)) or "."
    wav = os.path.join(work, "audio.wav")
    ass = os.path.join(work, "overlay.ass")
    write_wav(wav, soundtrack(spec, hits, left))
    overlay(spec, left, ass)
    vf = (f"scale=1080:1080:flags=lanczos,pad={W}:{H}:0:{VIDEO_Y}:black,"
          f"subtitles={os.path.basename(ass)}:fontsdir={os.path.join(ROOT, 'fonts')},format=yuv420p")
    cmd = [FFMPEG, "-y", "-framerate", str(fps), "-i", os.path.join(os.path.abspath(frames), "%05d.png"),
           "-i", os.path.basename(wav), "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "18",
           "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", os.path.abspath(out)]
    subprocess.run(cmd, check=True, cwd=work)
    print("VIDEO", out, f"ударов {sum(hits)}, осталось {left[-1]} из {left[0]}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
