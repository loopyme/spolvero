"""影片工程包（film package）的发现与加载。

约定：`films/<id>/adapter.py` 暴露 `meta() / render_frame() / png_bytes 可选`。
**元数据一律现问 adapter，不在这里缓存一份**（§3 派生约束：时间只有一个来源）。
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))   # 仓库根
FILMS_DIR = os.path.join(_ROOT, "films")

_CACHE: dict[str, object] = {}


def film_ids() -> list[str]:
    if not os.path.isdir(FILMS_DIR):
        return []
    out = []
    for name in sorted(os.listdir(FILMS_DIR)):
        if name.startswith("_") or name.startswith("."):
            continue
        if os.path.exists(os.path.join(FILMS_DIR, name, "adapter.py")):
            out.append(name)
    return out


def film_dir(fid: str) -> str:
    return os.path.join(FILMS_DIR, fid)


def out_dir(fid: str) -> str:
    p = os.path.join(film_dir(fid), "out")
    os.makedirs(p, exist_ok=True)
    return p


def load(fid: str):
    """按 id 载入工程包模块（进程内缓存）。id 来自 film_ids()，不接受任意路径。"""
    if fid in _CACHE:
        return _CACHE[fid]
    if fid not in film_ids():
        raise KeyError(f"影片工程包不存在：{fid}")
    path = os.path.join(film_dir(fid), "adapter.py")
    spec = importlib.util.spec_from_file_location(f"spolvero_film_{fid}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    _CACHE[fid] = mod
    return mod


def meta(fid: str) -> dict:
    m = dict(load(fid).meta())
    m["dir"] = film_dir(fid)
    m["out"] = out_dir(fid)
    return m


def all_meta() -> list[dict]:
    out = []
    for fid in film_ids():
        try:
            out.append(meta(fid))
        except Exception as e:                       # 一部片子坏了不影响列表
            out.append({"id": fid, "title": fid, "error": str(e)[:200]})
    return out


# ── 画幅比例：立项时**必须明确**，此后一切尺寸都从它派生 ──────────────────
# 为什么必须有这一步：画幅决定了全部构图参数（主体位置/高度、题款落点、景别 pivot）。
# 16:9 的默认值搬到 9:16 上，题款会飞出画面、主体会被裁掉半身 —— 事后再改等于重排全部幕。
RATIOS = [
    {"id": "16:9",   "name": "横屏",   "use": "屏幕全幅、常规短片", "w": 1600, "h": 900},
    {"id": "9:16",   "name": "竖屏",   "use": "手机全屏、竖版短视频", "w": 900,  "h": 1600},
    {"id": "2.39:1", "name": "宽银幕", "use": "电影感、横向长卷",   "w": 1600, "h": 670},
    {"id": "4:3",    "name": "经典",   "use": "老胶片、册页横开",   "w": 1200, "h": 900},
    {"id": "3:4",    "name": "册页竖", "use": "册页竖幅、屏风",     "w": 900,  "h": 1200},
    {"id": "1:1",    "name": "斗方",   "use": "方构图、社交方图",   "w": 1000, "h": 1000},
]

SIZE_MIN, SIZE_MAX = 320, 2560


def ratios() -> list[dict]:
    return [dict(r) for r in RATIOS]


def _even(v: int, lo: int = SIZE_MIN, hi: int = SIZE_MAX) -> int:
    """编码器要求偶数边长（libx264 yuv420p），顺手卡在可渲范围内。"""
    v = int(round(v))
    v = max(lo, min(hi, v))
    return v - (v % 2)


def _ratio_label(w: int, h: int) -> str:
    """给一组像素起个可读的比例名：先匹配预设，再试简单整数比，最后用小数式。"""
    r = float(w) / float(h)
    for p in RATIOS:
        if abs(p["w"] / p["h"] - r) < 0.01:
            return p["id"]
    from math import gcd
    g = gcd(int(w), int(h)) or 1
    a, b = int(w) // g, int(h) // g
    return f"{a}:{b}" if max(a, b) <= 20 else f"{r:.2f}:1"


def _fmtnum(v: float) -> str:
    return str(int(v)) if abs(v - round(v)) < 1e-6 else f"{v:g}"


def resolve_size(spec) -> tuple[list[int], str]:
    """比例 → 像素。接受预设 id（"9:16"）、自定义比例（"2.35:1" / "2.35"）、或直接 [w,h]。

    自定义的换算规则：**短边 900、长边不超过 1600**，与预设保持同一量级
    （分辨率一涨，单帧渲染时间按面积线性上涨，画幅不该成为性能上的意外）。
    返回 (size, ratio 名) —— 名字按用户的写法回填，所见即所存。
    """
    if isinstance(spec, (list, tuple)) and len(spec) == 2:
        w, h = _even(spec[0]), _even(spec[1])
        return [w, h], _ratio_label(w, h)
    s = str(spec if spec is not None else "").strip()
    if not s:
        raise ValueError("必须指定画幅比例：16:9 / 9:16 / 2.39:1 / 4:3 / 3:4 / 1:1，或自定义（如 2.35:1）")
    for r in RATIOS:
        if s == r["id"] or s == f'{r["w"]}:{r["h"]}':
            return [r["w"], r["h"]], r["id"]
    txt = s.replace("：", ":").replace(" ", "")
    try:
        a, _, b = txt.partition(":")
        fa, fb = float(a), (float(b) if b else 1.0)
        ratio = fa / fb
    except Exception:
        raise ValueError(f"看不懂这个比例：{s}（写成「宽:高」，如 2.35:1）")
    if not (0.05 <= ratio <= 20.0):
        raise ValueError(f"比例 {s} 超出范围（宽高比需在 0.05–20 之间）")
    if ratio >= 1.0:
        w, h = 900.0 * ratio, 900.0
        if w > 1600:
            w, h = 1600.0, 1600.0 / ratio
    else:
        w, h = 900.0, 900.0 / ratio
        if h > 1600:
            w, h = 1600.0 * ratio, 1600.0
    name = f"{_fmtnum(fa)}:{_fmtnum(fb)}"
    return [_even(w), _even(h)], name


# ── 新建影片：从模板复制，并生成一份**能立刻跑通**的幕表 ─────────────────
CN = "一二三四五六七八九十"


def create_film(fid: str, title: str, source: str = "", *, size=None,
                duration: float = 24.0, n_acts: int = 4, fps: int = 30,
                acts: list | None = None, idea: str = "") -> dict:
    """新建影片工程包。

    为什么必须生成完整幕表而不是空文件：新建出来一部空片子，
    用户点"出关键图"得到空白、判据全挂、也不知道从哪下手 —— 那就等于没建。
    **流程能跑起来，才谈得上往里填。**

    `size`（画幅比例）**必填**：它是构图的根参数，主体位置、主体高度、题款落点、
    景别 pivot 全部由它派生。缺了就报错，不给"先建后补"的口子 ——
    比例一改，等于全部幕重排，那就不叫改参数了。

    acts 可以由 AI 从一句想法生成（`llm.plan_film`）；缺省则按 n_acts 均分。
    生成的 `film.yaml` 是**可编辑的**（控制台里改幕长/题款/主体，见 `update_act`）。
    """
    import re
    import shutil
    fid = re.sub(r"[^a-zA-Z0-9_\-]", "", (fid or "").strip().lower()).strip("-_")
    if not fid:
        raise ValueError("影片 id 只能用小写字母、数字、下划线或连字符")
    if not re.match(r"^[a-z]", fid):
        raise ValueError("影片 id 必须以字母开头")
    dst = film_dir(fid)
    if os.path.exists(dst):
        raise ValueError(f"影片「{fid}」已存在")
    tpl = os.path.join(FILMS_DIR, "_template")
    if not os.path.isdir(tpl):
        raise FileNotFoundError("缺模板 films/_template")
    (W, H), rname = resolve_size(size)
    duration = max(0.5, float(duration))        # 只挡住 0 与负数，不替人决定该多长
    shutil.copytree(tpl, dst)

    if not acts:
        n_acts = max(1, min(20, int(n_acts)))
        step = duration / n_acts
        xs = [0.32, 0.50, 0.68, 0.50]
        acts = []
        for i in range(n_acts):
            note = "起" if i == 0 else "合" if i == n_acts - 1 else f"第{i + 1}段"
            acts.append({"note": note, "caption": [note, f"第{i + 1}幕"],
                         "dur": round(step, 2),
                         "subject": {"x": xs[i % len(xs)] * W,
                                     "base": H * 0.9556,
                                     "h": H * (0.28 + 0.025 * (i % 4))}})
    # 幕表落进 film.yaml —— 时间是唯一来源，duration 由末幕 t1 派生
    write_acts(dst, acts, title=title or fid, source=source or "原创", fps=fps,
               size=(W, H), ratio=rname)
    write_nodes(dst, title or fid, acts, idea=idea)
    _CACHE.pop(fid, None)
    return meta(fid)


def write_nodes(dst: str, title: str, acts: list, idea: str = "") -> str:
    """写原文节点表（`nodes.md`）—— **每一幕的剧本就在这里**。

    节点表是"这一幕要讲什么"的清单，第 3 步就是逐幕看它、改它。
    判据 C13 也直接读这张表：有未勾选项＝叙事断点。
    """
    nd = [f"# 剧本 · {title}", ""]
    if idea:
        nd += [f"> {idea}", ""]
    for i, a in enumerate(acts):
        aid = f"a{i + 1}"
        nd.append(f"## 幕 {aid} —— {a.get('note', aid)}（{a.get('dur', 6.0):.1f}s）")
        items = [str(x).strip() for x in (a.get("script") or []) if str(x).strip()]
        if not items:
            items = ["（这一幕要讲什么）"]
        for s in items:
            nd.append(f"- [ ] {s} （幕 {aid}）")
        nd.append("")
    p = os.path.join(dst, "nodes.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(nd) + "\n")
    return p


def script_of(fid: str) -> dict:
    """{幕 id: [{"done": bool, "text": str}]} —— 从 nodes.md 现读，不另存一份。"""
    p = os.path.join(film_dir(fid), "nodes.md")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        lines = f.read().splitlines()
    out: dict[str, list] = {}
    cur = None
    for ln in lines:
        s = ln.strip()
        if s.startswith("##"):
            cur = None
            m = re.search(r"幕\s*([A-Za-z0-9_]+)", s)
            if m:
                cur = m.group(1)
                out.setdefault(cur, [])
            continue
        if cur and re.match(r"^[-*]\s*\[[ xX]\]", s):
            done = bool(re.match(r"^[-*]\s*\[[xX]\]", s))
            body = re.sub(r"^[-*]\s*\[[ xX]\]\s*", "", s)
            body = re.sub(r"（幕\s*[A-Za-z0-9_]+）\s*$", "", body).strip()
            out[cur].append({"done": done, "text": body})
    return out


def write_script(fid: str, aid: str, items: list | None = None, text: str = "") -> dict:
    """改写**某一幕的剧本**，其它幕的段落原样不动。

    界面给的是**一段自然语言**（一行一句），这里落成 `- [ ] 一句` 的条目 ——
    条目是判据 C13 的读法，人写的是话。`items` 保留给程序化调用。
    """
    import yaml as _yaml
    if text:
        items = [{"done": False, "text": s.strip()}
                 for s in str(text).splitlines() if s.strip()]
    p = os.path.join(film_dir(fid), "nodes.md")
    head, blocks = [], {}
    order = []
    cur = None
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for ln in f.read().splitlines():
                if ln.strip().startswith("##"):
                    m = re.search(r"幕\s*([A-Za-z0-9_]+)", ln)
                    cur = m.group(1) if m else ln.strip()
                    if cur not in order:
                        order.append(cur)
                    blocks[cur] = [ln]
                elif cur is None:
                    head.append(ln)
                else:
                    blocks[cur].append(ln)
    # 取该幕的时长与幕名（标题行里带着）
    acts = (_yaml.safe_load(open(os.path.join(film_dir(fid), "film.yaml"), encoding="utf-8"))
            or {}).get("acts") or [] if os.path.exists(os.path.join(film_dir(fid), "film.yaml")) else []
    hit = next((a for a in acts if a.get("id") == aid), None)
    note = (hit or {}).get("note", aid)
    dur = (float((hit or {}).get("t1", 0)) - float((hit or {}).get("t0", 0))) or 6.0
    lines = [f"## 幕 {aid} —— {note}（{dur:.1f}s）"]
    for it in (items or []):
        t = str((it or {}).get("text", "") if isinstance(it, dict) else it).strip()
        if not t:
            continue
        mark = "x" if (isinstance(it, dict) and it.get("done")) else " "
        lines.append(f"- [{mark}] {t} （幕 {aid}）")
    lines.append("")
    if aid not in order:
        order.append(aid)
    blocks[aid] = lines
    out = list(head)
    for k in order:
        if k in blocks:
            out += blocks[k]
    text = "\n".join(x for x in out).rstrip() + "\n"
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, p)
    _CACHE.pop(fid, None)
    return {"ok": True, "act": aid, "items": len([x for x in items or [] if x])}


def write_acts(dst: str, acts: list, *, title: str, source: str, fps: int = 30,
               size=(1600, 900), ratio: str = "", palette: dict | None = None) -> str:
    """把幕表写成 film.yaml（t0/t1 由 dur 累加得到，保证首尾相接）。

    画幅只在这里写一次：`size: [W, H]`。幕表里其余数字都是**相对该画幅的落点**，
    所以换画幅＝重排幕表，而不是"顺手改个值"。
    """
    W, H = int(size[0]), int(size[1])
    rname = ratio or _ratio_label(W, H)
    pal = palette or {"paper": [246, 242, 232], "sky_top": "#DED3BC",
                      "sky_bottom": "#F3EEE2", "ink": "#2A2A24",
                      "mid": "#8A8578", "accent": "#B23A2C"}
    lines = [f"id: {os.path.basename(dst)}", f"title: {title}", f"source: {source}",
             f"fps: {int(fps)}", f'size: [{W}, {H}]', f'ratio: "{rname}"', "palette:",
             f"  paper: {pal['paper']}", f'  sky_top: "{pal["sky_top"]}"',
             f'  sky_bottom: "{pal["sky_bottom"]}"', f'  ink: "{pal["ink"]}"',
             f'  mid: "{pal["mid"]}"', f'  accent: "{pal["accent"]}"',
             "# 幕表 = 唯一时间真相；duration 由末幕 t1 派生，不单独写。",
             "# 画幅在立项时确定（size/ratio），主体与题款的落点都相对它而言。",
             "# 每一幕都可在控制台里改（时长/幕名/题款/主体）。",
             "acts:"]
    t = 0.0
    for i, a in enumerate(acts):
        d = max(0.05, float(a.get("dur", 6.0)))
        sub = a.get("subject") or {}
        x = float(sub.get("x", W * 0.5))
        h = float(sub.get("h", H * 0.30))
        base = float(sub.get("base", H * 0.9556))
        cap = list(a.get("caption") or [a.get("note", f"第{i + 1}段")])[:2]
        cap_txt = ", ".join('"%s"' % str(c).replace('"', "") for c in cap)
        lines.append(f"  - {{id: a{i + 1}, t0: {t:.2f}, t1: {t + d:.2f}, note: {a.get('note', f'第{i + 1}段')}, "
                     f"caption: [{cap_txt}], subject: {{x: {x:.1f}, base: {base:.1f}, h: {h:.1f}}}}}")
        t += d
    p = os.path.join(dst, "film.yaml")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    _CACHE.pop(os.path.basename(dst), None)
    return p


def update_act(fid: str, aid: str, fields: dict) -> dict:
    """改某一幕（幕名/题款/时长/主体）。**后面可以调** —— 这是必需的入口。

    改时长会顺延后续幕，保证时间轴始终首尾相接（§3 派生约束）。
    """
    import yaml as _yaml
    p = os.path.join(film_dir(fid), "film.yaml")
    if not os.path.exists(p):
        raise ValueError("这部片的幕表不在 film.yaml 里（未启用可直接编辑的幕表）")
    with open(p, encoding="utf-8") as f:
        cfg = _yaml.safe_load(f) or {}
    acts = cfg.get("acts") or []
    W, H = [int(v) for v in (cfg.get("size") or [1600, 900])][:2]
    hit = next((a for a in acts if a.get("id") == aid), None)
    if hit is None:
        raise KeyError(f"没有这一幕：{aid}")
    if fields.get("note"):
        hit["note"] = str(fields["note"])[:12]
    if fields.get("caption"):
        hit["caption"] = [str(c)[:8] for c in list(fields["caption"])[:2]]
    # 时长**不设下限**（只要求正数）：幕可以短到一闪，那是创作上的选择，不是错误。
    # 判据会在"太短看不清"时提醒，但**不在这里拦** —— 工作台的目的是给人改，不是替人决定。
    if fields.get("dur") is not None:
        try:
            d = float(fields["dur"])
        except Exception:
            d = None
        if d and d > 0:
            hit["_dur"] = d
    # 主体高度**原样存**：画幅只在"缺省值"上起作用，用户显式给的值不夹。
    if fields.get("h") is not None:
        try:
            hit.setdefault("subject", {})["h"] = float(fields["h"])
        except Exception:
            pass
    # 主体横向位置（构图直接改，不必去动 yaml）
    if fields.get("x") is not None:
        try:
            hit.setdefault("subject", {})["x"] = float(fields["x"])
        except Exception:
            pass
    # 景别：**存比例不存像素**（kx/ky 是画幅的比例），换画幅不会跑偏
    if fields.get("shot"):
        sh = fields["shot"] or {}
        cur = hit.setdefault("shot", {})
        for k in ("scale", "kx", "ky"):
            if sh.get(k) is not None:
                try:
                    cur[k] = float(sh[k])
                except Exception:
                    pass
    # 题款落点与字号（缺省由渲染器按画幅算，显式给了就按给的）
    if fields.get("cap_at"):
        try:
            hit["cap_at"] = [float(v) for v in list(fields["cap_at"])[:2]]
        except Exception:
            pass
    if fields.get("cap_size") is not None:
        try:
            hit["cap_size"] = float(fields["cap_size"])
        except Exception:
            pass
    # 重新累加时间轴（dur 优先，缺省用原 t1-t0）
    t = 0.0
    for a in acts:
        d = a.pop("_dur", None)
        if d is None:
            d = max(0.05, float(a.get("t1", 0)) - float(a.get("t0", 0)))
        a["t0"], a["t1"] = round(t, 2), round(t + float(d), 2)
        t += float(d)
    cfg["acts"] = acts
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, width=200)
    os.replace(tmp, p)
    _CACHE.pop(fid, None)
    return meta(fid)


def move_act(fid: str, aid: str, delta: int) -> dict:
    """把这一幕往前/后挪一位（成片阶段最容易发现的问题：顺序不对）。

    **整幕一起搬**（幕名、题款、主体、时长都跟着走），然后按新顺序重排时间轴。
    只改 t0/t1 是挪不动的 —— 那样变成"这一幕换了个时间，内容还留在原地"。
    """
    import yaml as _yaml
    p = os.path.join(film_dir(fid), "film.yaml")
    if not os.path.exists(p):
        raise ValueError("这部片的幕表不在 film.yaml 里（无法调整顺序）")
    with open(p, encoding="utf-8") as f:
        cfg = _yaml.safe_load(f) or {}
    acts = cfg.get("acts") or []
    i = next((k for k, a in enumerate(acts) if a.get("id") == aid), None)
    if i is None:
        raise KeyError(f"没有这一幕：{aid}")
    j = i + int(delta)
    if j < 0 or j >= len(acts):
        return meta(fid)                       # 到头了：不动，也不报错（用户看得见没变化）
    acts[i], acts[j] = acts[j], acts[i]
    t = 0.0
    for a in acts:                             # 时间轴按**新顺序**重新累加
        d = max(0.05, float(a.get("t1", 0)) - float(a.get("t0", 0)))
        a["t0"], a["t1"] = round(t, 2), round(t + d, 2)
        t += d
    cfg["acts"] = acts
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, width=200)
    os.replace(tmp, p)
    _CACHE.pop(fid, None)
    return meta(fid)


# ── 风格（视觉基调：纸色 / 墨色 / 点色）──────────────────────────────────
# styles/ 下每个子目录是一个风格预设（style.yaml 给调色板与质感，constraints.yaml 给判据阈值）。
# 选了风格＝整片换底色与墨色，旧画面自然该重渲。
STYLES_DIR = os.path.join(_ROOT, "styles")


def style_ids() -> list[str]:
    if not os.path.isdir(STYLES_DIR):
        return []
    return [d for d in sorted(os.listdir(STYLES_DIR))
            if os.path.isdir(os.path.join(STYLES_DIR, d)) and not d.startswith("_")]


def load_style(style_id: str) -> dict | None:
    p = os.path.join(STYLES_DIR, style_id, "style.yaml")
    if not os.path.exists(p):
        return None
    try:
        import yaml as _yaml
        with open(p, encoding="utf-8") as f:
            return _yaml.safe_load(f) or {}
    except Exception:
        return None


def style_summary(style_id: str) -> dict:
    """给界面看的一行：名字 + 三色卡（纸/墨/点），不用生成预览图。"""
    st = load_style(style_id) or {}
    pal = (st.get("tone") or {}).get("palette") or {}
    accents = pal.get("accents") or []
    return {"id": style_id, "name": st.get("name", style_id),
            "description": st.get("description", ""),
            "prompt": (st.get("prompt") or "").strip(),
            "paper": pal.get("paper", "#F7F5F0"),
            "ink": pal.get("ink", "#1A1A1A"),
            "accent": accents[0] if accents else pal.get("base", "#B23A2C")}


def style_of(fid: str) -> str:
    p = os.path.join(film_dir(fid), "film.yaml")
    if not os.path.exists(p):
        return ""
    try:
        import yaml as _yaml
        cfg = _yaml.safe_load(open(p, encoding="utf-8")) or {}
        return str(cfg.get("style") or "")
    except Exception:
        return ""


def _hex_to_rgb(c: str) -> list[int]:
    c = (c or "#000000").lstrip("#")
    if len(c) != 6:
        return [0, 0, 0]
    return [int(c[i:i + 2], 16) for i in (0, 2, 4)]


def set_style(fid: str, style_id: str) -> dict:
    """选风格：把该风格的调色板写进 film.yaml。

    风格是整片级的视觉基调（纸色 / 墨色 / 点色）——
    风格一换，旧画面就该重渲，否则新风格套在旧画上等于没选。
    `paper` 必须是 [r,g,b]（filmkit 按列表解析），其余按 hex。
    质感参数（effects：排线/纸疤/暗角/边框）一并存进 film.yaml，渲染器接入后即生效。
    """
    st = load_style(style_id)
    if not st:
        raise KeyError(f"没有这个风格：{style_id}")
    pal = (st.get("tone") or {}).get("palette") or {}
    paper = pal.get("paper") or "#F7F5F0"
    base = pal.get("base") or "#6E6A64"
    ink = pal.get("ink") or "#1A1A1A"
    accents = pal.get("accents") or []
    accent = accents[0] if accents else "#B23A2C"
    p = os.path.join(film_dir(fid), "film.yaml")
    if not os.path.exists(p):
        raise ValueError("这部片没有 film.yaml（无法应用风格）")
    import yaml as _yaml
    with open(p, encoding="utf-8") as f:
        cfg = _yaml.safe_load(f) or {}
    cfg["style"] = style_id
    cfg["palette"] = {
        "paper": _hex_to_rgb(paper),
        "sky_top": pal.get("sky_top", base),
        "sky_bottom": pal.get("sky_bottom", paper),
        "ink": ink,
        "mid": pal.get("mid", base),
        "accent": accent,
    }
    eff = st.get("effects")
    if eff:
        cfg["effects"] = eff
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, width=200)
    os.replace(tmp, p)
    _CACHE.pop(fid, None)
    return meta(fid)


def set_sound(fid: str, fields: dict) -> dict:
    """片级声音参数（整轨音量）。写在 film.yaml 的 `sound:` 段，渲染时由 runner 读。"""
    import yaml as _yaml
    p = os.path.join(film_dir(fid), "film.yaml")
    if not os.path.exists(p):
        raise ValueError("这部片没有 film.yaml（无法保存声音参数）")
    with open(p, encoding="utf-8") as f:
        cfg = _yaml.safe_load(f) or {}
    snd = dict(cfg.get("sound") or {})
    if fields.get("gain") is not None:
        try:
            snd["gain"] = max(0.0, min(4.0, float(fields["gain"])))
        except Exception:
            pass
    cfg["sound"] = snd
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, width=200)
    os.replace(tmp, p)
    _CACHE.pop(fid, None)
    return {"ok": True, "sound": snd}
