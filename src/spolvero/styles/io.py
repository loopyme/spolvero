"""风格预设的本地资产 I/O（M6a）。

落盘结构（SPEC §16）：
    styles/<id>/style.yaml        风格资产本体（带 schema_version）
    styles/<id>/constraints.yaml  构图约束（独立文件，便于单独 diff）
    styles/<id>/preview.png       缩略图——**必须由引擎自渲染**，不得用参考画原图

`save_style` 在写盘前校验 schema_version，避免把未来格式写成本版本的答案
（SPEC §3 派生约束：转录产物 schema_version 化且冻结落盘）。
"""

from __future__ import annotations

import os
from typing import List, Optional

import yaml

from spolvero.styles.asset import SCHEMA_VERSION, StyleAsset

DEFAULT_ROOT = "styles"
STYLE_FILE = "style.yaml"
CONSTRAINTS_FILE = "constraints.yaml"
PREVIEW_FILE = "preview.png"


class StyleIOError(Exception):
    pass


def style_dir(root: str, style_id: str) -> str:
    return os.path.join(root, style_id)


def _dump_yaml(path: str, data) -> None:
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def save_style(asset: StyleAsset, root: str = DEFAULT_ROOT, write_preview: bool = True) -> str:
    """把风格资产落盘为 `styles/<id>/`。返回目录路径。"""
    if asset.schema_version != SCHEMA_VERSION:
        raise StyleIOError(
            f"schema_version {asset.schema_version} 与引擎 {SCHEMA_VERSION} 不匹配，拒绝落盘"
        )
    d = style_dir(root, asset.id)
    os.makedirs(d, exist_ok=True)
    _dump_yaml(os.path.join(d, STYLE_FILE), asset.style_dict())
    _dump_yaml(os.path.join(d, CONSTRAINTS_FILE), asset.constraints_dict())
    if write_preview:
        from spolvero.styles.preview import render_preview_png

        with open(os.path.join(d, PREVIEW_FILE), "wb") as f:
            f.write(render_preview_png(asset))
    return d


def load_style_dir(d: str) -> StyleAsset:
    sf = os.path.join(d, STYLE_FILE)
    if not os.path.exists(sf):
        raise StyleIOError(f"缺少 {STYLE_FILE}: {d}")
    with open(sf, "r", encoding="utf-8") as f:
        style_d = yaml.safe_load(f) or {}
    constraints_d = None
    cf = os.path.join(d, CONSTRAINTS_FILE)
    if os.path.exists(cf):
        with open(cf, "r", encoding="utf-8") as f:
            constraints_d = yaml.safe_load(f) or {}
    if "id" not in style_d:
        style_d["id"] = os.path.basename(os.path.normpath(d))
    return StyleAsset.from_dicts(style_d, constraints_d)


def load_all_styles(root: str = DEFAULT_ROOT) -> List[StyleAsset]:
    if not os.path.isdir(root):
        return []
    out: List[StyleAsset] = []
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if os.path.isdir(d) and os.path.exists(os.path.join(d, STYLE_FILE)):
            try:
                out.append(load_style_dir(d))
            except StyleIOError:
                continue
    return out


def find_style_dir(root: str, style_id: str) -> Optional[str]:
    d = style_dir(root, style_id)
    return d if os.path.exists(os.path.join(d, STYLE_FILE)) else None
