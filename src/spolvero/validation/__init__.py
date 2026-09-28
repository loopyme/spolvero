"""Spolvero 三重自动校验（M4）。

三层校验：
  1. 几何拓扑（geometry）—— shapely 自相交 / 退化 / 朝向一致性
  2. 艺术相似度（similarity）—— 近重复形体检测（Fréchet + 重采样签名）
  3. 构图约束（composition）—— 留白 / 彩面积 / 密度 / 堆积 四约束（阈值可配）

所有问题以结构化 Issue 返回，带 severity（error / warning）、code、location、suggestion，
供 CLI 报告与 AI 自纠闭环（SPEC §8 / §11）。
"""

from spolvero.validation.diagnostics import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    Issue,
    ValidationReport,
)
from spolvero.validation.geometry import check_leaf_geometry, check_scene_geometry
from spolvero.validation.similarity import find_similar
from spolvero.validation.composition import validate_composition
from spolvero.validation.validator import validate_project, validate_scene

__all__ = [
    "SEVERITY_ERROR",
    "SEVERITY_WARNING",
    "Issue",
    "ValidationReport",
    "check_leaf_geometry",
    "check_scene_geometry",
    "find_similar",
    "validate_composition",
    "validate_project",
    "validate_scene",
]
