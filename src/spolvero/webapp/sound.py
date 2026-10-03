"""声音（第 6 步）：声轨**由幕表派生**，不写死秒数。

为什么必须有单独一步：
1. 声音与画面是两条时间轴，混在"渲染"里做，用户看不到落点，也提不了意见；
2. 声轨的**常见缺陷是长度不对**（旧版写死 60 秒 + `-shortest` → 71 秒的片子被截到 60 秒，
   观众以为后半段没生成）。所以这一步的自动检验第一条就是"声轨时长＝片长"。

合成手法：噪声（风/水/脚步/击打）+ 正弦（箫/铃/低鼓）+ 包络。不用任何音频素材，
全部 numpy 现场合成 → WAV → 与成片合流（视频流 copy，不重编码）。

**可覆盖**：`films/<id>/sound.py` 若存在，且提供 `build(fid)`，就完全用它的
（那是 AI 或人写的"这一部片的声音设计"）；没有就用下面的通用按幕合成。
"""

from __future__ import annotations

import inspect
import os
import wave

import numpy as np

SR = 44100

# 关键字 → 音型。命中就用，没命中走默认（一记起手 + 一记落点）。
# 这是"声音设计"的最小可用版本：**先让每一幕都有声音**，再让人提意见改。
KEY_CUES = (
    (("风", "雪", "夜", "霜", "寒"), "wind"),
    (("水", "江", "湖", "溪", "雨", "舟", "船"), "water"),
    (("步", "行", "走", "归", "去", "上", "下", "道", "路"), "steps"),
    (("钟", "铃", "磬", "寺", "塔"), "bell"),
    (("箫", "笛", "吹", "歌", "唱", "舞", "曲"), "flute"),
    (("鼓", "击", "撞", "砍", "劈", "伐", "打", "雷"), "hit"),
    (("月", "星", "空", "云", "天"), "air"),
)
CUE_CN = {"wind": "风声垫", "water": "水声", "steps": "脚步", "bell": "铃/钟",
          "flute": "箫音", "hit": "击打", "air": "空阔高频垫", "bed": "底噪"}


# ── 幕表 ───────────────────────────────────────────────────────────────
def _acts(fid: str) -> tuple[list[dict], float]:
    from . import films as fl
    m = fl.meta(fid)
    return (m.get("acts") or []), float(m.get("duration") or 0.0)


def user_module(fid: str):
    """本片自己的声音设计 `films/<id>/sound.py`（有就用它的）。"""
    from . import films as fl
    import importlib.util
    p = os.path.join(fl.film_dir(fid), "sound.py")
    if not os.path.exists(p):
        return None
    try:
        spec = importlib.util.spec_from_file_location(f"spolvero_sound_{fid}", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod if callable(getattr(mod, "build", None)) else None
    except Exception:
        return None


class Generic:
    """通用声轨：**按本片幕表**合成（`build(fid)`）。统一成无参 `build()` 便于调用方。"""

    def __init__(self, fid: str):
        self._fid = fid
        self.SR = SR

    def build(self):
        return build(self._fid)

    def mux(self, video_in, audio, video_out):
        return mux(video_in, audio, video_out)

    def cues(self):
        return cues(self._fid)


def resolve(fid: str):
    """本片用哪一份声音设计（三选一，顺序有讲究）：

    1. `films/<id>/sound.py` —— 这一部片自己的（人写或 AI 写的）；
    2. `spike/audio.py`      —— 现成手工稿，**但长度必须对得上本片幕表**
                                （对不上就弃用：60 秒的稿子配 71 秒的片子会被截断）；
    3. `Generic(fid)`        —— 通用按幕合成器，永远可用。

    为什么必须有第 3 条：只有前两条时，新片在第 6 步看到的是"还没有声轨模块"，
    那等于这一步不存在。**先让每一幕都有声音**，人再提意见改。
    """
    mod = user_module(fid)
    if mod is not None:
        return mod
    from . import films as fl
    dur = float(fl.meta(fid).get("duration") or 0)
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    q = os.path.join(root, "spike", "audio.py")
    if os.path.exists(q):
        try:
            import importlib.util
            import sys
            spec = importlib.util.spec_from_file_location("spolvero_sound_spike", q)
            m2 = importlib.util.module_from_spec(spec)
            if root not in sys.path:
                sys.path.insert(0, root)
            spec.loader.exec_module(m2)
            tot = float(m2.total()) if callable(getattr(m2, "total", None)) else dur
            if abs(tot - dur) <= 0.5:
                return m2
        except Exception:
            pass
    return Generic(fid)


def cues(fid: str) -> list[dict]:
    """每一幕配什么声音（给界面看：出轨前先让人看到设计）。

    自定义模块若不报 `cues()`，**照实说"未报音型"** —— 拿通用猜测去描述
    一份手写稿，界面上就是假信息。
    """
    mod = resolve(fid)
    acts, _dur = _acts(fid)
    if not isinstance(mod, Generic):
        if callable(getattr(mod, "cues", None)):
            try:
                return list(mod.cues(fid))
            except Exception:
                pass
        return [{"act": a["id"], "note": a.get("note", a["id"]), "t0": a["t0"], "t1": a["t1"],
                 "d": a["d"], "kinds": [], "text": "自定义声轨（模块未报音型）"} for a in acts]
    out = []
    for i, a in enumerate(acts):
        note = f'{a.get("note", "")}{"".join(a.get("caption") or [])}'
        kinds = [k for keys, k in KEY_CUES if any(w in note for w in keys)]
        if not kinds:
            kinds = ["bed"]
        out.append({"act": a["id"], "note": a.get("note", a["id"]), "t0": a["t0"], "t1": a["t1"],
                    "d": a["d"], "kinds": kinds[:2],
                    "text": " · ".join(CUE_CN.get(k, k) for k in kinds[:2])})
    return out


# ── 合成原语 ───────────────────────────────────────────────────────────
def _lp(x: np.ndarray, cutoff: float, taps: int = 96) -> np.ndarray:
    n = np.arange(taps)
    a = np.exp(-2.0 * np.pi * cutoff / SR)
    k = (1.0 - a) * (a ** n)
    k /= k.sum()
    return np.convolve(x, k, mode="same")


def _env(n: int, atk: float, dec: float, rel: float = 0.0) -> np.ndarray:
    e = np.zeros(n)
    a = max(1, int(atk * SR)); r = max(1, int(rel * SR))
    a = min(a, n); r = min(r, max(0, n - a))
    if a:
        e[:a] = np.linspace(0.0, 1.0, a)
    e[a:] = np.exp(-np.arange(n - a) / max(1.0, dec * SR))
    if r:
        e[-r:] *= np.linspace(1.0, 0.0, r)
    return e


def _add(buf: np.ndarray, sig: np.ndarray, t0: float, amp: float = 1.0) -> None:
    i = int(t0 * SR)
    n = min(len(sig), len(buf) - i)
    if n > 0:
        buf[i:i + n] += sig[:n] * amp


def tone(f: float, dur: float, amp: float = 0.5, dec: float = 0.25,
         harm: float = 0.0) -> np.ndarray:
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    ph = 2 * np.pi * f * t
    x = np.sin(ph) + harm * np.sin(2 * ph) * 0.5
    return x * _env(n, 0.06, dec) * amp


def noise_hit(dur: float, lp: float, amp: float = 0.5, dec: float = 0.08,
              seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = max(1, int(dur * SR))
    return _lp(rng.standard_normal(n), lp) * _env(n, 0.002, dec) * amp


# 五声音阶（D 羽）：按幕序取音，越往后越高 —— 听感上有"往前走"
SCALE = (293.66, 349.23, 392.00, 440.00, 523.25, 587.33)


def at(a: dict, u: float) -> float:
    """幕内进度 u（0..1）对应的绝对秒数 —— **所有落点都这么算，不写死**。"""
    return float(a["t0"]) + float(a["d"]) * u


def build(fid: str) -> np.ndarray:
    """合成全片声轨。长度＝片长（由幕表累计），采样率 44.1k，单声道。"""
    mod = user_module(fid)
    if mod is not None:
        fn = getattr(mod, "build", None)
        try:                                  # 有的稿子 build() 带 fid，有的不带
            x = np.asarray(fn(fid) if len(inspect.signature(fn).parameters) else fn(),
                           np.float32)
        except TypeError:
            x = np.asarray(fn(), np.float32)
        need = int(_acts(fid)[1] * SR)
        if len(x) < need:                      # 短了就补静音，**绝不让 mux 截断画面**
            x = np.concatenate([x, np.zeros(need - len(x), np.float32)])
        return x[:need] if len(x) > need else x

    acts, dur = _acts(fid)
    n = max(1, int(dur * SR))
    buf = np.zeros(n, np.float64)
    rng = np.random.default_rng(20260929)
    tt = np.arange(n) / SR

    # ① 底噪：风（全片）+ 缓慢起伏
    buf += _lp(rng.standard_normal(n), 420) * (0.55 + 0.45 * np.sin(2 * np.pi * 0.055 * tt)) * 0.14

    # ② 逐幕音型：落点全部由幕内的相对进度算
    for i, a in enumerate(acts):
        note = f'{a.get("note", "")}{"".join(a.get("caption") or [])}'
        kinds = [k for keys, k in KEY_CUES if any(w in note for w in keys)] or ["bed"]
        for k in kinds[:2]:
            if k == "wind":
                seg = _lp(rng.standard_normal(min(n, int(a["d"] * SR))), 520) \
                    * (0.6 + 0.4 * np.sin(2 * np.pi * 0.21 * np.arange(int(a["d"] * SR)) / SR))
                _add(buf, seg * 0.16, a["t0"])
            elif k == "water":
                seg = _lp(rng.standard_normal(int(a["d"] * SR)), 200)
                _add(buf, seg * (0.6 + 0.4 * np.sin(2 * np.pi * 0.13 * np.arange(int(a["d"] * SR)) / SR)) * 0.10,
                     a["t0"])
            elif k == "steps":
                cnt = max(3, int(a["d"] / 0.55))
                for j in range(cnt):
                    _add(buf, tone(76.0, 0.20, 0.16, dec=0.05), at(a, 0.15 + 0.8 * j / cnt))
            elif k == "bell":
                nn = int(2.4 * SR); t2 = np.arange(nn) / SR
                _add(buf, (np.sin(2 * np.pi * 1240 * t2) + 0.4 * np.sin(2 * np.pi * 1240 * 2.02 * t2))
                     * np.exp(-t2 * 1.6) * 0.13, at(a, 0.45))
            elif k == "flute":
                f = SCALE[(i * 2) % len(SCALE)]
                for u, du in ((0.22, min(2.6, a["d"] * 0.45)), (0.62, min(2.0, a["d"] * 0.32))):
                    _add(buf, tone(f, du, 0.15, dec=du * 0.55, harm=0.30), at(a, u))
            elif k == "hit":
                _add(buf, noise_hit(0.24, 1400, 0.30, 0.05, seed=100 + i), at(a, 0.62))
                _add(buf, tone(150, 0.26, 0.22, dec=0.07), at(a, 0.624))
            elif k == "air":
                nn = int(a["d"] * SR)
                t2 = np.arange(nn) / SR
                _add(buf, np.sin(2 * np.pi * 1760 * t2) * _env(nn, 0.8, 3.0) * 0.035, a["t0"])
            else:                              # 默认：起手一记 + 落点一记
                _add(buf, noise_hit(0.20, 900, 0.18, 0.05, seed=700 + i), at(a, 0.18))
                _add(buf, tone(SCALE[i % len(SCALE)], min(1.8, a["d"] * 0.3), 0.11, dec=0.8), at(a, 0.72))

    # ③ 收尾渐静（只留最后 1.2 秒，别把落点压掉）
    tail = np.ones(n)
    k = int(1.2 * SR)
    tail[-k:] = np.linspace(1.0, 0.0, k)
    buf *= tail

    rms = float(np.sqrt((buf ** 2).mean())) or 1e-6
    buf *= min(2.6, 0.17 / rms)
    return (0.98 * np.tanh(buf * 1.5)).astype(np.float32)


# ── 落盘与合流 ─────────────────────────────────────────────────────────
def write_wav(fid: str, path: str) -> str:
    x = build(fid)
    pcm = (np.clip(x, -1.0, 1.0) * 32767.0).astype(np.int16)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with wave.open(tmp, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    os.replace(tmp, path)
    return path


def mux(video_in: str, audio: str, video_out: str) -> str:
    """把声轨合进成片（视频流 copy，不重编码）。

    **不用 `-shortest`**：声轨短于视频时会静默截断画面 ——
    这个坑真踩过（60 秒声轨 → 71 秒的片子被截到 60 秒）。现在显式 map，长度以视频为准。
    """
    import subprocess
    import imageio_ffmpeg
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [exe, "-y", "-loglevel", "error", "-i", video_in, "-i", audio,
           "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", video_out]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "ignore")[:400])
    return video_out


def wav_seconds(path: str) -> float:
    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        return 0.0
