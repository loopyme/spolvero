"""DSL 解析器（M3）。

职责：读工程目录 → jsonschema 校验 → 解析为 Project（frozen 场景图）。
校验失败抛出 DSLValidationError，含 file + 字段路径，便于定位。

构件构建以 pattern 键引用引擎内置模式；裸原语模式直接构造四原语之一。
"""

from __future__ import annotations

import os
from typing import Any, List

import yaml
from jsonschema import Draft202012Validator

from spolvero.core.component import (
    ComponentLibrary,
    Instance,
    prototype_from_spec,
)
from spolvero.core.primitives import Group, InkDot, InkLine, InkShape
from spolvero.core.transform import Transform
from spolvero.core.types import Point
from spolvero.dsl.model import Project
from spolvero.dsl.schema import (
    COMPONENTS_SCHEMA,
    PROJECT_SCHEMA,
    STYLE_SCHEMA,
    TIMELINE_SCHEMA,
)

Bg = tuple[int, int, int]


class DSLValidationError(Exception):
    """DSL 校验失败，带 file + 字段路径定位。"""

    def __init__(self, file: str, path: str, message: str):
        self.file = file
        self.path = path
        self.message = message
        super().__init__(f"[{file}] {path}: {message}")


def _validate(schema: dict, data: Any, fname: str) -> None:
    validator = Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        path = "/".join(str(p) for p in err.path) or "<root>"
        raise DSLValidationError(fname, path, err.message)


def _hex_to_bg(h: str) -> Bg:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _parse_transform(spec: dict | None) -> Transform:
    if not spec:
        return Transform.identity()
    parts: List[Transform] = []
    if "scale" in spec:
        s = spec["scale"]
        parts.append(Transform.scale(s[0], s[1]) if isinstance(s, list) else Transform.scale(s))
    if "rotate" in spec:
        parts.append(Transform.rotate(float(spec["rotate"])))
    if "translate" in spec:
        t = spec["translate"]
        parts.append(Transform.translate(float(t[0]), float(t[1])))
    # 由内而外：scale → rotate → translate（局部缩放旋转，再放置）
    combined = parts[0]
    for p in parts[1:]:
        combined = p.compose(combined)
    return combined


def _parse_primitive(spec: dict, idx: int) -> Group:
    kind = spec.get("primitive")
    t = _parse_transform(spec.get("transform"))
    color = spec.get("color")
    if kind == "line":
        pts = [Point(float(x), float(y)) for x, y in spec["points"]]
        leaf = InkLine(
            points=tuple(pts),
            width=float(spec.get("width", 1.5)),
            ink=float(spec.get("ink", 0.4)),
            closed=bool(spec.get("closed", False)),
            color=color,
        )
    elif kind == "shape":
        pts = [Point(float(x), float(y)) for x, y in spec["ring"]]
        leaf = InkShape(
            ring=tuple(pts),
            ink=float(spec.get("ink", 0.4)),
            fill=bool(spec.get("fill", False)),
            width=float(spec.get("width", 1.5)),
            color=color,
        )
    elif kind == "dot":
        x, y = spec["pos"]
        leaf = InkDot(
            pos=Point(float(x), float(y)),
            r=float(spec.get("r", 2.0)),
            ink=float(spec.get("ink", 0.4)),
            color=color,
        )
    else:
        raise DSLValidationError("timeline", f"items[{idx}]", f"未知原语类型: {kind!r}")
    return Group((leaf,), t)


def _parse_item(item: dict, idx: int, lib: ComponentLibrary, seed: str) -> Group:
    if "component" in item:
        proto = item["component"]
        iid = item.get("iid", f"{proto}_{idx}")
        overrides = item.get("overrides", {}) or {}
        t = _parse_transform(item.get("transform"))
        inst = Instance(proto, iid, overrides, t)
        try:
            return lib.instantiate(inst, seed)
        except (KeyError, ValueError) as e:
            raise DSLValidationError("timeline", f"items[{idx}]", str(e))
    if "primitive" in item:
        return _parse_primitive(item, idx)
    raise DSLValidationError("timeline", f"items[{idx}]", "缺少 component 或 primitive 字段")


def _load_yaml(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_project(dir_path: str) -> Project:
    """读取工程目录，校验并解析为 Project。

    目录约定：
      project.yaml  style.yaml  components.yaml  timeline.yaml
    """
    dir_path = os.path.abspath(dir_path)
    project_f = os.path.join(dir_path, "project.yaml")
    style_f = os.path.join(dir_path, "style.yaml")
    comp_f = os.path.join(dir_path, "components.yaml")
    timeline_f = os.path.join(dir_path, "timeline.yaml")

    # 确保引擎内置构建模式已注册（import 触发 lonely_boat 的 register_pattern）
    import spolvero.components  # noqa: F401

    # —— project ——
    if not os.path.exists(project_f):
        raise DSLValidationError("project.yaml", "<root>", "文件缺失")
    project = _load_yaml(project_f)
    _validate(PROJECT_SCHEMA, project, "project.yaml")
    seed = project["seed"]
    width = int(project["width"])
    height = int(project["height"])
    fps = int(project.get("fps", 30))
    style_name = project.get("style", "eastern_minimal")
    bg = _hex_to_bg(project.get("background", "#F7F5F0"))

    # —— style ——
    palette: dict = {}
    if os.path.exists(style_f):
        style = _load_yaml(style_f)
        _validate(STYLE_SCHEMA, style, "style.yaml")
        palette = style.get("palette", {}) or {}

    # —— components（声明式构件定义）——
    if not os.path.exists(comp_f):
        raise DSLValidationError("components.yaml", "<root>", "文件缺失")
    comps = _load_yaml(comp_f)
    _validate(COMPONENTS_SCHEMA, comps, "components.yaml")
    lib = ComponentLibrary()
    for spec in comps:
        lib.register(prototype_from_spec(spec))

    # —— timeline ——
    if not os.path.exists(timeline_f):
        raise DSLValidationError("timeline.yaml", "<root>", "文件缺失")
    timeline = _load_yaml(timeline_f)
    _validate(TIMELINE_SCHEMA, timeline, "timeline.yaml")
    groups: List[Group] = [
        _parse_item(item, idx, lib, seed)
        for idx, item in enumerate(timeline.get("items", []))
    ]

    return Project(
        seed=seed,
        width=width,
        height=height,
        fps=fps,
        style=style_name,
        background=bg,
        groups=tuple(groups),
        palette=palette,
        src_dir=dir_path,
    )
