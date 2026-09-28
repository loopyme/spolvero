"""M1 内核测试：四原语 + 派生 RNG + 仿射 + 双后端确定性。

复刻 spike 的保证，但走真实包（core/rng, core/transform, core/primitives, render/*），
断言 M1 落地后三件「失败即项目死亡」的事仍然成立。
"""

from __future__ import annotations

import hashlib
from typing import List

from spolvero.core.primitives import Group, InkDot, InkLine, InkShape
from spolvero.core.rng import derive, range_of
from spolvero.core.transform import Transform
from spolvero.core.types import Point
from spolvero.render.backend import render

SEED = "spolvero-test-001"

# 船体恒定 8 控制点（命门 3）
HULL_T = [
    (-0.50, 0.00), (-0.34, 0.60), (-0.08, 1.00), (0.18, 0.94),
    (0.40, 0.56), (0.50, 0.00), (0.18, -0.14), (-0.22, -0.10),
]
CANOPY_T = [(-0.50, 0.0), (-0.28, -0.62), (0.0, -0.78), (0.28, -0.62), (0.50, 0.0)]


class BoatProto:
    DEFAULTS = dict(length=62.0, depth_ratio=0.22, canopy_w=0.42, canopy_h=0.15,
                    mast_h=0.85, has_canopy=True, has_mast=False, ink=0.45, rot=0.0)
    PARAMS = dict(length=(42.0, 88.0), depth_ratio=(0.16, 0.30), canopy_w=(0.30, 0.55),
                  canopy_h=(0.09, 0.22), mast_h=(0.55, 1.40), ink=(0.12, 0.88), rot=(-3.5, 3.5))

    @staticmethod
    def sample(iid: str) -> dict:
        p = dict(BoatProto.DEFAULTS)
        for k, (lo, hi) in BoatProto.PARAMS.items():
            p[k] = range_of(SEED, iid, k, lo, hi)
        p["has_canopy"] = derive(SEED, iid, "topo_canopy") > 0.35
        p["has_mast"] = derive(SEED, iid, "topo_mast") > 0.62
        p["has_lamp"] = derive(SEED, iid, "topo_lamp") > 0.45
        return p

    @staticmethod
    def build(iid: str) -> Group:
        p = BoatProto.sample(iid)
        L = p["length"]
        D = L * p["depth_ratio"]
        hull = [Point(ux * L + (derive(SEED, iid, f"hjx{k}") - 0.5) * 0.07 * L,
                      uy * D + (derive(SEED, iid, f"hjy{k}") - 0.5) * 0.20 * D)
                for k, (ux, uy) in enumerate(HULL_T)]
        children: List = [InkShape(ring=tuple(hull), ink=p["ink"])]
        if p["has_canopy"]:
            cw = p["canopy_w"] * L
            ch = p["canopy_h"] * L
            ox = (derive(SEED, iid, "cox") - 0.5) * 0.18 * L
            children.append(InkLine(
                points=tuple(Point(ox + ux * cw, -0.42 * D + uy * ch) for ux, uy in CANOPY_T),
                ink=p["ink"]))
        if p["has_mast"]:
            mx = (derive(SEED, iid, "mox") - 0.5) * 0.30 * L
            children.append(InkLine(
                points=(Point(mx, -0.30 * D), Point(mx, -0.30 * D - p["mast_h"] * L)),
                ink=p["ink"]))
        if p["has_lamp"]:
            lx = (derive(SEED, iid, "lox") - 0.5) * 0.40 * L
            children.append(InkDot(pos=Point(lx, -0.18 * D), r=1.9 + p["ink"], ink=p["ink"]))
        # 布局坐标 = (seed, iid) 纯函数，与列表顺序无关（命门补充）
        c = int(derive(SEED, iid, "gx") * 10)
        r = int(derive(SEED, iid, "gy") * 5)
        x = 90 + c * 150 + (derive(SEED, iid, "px") - 0.5) * 46
        y = 120 + r * 170 + (derive(SEED, iid, "py") - 0.5) * 40
        return Group(tuple(children), Transform.translate(x, y).compose(Transform.rotate(p["rot"])))


def scene(ids) -> List[Group]:
    return [BoatProto.build(iid) for iid in ids]


# golden 帧哈希（L1 同机同版本 byte-identical，CI 卡死）。首次运行后回填。
GOLDEN_SVG_HASH = "1d5c0d65608fb8f0bceb0b781af6196eac22c081edb06b8019eae03b5dd809cc"
GOLDEN_PNG_HASH = "2d39cafef1aa9d0a377751ab95a71982c871dc4f7affcf689bac53f28a235bbf"


def test_derive_stable_under_insertion():
    ids_a = [f"boat_{i:03d}" for i in range(12)]
    ids_b = ids_a[:5] + ["boat_inserted"] + ids_a[5:]
    pa = {iid: BoatProto.sample(iid) for iid in ids_a}
    pb = {iid: BoatProto.sample(iid) for iid in ids_b}
    shared = set(pa) & set(pb)
    drift = [k for k in shared if pa[k] != pb[k]]
    assert not drift, f"插入实例导致 {len(drift)} 个实例参数漂移：{drift[:3]}"


def test_flatten_group_transform():
    leaf = InkLine(points=(Point(0, 0), Point(10, 0)), width=2.0, ink=0.3)
    t1 = Transform.translate(100, 50).compose(Transform.rotate(90))
    g = Group((leaf,), t1)
    out = Group((g,), Transform.identity())
    from spolvero.core.scene import flatten_all
    leaves = flatten_all([out])
    got = [(p.x, p.y) for ln in leaves for p in ln.points]
    # rotate90 后再 translate(100,50)：期望 (0,0)->(100,50)，(10,0)->(100,~60)
    for ex in (t1(0.0, 0.0), t1(10.0, 0.0)):
        assert any(abs(ex[0] - gx) < 1e-6 and abs(ex[1] - gy) < 1e-6 for gx, gy in got)


def test_ink_shape_constant_points():
    for iid in [f"boat_{i:03d}" for i in range(20)]:
        g = BoatProto.build(iid)
        hull = next(c for c in g.children if isinstance(c, InkShape))
        # 控制点数量恒定 = 8，不随参数变化（命门 3）
        assert len(hull.ring) == 8


def test_svg_deterministic():
    sc = scene([f"boat_{i:03d}" for i in range(50)])
    s1 = render(sc, backend="svg")
    s2 = render(sc, backend="svg")
    assert s1 == s2
    h = hashlib.sha256(s1.encode()).hexdigest()
    assert h == GOLDEN_SVG_HASH, f"SVG 哈希漂移：{h}"


def test_png_deterministic():
    sc = scene([f"boat_{i:03d}" for i in range(50)])
    b1 = render(sc, backend="skia")
    b2 = render(sc, backend="skia")
    assert b1 == b2
    h = hashlib.sha256(b1).hexdigest()
    assert h == GOLDEN_PNG_HASH, f"PNG 哈希漂移：{h}"
