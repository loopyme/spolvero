"""风格预设子系统（M6a）。

对外入口（`api.py` 亦只经此处，落地「UI 层零业务逻辑」派生约束）：

    get_style(id)        → StyleAsset | None   （内置手写预设优先，其次仓库 styles/）
    list_styles(root)    → list[StyleAsset]
    save_style(asset)    → 落盘 styles/<id>/{style.yaml,constraints.yaml,preview.png}
    load_style_dir(dir)  → StyleAsset
    render_preview(asset, knobs, size) → SVG 字符串

M6a 只做「预设资产 + 渲染接入」；M6b 的转录器（参考画 → 资产）尚未实现，
其函数签名已在 `api.py` 定死，避免后续改动破坏 UI 边界。
"""

from __future__ import annotations

from typing import List, Optional

from spolvero.styles.asset import (
    SCHEMA_VERSION,
    CompositionFingerprint,
    StyleAsset,
    Texture,
    Tone,
    list_summary,
)
from spolvero.styles.io import (
    DEFAULT_ROOT,
    StyleIOError,
    load_all_styles,
    load_style_dir,
    save_style,
)
from spolvero.styles.presets import builtin_styles, get_builtin
from spolvero.styles.preview import apply_knobs, render_preview, render_preview_png

__all__ = [
    "SCHEMA_VERSION",
    "StyleAsset",
    "Tone",
    "CompositionFingerprint",
    "Texture",
    "StyleIOError",
    "get_style",
    "list_styles",
    "save_style",
    "load_style_dir",
    "load_all_styles",
    "render_preview",
    "render_preview_png",
    "apply_knobs",
    "list_summary",
    "DEFAULT_ROOT",
]


def get_style(style_id: str, root: str = DEFAULT_ROOT) -> Optional[StyleAsset]:
    """按 id 取风格资产：内置手写预设优先，其次仓库/用户 styles/ 目录。"""
    if not style_id:
        return None
    hit = get_builtin(style_id)
    if hit is not None:
        return hit
    for a in load_all_styles(root):
        if a.id == style_id:
            return a
    return None


def list_styles(root: str = DEFAULT_ROOT) -> List[StyleAsset]:
    """全部可用风格：内置手写预设 + 本地 styles/（同 id 以本地覆盖为准）。"""
    merged = dict(builtin_styles())
    for a in load_all_styles(root):
        merged[a.id] = a
    return [merged[k] for k in sorted(merged)]
