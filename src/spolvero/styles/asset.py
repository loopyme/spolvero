"""风格预设资产模型（M6a）。

对应 SPEC §7.2 的 `style.yaml` v1 扩展。设计要点：

- 四原语仍只有 `ink: 0–1` 灰度 + 可选 `color`；**风格资产是灰度 → RGB 的唯一映射表**，
  渲染时由 `styles.apply.recolor` 落到叶节点的 `color` 字段，引擎内核不含任何配色逻辑。
- 资产是**唯一真相**且带 `schema_version`（SPEC §3 派生约束）：一经 approve 即冻结落盘，
  禁止每次重跑重算——转录器要落进同一套 schema，否则说明抽象错了。
- `tone.palette` 只有 paper / base / ink 三档（+ 0–3 个 accents），刻意不让转录器输出
  任意长度色卡：三档足以表达水墨、朱砂、青绿、浮世绘等本项目的符号化风格，
  且色数越少越不容易毁掉 L1 确定性。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple

SCHEMA_VERSION = 1

# 灰度 → 三档调色板的转折点：ink ≥ BASE_BREAK 走 paper→base，以下走 base→ink
BASE_BREAK = 0.72


@dataclass(frozen=True)
class Tone:
    """调色层：三档调色板 + 点缀色 + 纯度轴。"""

    paper: str = "#FFFFFF"
    base: str = "#8A8580"
    ink: str = "#1A1A1A"
    accents: Tuple[str, ...] = ()
    purity_axis: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "palette": {"paper": self.paper, "base": self.base, "ink": self.ink},
            "accents": list(self.accents),
            "purity_axis": self.purity_axis,
        }

    @classmethod
    def from_dict(cls, d: Optional[Dict]) -> "Tone":
        d = d or {}
        p = d.get("palette", {}) or {}
        return cls(
            paper=str(p.get("paper", "#FFFFFF")),
            base=str(p.get("base", "#8A8580")),
            ink=str(p.get("ink", "#1A1A1A")),
            accents=tuple(d.get("accents", ()) or ()),
            purity_axis=float(d.get("purity_axis", 0.0)),
        )


@dataclass(frozen=True)
class CompositionFingerprint:
    """构图指纹：核心 4 约束 + 扩展 2。手写预设填目标值，转录器填实测值。"""

    whiteness: float = 0.0
    color_area: float = 0.0
    density_profile: Tuple[float, ...] = ()
    clustering: float = 0.0
    region_count: int = 0
    centroid: Tuple[float, float] = (0.5, 0.5)
    axis_deg: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "whiteness": self.whiteness,
            "color_area": self.color_area,
            "density_profile": list(self.density_profile),
            "clustering": self.clustering,
            "region_count": self.region_count,
            "centroid": list(self.centroid),
            "axis_deg": self.axis_deg,
        }

    @classmethod
    def from_dict(cls, d: Optional[Dict]) -> "CompositionFingerprint":
        d = d or {}
        c = d.get("centroid", (0.5, 0.5)) or (0.5, 0.5)
        return cls(
            whiteness=float(d.get("whiteness", 0.0)),
            color_area=float(d.get("color_area", 0.0)),
            density_profile=tuple(float(x) for x in (d.get("density_profile", ()) or ())),
            clustering=float(d.get("clustering", 0.0)),
            region_count=int(d.get("region_count", 0)),
            centroid=(float(c[0]), float(c[1])),
            axis_deg=float(d.get("axis_deg", 0.0)),
        )


@dataclass(frozen=True)
class Texture:
    """质感层（M6b 提取，M7 笔刷消费）。M6a 手写预设给保守默认值。"""

    stroke_coherence: float = 0.0
    grain: float = 0.0
    edge_hardness: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "stroke_coherence": self.stroke_coherence,
            "grain": self.grain,
            "edge_hardness": self.edge_hardness,
        }

    @classmethod
    def from_dict(cls, d: Optional[Dict]) -> "Texture":
        d = d or {}
        return cls(
            stroke_coherence=float(d.get("stroke_coherence", 0.0)),
            grain=float(d.get("grain", 0.0)),
            edge_hardness=float(d.get("edge_hardness", 0.0)),
        )


@dataclass(frozen=True)
class StyleAsset:
    """一份可复用的风格预设资产。"""

    id: str
    name: str
    description: str = ""
    schema_version: int = SCHEMA_VERSION
    default_ink: float = 0.30
    grayscale: bool = True
    fidelity_default: float = 0.0
    tone: Tone = field(default_factory=Tone)
    composition: CompositionFingerprint = field(default_factory=CompositionFingerprint)
    texture: Texture = field(default_factory=Texture)
    sources: Tuple[Dict, ...] = ()
    constraints: Dict = field(default_factory=dict)
    origin: str = "builtin"  # builtin（手写） | transcribed（转录）

    # —— 交互式调参（M6c 滑杆用）：返回新资产，不改原对象 ——
    def tweaked(self, **kv) -> "StyleAsset":
        return replace(self, **kv)

    def with_constraints(self, constraints: Dict) -> "StyleAsset":
        return replace(self, constraints=dict(constraints))

    # —— 序列化 ——
    def style_dict(self) -> Dict:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "default_ink": self.default_ink,
            "grayscale": self.grayscale,
            "fidelity_default": self.fidelity_default,
            "sources": [dict(s) for s in self.sources],
            "tone": self.tone.to_dict(),
            "composition": self.composition.to_dict(),
            "texture": self.texture.to_dict(),
        }

    def constraints_dict(self) -> Dict:
        return {"schema_version": self.schema_version, "id": self.id, **self.constraints}

    @classmethod
    def from_dicts(cls, style_d: Dict, constraints_d: Optional[Dict] = None) -> "StyleAsset":
        c = dict(constraints_d or {})
        c.pop("schema_version", None)
        c.pop("id", None)
        return cls(
            id=str(style_d["id"]),
            name=str(style_d.get("name", style_d["id"])),
            description=str(style_d.get("description", "")),
            schema_version=int(style_d.get("schema_version", SCHEMA_VERSION)),
            default_ink=float(style_d.get("default_ink", 0.30)),
            grayscale=bool(style_d.get("grayscale", True)),
            fidelity_default=float(style_d.get("fidelity_default", 0.0)),
            tone=Tone.from_dict(style_d.get("tone")),
            composition=CompositionFingerprint.from_dict(style_d.get("composition")),
            texture=Texture.from_dict(style_d.get("texture")),
            sources=tuple(style_d.get("sources", ()) or ()),
            constraints=c,
            origin=str(style_d.get("origin", "builtin")),
        )

    # —— 便捷读取 ——
    @property
    def paper_rgb(self) -> Tuple[int, int, int]:
        from spolvero.styles.apply import parse_hex

        return parse_hex(self.tone.paper)

    def summary(self) -> str:
        return (
            f"{self.id:20s} {self.name:14s} "
            f"{'灰度' if self.grayscale else '彩色':<4s} "
            f"ink={self.default_ink:.2f} accents={len(self.tone.accents)} "
            f"[{self.origin}]"
        )


def list_summary(assets: List[StyleAsset]) -> str:
    return "\n".join(a.summary() for a in assets)
