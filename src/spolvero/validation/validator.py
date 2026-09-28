"""校验器编排（M4）。

validate_scene  —— 对拍平后的叶节点跑三重建验（几何 / 相似度 / 构图）。
validate_project —— 渲染工程为叶节点，并接入风格预设的四约束阈值。

设计：校验只消费「场景图 + 画布 + 约束阈值」，与渲染后端解耦；
结构化 Issue 可直供 CLI 报告与 AI 自纠回灌（SPEC §8 / §11）。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from spolvero.core.scene import flatten_all
from spolvero.validation.composition import validate_composition
from spolvero.validation.diagnostics import ValidationReport
from spolvero.validation.geometry import check_scene_geometry
from spolvero.validation.similarity import find_similar


def validate_scene(
    nodes: Sequence,
    width: int,
    height: int,
    constraints: Optional[Dict] = None,
    label: str = "scene",
) -> ValidationReport:
    """对场景（节点或节点序列）做三重建验，返回结构化报告。"""
    if isinstance(nodes, (list, tuple)):
        leaves = flatten_all(nodes)
    else:
        leaves = flatten_all([nodes])
    report = ValidationReport()
    report.add(*check_scene_geometry(leaves, label))
    report.add(*find_similar(leaves, label=label))
    report.add(*validate_composition(leaves, width, height, constraints))
    return report


def _style_constraints(project) -> Optional[Dict]:
    """从风格预设（M6a）读取四约束 + 扩展 2 阈值；无预设则返回 None（不强制）。"""
    try:
        from spolvero.styles import get_style
    except Exception:
        return None
    preset = get_style(getattr(project, "style", "") or "")
    return preset.constraints if preset else None


def validate_project(project) -> ValidationReport:
    """校验整个工程（M3 的 Project / M5 的 AnimatedProject 通用）。"""
    leaves = flatten_all(project.groups)
    constraints = _style_constraints(project)
    return validate_scene(
        leaves, project.width, project.height, constraints, label="project"
    )
