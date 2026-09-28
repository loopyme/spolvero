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
    preset = _style_of(project)
    return preset.constraints if preset else None


def _style_of(project):
    try:
        from spolvero.styles import get_style
    except Exception:
        return None
    return get_style(getattr(project, "style", "") or "")


def _styled_leaves(project, t: Optional[float] = None) -> List:
    """按风格 + 实例 tint 着色后拍平——校验必须作用于**实际会被渲染的颜色与位置**，
    否则彩色与灰度会算出同一个彩面积，约束形同虚设。
    `t` 给定时先求该时刻的场景（含相机），用于校验动画过程中的构图是否越界。
    """
    if t is None:
        groups = list(project.groups)
    else:
        from spolvero.animation.film import scene_at

        groups = scene_at(project, t)
    preset = _style_of(project)
    if preset is None:
        return flatten_all(groups)

    from spolvero.styles.apply import recolor

    tints = getattr(project, "tints", None) or {}
    iids = getattr(project, "iids", ()) or ()
    # 相机可能把整场包成一个 Group；只有与 groups 等长时才逐实例取 tint
    if len(groups) == len(iids):
        groups = [
            recolor(g, preset, tints.get(iids[i])) for i, g in enumerate(groups)
        ]
    else:
        groups = [recolor(g, preset) for g in groups]
    return flatten_all(groups)


def validate_project(project, t: Optional[float] = None) -> ValidationReport:
    """校验整个工程（M3 的 Project / M5 的 AnimatedProject 通用）。

    t=None 校验 DSL 声明的**基准姿态**；给定 t 则校验该时刻（含动画与相机）——
    故事片的构图会随镜头变化，只卡基准姿态没有意义。
    """
    return validate_scene(
        _styled_leaves(project, t),
        project.width,
        project.height,
        _style_constraints(project),
        label="project" if t is None else f"t={t:g}s",
    )
