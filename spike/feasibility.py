"""Spolvero 可行性 spike.

只验证三件「失败即项目死亡」的事：

  A. 派生式 RNG —— 在场景中间插入一个实例，其余实例参数必须一字不变
  B. 四原语能否表达「舟」并产出 50 个差异化实例（含拓扑变体 L2）
  C. 确定性 —— 同一 seed 两次渲染输出必须 byte-identical

刻意不自己造轮子：几何校验与形状距离全部走 shapely，光栅走 skia。
"""
from __future__ import annotations

import hashlib
import math
import os
import sys

from shapely import LineString, Polygon, affinity
from shapely import frechet_distance, is_valid, is_valid_reason

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

SEED = "spolvero-spike-001"


# ---------------------------------------------------------------- 派生式 RNG


def dv(seed: str, *parts) -> float:
    """派生式随机：hash(global_seed, instance_id, param_name) -> [0, 1).

    与顺序无关，不消耗任何流。增删实例不会改变其他实例的任何取值。
    """
    key = "|".join([str(seed)] + [str(p) for p in parts]).encode("utf-8")
    return int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big") / (1 << 64)


def rng_range(seed: str, iid: str, name: str, lo: float, hi: float) -> float:
    return lo + (hi - lo) * dv(seed, iid, name)


# ------------------------------------------------- 构件原型：舟（四原语展开）

# 屏幕坐标系，y 向下。控制点数量恒定（命门 3）：hull 恒为 8 点。
HULL_T = [
    (-0.50, 0.00),
    (-0.34, 0.60),
    (-0.08, 1.00),
    (0.18, 0.94),
    (0.40, 0.56),
    (0.50, 0.00),
    (0.18, -0.14),
    (-0.22, -0.10),
]
# 篷：5 点折线（ink_line）
CANOPY_T = [(-0.50, 0.0), (-0.28, -0.62), (0.0, -0.78), (0.28, -0.62), (0.50, 0.0)]


class BoatProto:
    """构件原型：默认参数 + 原语展开规则。实例只存与默认值的差异。"""

    DEFAULTS = {
        "length": 62.0,
        "depth_ratio": 0.22,
        "canopy_w": 0.42,
        "canopy_h": 0.15,
        "mast_h": 0.85,
        "has_canopy": True,
        "has_mast": False,
        "ink": 0.45,
        "rot": 0.0,
        "x": 0.0,
        "y": 0.0,
    }

    PARAMS = {
        "length": (42.0, 88.0),
        "depth_ratio": (0.16, 0.30),
        "canopy_w": (0.30, 0.55),
        "canopy_h": (0.09, 0.22),
        "mast_h": (0.55, 1.40),
        "ink": (0.12, 0.88),
        "rot": (-3.5, 3.5),
    }

    @staticmethod
    def sample(seed: str, iid: str, x: float, y: float) -> dict:
        """原型默认值 + 派生式采样。拓扑变体（L2）在此决定。"""
        p = dict(BoatProto.DEFAULTS)
        for k, (lo, hi) in BoatProto.PARAMS.items():
            p[k] = rng_range(seed, iid, k, lo, hi)
        p["has_canopy"] = dv(seed, iid, "topo_canopy") > 0.35
        p["has_mast"] = dv(seed, iid, "topo_mast") > 0.62
        p["x"], p["y"] = x, y
        p["iid"] = iid
        return p

    @staticmethod
    def expand(seed: str, p: dict) -> dict:
        """原语展开：只产出 ink_shape / ink_line / ink_dot 三类 + 分组变换。"""
        iid = p["iid"]
        L = p["length"]
        D = L * p["depth_ratio"]

        hull = []
        for k, (ux, uy) in enumerate(HULL_T):
            jx = (dv(seed, iid, f"h_jx{k}") - 0.5) * 0.07 * L
            jy = (dv(seed, iid, f"h_jy{k}") - 0.5) * 0.20 * D
            hull.append((ux * L + jx, uy * D + jy))

        canopy = None
        if p["has_canopy"]:
            cw = p["canopy_w"] * L
            ch = p["canopy_h"] * L
            ox = (dv(seed, iid, "c_ox") - 0.5) * 0.18 * L
            canopy = [(ox + ux * cw, -0.42 * D + uy * ch) for ux, uy in CANOPY_T]

        mast = None
        if p["has_mast"]:
            mx = (dv(seed, iid, "m_ox") - 0.5) * 0.30 * L
            mast = [(mx, -0.30 * D), (mx, -0.30 * D - p["mast_h"] * L)]

        lamp = None
        if dv(seed, iid, "topo_lamp") > 0.45:
            lamp = ((dv(seed, iid, "l_ox") - 0.5) * 0.40 * L, -0.18 * D)

        return {"hull": hull, "canopy": canopy, "mast": mast, "lamp": lamp, "p": p}


# --------------------------------------------------------------- 场景与校验


def build(seed: str, cols: int = 10, rows: int = 5, ids: list[str] | None = None) -> list[dict]:
    """铺放实例。布局坐标 = (seed, iid) 的纯函数，与列表顺序无关 ——
    插入新实例不会改变既有实例的任何坐标，这正是真实引擎的行为
    （实例自带 transform，场景图增删不打扰其他节点）。"""
    if ids is None:
        ids = [f"boat_{n:03d}" for n in range(cols * rows)]
    out = []
    for iid in ids:
        c = int(dv(seed, iid, "gx") * cols)
        r = int(dv(seed, iid, "gy") * rows)
        x = 90 + c * 150 + (dv(seed, iid, "px") - 0.5) * 46
        y = 120 + r * 170 + (dv(seed, iid, "py") - 0.5) * 40
        out.append(BoatProto.expand(seed, BoatProto.sample(seed, iid, x, y)))
    return out


def normalized_ring(pts: list[tuple[float, float]]) -> LineString:
    """质心对齐 + 尺度归一化，用于跨尺寸比较形状。"""
    poly = Polygon(pts)
    cx, cy = poly.centroid.x, poly.centroid.y
    rel = [(x - cx, y - cy) for x, y in pts]
    scale = max(math.hypot(x, y) for x, y in rel) or 1.0
    ring = [(x / scale, y / scale) for x, y in rel]
    return LineString(ring + [ring[0]])


# ------------------------------------------------------------------- SVG 输出

W, H = 1600, 900


def to_svg(scene: list[dict]) -> str:
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">']
    s.append(f'<rect width="{W}" height="{H}" fill="#F7F5F0"/>')
    for it in scene:
        p = it["p"]
        g = int(255 * (1.0 - p["ink"]) ** 1.1)
        stroke = f"rgb({g},{g},{g})"
        sw = 1.6 + p["ink"] * 1.4
        x, y, rot = p["x"], p["y"], p["rot"]
        s.append(f'<g transform="translate({x:.2f},{y:.2f}) rotate({rot:.2f})">')
        pts = " ".join(f"{a:.2f},{b:.2f}" for a, b in it["hull"])
        s.append(f'<polygon points="{pts}" fill="none" stroke="{stroke}" stroke-width="{sw:.2f}" stroke-linejoin="round"/>')
        if it["canopy"]:
            pts = " ".join(f"{a:.2f},{b:.2f}" for a, b in it["canopy"])
            s.append(f'<polyline points="{pts}" fill="none" stroke="{stroke}" stroke-width="{sw:.2f}" stroke-linejoin="round" stroke-linecap="round"/>')
        if it["mast"]:
            (x1, y1), (x2, y2) = it["mast"]
            s.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{stroke}" stroke-width="{sw:.2f}" stroke-linecap="round"/>')
        if it["lamp"]:
            lx, ly = it["lamp"]
            s.append(f'<circle cx="{lx:.2f}" cy="{ly:.2f}" r="{1.9 + p["ink"]:.2f}" fill="{stroke}"/>')
        s.append("</g>")
    s.append("</svg>")
    return "".join(s)


def try_skia(scene: list[dict], path: str) -> str | None:
    try:
        import skia
    except Exception as e:
        return f"skia 不可用：{e}"

    surface = skia.Surface(W, H)
    canvas = surface.getCanvas()
    canvas.clear(skia.ColorSetARGB(0xFF, 0xF7, 0xF5, 0xF0))

    paint = skia.Paint()
    paint.setAntiAlias(True)
    paint.setStyle(skia.Paint.kStroke_Style)
    paint.setStrokeJoin(skia.Paint.kRound_Join)
    paint.setStrokeCap(skia.Paint.kRound_Cap)
    fill = skia.Paint()
    fill.setAntiAlias(True)
    fill.setStyle(skia.Paint.kFill_Style)

    for it in scene:
        p = it["p"]
        g = int(255 * (1.0 - p["ink"]) ** 1.1)
        col = skia.ColorSetARGB(0xFF, g, g, g)
        paint.setColor(col)
        paint.setStrokeWidth(1.6 + p["ink"] * 1.4)
        fill.setColor(col)

        def path_of(seq, close):
            path = skia.Path()
            path.moveTo(seq[0][0], seq[0][1])
            for a, b in seq[1:]:
                path.lineTo(a, b)
            if close:
                path.close()
            return path

        for seq, close in ((it["hull"], True), (it["canopy"], False), (it["mast"], False)):
            if not seq:
                continue
            canvas.save()
            canvas.translate(p["x"], p["y"])
            canvas.rotate(p["rot"])
            canvas.drawPath(path_of(seq, close), paint)
            canvas.restore()

        if it["lamp"]:
            canvas.save()
            canvas.translate(p["x"], p["y"])
            canvas.rotate(p["rot"])
            canvas.drawCircle(it["lamp"][0], it["lamp"][1], 1.9 + p["ink"], fill)
            canvas.restore()

    img = surface.makeImageSnapshot()
    data = img.encodeToData()
    with open(path, "wb") as f:
        f.write(bytes(data))
    return None


# ------------------------------------------------------------------------ 主流程


def main() -> int:
    print("=" * 66)
    print("Spolvero 可行性 spike")
    print("=" * 66)

    # --- A. 派生式 RNG 稳定性 -------------------------------------------
    print("\n[A] 派生式 RNG：在中间插入一个实例，其余实例参数必须一字不变")
    ids_a = [f"boat_{i:03d}" for i in range(12)]
    ids_b = ids_a[:5] + ["boat_inserted"] + ids_a[5:]  # 在第 6 位插入
    before = {e["p"]["iid"]: e["p"] for e in build(SEED, cols=4, ids=ids_a)}
    after = {e["p"]["iid"]: e["p"] for e in build(SEED, cols=4, ids=ids_b)}
    shared = set(before) & set(after)
    drift = [k for k in shared if before[k] != after[k]]
    print(f"    共有实例 {len(shared)} 个（另有 1 个新插入），参数漂移：{len(drift)} 个")
    ok_a = not drift
    print(f"    → {'通过' if ok_a else '失败'}")

    # --- B. 四原语表达力 + 差异化 ---------------------------------------
    print("\n[B] 四原语表达「舟」：50 个实例")
    scene = build(SEED, cols=10, rows=5)

    bad = []
    for e in scene:
        poly = Polygon(e["hull"])
        if not is_valid(poly):
            bad.append((e["p"]["iid"], is_valid_reason(poly)))
    print(f"    几何有效性（无自相交）：{len(scene) - len(bad)}/{len(scene)} 通过")
    if bad:
        print(f"    首个失败：{bad[0]}")
    ok_geo = not bad

    n_canopy = sum(1 for e in scene if e["canopy"])
    n_mast = sum(1 for e in scene if e["mast"])
    n_lamp = sum(1 for e in scene if e["lamp"])
    print(f"    拓扑变体分布：篷 {n_canopy} / 桅 {n_mast} / 灯 {n_lamp} （共 {len(scene)}）")

    rings = [normalized_ring(e["hull"]) for e in scene]
    dists = []
    for i in range(len(rings)):
        for j in range(i + 1, len(rings)):
            dists.append(frechet_distance(rings[i], rings[j]))
    dists.sort()
    n = len(dists)
    print(f"    形状距离（归一化 Fréchet，{n} 对）：")
    print(f"      min={dists[0]:.4f}  p05={dists[int(n*0.05)]:.4f}  "
          f"median={dists[n//2]:.4f}  max={dists[-1]:.4f}")
    near = sum(1 for d in dists if d < 0.05)
    print(f"      距离 < 0.05 的高度雷同对：{near} 对")
    ok_diff = dists[int(n * 0.05)] > 0.02
    print(f"    → {'通过' if ok_diff else '疑似同质化'}")

    # --- C. 确定性 -------------------------------------------------------
    print("\n[C] 确定性：同 seed 两次渲染")
    svg1 = to_svg(build(SEED, cols=10, rows=5))
    svg2 = to_svg(build(SEED, cols=10, rows=5))
    h1 = hashlib.sha256(svg1.encode()).hexdigest()[:16]
    h2 = hashlib.sha256(svg2.encode()).hexdigest()[:16]
    ok_svg = h1 == h2
    print(f"    SVG: {h1} vs {h2} → {'一致' if ok_svg else '不一致'}")

    png = os.path.join(OUT, "boats.png")
    err = try_skia(scene, png)
    ok_png = None
    if err:
        print(f"    PNG: {err}")
    else:
        png1 = open(png, "rb").read()
        try_skia(build(SEED, cols=10, rows=5), png)
        png2 = open(png, "rb").read()
        ok_png = png1 == png2
        print(f"    PNG: {len(png1)} bytes, 两次一致={ok_png}  → {png}")

    svg_path = os.path.join(OUT, "boats.svg")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(svg1)
    print(f"    SVG 已写出：{svg_path}")

    # --- 结论 ------------------------------------------------------------
    print("\n" + "=" * 66)
    print("判定")
    print("=" * 66)
    print(f"  A 派生式 RNG 稳定 ......... {'PASS' if ok_a else 'FAIL'}")
    print(f"  B1 四原语几何有效 ......... {'PASS' if ok_geo else 'FAIL'}")
    print(f"  B2 实例差异化 ............. {'PASS' if ok_diff else 'WARN'}")
    print(f"  C1 SVG 确定性 ............. {'PASS' if ok_svg else 'FAIL'}")
    print(f"  C2 PNG 确定性 ............. {'PASS' if ok_png else ('SKIP' if ok_png is None else 'FAIL')}")
    print(f"  B3 造型艺术质量 ........... 需人眼判读 → out/boats.svg")
    return 0 if (ok_a and ok_geo and ok_svg) else 1


if __name__ == "__main__":
    sys.exit(main())
