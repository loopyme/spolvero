"""工程级自定义构件体系（M2，项目核心设计）。

设计要点（SPEC §3 / §6）：
- 命门 1 · 派生式随机：所有随机来自 core.rng.derive / range_of，与实例顺序无关。
- 命门 2 · 原型↔实例稀疏差分：Instance 只存 sparse override + 自身 transform，
  渲染时 merge(原型默认, override)。改原型定义 → 所有实例重算而同步；
  改单实例 override → 仅该实例变化。
- 命门 3 · ink_shape 控制点数恒定：build 内部只调参数，不调点数（由各原型保证）。

关键约定：
- build(params, seed, iid) 在「局部坐标系」产出几何（锚点置原点，+y 向下），
  不含场景布局；布局属于 Instance.transform（实例化时整体外包一层 group）。
- 所有三角/超越计算走 core.dmath（dcos/dsin），不调用 libm，保跨平台 L2 一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from spolvero.core.primitives import Group
from spolvero.core.rng import derive, range_of
from spolvero.core.transform import Transform


@dataclass(frozen=True)
class ParamSpec:
    """单个构件参数的值域约束。

    kind:
      float — 连续量，[lo, hi] 派生采样（L1 差异化主来源）
      int   — 离散量，[lo, hi] 整数采样
      bool  — 拓扑开关（L2 差异化主来源），以概率 p_true 为真
    """

    name: str
    default: float
    lo: float = 0.0
    hi: float = 1.0
    kind: str = "float"
    p_true: float = 0.5  # 仅 bool：为 True 的概率

    def derive(self, seed: str, iid: str) -> float:
        if self.kind == "bool":
            return derive(seed, iid, self.name) < self.p_true
        if self.kind == "int":
            return int(range_of(seed, iid, self.name, self.lo, self.hi + 1))
        return range_of(seed, iid, self.name, self.lo, self.hi)


# build 签名：(派生后的完整参数表, seed, iid) -> Group（局部坐标系几何）
BuildFn = Callable[[Dict[str, float], str, str], Group]

# 引擎内置「构建模式」注册表。构件原型以 pattern 名引用之，而非内嵌 Python 代码，
# 从而 AI 层只产出声明式数据（参数表 + pattern 键），绝不生成可执行代码（红线性）。
PATTERN_REGISTRY: Dict[str, BuildFn] = {}


def register_pattern(name: str, fn: BuildFn) -> None:
    """注册一个引擎内置构建模式（几何展开纯函数）。"""
    PATTERN_REGISTRY[name] = fn


def param_spec_from_dict(d: dict) -> ParamSpec:
    """从声明式字典构造 ParamSpec（供 DSL 解析组件定义使用）。"""
    return ParamSpec(
        name=d["name"],
        default=float(d.get("default", 0.0)),
        lo=float(d.get("lo", 0.0)),
        hi=float(d.get("hi", 1.0)),
        kind=d.get("kind", "float"),
        p_true=float(d.get("p_true", 0.5)),
    )


def prototype_from_spec(spec: dict) -> "ComponentPrototype":
    """从声明式组件规格（components.yaml 的单项）构造 ComponentPrototype。"""
    params = [param_spec_from_dict(p) for p in spec["params"]]
    return ComponentPrototype(spec["name"], params, pattern=spec["pattern"])


class ComponentPrototype:
    """一个构件原型：参数表 + 原语展开规则。

    build 必须是纯函数：相同 (params, seed, iid) 永远产出相同几何。
    """

    def __init__(
        self,
        name: str,
        params: List[ParamSpec],
        build: Optional[BuildFn] = None,
        pattern: Optional[str] = None,
    ):
        self.name = name
        self.param_specs: Dict[str, ParamSpec] = {p.name: p for p in params}
        if pattern is not None:
            if pattern not in PATTERN_REGISTRY:
                raise KeyError(
                    f"未注册构建模式: {pattern}（已注册: {sorted(PATTERN_REGISTRY)}）"
                )
            self._build = PATTERN_REGISTRY[pattern]
        elif build is not None:
            self._build = build
        else:
            raise ValueError(f"构件 {name} 必须提供 build 或 pattern")

    # —— 参数派生 + 稀疏覆盖（命门 2）——
    def derive_params(
        self, seed: str, iid: str, overrides: Optional[Dict[str, float]] = None
    ) -> Dict[str, float]:
        ov = overrides or {}
        return {
            name: (ov[name] if name in ov else spec.derive(seed, iid))
            for name, spec in self.param_specs.items()
        }

    # —— 值域校验（M2 起生效，M4 强化为结构化诊断）——
    def validate(self, params: Dict[str, float]) -> List[str]:
        errs: List[str] = []
        for name, spec in self.param_specs.items():
            if name not in params:
                errs.append(f"{self.name}.{name}: 缺失参数")
                continue
            v = params[name]
            if spec.kind == "bool":
                if not isinstance(v, bool):
                    errs.append(f"{self.name}.{name}: 期望 bool，实际 {v!r}")
            elif spec.kind == "int":
                if not isinstance(v, int) or isinstance(v, bool):
                    errs.append(f"{self.name}.{name}={v!r}: 期望 int")
                elif not (spec.lo <= v <= spec.hi):
                    errs.append(f"{self.name}.{name}={v}: 越界 [{spec.lo},{spec.hi}]")
            else:
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    errs.append(f"{self.name}.{name}={v!r}: 期望 float")
                elif not (spec.lo <= v <= spec.hi):
                    errs.append(f"{self.name}.{name}={v}: 越界 [{spec.lo},{spec.hi}]")
        return errs

    # —— 实例化（稀疏 merge + 校验 + 展开 + 外包 group）——
    def instantiate(
        self,
        seed: str,
        iid: str,
        overrides: Optional[Dict[str, float]] = None,
        transform: Optional[Transform] = None,
    ) -> Group:
        params = self.derive_params(seed, iid, overrides)
        errs = self.validate(params)
        if errs:
            raise ValueError(
                f"构件 {self.name}#{iid} 校验失败:\n  " + "\n  ".join(errs)
            )
        inner = self._build(params, seed, iid)  # Group（局部坐标系）
        t = transform or Transform.identity()
        # 实例化 = 整体外包一层 group：placement ∘ 构件自身 transform
        return Group(inner.children, t.compose(inner.transform))


@dataclass(frozen=True)
class Instance:
    """构件实例：只存与原型默认值的 sparse override + 自身 transform。

    渲染时由 ComponentLibrary 解析原型并按 (seed, iid) 重算几何，
    因此「改原型定义 → 所有实例同步；改本实例 override → 仅本实例变化」。
    """

    proto: str
    iid: str
    overrides: Dict[str, float] = field(default_factory=dict)
    transform: Transform = field(default_factory=Transform)

    def with_override(self, **kv: float) -> "Instance":
        """返回叠加 override 的新实例（不改原对象，便于演示「改单实例」）。"""
        return Instance(
            self.proto,
            self.iid,
            {**self.overrides, **kv},
            self.transform,
        )


class ComponentLibrary:
    """原型注册表。改原型定义 → 所有实例重算同步（命门 2 的核心载体）。"""

    def __init__(self) -> None:
        self._protos: Dict[str, ComponentPrototype] = {}

    def register(self, proto: ComponentPrototype) -> None:
        self._protos[proto.name] = proto

    def get(self, name: str) -> ComponentPrototype:
        try:
            return self._protos[name]
        except KeyError:
            raise KeyError(
                f"未注册构件原型: {name}（已注册: {sorted(self._protos)}）"
            )

    def names(self) -> List[str]:
        return sorted(self._protos)

    def instantiate(self, inst: Instance, seed: str) -> Group:
        return self.get(inst.proto).instantiate(
            seed, inst.iid, inst.overrides, inst.transform
        )

    def build_scene(self, instances: List[Instance], seed: str) -> List[Group]:
        return [self.instantiate(i, seed) for i in instances]
