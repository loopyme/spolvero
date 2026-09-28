# Spolvero

**Symbol Composition Animator** — 矢量动画的确定性编译层。

自然语言驱动、人机协同、参数化构图可控、完全可复现的 2D 平面符号构成程序化动画系统。
内核是一台确定性矢量时间轴引擎 + 构件原型系统 + 三重校验器；AI 只做最外层的「剧本→DSL 翻译」。

> **命名**：spolvero 是文艺复兴壁画标准工序——沿设计稿轮廓扎针孔、扑炭粉转印点状轮廓线。
> 唐代敦煌莫高窟已有实物证据。与本项目的逻辑同构：cartoon=构件原型、针孔=参数化控制点、
> 扑粉转印=实例化、一稿多印=模板复用、转印后手改=实例 override、点状轮廓=`ink_dot`。

## 生态位

上游吃模型（OmniLottie）/ LottieFiles / SVG 素材，下游吐 Lottie / SVG / MP4。
独占**构件原型 + 实例差分 + 构图校验**这段确定性约束层——模型负责产生，Spolvero 负责收敛与交付。

## 三条技术命门

1. **派生式随机**：`rand = hash(seed, instance_id, param_name)`，增删实例不影响其他实例。
2. **原型↔实例稀疏差分**：实例只存与原型默认值的差异，改原型全场景同步。
3. **ink_shape 控制点数恒定**：形变只在参数空间插值。

## 状态

- M0+M1 在建：四原语数据模型、派生 RNG、仿射变换、SVG+Skia 双后端。
- 工程规范见 [SPEC.md](./SPEC.md)。

## 快速验证

```bash
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m spolvero --version
```

## 许可

MIT
