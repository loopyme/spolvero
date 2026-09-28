"""Lottie L0 导出（M6d）：DSL 工程 → Lottie / dotLottie JSON。

定位（SPEC §12）：L0 是**烘焙导出**，输出的是结果而不是参数化模型——丢参数化是不做
L2 内核对齐的代价，也是刻意为之：Lottie 装不下原型/实例/seed/随机，把它当内部表示是致命的。

实现要点：
- 每个 Spolvero 实例 → 一个 Lottie Shape Layer；几何写在**局部坐标系**（锚点即 layer 原点），
  摆放/动画落在 layer 的 ks 上，与引擎「构件在局部系建模 + 外包一层 group」的契约同构。
- 动画**逐帧烘焙为 hold 关键帧**：第 i 帧的值保持到第 i+1 帧。因为我们的输出本就是逐帧采样，
  hold 烘焙可保证「Lottie 播放 == 引擎渲染」，不引入插值近似差异。
- 仿射矩阵分解为 (translate, rotate, scale)：本项目变换只由 translate/rotate/scale 复合而成，
  无剪切，故分解无损。分解用到 atan2/degrees，属**非 L1** 路径（导出物不参与 golden 门禁）。
"""

from __future__ import annotations

import json
import math
import os
from typing import Dict, List, Optional, Tuple

from spolvero.core.primitives import Group, InkDot, InkLine, InkShape
from spolvero.core.transform import Transform
from spolvero.render.common import color_of

LOTTIE_VERSION = "5.7.4"


def _rgb(c: Tuple[int, int, int]) -> List[float]:
    return [round(c[0] / 255.0, 6), round(c[1] / 255.0, 6), round(c[2] / 255.0, 6), 1.0]


def _decompose(t: Transform) -> Tuple[float, float, float, float, float]:
    """2x3 仿射 → (tx, ty, rot_deg, sx, sy)。无剪切假设成立（仅平移/旋转/缩放复合）。"""
    sx = math.hypot(t.a, t.c)
    det = t.a * t.d - t.b * t.c
    sy = (det / sx) if sx > 1e-12 else math.hypot(t.b, t.d)
    rot = math.degrees(math.atan2(t.c, t.a))
    return (t.e, t.f, rot, sx, sy)


def _path_item(points, closed: bool, nm: str = "") -> Dict:
    v = [[round(p.x, 3), round(p.y, 3)] for p in points]
    z = [[0, 0] for _ in points]
    return {
        "ty": "sh",
        "nm": nm,
        "ks": {"a": 0, "k": {"i": z, "o": z, "v": v, "c": closed}},
    }


def _stroke_item(rgb, width: float) -> Dict:
    return {
        "ty": "st",
        "nm": "stroke",
        "c": {"a": 0, "k": _rgb(rgb)},
        "o": {"a": 0, "k": 100},
        "w": {"a": 0, "k": round(float(width), 3)},
        "lc": 2,
        "lj": 2,
    }


def _fill_item(rgb) -> Dict:
    return {"ty": "fl", "nm": "fill", "c": {"a": 0, "k": _rgb(rgb)}, "o": {"a": 0, "k": 100}}


def _tr_item() -> Dict:
    return {
        "ty": "tr",
        "p": {"a": 0, "k": [0, 0]},
        "a": {"a": 0, "k": [0, 0]},
        "s": {"a": 0, "k": [100, 100]},
        "r": {"a": 0, "k": 0},
        "o": {"a": 0, "k": 100},
    }


def _shape_groups(children, index: int) -> List[Dict]:
    """把一个实例的叶节点翻译为 Lottie shape item groups。"""
    out: List[Dict] = []
    for j, leaf in enumerate(children):
        rgb = color_of(leaf.ink, getattr(leaf, "color", None))
        items: List[Dict] = []
        if isinstance(leaf, InkDot):
            items.append({
                "ty": "el",
                "nm": f"{index}_{j}",
                "p": {"a": 0, "k": [round(leaf.pos.x, 3), round(leaf.pos.y, 3)]},
                "s": {"a": 0, "k": [round(leaf.r * 2, 3), round(leaf.r * 2, 3)]},
            })
            items.append(_fill_item(rgb))
        elif isinstance(leaf, InkLine):
            items.append(_path_item(leaf.points, bool(leaf.closed), f"{index}_{j}"))
            items.append(_stroke_item(rgb, leaf.width))
        elif isinstance(leaf, InkShape):
            items.append(_path_item(leaf.ring, True, f"{index}_{j}"))
            items.append(_fill_item(rgb) if leaf.fill else _stroke_item(rgb, leaf.width))
        else:  # 嵌套 group（容错：递归展开到同一 layer）
            out.extend(_shape_groups(leaf.children, index))
            continue
        items.append(_tr_item())
        out.append({"ty": "gr", "nm": f"g{index}_{j}", "it": items})
    return out


def _animated_prop(values: List[float]) -> Dict:
    """hold 关键帧（第 i 帧值保持到第 i+1 帧）；单值退化为静态属性。"""
    if len(values) == 1:
        return {"a": 0, "k": round(values[0], 4)}
    keys = [{"t": i, "s": [round(v, 4)], "h": 1} for i, v in enumerate(values)]
    return {"a": 1, "k": keys}


def _animated_vec(values: List[Tuple[float, float]]) -> Dict:
    if len(values) == 1:
        return {"a": 0, "k": [round(values[0][0], 3), round(values[0][1], 3), 0]}
    keys = [{"t": i, "s": [round(x, 3), round(y, 3), 0], "h": 1} for i, (x, y) in enumerate(values)]
    return {"a": 1, "k": keys}


def _layer_transform(project, g: Group, anim, frames: int) -> Dict:
    if anim is None or not anim.tracks or frames <= 1:
        tx, ty, rot, sx, sy = _decompose(g.transform)
        return {
            "o": {"a": 0, "k": 100},
            "r": {"a": 0, "k": round(rot, 4)},
            "p": {"a": 0, "k": [round(tx, 3), round(ty, 3), 0]},
            "a": {"a": 0, "k": [0, 0, 0]},
            "s": {"a": 0, "k": [round(sx * 100, 4), round(sy * 100, 4), 100]},
        }
    fps = int(project.fps or 24)
    ax, ay = g.transform(0.0, 0.0)
    ps, rs, ss = [], [], []
    for i in range(frames):
        m = anim.delta_transform(i / fps, ax, ay).compose(g.transform)
        tx, ty, rot, sx, sy = _decompose(m)
        ps.append((tx, ty))
        rs.append(rot)
        ss.append((sx * 100.0, sy * 100.0))
    return {
        "o": {"a": 0, "k": 100},
        "r": _animated_prop(rs),
        "p": _animated_vec(ps),
        "a": {"a": 0, "k": [0, 0, 0]},
        "s": {
            "a": 1,
            "k": [{"t": i, "s": [round(x, 4), round(y, 4), 100], "h": 1} for i, (x, y) in enumerate(ss)],
        },
    }


def export_lottie(project, out_path: str, style=None) -> Dict:
    """导出为 Lottie JSON。返回 {path, layers, frames, size, bytes}。"""
    from spolvero.styles.apply import recolor
    from spolvero.animation.film import scene_at  # noqa: F401  (保持内核依赖显式)

    fps = int(project.fps or 24)
    frames = max(1, int(round(project.duration * fps))) if project.duration > 0 else 1

    layers: List[Dict] = []
    for idx, g in enumerate(project.groups):
        iid = project.iids[idx] if idx < len(project.iids) else f"layer{idx}"
        node = recolor(g, style) if style is not None else g
        if not isinstance(node, Group):
            continue
        anim = project.anims.get(iid) if project.anims else None
        layers.append({
            "ddd": 0,
            "ind": idx + 1,
            "ty": 4,
            "nm": iid,
            "sr": 1,
            "ks": _layer_transform(project, node, anim, frames),
            "ao": 0,
            "shapes": _shape_groups(node.children, idx),
            "ip": 0,
            "op": frames,
            "st": 0,
            "bm": 0,
        })

    ratio = [round(project.width / project.height, 8), 1.0] if project.height else [1.777778, 1.0]
    doc = {
        "v": LOTTIE_VERSION,
        "fr": fps,
        "ip": 0,
        "op": frames,
        "w": int(project.width),
        "h": int(project.height),
        "nm": project.seed,
        "ddd": 0,
        "assets": [],
        "layers": layers,
        "markers": [],
        "meta": {
            "g": "Spolvero",
            "a": "spolvero",
            "k": ["spolvero", "symbol-composition"],
            "d": "Spolvero L0 烘焙导出（丢参数化，见 SPEC §12）",
            "tc": "#00000000",
            "ratio": ratio,
        },
    }

    out_path = os.path.abspath(out_path)
    d = os.path.dirname(out_path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))

    return {
        "path": out_path,
        "layers": len(layers),
        "frames": frames,
        "fps": fps,
        "size": [int(project.width), int(project.height)],
        "bytes": os.path.getsize(out_path),
    }
