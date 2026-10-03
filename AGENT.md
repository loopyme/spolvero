# AGENT.md — Spolvero (for AI coding agents / WorkBuddy)

This file is written **for other AI agents** that assist a user in making animated
videos with Spolvero. It tells you how the project is structured, which path is
reliable, how to write a programmatic scene script, and how to help the user debug.

> Spolvero is a **deterministic symbolic-composition animator**. You compose a scene
> from primitive ink shapes (dots / lines / polygons) and component prototypes, then
> either render a still or encode an MP4. Randomness is derived from `(seed, iid)`,
> never from a mutable RNG stream — same inputs always produce the same frames.

> **Workflow:** Do NOT jump straight to code. Follow **§0** first — co-create the story and act breakdown with the user across multiple turns before writing any scene script.

---

## 0. 协作流程：先聊故事与分幕，再动手（红线优先）

Spolvero 是确定性符号动画引擎。你的职责不是"尽快吐出一个 mp4"，而是和用户在**多轮对话**里把一部片子的创意先想清楚、对齐，再程序化生成。

**红线——禁止无脑直接生成。** 用户明确授权前，以下动作一律不做：
- 不要主动 `pip install`、不要创建 `.venv`、不要跑环境搭建；不要假定项目一定自带 venv——以 §0 阶段零的自检结果为准。除非用户明确要求，或运行报错且确认是环境缺失，否则不要碰环境。
- 不要一上来就写 `encode_film`、不要直接产出成片。
- 不要替用户拍板、也不要抛固定选择题考用户（见阶段一）。可基于简报给出默认方案提案，但须显式交用户确认 / 调整，不默默定死。

**四阶段流程（每阶段都先提案 → 等用户回复 → 再推进，绝不跳过）：**

### 阶段零 · 环境自检（动手前先确认能跑）

写任何代码前，先确认运行环境可用——避免 import 到一半才崩、且被红线拦住无法自救：

```bash
# 在仓库根目录执行；能打印 "env ok" 即环境就绪
PYTHONPATH=src python -c "import spolvero; print('env ok')"
```

- **通过**：继续阶段一。
- **报错 `ModuleNotFoundError: yaml` / `skia` / `shapely` 等**：即属红线允许的"运行报错且确认环境缺失"。此时**先问用户是否同意装环境**，获同意后再按 §2 安装；不要擅自动手。
- 注意：后台安装命令结尾的 `echo INSTALL_DONE` 只是回显、不代表装成功，必须用 `python -m pip list | findstr skia` 复核（见 §2）。

### 阶段一 · 先要故事（Story first，少问多提案）

**第一步必须拿到一个"完整的故事"，不是一句情绪、也不是一句梗概。** 引导用户直接给出可叙事的文本——有起承转合或明确情节的人物 / 寓言，例如"崂山道士的故事"（道士上山求道、学穿墙术、心不诚半途而废、墙前撞晕）。没有完整故事，后续分幕、配色都无锚点。

- **用户给故事的方式**：贴一段原文、口述完整情节、或指定某篇现成故事（如蒲松龄《聊斋志异·崂山道士》）都行。
- **不要抛选择题考用户**，也不要急着问风格 / 时长 / 画幅——先收故事。

收到故事后，你直接基于它**给出默认方案提案**（见下），交用户确认 / 微调，而不是反过来追问一堆问题：

- **叙事类型**：默认叙事型（有主角动作线）；仅当用户明确说"不画具体物、只讲节奏"时才选纯韵律型。
- **风格预设**：吴冠中系默认 `eastern_minimal`；具体子类（江南水乡 / 春如线 / 长城 / 都市）按故事氛围选一套 tints，不必提问。
- **时长与画幅**：默认按故事体量 8–15s @30fps、16:9（1600×900，宽高须偶数）；除非用户另有要求，直接采用并标注。
- **关键意象**：从故事提炼"要出现 / 不要出现"的元素（山、道观、舟、桥、树、鸟、色点…），列在提案里让用户勾。

> 原则：**故事由用户给，其余一律先提案、只问真正卡住的点**。用户给一段完整故事即可进入阶段二（分幕）。

### 阶段二 · 分幕（Act breakdown）
基于阶段一用户给的**完整故事**，提出**分幕结构**（把故事切成 3–5 幕），用表格呈现并请用户确认 / 调整：

| 幕 | 时长 | 画面内容 | 镜头 / 动画手段 | 情绪 |
|------|------|----------|----------------|------|
| 一 | 0–3s | … | `draw` 生长 / 相机推入 | … |
| 二 | … | … | … | … |

把整片切成 3–5 幕，标注每幕的 `draw` 生长节奏、相机推拉、幕间转场。这是后续动画通道设计的骨架。

### 阶段三 · 视觉方案（Visual plan）
对齐"怎么画"再写代码，向用户呈现一份方案摘要：
- **构件清单**：复用哪些内置原型（如 `lonely_boat` 的 `mountain` / `water` / `boat`），需新写哪些（如 `house` / `tree` / `bridge`）。
- **配色（tints）**：每个实例的 `#RRGGBB` 色系，对照风格 preset 的 `color_area` / `whiteness` 约束，避免超色域。
- **每幕动画通道**：`translate` / `rotate` / `scale` / `ink_shift` / `draw` / 相机 各自怎么动。
- 等用户确认方案后再进阶段四。

### 阶段四 · 程序化生成与交付（用户确认后才动手）

1. 写 `.py` 脚本（见 §5 模板），通过 `sys.path.insert(0,"src")` 或 `PYTHONPATH=src` 挂上库。
2. **先渲染静帧** `render_project` / `render_frame_at`，让用户肉眼看构图。
3. 跑 `check_project` 看校验报告，修几何 / 构图问题（自动校验只管几何、结构、确定性这类客观项）。
4. 确认无误后再 `encode_film` 出片。
5. **交付即人工校验，机器不代判「通过」**：把 mp4 直接交给用户过目节奏与色彩——动幅手感、叙事节奏、色彩浓淡属审美判断，自动校验不得代判。
6. **附分镜静帧**：用 `snapshot_frames` 抽 4–6 张关键幕起止时刻的静帧一并交付，便于用户快速过整片节奏（见 §7）。
7. **用户反馈的固定解读（迭代时照此办，勿自行另解）**：
   - 「动感太小 / 基本没动」→ **提量级**：让主体位移达到画幅宽度的 ~80% 级，不是把现有幅度再调大一点；叙事类要有幕次与故事线，不是静帧微晃。
   - 「颜色不鲜亮」→ 用**实例级 `tints`** 给每类元素各自的色系 + 高纯度点缀色，不要只全局提饱和度（同套配色映射所有元素会把整片压成同一色相）。

> 以上 5–7 为已确认的交付标准（跨项目适用）：凡产出视频一律人工校验、附分镜静帧、按量级与实例级配色迭代。

---

## 1. Current state (read this first)

| Area | Status | Notes |
|------|--------|-------|
| Core library `src/spolvero/` | **Solid** | Deterministic render + animation. This is what you build on. |
| Programmatic scene scripts (write `.py`, call the library) | **Recommended path** | Most reliable. The 71s "laoshan" film was made this way. |
| Declarative YAML project (`spol init` → `project/components/timeline.yaml` → `spol film`) | Usable for stills; **timeline layer is weak** | Animation channels exist but the YAML timeline authoring is immature. Prefer code for anything animated. |
| Flask web console (`spol studio`) | **WIP / not recommended** | Not the primary workflow. Tell the user to drive video-making through code + you, not the console. |
| `spike/` and `films/` directories | **Excluded from this snapshot** | They contain experiment scripts and an unfinished film-package example. Do not assume they exist. |

**What is in this repo:** `src/spolvero/` (library), `examples/`, `projects/`, `styles/`,
docs. **Not in this repo:** `spike/`, `films/` (per upload scope decision).

---

## 2. Environment setup

> ⚠️ **不要主动搭建环境（见 §0 红线）。** 不要假定项目一定自带 `.venv` 与依赖——以 §0 阶段零的自检结果为准。只有用户明确要求，或运行报错且确认是环境缺失时，才执行下方的安装步骤。无授权不要 `pip install`、不要新建 venv。

Requires **Python ≥ 3.12**. The renderer backend is **skia-python** (needs a prebuilt
wheel; install in an isolated venv).

```bash
# create & activate a venv
python -m venv .venv
.venv/Scripts/activate        # Windows  (Git Bash: source .venv/Scripts/activate)
# or on the managed runtime:
#   C:/Users/L-P-Y/.workbuddy/binaries/python/versions/3.13.12/python.exe -m venv .venv

# install (pin skia — other versions often fail to build)
pip install "skia-python==144.0.post2" shapely "numpy>=1.26" pyyaml jsonschema imageio-ffmpeg
# optional: pip install lottie   (Lottie export/import)
# optional: pip install flask     (only if you really need the WIP console)

# run anything with the library on PYTHONPATH=src
PYTHONPATH=src python your_script.py
```

> On **Windows CMD** the `PYTHONPATH=src python ...` bash form does NOT work. Use:
> ```cmd
> set PYTHONPATH=src
> python your_script.py
> ```
> Or from PowerShell: `$env:PYTHONPATH="src"; python your_script.py`

#### 装完务必复核（避免假成功）

后台安装命令的 `&& echo INSTALL_DONE` 只是回显，pip 实际失败时它仍会打印。务必用下方命令确认真装上了：

```bash
python -m pip list | findstr skia      # 应能看到 skia-python
python -m pip list | findstr pyyaml    # 注意包名是 pyyaml，import 名是 yaml
```

#### 环境缺失如何判定与破局

- 若 `PYTHONPATH=src python -c "import spolvero"` 报 `ModuleNotFoundError`，即环境缺失；
- 按 §0 红线，先向用户确认是否授权安装，获同意后再执行上方安装步骤；
- 不要假定"项目自带 venv"——同一仓库在不同机器 / 快照上可能根本没带依赖，一律以实际自检结果为准。

CLI entry points:
- `python -m spolvero.cli ...`  (always works)
- `spol ...`  (only after `pip install -e .` registers the console script)

---

## 3. Module map (where things live)

```
src/spolvero/
  core/
    primitives.py   # Group, InkShape, InkLine, InkDot, Point  — the 4 primitives
    component.py     # ComponentLibrary, ComponentPrototype, Instance, ParamSpec
    transform.py     # Transform (translate/rotate/scale, compose)
    rng.py           # derive(seed,iid,key) -> [0,1);  range_of(...) -> [lo,hi);  (DETERMINISTIC)
    dmath.py         # dcos/dcos — quadrant-folded trig, cross-platform identical (use INSTEAD of math.*)
    types.py         # Point, etc.
    scene.py         # scene() evaluation helpers
  components/        # component prototype libraries (lonely_boat.py = boat/mountain/water/moon)
  scenes/            # pre-composed instance layouts (lonely_boat.py)
  animation/
    track.py         # Key, Track, AnimSet  — keyframe channels
    film.py          # encode_mp4 / scene_at / frame iteration
    easing.py        # easing curves ("smooth" default)
  render/
    backend.py       # render(nodes, backend, w, h, bg, fx) -> svg str | png bytes
    skia.py / svg.py # backends (svg = zero-dep)
    common.py        # gray_of(ink), paper colors
    effects.py       # texture/material fields
  styles/            # (this is a top-level dir, not under src) style presets
  validation/        # validator.py — geometry / similarity / composition checks
  dsl/               # model.py: Project dataclass (the in-memory model)
  api.py             # PUBLIC API: render_project, render_frame_at, check_project,
                     #            encode_film, list_styles, get_style, snapshot_frames, ...
  cli.py             # `spol` / `python -m spolvero.cli`
```

Top-level `styles/` (NOT `src/spolvero/styles`) holds style presets:
`eastern_minimal` (彩色水墨), `film15s` (蚀刻梦境), `azurite`, `vermilion`.
Each preset = `style.yaml` + `constraints.yaml` + optional `preview.png`.
A style's `prompt:` field is the **aesthetic brief** that an LLM advisor would read —
style is expressed in the prompt, not only in the palette.

---

## 4. Built-in components & styles (what you can reuse)

- **Component library** `lonely_boat_library()` (from `spolvero.components`):
  prototypes `boat`, `mountain`, `water`, `moon`. Each has a `ParamSpec` range.
- **Scene** `lonely_boat_scene()` (from `spolvero.scenes`): a ready `List[Instance]`.
- **Styles**: `eastern_minimal`, `film15s`, `azurite`, `vermilion` (list with
  `python -m spolvero.cli style list`).

To make a *new* film, you usually write your own component library + scene (see §5),
or reuse `lonely_boat` as a template.

---

## 5. How to generate a programmatic scene script (the recommended path)

> 本节只讲"怎么写代码"。**何时写、写给什么创意**由 §0 的四阶段决定：必须先和用户对齐故事与分幕、确认视觉方案，再落笔写脚本。不要跳过 §0 直接进本节。

A "programmatic scene script" is a plain `.py` that builds a `Project` and calls
`encode_film`. This is what you (the agent) write/edit for the user.

### 5.1 Minimal static still

```python
import sys
sys.path.insert(0, "src")                      # or run with PYTHONPATH=src

from spolvero.components import lonely_boat_library
from spolvero.scenes import LONELY_BOAT_SEED, lonely_boat_scene
from spolvero.core.primitives import Group
from spolvero.core.transform import Transform
from spolvero.dsl.model import Project
from spolvero.api import render_project

lib = lonely_boat_library()
scene = lib.build_scene(lonely_boat_scene(), LONELY_BOAT_SEED)   # List[Group]
root = Group(tuple(scene), Transform.identity())

proj = Project(
    seed=LONELY_BOAT_SEED,
    width=1600, height=900, fps=30,
    style="eastern_minimal",
    background=(247, 245, 240),
    groups=(root,),
)
png = render_project(proj, backend="skia")     # bytes (PNG)
open("frame.png", "wb").write(png)
```

### 5.2 Minimal animated film (verified end-to-end)

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
groups = tuple(lib.build_scene(insts, LONELY_BOAT_SEED))   # one Group per instance
iids = tuple(i.iid for i in insts)                          # matching instance ids

# Animate the main boat drifting up + the whole scene "drawing itself" in.
anims = {
    "boat_main": AnimSet(tracks=(
        Track("translate", (Key(0.0, (0.0, 0.0)), Key(3.0, (0.0, -30.0))), "smooth"),
    )),
    # To animate the WHOLE scene as one group instead, wrap groups in a single
    # Group(...) and use iids=("whole",) with an anims={"whole": ...} entry.
}

proj = Project(
    seed=LONELY_BOAT_SEED,
    width=1600, height=900, fps=30,
    style="eastern_minimal",
    background=(247, 245, 240),
    groups=groups,
    duration=3.0,
    iids=iids,
    anims=anims,
)

info = encode_film(proj, "out.mp4", style=None, fps=30, duration=3.0)
print(info["path"], info["frames"], "frames")
```

### 5.3 Writing a NEW component library (when the user wants original visuals)

Pattern to follow (see `src/spolvero/components/lonely_boat.py`):

1. Define `ParamSpec` ranges per prototype.
2. Write a **pure** `build(params, seed, iid) -> Group` that produces geometry in a
   *local coordinate system* (anchor at origin, +y down). It must NOT do scene layout.
3. Derive all randomness from `core.rng.derive(seed, iid, key)` / `range_of(...)`.
   Never `random.*` or `numpy.random` — that breaks determinism.
4. Keep the **number of control points constant** across instances; only change
   *parameters*. (This is a hard invariant — the validator enforces it.)
5. Use `core.dmath.dcos` / `dsin` for any trig (cross-platform identical). Do NOT call
   `math.cos`/`math.sin` for geometry that must match across platforms.
6. `ink` is in `[0,1]`; low = dark, high = light (see `render.common.gray_of`).
7. Register prototypes with `ComponentLibrary().register(prototype_from_spec(spec))`
   or `register_pattern(name, build_fn)` for engine-internal builds.

Then a "scene" is just a `List[Instance]` placing prototypes via `Transform.translate(...)`
(+ optional rotate/scale) with sparse `overrides`.

---

## 6. Animation API (keyframe channels)

`anims` maps `iid -> AnimSet(tracks=(Track(...), ...))`. A `Track` is one channel:

```python
Track(channel, (Key(t0, value_vec), Key(t1, value_vec), ...), ease="smooth")
```

| Channel | Dim | Meaning |
|---------|-----|---------|
| `translate` | 2 | world-space translation delta (dx, dy), added after instance placement |
| `rotate`    | 1 | rotation about the instance anchor, degrees |
| `scale`     | 1 | uniform scale about the instance anchor, multiplier |
| `ink_shift` | 1 | ink offset added to the instance, clamped to [0,1] (brightness breathing / fade) |
| `draw`      | 1 | line-growth 0→1 (arc-length truncation — strokes "draw themselves") |
| `shake`     | 1 | camera-shake amplitude in px (per-frame integer-hash jitter) |
| `flash`     | 1 | exposure flash; >0 flashes toward paper color, <0 toward black |

Rules:
- Times in `Key` must be **ascending**. Outside the span the endpoint value is held.
- `ease` default `"smooth"`; other curves live in `animation/easing.py`.
- Missing `draw` channel ⇒ instance is fully drawn (value 1.0), NOT invisible.
- The global `camera` field on `Project` can hold an `AnimSet` for camera moves.

---

## 7. Render & validate

```python
from spolvero.api import render_project, render_frame_at, check_project, encode_film, snapshot_frames

render_project(proj, backend="skia")          # -> PNG bytes (or backend="svg" -> str)
render_frame_at(proj, t=1.5, backend="skia")  # -> PNG bytes at time t
check_project(proj)                            # -> ValidationReport (geometry/similarity/composition)
encode_film(proj, "out.mp4", style=None, fps=30, duration=proj.duration)  # -> dict w/ path/frames/bytes
```

`check_project` returns a report you can print for the user — it catches:
- invalid polygons (non-simple / self-intersecting),
- out-of-range parameters,
- composition constraints (whiteness, density, clustering).

Always render a **still first** (`render_project`) before encoding a full film — it is
10–100× faster to iterate on.

---

## 8. Red lines (do NOT violate — the engine enforces several)

1. **No lighting / photo-realistic shading model.** Allowed: ink gradients, glow
   halos, haze, vignette, hatching, paper grain, 12fps "boil" jitter, rough edges.
   Forbidden: physically-based light, smooth tonal shading that mimics a photo.
2. **Deterministic RNG only.** `core.rng.derive` / `range_of`. Never `random` /
   `numpy.random` / time-seeded streams.
3. **Constant control-point count** per prototype. Deform only in parameter space.
4. **Use `core.dmath` for trig**, not `math.*` — guarantees cross-platform frame parity.
5. **`ink ∈ [0,1]`**, low=dark. Negative or >1 will clamp or error.
6. **MP4 needs even width & height** (`w % 2 == 0 and h % 2 == 0`) or encode fails.
7. Keep `build()` a **pure function**: same `(params, seed, iid)` ⇒ identical geometry.

---

## 9. Helping the user debug (common failures)

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `encode_film` raises "H.264 yuv420p 要求宽高为偶数" | odd dimension | make `width`/`height` even |
| Boat/shape invisible for whole film | you added a `draw` track that ends at 0, or forgot it should end at 1 | ensure `draw` goes 0→1 (or omit it — default is 1.0/drawn) |
| `KeyError: 未注册构建模式: X` | `pattern` name not in `PATTERN_REGISTRY` | use a registered pattern or pass `build=` directly |
| `ValueError: 构件 X#iid 校验失败` | override outside `[lo,hi]` or wrong type | clamp/remove the override |
| Randomness differs run-to-run | used `random`/`numpy.random` | switch to `core.rng.derive`/`range_of` |
| `ImportError: No module named spolvero` | `src` not on path | run with `PYTHONPATH=src` (or `sys.path.insert(0,"src")`) |
| `ModuleNotFoundError: skia` | skia not installed in this venv | `pip install "skia-python==144.0.post2"` in an isolated venv |
| Windows CMD: `PYTHONPATH=src python` errors | bash syntax in CMD | use `set PYTHONPATH=src` then `python ...` |
| Polygon validator fails (non-simple) | x not strictly monotonic / mid vertices cross the closing edge | keep x monotonic; clamp all interior points to one side of the baseline |

Workflow when something looks wrong:
1. Print `check_project(proj)` — it localizes geometry/composition issues.
2. Render a single `render_frame_at(proj, t)` still and **look at it** before re-encoding.
3. If animation is wrong, inspect one `Track.sample(t)` at a few `t` values.
4. Reproduce with a tiny script (like §5.2) before touching the user's full film.

---

## 10. CLI quick reference

```bash
python -m spolvero.cli init <dir>            # scaffold a declarative project
python -m spolvero.cli render --project <dir> --out frame.svg
python -m spolvero.cli check --project <dir>
python -m spolvero.cli film  --project <dir> --out out.mp4
python -m spolvero.cli snapshot --project <dir>
python -m spolvero.cli style list            # list presets (eastern_minimal, film15s, ...)
python -m spolvero.cli style preview <id>    # render a preset thumbnail
# python -m spolvero.cli studio             # Flask console (WIP — not recommended)
```

Declarative YAML is fine for stills + simple timelines; for anything non-trivial,
**write a programmatic script (§5)** — it is the path the engine actually supports well.

---

## 11. What is NOT here

- `spike/` — experiment scripts (excluded).
- `films/` — an unfinished film-package example whose "source of truth" lived in
  `spike/story.py` (also excluded). Do not reference `films/laoshan/adapter.py`; its
  dependency is missing in this snapshot.

If the user needs a film-package (multi-act) workflow, build it as a programmatic
script first; the declarative `films/<id>` package format is not yet stable.
