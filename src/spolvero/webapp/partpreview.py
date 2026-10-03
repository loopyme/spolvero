"""构件预览（SPEC §17.1 第 4 步）。

为什么要有：构件是"看不见的东西" —— 只列名字，用户没法判断该采纳哪个、哪个能改。
所以每个构件都要能看见它长什么样。

两条路，都不造假：
- **引擎构件**（boat/moon/mountain/water…）：它们是四原语展开的纯几何，
  用引擎自己的 SVG 后端画出来（零新依赖，与最终画面同源）。
- **本片在用的底座**：直接渲染该片的一帧 —— 那才是它在画面里的真实样子。
"""

from __future__ import annotations

import os

from . import films as fl

_CACHE: dict[str, str] = {}
_BASE_CACHE: dict[str, bytes] = {}


def engine_svg(name: str, w: int = 260, h: int = 170, bg=(248, 245, 238)) -> str:
    """把引擎构件画成 SVG（同一套四原语 → 与成片同源，不是示意图）。"""
    key = f"{name}:{w}x{h}"
    if key in _CACHE:
        return _CACHE[key]
    import spolvero.components          # noqa: F401  触发注册
    from spolvero.components.lonely_boat import lonely_boat_library
    from spolvero.core.scene import flatten
    from spolvero.render.svg import render_svg

    lib = lonely_boat_library()
    proto = lib.get(name)
    seed, iid = "preview", name
    inner = proto.instantiate(seed, iid)          # 已验证 + 外包 group
    leaves = flatten(inner)
    if not leaves:
        raise KeyError(f"构件 {name} 没有几何")
    # 归一化到预览画布：算出包围盒，等比缩放居中
    xs, ys = [], []
    for lf in leaves:
        pts = getattr(lf, "points", None) or getattr(lf, "ring", None)
        if pts:
            xs += [p.x for p in pts]
            ys += [p.y for p in pts]
        elif hasattr(lf, "pos"):
            xs.append(lf.pos.x)
            ys.append(lf.pos.y)
    if not xs:
        raise KeyError(f"构件 {name} 没有可用几何")
    bw, bh = max(1e-6, max(xs) - min(xs)), max(1e-6, max(ys) - min(ys))
    k = min((w - 24) / bw, (h - 24) / bh)
    ox = (w - bw * k) / 2 - min(xs) * k
    oy = (h - bh * k) / 2 - min(ys) * k

    def tf(p):
        from spolvero.core.types import Point
        return Point(p.x * k + ox, p.y * k + oy)

    scaled = []
    for lf in leaves:
        cls = type(lf)
        kw = dict(ink=lf.ink, color=getattr(lf, "color", None))
        if hasattr(lf, "points"):
            scaled.append(cls(points=tuple(tf(p) for p in lf.points),
                              width=max(0.8, lf.width * k), closed=lf.closed, **kw))
        elif hasattr(lf, "ring"):
            scaled.append(cls(ring=tuple(tf(p) for p in lf.ring),
                              fill=lf.fill, width=max(0.8, lf.width * k), **kw))
        else:
            scaled.append(cls(pos=tf(lf.pos), r=max(1.0, lf.r * k), **kw))
    svg = render_svg(scaled, w, h, bg)
    _CACHE[key] = svg
    return svg


def base_preview_png(fid: str) -> bytes:
    """本片在用的底座：直接渲染一帧，画面上是什么就是什么。

    带缓存（按 fid + film.yaml 的 mtime）：渲染一帧要几百毫秒，
    页面每次刷新都重算没必要，而且这只是一张给人看的参考图。
    """
    from .runner import _png_bytes
    yml = os.path.join(fl.film_dir(fid), "film.yaml")
    key = f"{fid}:{int(os.path.getmtime(yml)) if os.path.exists(yml) else 0}"
    if key in _BASE_CACHE:
        return _BASE_CACHE[key]
    mod = fl.load(fid)
    m = fl.meta(fid)
    t = float(m["acts"][0]["t0"]) + float(m["acts"][0]["d"]) * 0.5 if m.get("acts") else 0.0
    arr = mod.render_frame(t)
    h, w = arr.shape[0], arr.shape[1]
    step = 2 if max(h, w) > 700 else 1
    png = _png_bytes(arr[::step, ::step])
    _BASE_CACHE.clear()                    # 只留当前这一部片的，别把内存吃满
    _BASE_CACHE[key] = png
    return png


def _h2rgb(c: str) -> list:
    c = (c or "#000000").lstrip("#")
    if len(c) != 6:
        return [0, 0, 0]
    return [int(c[i:i + 2], 16) for i in (0, 2, 4)]


def _fill_circle(arr: "np.ndarray", cx: float, cy: float, r: float, rgb) -> None:
    h, w = arr.shape[:2]
    for y in range(max(0, int(cy - r)), min(h, int(cy + r) + 1)):
        for x in range(max(0, int(cx - r)), min(w, int(cx + r) + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                arr[y, x, :3] = rgb


def _line(arr: "np.ndarray", x0: float, y0: float, x1: float, y1: float, rgb, wd: float) -> None:
    steps = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
    for i in range(steps + 1):
        t = i / steps
        _fill_circle(arr, x0 + t * (x1 - x0), y0 + t * (y1 - y0), wd / 2, rgb)


def _fill_poly(arr: "np.ndarray", pts: list, rgb, alpha: float = 1.0) -> None:
    h, w = arr.shape[:2]
    ys = [p[1] for p in pts]
    y0, y1 = max(0, int(min(ys))), min(h - 1, int(max(ys)))
    for y in range(y0, y1 + 1):
        cross = []
        for i in range(len(pts)):
            x1, yy1 = pts[i]
            x2, yy2 = pts[(i + 1) % len(pts)]
            if (yy1 <= y < yy2) or (yy2 <= y < yy1):
                t = (y - yy1) / (yy2 - yy1)
                cross.append(x1 + t * (x2 - x1))
        cross.sort()
        for k in range(0, len(cross) - 1, 2):
            xa, xb = int(round(cross[k])), int(round(cross[k + 1]))
            xa, xb = max(0, min(w - 1, xa)), max(0, min(w - 1, xb))
            for x in range(xa, xb + 1):
                arr[y, x, :3] = (arr[y, x, :3] * (1 - alpha) + rgb * alpha).astype(np.uint8)


def _used_thumb(fid: str, name: str, w: int = 240, h: int = 160) -> "np.ndarray":
    """代表性缩略图：渲染器没提供 render_part 时，按元素名画一个示意（与当前风格同色）。

    不造假 —— 它标的是「这个底座元素大致长这样」，真实样子看「整体画面」那张。
    """
    import numpy as np
    sid = fl.style_of(fid) or "eastern_minimal"
    st = fl.load_style(sid) or {}
    pal = (st.get("tone") or {}).get("palette") or {}
    paper = np.array(_h2rgb(pal.get("paper", "#F7F5F0")), dtype=np.float32)
    ink = np.array(_h2rgb(pal.get("ink", "#1A1A1A")), dtype=np.float32)
    acc = np.array(_h2rgb((pal.get("accents") or ["#B23A2C"])[0]), dtype=np.float32)
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[..., :3] = paper.astype(np.uint8)
    arr[..., 3] = 255
    n = (name or "").strip()
    if n in ("纸底", "纸"):
        rng = np.random.default_rng(abs(hash(n)) % (2 ** 31))
        noise = rng.integers(-7, 7, size=(h, w, 1)).astype(np.int16)
        arr[..., :3] = np.clip(arr[..., :3].astype(np.int16) + noise, 0, 255).astype(np.uint8)
    elif n in ("天空分带", "天空", "天"):
        for y in range(h):
            f = y / h
            arr[y, :, :3] = np.clip(arr[y, :, :3].astype(np.float32) * (1 - 0.22 * f)
                                     + ink * 0.22 * f, 0, 255).astype(np.uint8)
    elif n in ("远山", "山", "群山"):
        _fill_poly(arr, [(0, h), (w * 0.18, h * 0.42), (w * 0.36, h * 0.58),
                         (w * 0.54, h * 0.34), (w * 0.72, h * 0.56), (w, h * 0.46), (w, h)], ink, 0.55)
    elif n in ("地平线", "平线"):
        _line(arr, 0, h * 0.5, w, h * 0.5, ink, 3)
        _line(arr, 0, h * 0.52, w, h * 0.52, ink, 1)
    elif n in ("主体剪影", "主体", "人物", "人"):
        cx = w * 0.5
        _fill_circle(arr, cx, h * 0.28, h * 0.1, ink)
        _fill_poly(arr, [(cx - h * 0.13, h * 0.36), (cx + h * 0.13, h * 0.36),
                         (cx + h * 0.18, h * 0.72), (cx - h * 0.18, h * 0.72)], ink)
        _line(arr, cx - h * 0.13, h * 0.72, cx - h * 0.22, h * 0.96, ink, 5)
        _line(arr, cx + h * 0.13, h * 0.72, cx + h * 0.22, h * 0.96, ink, 5)
    elif n in ("题款", "款", "字"):
        _line(arr, w * 0.22, 0, w * 0.22, h, ink, 8)
        _line(arr, w * 0.6, 0, w * 0.6, h, ink, 8)
    elif n in ("朱砂点", "朱砂", "点"):
        _fill_circle(arr, w * 0.5, h * 0.5, min(w, h) * 0.18, acc)
    else:
        rng = np.random.default_rng(abs(hash(n)) % (2 ** 31))
        for _ in range(3):
            _fill_circle(arr, int(rng.integers(0, w)), int(rng.integers(0, h)),
                         int(rng.integers(6, 18)), ink)
        _line(arr, int(rng.integers(0, w)), int(rng.integers(0, h)),
              int(rng.integers(0, w)), int(rng.integers(0, h)), ink, 2)
    return arr


def used_png(fid: str, name: str) -> bytes:
    """单个底座元素的样子（纸底上的那一个元素）。

    渲染器提供了 render_part 就用它（真实）；否则回退到代表性缩略图，保证工作台永远有图。
    """
    from .runner import _png_bytes
    mod = fl.load(fid)
    fn = getattr(mod, "render_part", None)
    if callable(fn):
        ids = [a["id"] for a in (fl.meta(fid).get("acts") or [])]
        return _png_bytes(fn(name, ids[0] if ids else ""))
    return _png_bytes(_used_thumb(fid, name))
