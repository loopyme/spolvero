"""DSL 包（M3）：声明式工程资产 → 确定性场景图。

两层结构（SPEC §7）：
- 工程层：project.yaml / style.yaml / components.yaml（构件*定义*为声明式资产）
- 时序层：timeline.yaml（构件实例 + 裸原语）

构件构建以 pattern 键引用引擎内置模式（红线性：AI 只产出数据，绝不生成代码）。
"""
