# Spolvero

**确定性符号构成动画器** —— 用「墨点 / 墨线 / 墨块 / 组合」四种图元与构件原型作曲面，
确定性地渲染静帧或合成 MP4。随机性由 `(seed, 实例id)` 派生，同一输入永远得到同一帧。

> 命名：spolvero 是文艺复兴壁画转印工序（沿稿扎孔、扑粉转印点状轮廓）。与本项目的逻辑同构：
> 卡通稿＝构件原型、针孔＝参数化控制点、扑粉＝实例化、一稿多印＝模板复用、转印后手改＝实例 override。

**不是**"一句话出片"的黑箱，**不是**图片生成模型的封装。

## 现状（诚实说明）

| 区块 | 状态 | 说明 |
|---|---|---|
| 核心库 `src/spolvero/` | **可用** | 确定性渲染 + 关键帧动画，是做片的主依靠。 |
| **程序化场景脚本**（写 `.py` 调库） | **推荐路径** | 最稳。71 秒《崂山道士》即用此法。 |
| 声明式 YAML 工程（`spol init` → `project/components/timeline.yaml` → `spol film`） | 静帧可用；**时间轴能力弱** | 动画通道齐全，但 YAML 时间轴编排尚不成熟，非简单片建议直接写代码。 |
| Flask 控制台（`spol studio`） | **开发中，暂不推荐** | 不是主工作流；做片请走"代码 + AI agent"，不要依赖控制台。 |
| `spike/`、`films/` | **本快照未包含** | 实验脚本与一个未完工的影片工程包示例（其"真相"在 `spike/story.py`，同样未收录）。 |

**本仓库包含**：`src/spolvero/`（库）、`examples/`、`projects/`、`styles/`、文档。
**本仓库不含**：`spike/`、`films/`。

## 怎么用（推荐：用 WorkBuddy / 编码 agent + 库组件出片）

最可靠的流程是：让 AI agent（如 WorkBuddy）直接写/改 Python 场景脚本，调用 `spolvero`
库渲染、迭代。**给其他 agent 看的专用说明在 [`AGENT.md`](./AGENT.md)**（环境配置、组件与
API 清单、程序化脚本写法、红线、调试提示都在里面），agent 应优先读它。

### 环境

需要 **Python ≥ 3.12**。渲染后端是 **skia-python**（装隔离 venv，锁版本）：

```bash
python -m venv .venv && .venv/Scripts/activate
pip install "skia-python==144.0.post2" shapely "numpy>=1.26" pyyaml jsonschema imageio-ffmpeg
# 运行任何脚本都把库放在 PYTHONPATH=src
PYTHONPATH=src python your_script.py
```

> Windows CMD 不支持 `PYTHONPATH=src python ...`（那是 bash 写法）。用：
> `set PYTHONPATH=src` 然后 `python your_script.py`。

### 快速开始

```bash
# 跑内置示例（生成 examples/lonely_boat.png + .svg）
PYTHONPATH=src python examples/demo_lonely_boat.py

# CLI
PYTHONPATH=src python -m spolvero.cli style list          # 列出风格预设
PYTHONPATH=src python -m spolvero.cli init  myproj        # 脚手架一个声明式工程
PYTHONPATH=src python -m spolvero.cli render --project myproj --out frame.svg
PYTHONPATH=src python -m spolvero.cli check  --project myproj
```

### 程序化最小示例（已端到端验证）

```python
import sys
sys.path.insert(0, "src")
from spolvero.components import lonely_boat_library
from spolvero.scenes import LONELY_BOAT_SEED, lonely_boat_scene
from spolvero.core.primitives import Group
from spolvero.core.transform import Transform
from spolvero.dsl.model import Project
from spolvero.animation.track import AnimSet, Track, Key
from spolvero.api import encode_film

lib = lonely_boat_library()
insts = lonely_boat_scene()
groups = tuple(lib.build_scene(insts, LONELY_BOAT_SEED))
iids = tuple(i.iid for i in insts)

anims = {"boat_main": AnimSet(tracks=(
    Track("translate", (Key(0.0, (0.0, 0.0)), Key(3.0, (0.0, -30.0))), "smooth"),
))}
proj = Project(
    seed=LONELY_BOAT_SEED, width=1600, height=900, fps=30,
    style="eastern_minimal", background=(247, 245, 240),
    groups=groups, duration=3.0, iids=iids, anims=anims,
)
info = encode_film(proj, "out.mp4", style=None, fps=30, duration=3.0)
print(info["path"], info["frames"], "frames")
```

完整 API、动画通道（translate/rotate/scale/ink_shift/draw/shake/flash）、构件库写法、
红线与调试清单见 [`AGENT.md`](./AGENT.md)。

## 三条技术命门

1. **派生式随机**：`rand = hash(seed, instance_id, param_name)`，增删实例不影响其他实例。
2. **原型↔实例稀疏差分**：实例只存与原型默认值的差异，改原型全场景同步。
3. **ink_shape 控制点数恒定**：形变只在参数空间插值。

## 红线（引擎强约束）

- 禁**照片级写实光照模型**；允许明暗渐变 / 发光晕 / 雾化 / 暗角 / 排线 / 纸纹 / 12fps 抖动 / 毛边。
- 随机性只走 `core.rng.derive` / `range_of`，禁 `random` / `numpy.random`。
- 每个原型控制点数恒定，只在参数空间形变。
- 三角计算走 `core.dmath`（跨平台一致），不调 `math.*`。
- `ink ∈ [0,1]`（低＝深、高＝浅）；MP4 宽高须为偶数。

## 风格

`styles/` 下预设：`eastern_minimal`（彩色水墨）、`film15s`（蚀刻梦境）、`azurite`、`vermilion`。
风格体现在预设的 `prompt:` 美学 brief 里，不只是调色板。`spol style list` 查看全部。

## 文档导航

- [`AGENT.md`](./AGENT.md) — **给其他 AI agent 看**：如何配置环境、生成程序化场景脚本、协助用户调试。
- [`SPEC.md`](./SPEC.md) — 工程规范（判据体系、AI 层、Web 控制台、影片工程包等）。
- `examples/` / `projects/` — 可跑示例。

## 许可

MIT
