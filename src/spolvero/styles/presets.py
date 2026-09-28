"""两套官方**手写**风格预设（M6a）。

刻意手写而非转录：它们为 M6b 转录器提供 **schema 对标基线**——转录产物必须能落进
同一套 `StyleAsset`，否则说明抽象错了（SPEC §13 M6a 说明）。

约束取值依据 `projects/lonely_boat` 实测（1600×900）：
    留白 0.9246 / 密度 0.00730 / 堆积 0.3167 / 色块数 5
预设取「区间」而非点值，留出创作余量；超区间出 warning 不阻断（SPEC §2 修正 1）。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from spolvero.styles.asset import (
    SCHEMA_VERSION,
    CompositionFingerprint,
    StyleAsset,
    Texture,
    Tone,
)

# ── 1. eastern_minimal：东方极简水墨（灰度）──
_EASTERN_MINIMAL: Dict = {
    "schema_version": SCHEMA_VERSION,
    "id": "eastern_minimal",
    "name": "东方极简",
    "description": (
        "水墨符号构成：以大量留白为主，线条克制、远山浅墨、焦点元素深墨。"
        "全片灰度（grayscale=true），不允许出现任何彩色元素。"
    ),
    "default_ink": 0.30,
    "grayscale": True,
    "fidelity_default": 0.0,
    "sources": [],
    "tone": {
        "palette": {"paper": "#F7F5F0", "base": "#6E6A64", "ink": "#1A1A1A"},
        "accents": [],
        "purity_axis": 0.0,
    },
    "composition": {
        "whiteness": 0.92,
        "color_area": 0.0,
        "density_profile": [],
        "clustering": 0.32,
        "region_count": 5,
        "centroid": [0.45, 0.58],
        "axis_deg": -17.6,
    },
    "texture": {"stroke_coherence": 0.0, "grain": 0.0, "edge_hardness": 1.0},
}
_EASTERN_MINIMAL_CONSTRAINTS: Dict = {
    "severity": "warning",
    "as_error": [],
    "whitespace_min": 0.80,
    "color_area_max": 0.0,
    "density_max": 0.020,
    "overlap_max": 0.55,
    "region_count_min": 2,
    "region_count_max": 60,
}

# ── 2. vermilion：朱砂点染（彩色，仍以墨为主体）──
_VERMILION: Dict = {
    "schema_version": SCHEMA_VERSION,
    "id": "vermilion",
    "name": "朱砂点染",
    "description": (
        "在东方极简骨架上加一层朱砂：主体仍是三档墨色（纸/淡墨/主墨），"
        "只让点染元素（小墨点）取朱红 accents[0]。彩面积受约束，避免变成彩色插画。"
    ),
    "default_ink": 0.30,
    "grayscale": False,
    "fidelity_default": 0.0,
    "sources": [],
    "tone": {
        "palette": {"paper": "#F6F1E7", "base": "#7A5A48", "ink": "#20160F"},
        "accents": ["#9A3B30"],
        "purity_axis": 0.62,
    },
    "composition": {
        "whiteness": 0.92,
        "color_area": 0.002,
        "density_profile": [],
        "clustering": 0.32,
        "region_count": 5,
        "centroid": [0.45, 0.58],
        "axis_deg": -17.6,
    },
    "texture": {"stroke_coherence": 0.0, "grain": 0.0, "edge_hardness": 1.0},
}
_VERMILION_CONSTRAINTS: Dict = {
    "severity": "warning",
    "as_error": [],
    "whitespace_min": 0.75,
    "color_area_max": 0.05,
    "density_max": 0.024,
    "overlap_max": 0.60,
    "region_count_min": 2,
    "region_count_max": 60,
}

OFFICIAL_STYLES: Dict[str, Dict] = {
    "eastern_minimal": _EASTERN_MINIMAL,
    "vermilion": _VERMILION,
}
OFFICIAL_CONSTRAINTS: Dict[str, Dict] = {
    "eastern_minimal": _EASTERN_MINIMAL_CONSTRAINTS,
    "vermilion": _VERMILION_CONSTRAINTS,
}

_CACHE: Optional[Dict[str, StyleAsset]] = None


def builtin_styles() -> Dict[str, StyleAsset]:
    """全部内置（手写）预设，key 为 id。"""
    global _CACHE
    if _CACHE is None:
        _CACHE = {
            sid: StyleAsset.from_dicts(sd, OFFICIAL_CONSTRAINTS.get(sid))
            for sid, sd in OFFICIAL_STYLES.items()
        }
    return _CACHE


def get_builtin(style_id: str) -> Optional[StyleAsset]:
    return builtin_styles().get(style_id)


def builtin_preview_scene(style_id: str):  # 供缩略图自渲染（见 preview.py）
    from spolvero.styles.preview import preview_scene

    return preview_scene(style_id)
