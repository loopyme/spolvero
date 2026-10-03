"""判据执行器（SPEC §8）。

判据＝纯函数：`(film_module, ctx) -> item`。执行器只负责**按顺序跑、报进度、汇总**。
判据本身分三层：
  structure  结构层  —— 脚本全量，可 FAIL
  composition 构成层 —— 脚本全量 + AI 抽检
  aesthetic  审美层  —— 脚本**不得判定**，只输出"待人工确认"占位

**没实现的判据一律标 skip 并说明原因，绝不假装通过。**
"""

from __future__ import annotations

import json
import os
import re
import time

import numpy as np

from . import films as fl

LUMA = np.array((0.299, 0.587, 0.114), np.float32)


# ── 上下文：带缓存的渲染与采样 ─────────────────────────────────────────
class Ctx:
    def __init__(self, fid: str):
        self.fid = fid
        self.mod = fl.load(fid)
        self.meta = fl.meta(fid)
        self.acts = self.meta["acts"]
        self.W, self.H = self.meta["size"]
        self._cache: dict[float, np.ndarray] = {}
        self.renders = 0

    def rgb(self, t: float) -> np.ndarray:
        t = round(float(t), 4)
        if t not in self._cache:
            self._cache[t] = self.mod.render_frame(t)
            self.renders += 1
        return self._cache[t]


def lum(a) -> np.ndarray:
    return a.astype(np.float32) @ LUMA


def item(jid, name, layer, status, detail, *,
         spec="", evidence=None, fix="", approx=False) -> dict:
    return {"id": jid, "name": name, "layer": layer, "status": status,
            "spec": spec, "detail": detail, "evidence": evidence or {},
            "fix": fix, "approx": approx}


def _ok(v, lo, hi) -> bool:
    return lo <= v <= hi


# ── 主体近似定位（C3 / C8 共用）────────────────────────────────────────
def subject_box(a: np.ndarray, W: int, H: int, q: float = 3.0, cols: int = 40):
    """近似主体：取最深 q% 像素，再找**集中在少数几列**的那一簇，返回其包围盒。

    为什么这么做：主体（人）是**竖向**的、且**只占局部横向范围**；
    远山条带横跨全幅、y 跨度小，不会被误判成主体。
    """
    L = lum(a)
    th = float(np.percentile(L, q))
    m = L <= th
    if m.sum() < 40:
        return None
    colw = max(1, W // cols)
    hist = m.sum(axis=0)
    bins = np.array([hist[i * colw:(i + 1) * colw].sum() for i in range(cols)], float)
    # 滑动窗口，宽度不超过画宽 30%
    k = max(1, int(cols * 0.30))
    if k >= cols:
        k = cols - 1
    best, bi = -1.0, 0
    for i in range(cols - k + 1):
        s = bins[i:i + k].sum()
        if s > best:
            best, bi = s, i
    x0, x1 = bi * colw, min(W, (bi + k) * colw)
    sub = m[:, x0:x1]
    ys = np.nonzero(sub.any(axis=1))[0]
    if ys.size == 0:
        return None
    return int(x0), int(x1), int(ys.min()), int(ys.max())


# ═══════════════ 结构层 ═══════════════
def s4_determinism(ctx: Ctx) -> dict:
    t = ctx.acts[0]["t0"] + ctx.acts[0]["d"] * 0.5
    a = ctx.mod.render_frame(t)
    b = ctx.mod.render_frame(t)
    same = bool(np.array_equal(a, b))
    return item("S4", "确定性（同 t 两次渲染逐字节一致）", "structure",
                "pass" if same else "fail",
                "同一时刻两次渲染" + ("逐字节相同" if same else "**不一致**"),
                spec="SPEC §8.1 S4 / L1 门禁",
                evidence={"t": t, "equal": same},
                fix="" if same else "确定性被破坏：检查是否有未派生的随机源（如顺序消耗的 RNG）")


def s3_distinct(ctx: Ctx) -> dict:
    ts = [round(a["t0"] + a["d"] * u, 2)
          for a in ctx.acts for u in (0.25, 0.5, 0.75)]
    hs = [ctx.mod.frame_hash(t) for t in ts]
    uniq = len(set(hs))
    ratio = uniq / max(1, len(hs))
    return item("S3", "帧互异（无假动画）", "structure",
                "pass" if ratio >= 0.99 else "fail",
                f"{uniq}/{len(hs)} 抽样帧互异（{ratio*100:.0f}%）",
                spec="SPEC §8.1 S3 ≥99%",
                evidence={"unique": uniq, "n": len(hs), "ratio": round(ratio, 4)},
                fix="" if ratio >= 0.99 else "有帧完全相同：检查该幕是否有实际动作，或动画窗是否落在幕外")


def s7_flash(ctx: Ctx) -> dict:
    """全屏闪烁：连续 45 帧里全屏帧间均差 > 4 的比例。"""
    a0 = ctx.acts[0]
    bad = 0
    n = 0
    prev = None
    for i in range(45):
        t = a0["t0"] + a0["d"] * 0.15 + i / ctx.meta["fps"]
        L = lum(ctx.rgb(t))
        if prev is not None:
            d = float(np.abs(L - prev).mean())
            n += 1
            if d > 4.0:
                bad += 1
        prev = L
    ratio = bad / max(1, n)
    return item("S7", "亮度闪烁（全屏层不得逐帧跳）", "structure",
                "pass" if ratio <= 0.02 else "fail",
                f"45 帧窗口内 Δ>4 的帧 {bad}/{n}（{ratio*100:.1f}%）",
                spec="SPEC §8.1 S7 ≤2%",
                evidence={"bad": bad, "n": n},
                fix="" if ratio <= 0.02 else "全屏层在逐帧变化：整幅预光栅层不要每帧换种子（曾因纸疤 12fps 轮换导致 51 帧闪烁）")


def s5_frames(ctx: Ctx) -> dict:
    """成片帧数 = duration×fps；带声与无声必须一致。"""
    fps = ctx.meta["fps"]
    want = int(round(ctx.meta["duration"] * fps))
    got = ctx.meta.get("frames", 0)
    ev = {"want": want, "got": got, "checked_files": []}
    st = "pass" if got == want else "fail"
    detail = f"帧数 {got}（应为 {want}）"
    try:
        import imageio_ffmpeg
        o = fl.out_dir(ctx.fid)
        for name in ("laoshan_story.mp4", "laoshan_story_snd.mp4", "film.mp4", "film_snd.mp4"):
            p = os.path.join(o, name)
            if os.path.exists(p):
                n, s = imageio_ffmpeg.count_frames_and_secs(p)
                ev["checked_files"].append({"file": name, "frames": int(n), "secs": round(float(s), 2)})
        if len(ev["checked_files"]) >= 2:
            fr = {f["frames"] for f in ev["checked_files"]}
            if len(fr) > 1:
                st = "fail"
                detail = "带声版与无声版帧数不一致：" + ", ".join(
                    f"{f['file']}={f['frames']}" for f in ev["checked_files"])
            else:
                detail += f"；带声/无声一致（{list(fr)[0]} 帧）"
    except Exception as e:
        ev["error"] = str(e)[:120]
    return item("S5", "时长与帧数（含带声/无声一致）", "structure", st, detail,
                spec="SPEC §8.1 S5",
                evidence=ev,
                fix="" if st == "pass" else "声轨长度必须从幕表派生；合流禁用 -shortest（曾静默把 71s 片截到 60s）")


# ═══════════════ 构成层 ═══════════════
def c1c2_tone(ctx: Ctx) -> list[dict]:
    out = []
    for a in ctx.acts:
        t = round(a["t0"] + a["d"] * 0.5, 2)
        L = lum(ctx.rgb(t))
        q1 = float(np.percentile(L, 1.0))
        out.append((a["id"], t, q1, L))
    items = []
    for aid, t, q1, L in out:
        items.append(item("C1", f"深色存在性 · {aid}", "composition",
                          "pass" if q1 < 110.0 else "fail",
                          f"最深 1% 均值 {q1:.1f}（<110 为有骨）",
                          spec="SPEC §8.2 C1",
                          evidence={"t": t, "q1": round(q1, 1)},
                          fix="" if q1 < 110.0 else "画面无骨：主体墨色是否被雾/提亮冲掉？"
                                                    "（注意：口径是**最深 1% 有多深**，不是深色占几个百分点）"))
    return items


def c2_layers(ctx: Ctx) -> list[dict]:
    items = []
    for a in ctx.acts:
        t = round(a["t0"] + a["d"] * 0.5, 2)
        a_rgb = ctx.rgb(t)
        L = lum(a_rgb)
        paper = np.array(ctx.meta.get("paper", [244, 239, 230]), np.float32)
        m = np.abs(a_rgb.astype(np.float32) - paper).sum(axis=2) > 40
        lv = L[m]
        if lv.size < 2000:
            items.append(item("C2", f"明度分层 · {a['id']}", "composition", "skip",
                              "非纸区像素过少，无法分层", spec="SPEC §8.2 C2"))
            continue
        hist, _ = np.histogram(lv, bins=(0, 60, 110, 160, 205, 256))
        bands = int((hist > lv.size * 0.012).sum())
        items.append(item("C2", f"明度分层 · {a['id']}", "composition",
                          "pass" if bands >= 3 else "warn",
                          f"明度分 {bands} 档（≥3 为有层次）",
                          spec="SPEC §8.2 C2", evidence={"t": t, "bands": bands},
                          fix="" if bands >= 3 else "层次偏平：检查色板是否各幕趋同、或雾/提亮是否压掉了中灰"))
    return items


def c3_subject(ctx: Ctx) -> list[dict]:
    items = []
    for a in ctx.acts:
        t = round(a["t0"] + a["d"] * 0.62, 2)
        a_rgb = ctx.rgb(t)
        box = subject_box(a_rgb, ctx.W, ctx.H)
        if box is None:
            items.append(item("C3", f"主体尺度 · {a['id']}", "composition", "skip",
                              "未定位到主体簇", spec="SPEC §8.2 C3"))
            continue
        x0, x1, y0, y1 = box
        h = y1 - y0
        ratio = h / ctx.H
        items.append(item("C3", f"主体尺度 · {a['id']}", "composition",
                          "pass" if ratio >= 0.25 else "warn",
                          f"主体高 {h}px = 画高 {ratio*100:.0f}%（≥25% 才读得出「谁在做什么」）",
                          spec="SPEC §8.2 C3", approx=True,
                          evidence={"t": t, "box": [x0, x1, y0, y1], "h": h},
                          fix="" if ratio >= 0.25 else "主体偏小：放大主体、缩小环境，或改用更近的景别"))
    return items


def c8_continuity(ctx: Ctx) -> list[dict]:
    """帧间连续性：主体区变化率不得连续 10 帧 < 0.25%。"""
    items = []
    fps = ctx.meta["fps"]
    for a in ctx.acts:
        t0 = a["t0"] + a["d"] * 0.2
        Ls = []
        for i in range(16):
            t = round(t0 + i / fps, 4)
            Ls.append(lum(ctx.rgb(t)))
        box = subject_box(ctx.rgb(round(t0, 2)), ctx.W, ctx.H)
        if box is None:
            items.append(item("C8", f"帧间连续性 · {a['id']}", "composition", "skip",
                              "未定位到主体", spec="SPEC §8.2 C8"))
            continue
        x0, x1, y0, y1 = box
        rates = []
        for i in range(1, len(Ls)):
            pa = Ls[i - 1][y0:y1, x0:x1]
            pb = Ls[i][y0:y1, x0:x1]
            if pa.size:
                rates.append(float((np.abs(pb - pa) > 3.0).mean()) * 100)
        r = np.array(rates)
        stall = 0
        run = 0
        for v in r:
            run = run + 1 if v < 0.25 else 0
            stall = max(stall, run)
        items.append(item("C8", f"帧间连续性 · {a['id']}", "composition",
                          "pass" if stall < 10 else "fail",
                          f"主体区变化率中位 {np.median(r):.2f}% · 最长静止连段 {stall} 帧",
                          spec="SPEC §8.2 C8", approx=True,
                          evidence={"median": round(float(np.median(r)), 3),
                                    "min": round(float(r.min()), 3), "stall": stall},
                          fix="" if stall < 10 else "主体在某段时间完全静止：加待机微动，或把动作窗提前（旧版幕七人有 1.8 秒纹丝不动）"))
    return items


def c9_beat(ctx: Ctx) -> dict:
    """视觉节拍：连续 2 秒内至少一次变化（全屏帧间均差 > 0.02）。"""
    fps = ctx.meta["fps"]
    a = ctx.acts[0]
    worst = 9e9
    worst_at = 0.0
    prev = None
    for i in range(int(2.0 * fps) * 2):
        t = round(a["t0"] + a["d"] * 0.2 + i / fps, 4)
        L = lum(ctx.rgb(t))
        if prev is not None:
            d = float(np.abs(L - prev).mean())
            if d < worst:
                worst, worst_at = d, t
        prev = L
    return item("C9", "视觉节拍（每 ≤2s 必有变化）", "composition",
                "pass" if worst > 0.02 else "fail",
                f"窗口内最小帧间差 {worst:.4f} @t={worst_at:.2f}",
                spec="SPEC §8.2 C9",
                evidence={"worst": round(worst, 4), "t": worst_at},
                fix="" if worst > 0.02 else "存在真正的静止段：加次生运动（落叶/涟漪/灯焰/彩点节拍）")


def c10_caption(ctx: Ctx) -> list[dict]:
    """题款可读：衬底 p95 与墨字 p5 对比 ≥ 80。"""
    caps = ctx.meta.get("captions") or {}
    items = []
    for a in ctx.acts:
        c = caps.get(a["id"])
        if not c:
            continue
        cols, (ix, iy), size = c["cols"], c["at"], c["size"]
        t = round(a["t0"] + a["d"] * 0.5, 2)
        a_rgb = ctx.rgb(t, ) if False else ctx.rgb(t)
        L = lum(a_rgb)
        cg = size * 1.42
        per = max(len(x) for x in cols)
        x0 = int(max(0, ix - cg * (len(cols) - 1) - size * 0.62))
        x1 = int(min(ctx.W, ix + cg * 0.5))
        y0 = int(max(0, iy - size * 1.02))
        y1 = int(min(ctx.H, iy + size * 1.16 * per + size * 0.35))
        box = L[y0:y1, x0:x1]
        if box.size < 200:
            continue
        p5, p95 = np.percentile(box, [5, 95])
        contrast = float(p95 - p5)
        items.append(item("C10", f"题款可读 · {a['id']}", "composition",
                          "pass" if contrast >= 80 else "warn",
                          f"衬底 p95 {p95:.0f} − 墨字 p5 {p5:.0f} = 对比 {contrast:.0f}（≥80）",
                          spec="SPEC §8.2 C10", evidence={"t": t, "contrast": round(contrast, 1)},
                          fix="" if contrast >= 80 else "题款压在中间调上：垫一层纸色淡底（alpha≈112）"))
        break                                     # 抽第一处即可，避免判据耗时失控
    return items


def _is_placeholder(t: str) -> bool:
    """还没写内容的占位行（新片的剧本初稿就是这种）—— 这不是"叙事断点"，是"还没写"。"""
    t = (t or "").strip()
    return t.startswith("（") or "写这一幕要表达" in t


def c13_nodes(ctx: Ctx) -> dict:
    """剧本：写了多少条、还差多少条。

    两种状态必须分开：**没写**（skip，提醒去写）与**写了但有没落实的**（warn，真问题）。
    把它们混在一起，就会出现"7 项未表达（（写这一幕要表达的节点…"这种既看不懂又没用的警告。
    """
    try:
        md = ctx.mod.nodes_md()
    except Exception:
        md = ""
    if not md:
        return item("C13", "剧本齐备", "composition", "skip",
                    "本片还没有剧本（nodes.md）", spec="SPEC §8.2 C13")
    rows = []
    for ln in md.splitlines():
        s = ln.strip()
        if not s.startswith("- [ ]"):
            continue
        body = re.sub(r"（幕\s*[A-Za-z0-9_]+）\s*$", "", s[5:].strip()).strip()
        rows.append(body)
    todo = [t for t in rows if t and not _is_placeholder(t)]
    if not rows or (not todo and all(_is_placeholder(t) for t in rows)):
        return item("C13", "剧本齐备", "composition", "skip",
                    "剧本还没写（第 3 步：每一幕大致说清讲什么）", spec="SPEC §8.2 C13")
    if not todo:
        return item("C13", "剧本齐备", "composition", "pass",
                    f"剧本 {len(rows)} 条都有内容", spec="SPEC §8.2 C13")
    head = "、".join(f"「{t[:12]}」" for t in todo[:3])
    more = f" 等 {len(todo)} 条" if len(todo) > 3 else ""
    return item("C13", "剧本齐备", "composition", "warn",
                f"{len(todo)} 条还没在画面里落实：{head}{more}",
                spec="SPEC §8.2 C13 / §18.2",
                evidence={"todo": todo[:20]},
                fix="这几件事观众看不到就会看不懂：补镜头，或者把它们从剧本里删掉")


# ═══════════════ 声音（第 6 步）═══════════════
def _sound_files(ctx: Ctx) -> dict:
    """当前声轨产物：整轨 wav / 测量 json / 带声视频，以及**无声对照**（用于帧数比对）。"""
    o = fl.out_dir(ctx.fid)
    cur = {}
    p = os.path.join(o, "current.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                cur = json.load(f)
        except Exception:
            cur = {}
    out: dict = {"wav": "", "stats": None, "snd": []}
    for it in (cur.get("sound") or {}).get("files") or []:
        fp = os.path.join(o, it.get("file", ""))
        if not os.path.exists(fp):
            continue
        nm = os.path.basename(fp)
        if nm.endswith(".wav"):
            out["wav"] = fp
        elif nm == "sound.json":
            try:
                with open(fp, encoding="utf-8") as f:
                    out["stats"] = json.load(f)
            except Exception:
                pass
        elif nm.endswith("_snd.mp4"):
            out["snd"].append((fp, it.get("act", "")))
    out["mute"] = {}
    for kind in ("film", "clip"):
        for it in (cur.get(kind) or {}).get("files") or []:
            fp = os.path.join(o, it.get("file", ""))
            if fp.endswith(".mp4") and not fp.endswith("_snd.mp4") and os.path.exists(fp):
                out["mute"][it.get("act", "")] = fp
    return out


def _wav_len(path: str) -> tuple[float, float, float]:
    """(时长, RMS, 峰值) —— 直接读 WAV，不依赖任何音频库。"""
    import wave
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        x = np.frombuffer(w.readframes(n), "<i2").astype(np.float64) / 32768.0
    if x.size == 0:
        return 0.0, 0.0, 0.0
    return n / float(sr), float(np.sqrt((x ** 2).mean())), float(np.abs(x).max())


def s6_track_len(ctx: Ctx) -> dict:
    """S6 声轨时长＝幕表时长。

    为什么单列一条：这是**真踩过的坑** —— 声轨里写死 60 秒，片长扩到 71 秒后
    `mux` 带 `-shortest`，带声成片被静默截断，观众以为后半段没生成。
    凡与时间轴绑定的数字，都要从幕表派生。
    """
    s = _sound_files(ctx)
    if not s["wav"]:
        return item("S6", "声轨时长＝幕表时长", "structure", "skip",
                    "还没出声轨（第 6 步）", spec="SPEC §8.1 S6")
    dur = float((s["stats"] or {}).get("duration") or 0) or _wav_len(s["wav"])[0]
    want = float(ctx.meta["duration"])
    gap = dur - want
    ok = abs(gap) <= 0.15
    return item("S6", "声轨时长＝幕表时长", "structure", "pass" if ok else "fail",
                f'声轨 {dur:.2f}s / 幕表 {want:.2f}s（差 {gap:+.2f}s）'
                + ("　**带声版会被 -shortest 截断**" if gap < -0.15 else ""),
                spec="SPEC §8.1 S6 / §3 时间只有一个来源",
                evidence={"track_s": dur, "film_s": want, "gap_s": round(gap, 3)},
                fix="" if ok else "声轨时长必须从幕表现算（films/<id>/sound.py 读 acts），不要写死秒数")


def s8_level(ctx: Ctx) -> dict:
    """S8 响度与削顶：听不见（RMS < 0.04）和爆音（峰值 ≥1）都是硬伤。"""
    s = _sound_files(ctx)
    if not s["wav"]:
        return item("S8", "响度与削顶", "structure", "skip",
                    "还没出声轨（第 6 步）", spec="SPEC §8.1 S8")
    st = s["stats"]
    if st:
        rms, peak = float(st.get("rms") or 0), float(st.get("peak") or 0)
    else:
        _, rms, peak = _wav_len(s["wav"])
    if peak >= 0.999:
        stt, msg, fx = "fail", f"峰值 {peak:.3f} —— **削顶了**（会有爆音）", "软限幅：`0.98*tanh(x*1.5)`，别直接归一化到 1"
    elif rms < 0.04:
        stt, msg, fx = "warn", f"RMS {rms:.3f} —— 太轻，几乎听不见", "按 RMS 提升（上限 ×2.6）后再软限幅"
    elif rms > 0.35:
        stt, msg, fx = "warn", f"RMS {rms:.3f} —— 偏吵", "整体压一点，留出发声落点的余量"
    else:
        stt, msg, fx = "pass", f"RMS {rms:.3f} · 峰值 {peak:.2f}", ""
    return item("S8", "响度与削顶", "structure", stt, msg,
                spec="SPEC §8.1 S8", evidence={"rms": round(rms, 4), "peak": round(peak, 3)}, fix=fx)


def s9_av_sync(ctx: Ctx) -> dict:
    """S9 声画对齐：带声版与无声版**帧数必须相同**（差一帧就是声画错位）。"""
    s = _sound_files(ctx)
    if not s["snd"] or not s["mute"]:
        return item("S9", "声画帧数一致", "structure", "skip",
                    "还没有成对的带声/无声视频（先出视频，再出声轨）", spec="SPEC §8.1 S9")
    try:
        import imageio_ffmpeg as iof
    except Exception:
        return item("S9", "声画帧数一致", "structure", "skip", "缺 imageio-ffmpeg", spec="SPEC §8.1 S9")
    bad, rows = [], []
    for fp, act in s["snd"][:4]:
        src = s["mute"].get(act) or next(iter(s["mute"].values()), "")
        if not src:
            continue
        n1, d1 = iof.count_frames_and_secs(src)
        n2, d2 = iof.count_frames_and_secs(fp)
        same = int(n1) == int(n2)
        rows.append({"act": act, "silent": int(n1), "sound": int(n2)})
        if not same:
            bad.append(f'{act or "全片"}：无声 {int(n1)} 帧 / 带声 {int(n2)} 帧')
    if not rows:
        return item("S9", "声画帧数一致", "structure", "skip",
                    "没有可比对的一对（带声视频对应的无声版不在了）", spec="SPEC §8.1 S9")
    return item("S9", "声画帧数一致", "structure", "pass" if not bad else "fail",
                "；".join(bad) if bad else
                f'{len(rows)} 段声画帧数一致（{rows[0]["sound"]} 帧）',
                spec="SPEC §8.1 S9",
                evidence={"rows": rows},
                fix="" if not bad else "声轨比画面短会被截断：让声轨长度从幕表派生，且 mux 不许带 -shortest")


def c_skipped(ctx: Ctx) -> list[dict]:
    """**诚实地列出尚未实现的判据** —— 不假装通过。"""
    rows = [
        ("C4", "图层可见性（关键部位不被同色上层覆盖）", "需要构件级包围盒信息（M7 随构件库一起补）"),
        ("C5", "图层顺序显式（L0–L7）", "需要 build 层暴露图层分组（M8 迁入 films/ 时补）"),
        ("C6", "地平线分离（人头不撞建筑）", "需要人物基线元数据（M8 补）"),
        ("C7", "镜头语言（CV / 停顿 / 反向 / 轴心位移）", "需要镜头关键帧元数据（M8 补）"),
        ("C11", "环境让路（主体周围无高频线、水纹 ≤14）", "需要构件级信息（M7 补）"),
        ("C12", "角色可辨（形或色可区分）", "需要角色表（M8 补）"),
        ("C14", "音画对齐（音效落点前后 0.25s 有对应事件）", "需要音效落点表（M11 补）"),
        ("C15", "元素配比（同屏叶节点 ≤120）", "需要叶节点计数接口（M7 补）"),
        ("A1", "审美层：诗意 / 现代感 / 动幅手感 / 叙事节奏 / 色彩浓淡", "**脚本不得判定**，交人过目（§8.3）"),
    ]
    return [item(j, n, "composition" if j[0] in "C" else "aesthetic", "skip",
                 "待实现：" + why, spec="SPEC §8") for j, n, why in rows]


# ═══════════════ 执行 ═══════════════
def plan() -> list[dict]:
    return [{"id": "S4", "name": "确定性"}, {"id": "S3", "name": "帧互异"},
            {"id": "S7", "name": "亮度闪烁"}, {"id": "S5", "name": "时长与帧数"},
            {"id": "C1", "name": "深色存在性（逐幕）"}, {"id": "C2", "name": "明度分层（逐幕）"},
            {"id": "C3", "name": "主体尺度（逐幕）"}, {"id": "C8", "name": "帧间连续性（逐幕）"},
            {"id": "C9", "name": "视觉节拍"}, {"id": "C10", "name": "题款可读"},
            {"id": "C13", "name": "叙事节点齐备"},
            {"id": "S6", "name": "声轨时长"}, {"id": "S8", "name": "响度与削顶"},
            {"id": "S9", "name": "声画帧数一致"}]


def run(fid: str, scope: str = "full", progress=None, save: bool = True) -> dict:
    """跑判据。progress(done, total, note) 由调用方决定怎么写。"""
    ctx = Ctx(fid)
    steps = plan()
    if scope in ("static", "sound"):
        # static / sound：跳过最重的两条（逐幕主体定位与逐幕帧间连续性，共约 150 帧渲染），
        # 保留"秒级就能给出结论"的那些（确定性／帧互异／闪烁／帧数／色调／题款／节点表／声音）。
        steps = [s for s in steps if s["id"] not in ("C3", "C8")]
        if scope == "static":
            # S9 要数两个视频的帧数（几秒），只在画面或声音落定后才值得跑
            steps = [s for s in steps if s["id"] != "S9"]
    items: list[dict] = []
    total = len(steps) + 2
    t_start = time.time()

    def tick(n, note):
        if progress:
            progress(n, total, note)

    tick(0, "载入工程")
    for i, st in enumerate(steps):
        jid = st["id"]
        if jid == "S4":
            items.append(s4_determinism(ctx))
        elif jid == "S3":
            items.append(s3_distinct(ctx))
        elif jid == "S7":
            items.append(s7_flash(ctx))
        elif jid == "S5":
            items.append(s5_frames(ctx))
        elif jid == "C1":
            items += c1c2_tone(ctx)
        elif jid == "C2":
            items += c2_layers(ctx)
        elif jid == "C3":
            items += c3_subject(ctx)
        elif jid == "C8":
            items += c8_continuity(ctx)
        elif jid == "C9":
            items.append(c9_beat(ctx))
        elif jid == "C10":
            items += c10_caption(ctx)
        elif jid == "C13":
            items.append(c13_nodes(ctx))
        elif jid == "S6":
            items.append(s6_track_len(ctx))
        elif jid == "S8":
            items.append(s8_level(ctx))
        elif jid == "S9":
            items.append(s9_av_sync(ctx))
        tick(i + 1, f"{st['id']} {st['name']}")

    tick(total - 1, "未实现判据登记")
    items += c_skipped(ctx)

    summary = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
    for it in items:
        summary[it["status"]] = summary.get(it["status"], 0) + 1
    report = {"film": fid, "when": time.strftime("%Y-%m-%d %H:%M:%S"),
              "scope": scope, "elapsed_s": round(time.time() - t_start, 1),
              "renders": ctx.renders, "summary": summary, "items": items,
              "note": "审美层不由脚本判定；skip 项是尚未实现的判据，不是通过"}
    tick(total, "完成")
    if save:
        p = os.path.join(fl.out_dir(fid), "judges.json")
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    return report
