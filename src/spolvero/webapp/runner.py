"""子进程执行器：`python -m spolvero.webapp.runner <job.json>`

**所有长任务都在这里跑**（SPEC §17.3）：主进程只读 `progress.json`。
支持的任务：stills / sheet / judges / clip / sound / film / part_check。
顺序即工作顺序：**画面（clip）→ 声音（sound）→ 成片（film）**，三步各判各的。

两条硬要求：
- **断点续渲**：帧文件按帧号命名，已存在即跳过 —— 改一处参数只重画受影响时段。
- **音频从幕表现算**：调 `films/<id>/sound.py` 或 `spike/audio.py` 时，
  时长由工程包给，**不在这里写死秒数**（§3 派生约束）。
"""

from __future__ import annotations

import json
import os
import sys
import time

import numpy as np


# ── 工具 ────────────────────────────────────────────────────────────────
def _say(jid: str, msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _png_bytes(a: np.ndarray) -> bytes:
    import skia
    rgba = np.empty((a.shape[0], a.shape[1], 4), np.uint8)
    rgba[:, :, 0] = a[:, :, 2]
    rgba[:, :, 1] = a[:, :, 1]
    rgba[:, :, 2] = a[:, :, 0]
    rgba[:, :, 3] = 255
    img = skia.Image.fromarray(np.ascontiguousarray(rgba), skia.kBGRA_8888_ColorType,
                               alphaType=skia.kOpaque_AlphaType)
    return bytes(img.encodeToData())


def _write_png(path: str, a: np.ndarray) -> None:
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(_png_bytes(a))
    os.replace(tmp, path)


def _read_png_rgb(path: str) -> np.ndarray:
    import skia
    img = skia.Image.open(path)
    a = img.toarray()
    if img.colorType() == skia.kBGRA_8888_ColorType:
        return a[:, :, [2, 1, 0]]
    return a[:, :, :3]


# ── 产物按批次归档：**历史留在历史里，当前留在当前** ─────────────────────
def _batch(fid: str, jid: str, kind: str) -> str:
    """每次任务的产物落进自己的目录 `out/runs/<任务号>_<类型>/`。

    为什么不能都用固定文件名：一覆盖，上一次的产物就没了，
    界面上"当前"和"历史"就分不开 —— 用户看到的就是一堆文件混在一起。
    """
    from . import films as fl
    d = os.path.join(fl.out_dir(fid), "runs", f"{jid}_{kind}")
    os.makedirs(d, exist_ok=True)
    return d


def _mark_current(fid: str, kind: str, jid: str, files: list[dict]) -> None:
    """把"当前"指针写进 out/current.json（原子写）。"""
    from . import films as fl
    p = os.path.join(fl.out_dir(fid), "current.json")
    cur = {}
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                cur = json.load(f)
        except Exception:
            cur = {}
    cur[kind] = {"job": jid, "when": time.strftime("%Y-%m-%d %H:%M:%S"), "files": files}
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _rel(fid: str, path: str) -> str:
    from . import films as fl
    return os.path.relpath(path, fl.out_dir(fid)).replace("\\", "/")


def _auto_check(fid: str, jid: str, scope: str = "static") -> str:
    """产物一出就**自动检验** —— 用户不该记得"还要点一下跑判据"。

    自动检验在产物落盘之后、同一个子进程里跑：几秒到几十秒。
    它失败**不算任务失败**（画面已经出来了），只把摘要写进 note 让界面显示。
    scope=static 是秒级的（确定性/帧互异/色调/题款/节点表）；
    clip 出来之后跑 full，把逐幕的 C3 主体尺度与 C8 帧间连续性也算上。
    """
    try:
        from . import judges as J
        _say(jid, f"自动检验（{scope}）…")
        r = J.run(fid, scope=scope, save=True, progress=lambda d, t, n: None)
        s = r["summary"]
        return f'自动检验：通过 {s["pass"]} · 警告 {s["warn"]} · 失败 {s["fail"]}'
    except Exception as e:
        return f"自动检验没能跑完（{type(e).__name__}）：产物不受影响"


def _built(fid: str, kind: str, extra: dict | None = None) -> None:
    """记录这批产物是靠什么画出来的（依赖一变就自动过期，§4 派生约束）。"""
    try:
        from .pipeline import mark_film
        mark_film(fid, kind, extra)
    except Exception as e:
        _say("", f"依赖记录失败：{e}")


def _built_act(fid: str, kind: str, aid: str, extra: dict | None = None) -> None:
    """按**幕**登记依赖 —— 别的幕改了不该让这一幕重渲。"""
    try:
        from .pipeline import mark_act
        mark_act(fid, kind, aid, extra)
    except Exception as e:
        _say("", f"依赖记录失败：{e}")


def _built_sound(fid: str, extra: dict | None = None) -> None:
    try:
        from .pipeline import mark_film
        mark_film(fid, "sound", extra)
    except Exception as e:
        _say("", f"依赖记录失败：{e}")


def _prev_files(fid: str, kind: str) -> list[dict]:
    """上一版"当前产物"的记录（用于把跳过的幕原样保留，而不是把它们从指针里抹掉）。"""
    from . import films as fl
    p = os.path.join(fl.out_dir(fid), "current.json")
    if not os.path.exists(p):
        return []
    try:
        with open(p, encoding="utf-8") as f:
            return (json.load(f).get(kind) or {}).get("files", [])
    except Exception:
        return []


def _fresh(fid: str, kind: str, aid: str) -> bool:
    try:
        from .pipeline import is_fresh
        return is_fresh(fid, kind, aid) and bool([x for x in _prev_files(fid, kind)
                                                  if x.get("act") == aid])
    except Exception:
        return False


def _film_fresh(fid: str) -> bool:
    try:
        from .pipeline import is_film_fresh
        return is_film_fresh(fid, "film") and bool(_prev_files(fid, "film"))
    except Exception:
        return False


def _sound_fresh(fid: str) -> bool:
    """声轨的依赖是**所有幕**（幕长一改，落点全变），所以按整片指纹判。"""
    try:
        from .pipeline import is_film_fresh
        return is_film_fresh(fid, "sound") and bool(_prev_files(fid, "sound"))
    except Exception:
        return False


# 各幕默认景别（真景别：图别一给到，主体才读得出）——键是幕 id，值是 (scale, kx, ky)。
# **存比例不存像素**（下表的分母就是标定画幅 1600×900）：相机 pivot 是画幅的函数，
# 写死像素值换到竖屏就会"看着没变、取景偏到画外"。渲染时按实际 size 换算。
SHOT_SCALE = {
    "road": (1.10, 800 / 1600, 540 / 900), "call": (1.60, 700 / 1600, 600 / 900),
    "wood": (2.00, 760 / 1600, 640 / 900), "moon": (2.10, 780 / 1600, 600 / 900),
    "dance": (1.50, 960 / 1600, 560 / 900), "into": (1.80, 1080 / 1600, 420 / 900),
    "wall": (1.55, 800 / 1600, 620 / 900), "leave": (1.20, 700 / 1600, 560 / 900),
    "crash": (2.60, 820 / 1600, 660 / 900),
}
SHOT_SCALE_DEFAULT = (1.20, 800 / 1600, 540 / 900)


def shot_camera(aid: str, size, shot: dict | None = None) -> tuple[float, float, float]:
    """(scale, px, py)：景别按**当前画幅**换算成像素 pivot。

    `shot` 来自幕表（`film.yaml` 的 acts[].shot），**人改了就以人改的为准** ——
    内置那张表只是"还没调过"时的缺省，不是上限。
    """
    s, kx, ky = SHOT_SCALE.get(aid, SHOT_SCALE_DEFAULT)
    if shot:
        s = float(shot.get("scale") or s)
        kx = float(shot.get("kx", kx))
        ky = float(shot.get("ky", ky))
    return (s, float(size[0]) * kx, float(size[1]) * ky)



# ── 各类任务 ────────────────────────────────────────────────────────────
def task_stills(jid, fid, args, rep):
    """出关键图。**支持只出指定几幕**（args.acts）—— 工作单位是"幕"，不是整片。

    **依赖没变的幕一律跳过**（args.force 可强制重画）：改第三幕的题款，
    不该把第一幕的图再画一遍。跳过的那几幕，原来的产物指针原样保留。
    """
    from . import films as fl
    m = fl.load(fid)
    o = _batch(fid, jid, "stills")
    pts = m.stills_points()
    only = set(args.get("acts") or [])
    if only:
        pts = [p for p in pts if p["act"] in only]
    force = bool(args.get("force"))
    todo = [p for p in pts if force or not _fresh(fid, "stills", p["act"])]
    skipped = [p for p in pts if p not in todo]
    prev = {x.get("act"): x for x in _prev_files(fid, "stills")}

    size = fl.meta(fid)["size"]
    rep(0, max(1, len(todo)), f"待画 {len(todo)} 幕（跳过 {len(skipped)} 幕：依赖没变）")
    made = []
    shots = {a["id"]: (a.get("shot") or {}) for a in fl.meta(fid)["acts"]}
    for i, p in enumerate(todo):
        cam = shot_camera(p["act"], size, shots.get(p["act"]))
        ins = None
        if p.get("caption"):
            c = fl.meta(fid)["captions"][p["act"]]
            ins = (c["cols"], c["at"][0], c["at"][1], c["size"])
        a = m.render_frame(p["t"], camera=cam, ins=ins)
        name = f"{i+1:02d}_{p['act']}.png"
        _write_png(os.path.join(o, name), a)
        rec = {"file": _rel(fid, os.path.join(o, name)), "name": name,
               "note": p["note"], "t": p["t"], "act": p["act"], "shot": f"{cam[0]:.2f}×"}
        made.append(rec)
        _built_act(fid, "stills", p["act"], {"file": rec["file"]})
        rep(i + 1, len(todo), p["note"])
    for p in skipped:                      # 跳过的幕：保留上一版记录，不让它们从"当前"里消失
        if p["act"] in prev:
            made.append(prev[p["act"]])
    if made:
        _mark_current(fid, "stills", jid, made)
    note = f"{len(todo)} 张关键图（真景别 + 题款）"
    if skipped:
        note += f" · 跳过 {len(skipped)} 幕（依赖没变，复用旧图）"
    if not todo:
        return {"artifacts": [], "note": "所有幕的依赖都没变 —— 一张都没重画。"}
    chk = _auto_check(fid, jid, "static")
    return {"artifacts": made, "note": note + " · " + chk}


def task_sheet(jid, fid, args, rep):
    from . import films as fl
    m = fl.load(fid)
    o = _batch(fid, jid, "sheet")
    acts = fl.meta(fid)["acts"]
    reps = int(args.get("per_act", 2))
    ts = []
    for a in acts:
        for k in range(reps):
            ts.append(a["t0"] + a["d"] * (k + 1) / (reps + 1))
    rep(0, len(ts), "渲染分镜格")
    tiles = []
    for i, t in enumerate(ts):
        tiles.append(m.render_frame(round(t, 2))[::3, ::3])
        rep(i + 1, len(ts), f"t={t:.1f}")
    per = 5
    th, tw = tiles[0].shape[0], tiles[0].shape[1]      # 填充块尺寸按实际格子算，别写死
    sep = lambda: np.full((th, 6, 3), 60, np.uint8)
    rows = []
    for r0 in range(0, len(tiles), per):
        chunk = tiles[r0:r0 + per]
        row = []
        for j in range(per):                            # 每行恒为 per 格 + (per-1) 条分隔
            row.append(chunk[j] if j < len(chunk)
                       else np.full((th, tw, 3), 60, np.uint8))
            if j < per - 1:
                row.append(sep())
        rows.append(np.concatenate(row, axis=1))
        rows.append(np.full((6, rows[0].shape[1], 3), 60, np.uint8))
    sheet = np.concatenate(rows[:-1], axis=0)
    p = os.path.join(o, "sheet.png")
    _write_png(p, sheet)
    arts = [{"file": _rel(fid, p), "name": "sheet.png", "note": f"分镜格 {len(ts)} 格"}]
    _mark_current(fid, "sheet", jid, arts)
    return {"artifacts": arts, "note": f"分镜格 {len(ts)} 格"}


def task_judges(jid, fid, args, rep):
    from . import judges as J
    from . import films as fl
    import shutil
    rep(0, 1, "载入")
    r = J.run(fid, scope=args.get("scope", "full"),
              progress=lambda d, t, note: rep(d, t, note), save=True)
    # 归档一份到本批次目录（out/judges.json 始终是"最新报告"，批次目录留历史）
    o = _batch(fid, jid, "judges")
    src = os.path.join(fl.out_dir(fid), "judges.json")
    dst = os.path.join(o, "judges.json")
    try:
        shutil.copyfile(src, dst)
    except Exception:
        pass
    s = r["summary"]
    arts = [{"file": _rel(fid, dst), "name": "judges.json",
             "note": f"通过 {s['pass']} · 警告 {s['warn']} · 失败 {s['fail']} · 未实现 {s['skip']}"}]
    _mark_current(fid, "judges", jid, arts)
    return {"artifacts": arts,
            "note": f"通过 {s['pass']} · 警告 {s['warn']} · 失败 {s['fail']} · 未实现 {s['skip']}",
            "report": r}


# ── 渲染内核（带断点续渲 + 进度）────────────────────────────────────────
def _render_one(task):
    """子进程：渲染一帧并落盘。任务元组必须可 pickle，故只传基本类型。"""
    fid, idx, out_path, root = task
    if os.path.exists(out_path):
        return idx, True
    if root not in sys.path:
        sys.path.insert(0, os.path.join(root, "src"))
    spike = os.path.join(root, "spike")
    if spike not in sys.path:
        sys.path.insert(0, spike)
    from spolvero.webapp import films as fl
    m = fl.load(fid)
    fps = fl.meta(fid)["fps"]
    a = m.render_frame(idx / fps)
    _write_png(out_path, a)
    return idx, False


def render_range(jid, fid, args, rep, root):
    from . import films as fl
    from concurrent.futures import ProcessPoolExecutor, as_completed

    meta = fl.meta(fid)
    fps = meta["fps"]
    dur = meta["duration"]
    if args.get("act"):                       # 按幕渲染：时刻从幕表现取（不写死）
        a = next(x for x in meta["acts"] if x["id"] == args["act"])
        t0, t1 = float(a["t0"]), float(a["t1"])
    else:
        t0 = float(args.get("t0", 0.0))
        t1 = float(args.get("t1", dur))
    i0 = max(0, int(round(t0 * fps)))
    i1 = min(meta["frames"], int(round(t1 * fps)))
    fdir = os.path.join(fl.out_dir(fid), "frames")
    os.makedirs(fdir, exist_ok=True)

    idx = list(range(i0, i1))
    todo = [i for i in idx if not os.path.exists(os.path.join(fdir, f"f{i:05d}.png"))]
    done0 = len(idx) - len(todo)
    rep(done0, len(idx), f"待渲 {len(todo)} 帧（已有 {done0} 帧，跳过）")
    _say(jid, f"帧目录 {fdir}；本次需渲染 {len(todo)}/{len(idx)} 帧")

    procs = int(args.get("procs") or 0)
    if procs <= 0:
        procs = min(8, max(1, (os.cpu_count() or 4) - 2))
    done = done0
    t_start = time.perf_counter()
    if todo:
        if procs == 1:
            for i in todo:
                _render_one((fid, i, os.path.join(fdir, f"f{i:05d}.png"), root))
                done += 1
                sp = (time.perf_counter() - t_start) / max(1, done - done0)
                rep(done, len(idx), f"{done}/{len(idx)} 帧 · {1/sp:.1f} 帧/秒"
                                    f" · 预计还需 {(len(idx)-done)*sp/60:.1f} 分钟")
        else:
            with ProcessPoolExecutor(max_workers=procs) as pool:
                futs = [pool.submit(_render_one,
                                    (fid, i, os.path.join(fdir, f"f{i:05d}.png"), root))
                        for i in todo]
                for f in as_completed(futs):
                    f.result()
                    done += 1
                    sp = (time.perf_counter() - t_start) / max(1, done - done0)
                    rep(done, len(idx),
                        f"{done}/{len(idx)} 帧 · {1/sp*procs:.1f} 帧/秒/核 ×{procs}"
                        f" · 预计还需 {(len(idx)-done)*sp/60:.1f} 分钟")
    return fdir, idx


def encode(jid, fid, args, rep, root, fdir, idx, o, suffix=""):
    import imageio_ffmpeg
    from . import films as fl
    meta = fl.meta(fid)
    fps = meta["fps"]
    w, h = meta["size"]
    clip = args.get("t0") is not None or bool(args.get("act"))
    name = f"clip{suffix}.mp4" if clip else f"film{suffix}.mp4"
    path = os.path.join(o, name)
    writer = imageio_ffmpeg.write_frames(
        path, (w, h), fps=fps, codec="libx264", pix_fmt_in="rgb24", pix_fmt_out="yuv420p",
        macro_block_size=1, output_params=["-crf", "18"])
    writer.send(None)
    for k, i in enumerate(idx):
        rgb = _read_png_rgb(os.path.join(fdir, f"f{i:05d}.png"))
        writer.send(np.ascontiguousarray(rgb).tobytes())
        if k % 30 == 0:
            rep(k, len(idx), f"编码 {k}/{len(idx)}")
    writer.close()
    rep(len(idx), len(idx), "编码完成")
    return path, name


def task_render(jid, fid, args, rep, root):
    """片段或全片：渲染 → 编码。**只出画面，不配音** —— 声音是下一步的事。

    为什么把声音摘出去：合声轨要重跑 ffmpeg，而调画面时每改一次都要重渲；
    把两件不同频的事捆在一起，画面每改一次就多付一次声音的等待。
    而且"这段画面行不行"和"这一幕该有什么声音"是两种判断，放在一起看不清。

    **依赖没变就不重渲**（args.force 可强制）：
    单幕片段的依赖是"这一幕的参数 + 构件 + 色板 + 渲染器"；
    全片的依赖是所有幕。改第三幕，不该动第一幕的视频。
    """
    from . import films as fl
    is_clip = args.get("t0") is not None or bool(args.get("act"))
    act = str(args.get("act") or "")
    force = bool(args.get("force"))
    if not force:
        if is_clip and act and _fresh(fid, "clip", act):
            _say(jid, f"幕 {act} 依赖没变 —— 跳过，复用上一版")
            return {"artifacts": [], "skipped": True,
                    "note": f"幕 {act} 依赖没变，复用上一版视频（没重渲）"}
        if not is_clip and _film_fresh(fid):
            _say(jid, "全片依赖没变 —— 跳过，复用上一版成片")
            return {"artifacts": [], "skipped": True, "note": "全片依赖没变，复用上一版成片（没重渲）"}

    o = _batch(fid, jid, "clip" if is_clip else "film")
    fdir, idx = render_range(jid, fid, args, rep, root)
    path, name = encode(jid, fid, args, rep, root, fdir, idx, o)
    arts = [{"file": _rel(fid, path), "name": name, "act": act,
             "note": f"{len(idx)} 帧 @ {fl.meta(fid)['fps']}fps"}]
    kind = "clip" if is_clip else "film"
    if is_clip and act:
        # 只重渲了一幕：把它插到"当前"里，**其它幕的记录原样保留**
        keep = [x for x in _prev_files(fid, "clip") if x.get("act") != act]
        _mark_current(fid, kind, jid, arts + keep)
    else:
        _mark_current(fid, kind, jid, arts)
    if is_clip and act:
        _built_act(fid, "clip", act, {"file": arts[0]["file"]})
    else:
        _built(fid, kind, {"file": arts[0]["file"]})
    chk = _auto_check(fid, jid, "full" if is_clip else "static")
    return {"artifacts": arts, "note": "；".join(a["note"] for a in arts) + " · " + chk}


def _sound_for(fid):
    """本片用哪一份声音设计（三选一的顺序见 `sound.resolve`）。

    为什么要有兜底：只有"本片 sound.py"一条路时，新片在第 6 步看到的是
    "还没有声轨模块" —— 那等于这一步不存在。**先让每一幕都有声音**，人再提意见改。
    """
    from . import sound as SND
    return SND.resolve(fid)


def _wav_write(path: str, x: np.ndarray, sr: int) -> str:
    import wave
    pcm = (np.clip(np.asarray(x, np.float64), -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(pcm.tobytes())
    return path


def _wav_read(path: str) -> tuple[np.ndarray, int]:
    import wave
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
    return np.frombuffer(raw, "<i2").astype(np.float64) / 32768.0, sr


def _ffmpeg_mux(video_in: str, audio: str, video_out: str) -> str:
    """把声轨合进视频（视频流 copy，不重编码）。

    **不用 `-shortest`**：声轨短于视频时会静默把画面截断 —— 这个坑真踩过
    （60 秒声轨 + `-shortest` → 71 秒的片子被截到 60 秒，观众以为后半段没生成）。
    """
    import imageio_ffmpeg
    import subprocess
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [exe, "-y", "-loglevel", "error", "-i", video_in, "-i", audio,
           "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", video_out]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "ignore")[:400])
    return video_out


def _track_array(mod, fid="") -> tuple[np.ndarray, int]:
    """取声轨样本：优先 `build()`（能拿到数组做逐幕测量），否则退回 `write_wav()` 再读回。

    `build` 有的稿子带 fid、有的不带 —— 用签名判断，别靠 try/except 碰运气。
    """
    import inspect
    sr = int(getattr(mod, "SR", 44100))
    fn = getattr(mod, "build", None)
    if callable(fn):
        x = fn(fid) if len(inspect.signature(fn).parameters) else fn()
        return np.asarray(x, np.float64), sr
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        mod.write_wav(tmp)
        return _wav_read(tmp)
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass


def _sound_metrics(x: np.ndarray, sr: int, acts: list) -> dict:
    """逐幕响度与落点数 —— 给人看的那一栏"这一幕有没有声音"。

    落点数用**包络上升沿**计数：越过阈值（3×中位 + 0.02）的次数。
    它不追求精确，只回答"这一幕是空的还是有几下"。
    """
    per = []
    for a in acts:
        i0 = int(float(a["t0"]) * sr)
        i1 = min(len(x), int(float(a["t1"]) * sr))
        seg = x[i0:i1]
        if seg.size < 8:
            per.append({"id": a["id"], "note": a.get("note", a["id"]), "t0": a["t0"],
                        "t1": a["t1"], "rms": 0.0, "peak": 0.0, "events": 0, "silent": True})
            continue
        env = np.abs(seg)
        rms = float(np.sqrt((seg ** 2).mean()))
        peak = float(env.max())
        # 先做 50ms 平滑再取上升沿，再按 0.15s 去抖 —— 直接数原始样本的越界次数
        # 会把连续的风声垫算成几千个"落点"（实测 5 秒的幕数出 3701），那不是落点，是噪声。
        w = max(1, int(0.05 * sr))
        c = np.concatenate([[0.0], np.cumsum(env)])
        sm = (c[w:] - c[:-w]) / w
        if sm.size == 0:
            sm = env
        elif sm.size < env.size:
            sm = np.concatenate([sm, np.full(env.size - sm.size, sm[-1])])
        thr = max(0.06, 3.0 * float(np.median(sm)) + 0.02)
        idx = np.flatnonzero((sm[1:] > thr) & (sm[:-1] <= thr)) + 1
        events, last = 0, -1e9
        for i in idx:
            t = float(i) / sr
            if t - last >= 0.15:
                events += 1
                last = t
        # silent＝**真的没声**（响度判）；events==0 只是"没有明显的落点"，
        # 风声垫与长音那一类本来就没有落点，把它算成静音是假警报（实测 4 幕被误判）。
        per.append({"id": a["id"], "note": a.get("note", a["id"]), "t0": a["t0"], "t1": a["t1"],
                    "rms": round(rms, 4), "peak": round(peak, 3), "events": events,
                    "silent": bool(rms < 0.02), "flat": events == 0})
    return {"duration": round(len(x) / float(sr), 3), "sr": sr,
            "rms": round(float(np.sqrt((x ** 2).mean())), 4),
            "peak": round(float(np.abs(x).max()), 3), "per_act": per}


def _wave_png(x: np.ndarray, sr: int, acts: list, W: int = 1200, H: int = 260) -> np.ndarray:
    """波形图：**逐幕**画出来（幕界竖线 + 静音幕标红）—— 一眼看出哪一幕没配声。"""
    a = np.empty((H, W, 3), np.uint8)
    a[:, :, 0], a[:, :, 1], a[:, :, 2] = 246, 242, 232
    dur = max(1e-6, len(x) / float(sr))
    step = max(1, len(x) // W)
    m = x[:step * W].reshape(W, step)
    lo, hi = m.min(1), m.max(1)
    mid = H // 2
    y0 = np.clip(mid - (hi * H * 0.46).astype(int), 0, H - 1)
    y1 = np.clip(mid - (lo * H * 0.46).astype(int), 0, H - 1)
    for i in range(W):
        t, b = int(y0[i]), int(y1[i])
        if b < t:
            t, b = b, t
        a[t:b + 1, i] = (42, 42, 36)
    for act in (acts or []):                       # 幕界：竖线
        cx = int(float(act["t0"]) / dur * W)
        if 0 <= cx < W:
            a[:, cx:cx + 1] = (150, 140, 120)
    for i, act in enumerate(acts or []):           # 静音幕：底部一条红
        st = _sound_metrics(x, sr, [act])["per_act"][0]
        if st.get("silent"):
            cx0 = int(float(act["t0"]) / dur * W)
            cx1 = int(float(act["t1"]) / dur * W)
            a[H - 7:H, max(0, cx0):min(W, cx1)] = (178, 58, 44)
    a[mid - 1:mid + 1, :] = (120, 115, 100)
    return a


def task_sound(jid, fid, args, rep):
    """第 6 步：出声轨 + 逐幕测量 + 波形图，并把声合到已有的画面上。

    **时长必须从幕表派生**（`films/<id>/sound.py` 或 `spike/audio.py` 自己算），
    这里只做测量与合成 —— 写死秒数的后果是带声成片被 `-shortest` 截断。
    """
    from . import films as fl
    force = bool(args.get("force"))
    if not force and _sound_fresh(fid):
        _say(jid, "声轨依赖没变 —— 跳过，复用上一版")
        return {"artifacts": [], "skipped": True, "note": "声轨依赖没变，复用上一版（没重出）"}

    mod = _sound_for(fid)
    if mod is None:
        return {"artifacts": [], "note":
                "还没有声轨模块 —— 在下面说一句「给每一幕配上声音」（会生成 films/%s/sound.py）" % fid}
    from .pipeline import _film_cfg
    o = _batch(fid, jid, "sound")
    rep(0, 4, "合成声轨")
    x, sr = _track_array(mod, fid)
    gain = float((_film_cfg(fid).get("sound") or {}).get("gain") or 1.0)
    if abs(gain - 1.0) > 1e-6:
        x = np.clip(x * gain, -1.0, 1.0)          # 增益后必须再限幅，否则会削顶
    rep(1, 4, "写 WAV")
    wav = _wav_write(os.path.join(o, "track.wav"), x, sr)

    rep(2, 4, "逐幕测量")
    meta = fl.meta(fid)
    stats = _sound_metrics(x, sr, meta["acts"])
    stats["film_duration"] = round(float(meta["duration"]), 3)
    stats["acts"] = len(meta["acts"])
    _write_png(os.path.join(o, "wave.png"), _wave_png(x, sr, meta["acts"]))
    with open(os.path.join(o, "sound.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    rep(3, 4, "合到画面上")
    arts = [
        {"file": _rel(fid, wav), "name": "track.wav",
         "note": f'{stats["duration"]:.1f}s · RMS {stats["rms"]:.3f} · 峰值 {stats["peak"]:.2f}'},
        {"file": _rel(fid, os.path.join(o, "wave.png")), "name": "wave.png", "note": "波形（逐幕）"},
        {"file": _rel(fid, os.path.join(o, "sound.json")), "name": "sound.json", "note": "逐幕测量"},
    ]
    muted = [p["note"] for p in stats["per_act"] if p.get("silent")]
    flats = [p["note"] for p in stats["per_act"] if not p.get("silent") and p.get("flat")]
    muxed = 0
    for rec in _prev_files(fid, "clip") + _prev_files(fid, "film"):
        src = os.path.join(fl.out_dir(fid), rec.get("file", ""))
        if not src.endswith(".mp4") or not os.path.exists(src):
            continue
        if rec.get("name", "").endswith("_snd.mp4"):
            continue
        dst = os.path.join(o, os.path.basename(rec["file"]).replace(".mp4", "_snd.mp4"))
        try:
            (mod.mux if callable(getattr(mod, "mux", None)) else _ffmpeg_mux)(src, wav, dst)
            arts.append({"file": _rel(fid, dst), "name": os.path.basename(dst),
                         "act": rec.get("act", ""),
                         "note": ("带声 · " + (rec.get("note", "") or ""))[:60]})
            muxed += 1
        except Exception as e:
            _say(jid, f"合声失败（{os.path.basename(src)}）：{e}")
    _mark_current(fid, "sound", jid, arts)
    _built_sound(fid, {"file": arts[0]["file"]})
    rep(4, 4, "完成")
    note = (f'声轨 {stats["duration"]:.1f}s（幕表 {meta["duration"]:.1f}s）'
            f' · 峰值 {stats["peak"]:.2f} · 合了 {muxed} 段')
    if abs(stats["duration"] - float(meta["duration"])) > 0.15:
        note += f' · **时长差 {stats["duration"] - float(meta["duration"]):+.1f}s**'
    if muted:
        note += f' · {len(muted)} 幕几乎无声：{"、".join(muted[:3])}'
    elif flats:
        note += f' · {len(flats)} 幕没有明显落点：{"、".join(flats[:3])}'
    chk = _auto_check(fid, jid, "sound")
    return {"artifacts": arts, "note": note + " · " + chk}


def task_part_check(jid, fid, args, rep):
    """构件检验台（SPEC §17.5）：P1 几何有效 / P2 点数恒定 / P3 参数差异化 / P4 接触表（待人看）。"""
    from . import films as fl
    m = fl.load(fid)
    name = args.get("part") or ""
    res = []
    if not hasattr(m, "check_part"):
        return {"artifacts": [], "checks": [],
                "note": "本片尚未接入构件检验（需 films/<id>/adapter.py 提供 check_part()，M9 补）"}
    rep(0, 1, f"检验 {name}")
    res = m.check_part(name, progress=lambda d, t, n: rep(d, t, n))
    rep(1, 1, "完成")
    return {"artifacts": res.get("artifacts", []), "checks": res.get("checks", []),
            "note": res.get("note", "")}


# ── 入口 ────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    spec_path = argv[0]
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    jid, kind, fid = spec["id"], spec["kind"], spec["film"]
    args = spec.get("args") or {}
    root = spec["root"]
    from . import jobs as J

    def rep(done, total, note):
        J.write_progress(jid, state="running", done=int(done), total=int(total), note=str(note))

    try:
        _say(jid, f"任务 {kind} · 影片 {fid}")
        if kind == "stills":
            out = task_stills(jid, fid, args, rep)
        elif kind == "sheet":
            out = task_sheet(jid, fid, args, rep)
        elif kind == "judges":
            out = task_judges(jid, fid, args, rep)
        elif kind in ("clip", "film"):
            out = task_render(jid, fid, args, rep, root)
        elif kind == "sound":
            out = task_sound(jid, fid, args, rep)
        elif kind == "part_check":
            out = task_part_check(jid, fid, args, rep)
        else:
            raise KeyError(kind)
        J.write_progress(jid, state="done", note=out.get("note", "完成"),
                         artifacts=out.get("artifacts", []),
                         checks=out.get("checks", []),
                         report_summary=(out.get("report") or {}).get("summary"))
        _say(jid, "完成：" + str(out.get("note", "")))
        return 0
    except Exception as e:
        import traceback
        traceback.print_exc()
        J.write_progress(jid, state="error", note=f"{type(e).__name__}: {e}",
                         error=traceback.format_exc()[-1200:])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
