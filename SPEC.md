# Spolvero · 工程规范（SPEC）

> Symbol Composition Animator — 矢量动画的确定性编译层
> 本文件是 Spolvero 的权威工程规范。所有代码、DSL、CI、文档以本文件为基准。
> 状态：可行性已 spike 验证（§14），**M0–M5 与 M6a／M6d 已完成（126 项测试全绿）**。
> 官方交付两件：**故事片** `examples/lonely_boat_story.mp4`（10s 三幕叙事，300/300 帧互异，
> 主舟横穿 85% 画布，石青重彩）与**循环片** `examples/lonely_boat_film.mp4`（4s 满环无缝）。
> 下一步 M6b 风格转录器（签名已在 `api.py` 定死）、M6c 本地界面。
> M6 已拆分（M6a 预设资产 / M6b 转录器 / M6c 本地界面 / M6d Lottie），风格转录方案见 §7.2。
>
> **审查分工（用户 2026-09-28 明确）**：自动校验只负责几何 / 构图 / 确定性；
> **成片与画面一律交人工过目**——动幅手感、叙事节奏、色彩浓淡属审美判断，不得由脚本自行判定通过。

---

## 0. 与原始需求文档的关系

原始《SymbolCompose Animator 项目官方需求文档》（用户与豆包对话产出）是**愿景与红线来源**。本 SPEC 是经可行性验证后的**落地约束**，对原始文档有 5 处修正（§2）与 3 条技术命门（§3），并补全了原始文档缺失的工程细节（确定性分级、Lottie 定位、AI 层闭环、API 实测结论、风格转录路径）。

---

## 1. 项目身份与生态位

- **名称**：Spolvero（CLI 短名 `spol`；长名 Symbol Composition Animator）
- **命名考据**：spolvero 是文艺复兴壁画标准工序——把全尺寸设计稿（cartoon）沿轮廓扎针孔，用炭粉袋扑打，粉末透过针孔在湿灰泥上留下**点状轮廓线**作绘制引导。唐代敦煌莫高窟已有实物证据。与本项目工作逻辑同构：cartoon=构件原型、针孔=参数化控制点、扑粉转印=实例化、一稿多印=模板复用、转印后手改=实例 override、点状轮廓=`ink_dot`。
- **一句话定位**：矢量动画的**确定性编译层**。
- **生态位**：上游吃模型（OmniLottie）/ LottieFiles / SVG 素材，下游吐 Lottie / SVG / MP4；独占**构件原型 + 实例差分 + 构图校验**这段确定性约束层，模型越发达越需要它。不做模型、不竞争产生，只做收敛与交付。

---

## 2. 对原始需求文档的 5 处修正（已决）

| # | 原文 | 问题 | 本 SPEC 决策 |
|---|---|---|---|
| 1 | 校验不通过禁止渲染 | 与"自由拓展"冲突，实用中反复卡死 | 分级 `error`（阻断）/ `warning`（放行+报告），阈值写在工程配置，可配 |
| 2 | 禁止 LLM 生成代码/SVG | 只说禁、没给替代闭环 | LLM 唯一输出契约＝**结构化 DSL/资产**；校验诊断结构化回灌 LLM 自纠（§11） |
| 3 | 第八节音频 | 工作量被严重低估 | 首版只做时序轨 + 触发事件，出声后置 M9 |
| 4 | 全局线条质感（干笔/飞白/毛涩） | 纯矢量画不出"墨" | 独立光栅笔刷模块（M7）；**实测 skia-python 未暴露 `PathEffect.MakeDiscrete/MakeDash`，须自研路径重采样+扰动实现**，非白送 |
| 5 | AI 层四管线（剧本→分镜→构件→DSL） | 未界定 AI 的介入粒度与失败路径 | 风格转录中 AI **只介入一次**（仅产出 `tone.description` 与命名建议），提取主流程全走确定性 CV；无 API key / 断网时降级为规则模板，功能不得因此不可用 |

---

## 3. 永久架构红线（原始 11 条 + 3 条技术命门 + 3 条派生约束）

**原始 11 条（绝对禁止）**
1. 禁止新增引擎底层业务组件（只能用四大原语）
2. 禁止固定内置全局房屋/山/树等硬编码模板
3. 禁止抛弃「构件设计→实例差异化」创作流程
4. 禁止引入像素扩散模型作为主渲染管线
5. 禁止 3D 透视、写实光影、复杂肌理、卡通特效
6. 禁止 LLM 直接生成底层代码、SVG、可执行脚本
7. 禁止取消全局 Seed 确定性复现机制
8. 禁止跨平台确定性过度承诺（改分级，见 §9）
9. 禁止用 Lottie 关键帧模型作内部表示（见 §12）
10. 禁止系统字体参与复现（见 §9 破坏源）
11. 禁止在列表顺序/索引上耦合布局坐标（见命门补充）

**三条技术命门（定错即返工，写进所有实现）**
- **命门 1 · 派生式随机**：`rand = hash(global_seed, instance_id, param_name)`，禁止顺序消耗的随机流。增删实例不改变其他实例任何取值。
- **命门 2 · 原型↔实例稀疏差分**：实例只存与原型默认值的差异，渲染时 `merge(原型默认, 实例override)`。全量快照会导致"改原型→全场景同步"永远做不对。
- **命门 3 · ink_shape 控制点数恒定**：形变只在参数空间插值，不在点数上插值。

**派生约束（原始文档缺失，已决）**
- **布局坐标必须是 `(seed, instance_id)` 的纯函数**，绝不依赖数组顺序/索引。（spike 实测暴露）首版 A 测试用列表索引算网格坐标 → 插入实例后后续坐标全变（误报 FAIL），修正后漂移归零。真实引擎中实例自带 transform，场景图增删不打扰其他节点。
- **UI 层零业务逻辑**。（本地自托管决策引入）`cli.py` 与 M6c 的 Flask 界面均只是 `api.py` 的薄调用方；造型、时序、转录逻辑一律不得出现在 UI 层。渲染与转录必须能在完全无 UI 的情况下独立运行——UI 内嵌业务逻辑等同破坏「离线渲染铁律」（§11）。
- **转录产物 schema_version 化且冻结落盘**。（风格转录决策引入）风格转录器不在渲染路径上（创作期一次性），但其产物是唯一真相：`style.yaml` 必须带 `schema_version`，转录结果一经 `approve` 即冻结，禁止每次重跑重算——否则 palette 漂移会直接摧毁 L1 确定性（§9）。

---

## 4. 技术栈与锁定依赖

- **语言**：Python ≥ 3.12（3.13 实测通过）。内核零重依赖优先。
- **包管理**：uv 或 pip；隔离 venv 在 `.venv/`。
- **镜像**：清华 PyPI 源不可用，阿里云源正常；skia-python 需从 PyPI 或阿里源直装。

| 依赖 | 锁版本 | 用途 | 决策（build/buy） |
|---|---|---|---|
| `skia-python` | `==144.0.post2` | png 光栅后端 | BUY（不自研光栅器） |
| `shapely` | `>=2.0` | 几何校验/相似度（GEOS） | BUY（不自研几何内核） |
| `pyyaml` | `>=6.0` | DSL 解析 | BUY |
| `jsonschema` | `>=4.0` | DSL Schema 校验 | BUY |
| `imageio-ffmpeg` | `>=0.5` | 提供静态 ffmpeg 二进制 | BUY |
| `numpy` | `>=1.26`（可选） | 数值/批量；本内核暂不强制 | 评估中（确定性风险见 §9） |
| `python-lottie` | `>=0.9`（M6d 起） | Lottie 导入解析 | BUY（L1 导入用） |
| `flask` | `>=3.0`（M6c，可选） | 本地自托管界面（薄壳） | BUY；**声明为可选 extras `[ui]`**，内核与 CLI 不依赖 |

**自研模块（不引库）**：派生 RNG、仿射变换、缓动曲线、SVG 后端、笔刷质感、CLI（stdlib `argparse`）、**风格转录算法（中位切分色卡、8×6 密度直方图、结构张量笔触估计）**。

**风格转录（M6b）不新增任何图像库**：参考画解码与确定性下采样复用已锁定的 `skia-python`（强制统一像素格式以规避跨平台 BGRA/RGBA 差异），不引 Pillow / OpenCV / numpy（numpy 的确定性风险见 §9）。

---

## 5. 四原语（引擎内核，永久固定）

所有画面最终由以下四原语构成。坐标系：父级局部系，y 轴向下。

| 原语 | 数据结构（frozen） | 关键参数 | 渲染语义 |
|---|---|---|---|
| `ink_line` | `points: list[Point]`, `closed: bool` | `width`, `ink`(0–1 灰度), `dash?`, `jitter?` | 自由折线/书法线；闭合则成环 |
| `ink_shape` | `ring: list[Point]`（**恒定 N 点，闭合**） | `ink`, `fill?: bool` | 任意闭合轮廓；形变只在参数空间插值 |
| `ink_dot` | `pos: Point`, `r: float` | `ink` | 点状色点/墨点 |
| `group` | `children: list[Node]`, `transform` | 仅批量变换 | 无造型，仅做变换容器 |

- `ink` 为 0（黑）–1（白/留白）灰度，全局墨色体系由风格预设映射为 RGB。
- `ink_shape.ring` 控制点数量在原型定义时固定，实例化只调参数、不调点数（命门 3）。
- group 携带 `translate / rotate / scale / anchor`，实例化构件时整体包一层 group，使整体挪动/淡入无需触碰子元素。

---

## 6. 工程级自定义构件体系（项目核心）

- **原型 `Prototype`**：默认参数表 + 原语展开规则（line/shape/dot/group 组合）+ 参数值域约束 + **拓扑变体开关（L2）**。
- **实例 `Instance`**：只存与原型默认值的 sparse override + 自身 transform + `instance_id`。
- **双向迭代同步**：改原型 → 渲染时所有实例按新原型重算；改单实例 → 仅该实例变化。
- **差异化层级**：
  - L1 参数随机（大小/比例/墨色/旋转/抖动）—— M2 必做
  - L2 拓扑变体（原型内声明可选子结构：篷有/无、桅高/矮）—— **性价比最高，M2 必做**
  - L3 原型族（同语义 3–5 个原型：乌篷船/渔船/小舟）—— 交给 AI 构件设计阶段产出
- 所有随机来自 `dv(seed, iid, name)`（派生式，命门 1）。

### 6.1 落地数据模型（M2 已实现，`core/component.py`）

| 类型 | 字段 | 语义 |
|---|---|---|
| `ParamSpec` | `name, default, lo, hi, kind(float\|int\|bool), p_true` | 参数值域约束；`bool` 为 L2 拓扑开关，以概率 `p_true` 取真 |
| `ComponentPrototype` | `name, param_specs, build(params, seed, iid)→Group` | 原型＝参数表＋原语展开规则；`build` 纯函数，在**局部坐标系**产几何（不含布局） |
| `Instance` | `proto, iid, overrides, transform` | 实例＝原型名＋稀疏 override＋自身 transform，**不存全量快照** |
| `ComponentLibrary` | `register / get / instantiate / build_scene` | 原型注册表；改变原型定义 → 全部实例重算同步 |

- 实例化契约：`params = merge(原型派生, override)` → `validate` → `build` → **整体外包一层 group**（`placement ∘ 构件自身 transform`），故整体挪动/淡入无需触碰子元素。
- 派生规则：`bool → derive(seed,iid,name) < p_true`；`int → int(range_of(lo, hi+1))`；`float → range_of(lo, hi)`。
- 值域校验在实例化时生效：越界 / 类型不符 → `ValueError`（M4 升级为结构化诊断）。
- 已验证（`tests/test_m2.py`）：单参 override 不外泄、改原型全实例同步、override 优先级最高、50 实例 L1/L2 全差异化、控制点数恒定（船 8 / 山 9 / 水纹 16）、船体 shapely `is_valid` 全过。

---

## 7. DSL 规范

- **两层结构**
  - 工程层（资产）：`style`（风格预设）、`constraints`（构图约束）、`components/*.yaml`（本片构件库）
  - 时序层：`timeline`（时间区间）、`instances`（构件/原语实例声明）、`anim`（参数插值动画）、`groups`（分组动画）、`audio`（音频时序）
- **格式**：YAML 书写 + JSON Schema 校验，内部转 frozen dataclass。
- **面向 LLM 的硬约束**（OmniLottie 论文警示 + 分镜不写坐标原则）：短、嵌套 ≤3 层、大量默认值、坐标优先用语义/相对占位（`anchor: lower-left`）而非绝对像素。
- **两种模式**：构件模式（推荐 AI 用）/ 裸原语模式（高级自由创作）。
- **三层职责分离**（AI 管线铁律）：分镜不说坐标、构件不管时序、DSL 不做造型决策。分镜只写"这一镜要什么、呼吸节奏"；元素写语义（`舟 ×1，视觉重心`）不写构件/位置/尺寸。

### 7.1 M3 落地格式（已实现，`dsl/`）

工程目录四文件，均经 JSON Schema 校验（`dsl/schema.py`），错误定位到字段路径（`DSLValidationError`）：

```
project.yaml    seed / width / height / fps / duration / style / background(#RRGGBB)
                camera: [ {channel,ease,keys} ]          ← 可选，全局镜头（推/拉/摇）
style.yaml      name / description / default_ink / grayscale / palette{#RRGGBB 调色板}
components.yaml  [ {name, pattern, params:[{name,default,lo,hi,kind,p_true}]} ]  ← 构件*定义*为声明式资产
timeline.yaml   items: [ {component,iid,overrides,transform,tint?,anim?}
                       | {primitive,iid,points/ring/pos,...,color?,tint?,anim?} ]
```

- **构件以 `pattern` 键引用引擎内置构建模式**（`core/component.PATTERN_REGISTRY`），AI 只产出声明式 `components.yaml`（参数表 + pattern 键），**绝不持有构建代码**——既满足红线性（§3 红线 6），又让构件定义成为可 diff / 可版本化的资产。
- **裸原语模式**：`primitive: line|shape|dot` 直接声明四原语之一，`points/ring/pos` 为绝对坐标，可选 `color: #RRGGBB`。
- **颜色支持**：四原语均有可选 `color` 字段（`#RRGGBB`），渲染时优先于 `ink` 灰度（`render/common.color_of`）。
- **`tint`（实例级色系，M6a）**：给一个 `#RRGGBB`，该实例的 `ink` 就映射到「纸 → 淡 tint → tint 本色 → 深 tint」四档。
  这是**故事片的默认配色方式**——远山石青、水纹石绿、孤舟朱砂各走各自色系且仍保留明暗层次；
  若只用 `tone.palette` 一套三档，全片会压成同一个色相，那正是「线色不鲜亮」的成因。
  `tint` 是显式指定，**优先于风格的 `grayscale`**（给了颜色却被风格静默忽略，比约束失效更糟）。
- **`camera`（全局镜头，M6a）**：工程级 `AnimSet`，通道语义与实例 anim 相同，但**绕画布中心**施加，
  包在整场的合成层上。分工是刻意的：**主体的位移负责叙事，相机的位移负责观感**——
  没有相机就只能做「物体在画面里挪」，加了相机才有推轨、摇移、由远及近的镜头语言。
- **动幅纪律（经验，写死以免回退）**：叙事片的位移量应以**画布宽度**为度量（主人公横穿 ≥80% 画布），
  而不是以「像素级微动」为目标；且**中间关键帧不得正中对称**（见 §14.4 第 2 条）。

> M6a 将对 `style.yaml` 做向后兼容扩展，并新增 `constraints.yaml`，见 §7.2。

### 7.2 风格预设资产与转录器（M6a / M6b）

**定位**：面向终端用户的本地功能——用户上传参考画，系统转录为**可复用的风格预设资产**。转录器是**编译器前端**（参考画＝源文件），不是风格迁移：不引入像素扩散模型（红线 4）、不复刻参考画构图（红线 3）、产物为数值参数而非像素。运行形态为本地自托管（`pip install` 后自行运行，无线上平台）。

**style.yaml v1 扩展**（向后兼容，缺省字段走默认值）：

```yaml
schema_version: 1               # 必备；产物冻结的唯一标识
id: <slug>
name: <用户可改>
description: <AI 或规则模板产出>
default_ink: 0.30
grayscale: false
fidelity_default: 0.0           # 0=仅取调性；1=强贴合参考构图
sources:                        # 多图合成：角色分层
  - {sha256: <原图哈希>, role: color|composition|texture|all, weight: 1.0}
tone:
  palette: {paper: "#RRGGBB", base: "#RRGGBB", ink: "#RRGGBB"}
  accents: ["#RRGGBB", ...]     # 0–3 个；纯水墨/素描可为空
  purity_axis: 0.0              # 0–1，点缀色纯度轴
composition:                    # 核心 4 约束 + 扩展 2 指纹
  whiteness: 0.0                # 留白率
  color_area: 0.0               # 彩面积占比
  density_profile: []           # 8×6 归一化覆盖率直方图
  clustering: 0.0               # 堆积度（局部聚集指数）
  region_count: 0               # 扩展 2：色块/连通域数（平涂类风格关键特征）
  centroid: [0.5, 0.5]          # 扩展 2：墨质心 (cx, cy)
  axis_deg: 0.0                 # 主轴角度（二阶矩）
texture:
  stroke_coherence: 0.0         # 结构张量方向场相干度
  grain: 0.0                    # 颗粒度
  edge_hardness: 0.0            # 边缘硬度
```

**constraints.yaml**（M6a 起独立落地，便于单独 diff）：渲染后实测留白 / 彩面 / 密度 / 堆积，超出配置区间出 `warning` 而非阻断——承接 §2 修正 1 的分级原则。

**转录三层**（全部确定性，不引 Pillow / OpenCV / numpy）：

| 层 | 算法 | 输出 |
|---|---|---|
| 色彩 | 固定位深直方图 + **中位切分**（**禁用 k-means**：随机初始化破坏确定性）；**彩度分支**（近灰图改走明度分层，`accents` 为空）；**面积 × 纯度双轴**分类 | `palette` / `accents` / `purity_axis` |
| 构图 | 8×6 网格覆盖率直方图 + 连通域聚集指数 + 质心 + 二阶矩主轴 | 核心 4 + 扩展 2 |
| 质感 | **结构张量**方向场 → 相干度 / 颗粒 / 边缘硬度 | 交 M7 光栅笔刷模块 |

阈值（`T_paper` / `T_sat`）必须**自适应**（分位数或 Otsu），不得写死，否则亮调画与暗调画各崩一边。

**可表达性三档 + 自动降档**（是降档，不是拒绝）：

| 档 | 参考画类型 | 策略 |
|---|---|---|
| A | 天生符号化：吴冠中 / 八大山人 / 浮世绘 / 敦煌 / 剪纸 / 构成主义 | 直接转录，几乎无损 |
| B | 结构化但有连续调：印象派 / 马蒂斯 / 梵高 | 先色阶量化（posterize 至 5–7 阶）再转录，损失可控 |
| C | 写实 / 渐变为主：古典油画 / 摄影 / 3D 渲染图 | 强制抽象化，界面明示「非复制」——承接红线 5 |

判定量两个标量即可（均确定性）：**高频细节能量**（结构张量响应方差）与**连续色调占比**（直方图局部平滑度）。

**多图合成语义**：默认**分层选取**（色层取 A、构图取 B、质感取 C）。同层多图时：`accents` 取**并集去重后按面积排序取 top 3**，`density_profile` 按权重加权平均，标量按权重插值。**禁止同层 palette 做色相插值**——色相插值会产出「谁都不是」的脏色。

**UI 边界**（落地 §3 派生约束）：`api.py` 是唯一稳定边界，`cli.py` 与 M6c 的 Flask 界面均为薄调用方。

```python
transcribe_style(sources, *, name=None, ai=True) -> StyleAsset
compose_styles(parts, *, name=None) -> StyleAsset        # 多图合成
render_preview(asset, knobs, size=(720, 480)) -> str     # 返回 SVG，供滑杆实时重渲染
save_style(asset) -> Path
list_styles() -> list[StyleAsset]
```

`render_preview` 返回 **SVG 字符串**是刻意选择：引擎天然矢量，界面滑杆改动后直接替换 DOM 即可，无需落盘、无状态、且天然确定性。

**CLI**：`spol style from-image <ref...> [--role color|composition|texture|all] [--no-ai]`、`spol style merge`、`spol style preview`、`spol style list`。

**AI 介入粒度**（§2 修正 5）：全程仅一次调用，产出 `description` 与命名建议；`--no-ai` 或无 API key 时降级为规则模板命名，功能不得因此不可用。响应按 sha 缓存（§11）。

**预设缩略图必须由引擎自渲染**（`styles/<id>/preview.png`），不得使用参考画原图——保证本地资产可自由传递，且顺带是最好的功能演示。

**确定性**：转录器在渲染路径之外（创作期一次性），自身不受 L1 约束；但产物一经 `approve` 即冻结落盘为唯一真相（§3 派生约束）。

---

## 8. 三重自动校验体系

1. **语法参数校验**：DSL 合法、参数值域合法、ID 唯一。
2. **几何拓扑校验**（shapely）：自相交检测（`is_valid`）、控制点数量稳定（命门 3）、顶点顺序一致、非法轮廓拦截。
3. **艺术相似度校验**：归一化形状签名距离（Fréchet）+ 参数向量标准差 + 位图 pHash 汉明距离，检测高度相似形体，强制同类参数差异化。

分级：`error` 阻断渲染并输出结构化修改建议；`warning` 放行+报告。阈值写在工程配置，可配。

---

## 9. 确定性分级（跨平台必须分级，禁止过度承诺）

| 级别 | 范围 | 保证 |
|---|---|---|
| L1 | 同机同版本 | byte-identical，CI 卡死（golden-frame hash） |
| L2 | 跨平台（Win/macOS） | PNG 帧级一致（像素值一致） |
| L3 | 视频文件 | 像素一致，字节不保证（ffmpeg 版本差异） |

**两个破坏源与对策**
- 系统字体：引擎不渲染文本，或自带 OFL 字体文件（红线 10）。
- 超越函数 1ulp 差异（glibc vs Apple libm）：缓动用多项式实现、噪声用整数哈希，不碰 libm（故仿射/RNG 自研纯 Python，不引 numpy）。

---

## 10. 时间模型

- 内部统一**连续时间（秒，float）**，输出按 fps 采样。帧只是采样点——内部按帧计数会破坏缓动与音画同步。
- 缓动曲线**自研**（~30 行多项式），不引库。
- 音画双轨时序对齐（continuous 持续音 / trigger 瞬时音效）。

---

## 11. AI 层（内置 API provider）

- **4 管线**：剧本 → 分镜 → 构件 → DSL。每管线输出契约＝结构化 DSL/资产，**绝不生成代码/SVG**（红线 6）。
- **接口**：OpenAI 兼容层，默认 DeepSeek（`base_url` 可换豆包/通义/Ollama）。
- **sha 缓存**：响应按输入 sha 缓存，同输入不重复请求。
- **人工审核闸门**：`spol review <stage>` → 编辑 yaml → `spol approve`；未 approve 不得进下一步。
- **离线渲染铁律**：AI 只在创作期介入一次，产出落盘为工程资产；渲染期完全离线、不调用任何模型。
- **自纠闭环**：校验结构化诊断回灌 LLM，修正后重生成。

---

## 12. Lottie 生态对接（格式级，不做内核对齐）

| 档位 | 内容 | 决策 | 实现 |
|---|---|---|---|
| L0 导出 | DSL → Lottie / dotLottie JSON（烘焙结果，丢参数化） | 做（M6d） | 自研 DSL→Lottie 序列化 |
| L1 导入 | Lottie / SVG → 构件原型 | 做（M6d） | **python-lottie 解析 → shapely 几何化 → 控制点归一化 → 四原语**（Skia Skottie 未暴露，非走 Skia） |
| L2 内核对齐 | Lottie 数据模型作内部表示 | **不做（致命）** | Lottie 装不下原型/实例/seed/随机；JSON 冗长到模型喂不下 |

导出同时支持 Lottie 与 dotLottie，不押注单一；保留 SVG 输出（设计交付更友好，引擎天然矢量）。

---

## 13. 里程碑

| 里程碑 | 内容 | 关键验收 |
|---|---|---|
| M0 ✅ | 仓库/包结构/CLI 壳/许可/CI 双平台 | `spol --version` 可跑，CI 绿 |
| M1 ✅ | 四原语数据模型、路径求值、仿射、派生 RNG、SVG+Skia 双后端 | 手写原语可出图、确定性通过 |
| M2 ✅ | 构件系统：原型、值域校验、原语展开、实例稀疏 override、L1/L2 差异化 | 一原型出 50 差异化实例（见 §14.1） |
| M3 ✅ | DSL：Schema、解析器、工程层/时序层、裸原语模式、错误定位 | 合法/非法 DSL 各跑通（见 §14.2） |
| M4 ✅ | 三重校验：语法/几何/艺术相似度 + 结构化诊断 | 故意造相似形体被拦（见 §14.3） |
| M5 ✅ | 时序动画、缓动、group 变换、帧序列、ffmpeg 合成、快照(含哈希) | 单镜头 4 秒可循环成片（见 §14.4） |
| M6a ✅ | 预设资产与渲染接入：`style.yaml` v1 扩展、`constraints.yaml`、核心 4 + 扩展 2 约束在渲染器生效、`color_of` 接入 palette、两套官方**手写**预设、**定死 `api.py` 边界** | 官方预设 golden 哈希锁定；约束实测值落入配置区间（见 §14.5） |
| M6b | 风格转录器：三层确定性提取、三档可表达性降档、多图合成、sidecar 证据、AI 单次命名（可降级）、CLI | 同图两次转录 sidecar 逐字段一致；A/B/C 三档命中；极端图（全黑/全白/单色/1×1）不崩且不产出空 palette |
| M6c | 本地 Flask 薄壳（可选 extras `[ui]`）：上传 → 风格卡片 → 滑杆 → SVG 实时预览 → 存预设 | 滑杆拖动下预览确定性；无 AI key 可用 |
| M6d ✅ | Lottie 对接 L0 导出 / L1 导入（原 M6 后半，彻底独立） | 导出可被 Lottie 播放器加载（见 §14.5） |
| M7 | 光栅笔刷渲染器（干笔/飞白/毛涩，自研路径重采样+扰动） | 质感对比图 |
| M8 | 静态构图预览、甘特图、插值曲线可视化 | 预览面板 |
| M9 | 双轨音频、混音限幅、音画联动 | 带声成片 |
| M10 | AI 适配器：四段 prompt + 自纠回灌 + sha 缓存 + 审核闸门 | 全 AI 驱动成片 |

M1→M5 为最小垂直切片，先出一条成片再横向扩。M6a 先做**手写**官方预设，为 M6b 提供 schema 对标基线——转录产物必须能落进同一套 schema，否则说明抽象错了；M6c 依赖 M6b，M6d 可与其他并行。

---

## 14. 可行性证据（spike，全部通过）

代码 `spike/feasibility.py`（约 340 行自包含），产物 `spike/out/boats.{png,svg}`。

| 检验项 | 结果 | 硬证据 |
|---|---|---|
| A 派生式 RNG 稳定 | ✅ | 12 实例中间插入 1 个新实例，其余参数漂移 0 |
| B1 四原语几何有效 | ✅ | 50/50 舟无自相交（shapely `is_valid`） |
| B2 实例差异化 | ✅ | 归一化 Fréchet 1225 对：p05=0.082 / median=0.128；雷同对(<0.05)仅 2 |
| C1 SVG 确定性 | ✅ | 同 seed 两次 sha256 完全一致 |
| C2 PNG 确定性 | ✅ | Skia 两次渲染 byte-identical |

拓扑变体分布（L2）：篷 33 / 桅 17 / 灯 25（共 50）——可选子结构开关有效。
弱点（M2 调参，非架构）：部分船体偏叶形、篷与船体偶悬空。

## 14.1 M2 构件系统证据（已通过，`tests/test_m2.py` 12 项全绿）

产物：`examples/lonely_boat.{png,svg}`（孤舟渡江首片）、`examples/boats_grid.{png,svg}`（构件接触表）。

| 检验项 | 结果 | 硬证据 |
|---|---|---|
| 稀疏 override 不外泄 | ✅ | 单参 override 后，其余参数逐位不变 |
| 改原型 → 全实例同步 | ✅ | 原型 `has_canopy` 概率改恒真 → 无 override 实例全部同步；override 实例仍保留自身值 |
| 值域/类型校验 | ✅ | 越界 / bool 传 float / 缺参 → `ValueError` + 结构化消息 |
| L1+L2 差异化 | ✅ | 50 实例：不同长度值 ≥30、拓扑组合 ≥4、船体首点 x 各异 ≥40 |
| 控制点数恒定（命门 3） | ✅ | 船 8 / 山 9 / 水纹每线 16，30 实例抽查恒定 |
| 几何有效 | ✅ | 50 船体 shapely `Polygon.is_valid` 全过 |
| 确定性 | ✅ | 示例片 SVG/PNG 两次渲染逐字节一致（golden 哈希锁定） |

构件层调参已修：船体轮廓改为「两端上翘、龙骨下沉、甲板近平」（原叶形问题），篷/灯基准对齐甲板。

## 14.2 M3 DSL 证据（已通过，`tests/test_m3.py` 8 项全绿）

产物：`projects/lonely_boat/{project,style,components,timeline}.yaml`、`examples/lonely_boat_cli.{png,svg}`（CLI 渲染）。

| 检验项 | 结果 | 硬证据 |
|---|---|---|
| DSL 与 M2 demo 字节一致 | ✅ | `projects/lonely_boat` 渲染 PNG/SVG 与 `lonely_boat_scene()` 逐字节相同（golden PNG `a4fda813…` / SVG `773b962a…`） |
| 确定性 | ✅ | 同工程两次 `load_project` 渲染一致 |
| 未知构件 | ✅ | `DSLValidationError: [timeline] items[0]: 未注册构件原型 ghost` |
| 参数越界 | ✅ | `构件 boat#b 校验失败: length=9999 越界 [30.0,150.0]` |
| 坏色值 | ✅ | jsonschema 拦截 `color` 不合法 `#ZZZ` |
| 未知原语 | ✅ | jsonschema 拦截 `primitive: blob` |
| 裸原语模式 | ✅ | `primitive: line` 直接构造并渲染 |
| 声明式与引擎不漂移 | ✅ | `components.yaml` 与 `LONELY_BOAT_COMPONENT_SPECS` 逐参数一致（测试守护） |

CLI：`spol render --project projects/lonely_boat --backend skia --out out.png` 已通；`spol init <dir>` 脚手架已就绪。

## 14.3 M4 三重校验证据（已通过，`tests/test_m4.py` 22 项全绿）

| 检验项 | 结果 | 硬证据 |
|---|---|---|
| 几何拓扑 | ✅ | 蝴蝶结自相交 → `GEOM_SELF_INTERSECT`(error)；顶点<3 → error；重复点 → warning 放行；合法方形零误报 |
| 相似度真阳性 | ✅ | 两个近重合方形 → `ART_NEAR_DUPLICATE`（相对距离 0.0183 < 0.06） |
| 相似度尺度自适应 | ✅ | 250px 远山 vs 132px 船体：绝对距离仅 0.0258，**相对**距离 0.33 → 不误报（见下方设计修正） |
| 空间门限 | ✅ | 远处同形重复（≥0.25 对角线）豁免，避免误伤「三重远山」母题 |
| 构图四约束 | ✅ | 满覆盖长方形 → `COMP_LOW_WHITESPACE`；着色叶节点在灰度风格下 → `COMP_COLOR_AREA`；`as_error` 可升级为阻断 |
| 真实缺陷捕获 | ✅ | 校验器抓出远山构建器的退化边（抖动使顶点下潜到闭合边另一侧 → shapely 判自相交），已修（首末钉基线 + 中间点钳制） |

**设计修正记录（重要）**：第二重相似度最初用「绝对签名距离」，在元素变小后绝对距离整体变小，导致 250px 远山与 132px 船体几乎任何差异都 < 阈值而误报。改为 **尺度自适应相对距离**（绝对距离 ÷ 较大一方的 RMS 幅值）后，阈值语义变成「形状差异占自身尺度的比例」，与元素大小解耦。另：开放笔画（水纹/云纹一类**有意重复母题**）默认不参与比较，否则同组 16 点正弦线会互相误报；需严格模式时 `include_lines=True`。

## 14.4 M5 时序动画证据（已通过，`tests/test_m5.py` 23 项全绿）

| 检验项 | 结果 | 硬证据 |
|---|---|---|
| 缓动确定性 | ✅ | 4 种缓动端点严格 0/1、单调；纯多项式无 libm |
| 关键帧轨 | ✅ | 维度/升序校验报错；区间外 hold；线性中点精确 50.0 |
| 变换增量 | ✅ | 绕世界锚点旋转时锚点自身不动；180° 后半径 10px 处误差 < 1e-3 |
| 帧序无关 | ✅ | 正序/逆序求值结果一致（可跳帧渲染） |
| 满环闭合 | ✅ | 首末键同值 → `scene_at(0) == scene_at(duration)` 严格相等 |
| 成片 | ✅ | 6 帧 mp4 产出、`ftyp/moov` 封装正确、宽高奇数时报错 |
| 快照 | ✅ | manifest 中每个 sha256 与落盘 PNG 实际哈希一致 |
| DSL 接入 | ✅ | anim 解析；缺 duration / iid 重复 / 非法通道均结构化定位报错 |

**顺带修复的真实缺陷（关键）**：`core/dmath` 的 Taylor 级数直接作用在归约到 [-π, π] 的角上，`cos(π)` 误差达 **~2.4e-2**（-0.976 而非 -1），180° 旋转会出现可见的尺寸偏差——动画旋转通道一上就暴露。改为「归约 → 象限折叠 → |x| ≤ π/4 小角核函数」后，全定义域误差 ≤ **1.15e-10**，`dcos(π) == -1.0` 精确成立。

## 14.5 M6a 风格预设 + M6d Lottie 证据（已通过，`tests/test_m6.py` 28 + `test_m6_film.py` 12 项全绿）

官方示例片产物：`examples/lonely_boat_film.{mp4,png,svg,json}`、
`examples/lonely_boat_film_manifest.json`、`examples/film_snapshots/`。

| 检验项 | 结果 | 硬证据 |
|---|---|---|
| 灰度预设恒等 | ✅ | `eastern_minimal` 渲染结果与 M3 golden **逐字节相同**（`64de3c73…`）——着色层不改动既有确定性 |
| 彩色预设确定性 | ✅ | `vermilion` 两次渲染逐字节一致；底色换为预设纸色 `#F6F1E7` |
| 三档映射 | ✅ | ink=1→paper、ink=BASE_BREAK→base、ink=0→ink，精度单调 |
| 点染规则 | ✅ | 仅小半径低墨墨点取 `accents[0]`（实测 10px 朱红），月亮/深墨点不误取 |
| 约束接入 | ✅ | 工程在 `eastern_minimal` 下 0 error / 0 warning；把灯染红则 `COMP_COLOR_AREA` 触发 |
| 扩展 2 指纹 | ✅ | 色块数/质心/主轴可重复；8×6 覆盖率直方图长度 48 |
| 预览 | ✅ | `render_preview` 返回 SVG 字符串、确定性、滑杆参数不改原资产；缩略图 720×480 引擎自渲染 |
| 资产 I/O | ✅ | 落盘/回读逐字段相等；`schema_version` 不匹配拒绝落盘；`styles/<id>/` 与内置预设**防漂移测试**守护 |
| Lottie L0 | ✅ | 10 层、可被 python-lottie 解析、两次导出字节一致；动画层逐帧烘焙为 96 个 hold 关键帧 |
| Lottie L1 | ✅ | 回读 22 叶节点，**全部控制点归一化为 24**（命门 3）；几何尺度保持；gzip/tgs 亦可导入 |
| 成片验收 | ✅ | 96 帧 @24fps 1600×900 H.264(yuv420p) 4.000s；**96/96 帧互异**；满环闭合；校验 0 error |

**两处设计修正（重要）**：
1. `color_area` 不能按「有 color 字段的叶节点占比」统计——彩色风格下所有叶节点都会带 color，比值恒为 1，约束失去意义。改为**按色度判定**（RGB 通道极差 > 60 才算彩色；朱砂墨色是暖调，极差仅 17–50，属「墨」不属于「彩」）。
2. 中间关键帧若取正中对称（t=2），smooth 缓动会使 t 与 4-t 姿态完全相同，96 帧只剩 49 个不同画面（运动变成「出去再原路回来」）。改为**不等距中间键**后 96/96 帧互异，运动成为单向缓流，循环仍无缝。

**审查分工**：`make_official_film.py` 只断言几何 / 构图 / 确定性；**成片必须人工过目**（用户 2026-09-28 明确）——动幅手感与叙事节奏不由脚本判定。

## 14.6 故事片「孤舟渡江 · 三幕」证据（已通过，`test_m6_film.py`）

产物：`examples/lonely_boat_story.{mp4,png,svg,json}`、`lonely_boat_story_manifest.json`、
`story_snapshots/`（t=0/2/4/6/8/9.9s 分镜格）。

工程：`projects/lonely_boat_story` —— 10s @30fps = 300 帧，16 个实例（10 构件 + 6 只裸原语归鸟），
16 条实例动画轨 + 3 条相机轨（translate/scale/rotate），风格 `azurite`（石青重彩）。

三幕：I 启程（雾中远山渐显、孤舟自画外入画、相机缓推）→ II 渡江（主舟横穿中景并渐大、月自地平升起、
群鸟横越拉出纵深、相机跟随）→ III 月明（抵达右侧放缓、相机顶点后回稳、雾尽灯明）。

| 检验项 | 结果 | 硬证据 |
|---|---|---|
| 动幅（回归「基本没动」） | ✅ | 主舟自身横移 **1310px = 85% 画布宽**；屏幕空间 -46px → 1311px；半程间画面变化像素 **4.63% / 4.81%** |
| 帧帧互异 | ✅ | **300/300** 帧哈希互不相同 |
| 叙事而非循环 | ✅ | 首末姿态不同（`loop_closed=False`）——叙事片**必须**不闭合，否则等于没有故事 |
| 色彩鲜亮（回归「线色不鲜亮」） | ✅ | 着墨像素平均色度 **67.6**（对比灰度版 1.0）；`azurite` 预设刻意**不设** `color_area_max` |
| 实例级分色 | ✅ | 16 实例全部带 tint；`tint` 四档停靠点使同一实例内仍有 ≥12 级明度层次 |
| 全时长校验 | ✅ | 基准姿态与 t=2.5/5.0/7.5s 四处采样均 **0 error / 0 warning** |
| 成片 | ✅ | 300 帧 @30fps 1600×900 H.264(yuv420p) 10.000s，814 KiB |

**两处引擎能力补齐**（此前做不出「动漫感」，只能靠微调凑）：
1. `camera` 全局镜头（工程级 AnimSet，绕画布中心）。
2. `tint` 实例级色系（替代「全片一个色相」的单一调色板）。

**校验器随之修正**：`validate_project(project, t=None)` 现按**风格 + tint 实际着色后**的叶节点计算构图，
并支持按时刻采样——否则彩色与灰度会算出同一个彩面积，且故事片的构图变化完全不在校验范围内。

---

## 15. 库使用纪律（build vs buy 评估，强制）

- 调用任何第三方库前，**先读其 API 文档/内省实际接口**，禁止盲目 trial-and-error。
- 已决评估（详见 §4 表）：RNG/仿射/缓动/SVG/笔刷/CLI 自研；skia/shapely/pyyaml/jsonschema/imageio-ffmpeg/python-lottie/flask BUY。
- 风格转录（M6b）同理：**BUY Skia 做解码与下采样，BUILD 色卡/构图/质感算法**——不因「要做图像处理」就顺手引入 Pillow/OpenCV。
- 笔刷质感（M7）定位变更：**BUY Skia 做光栅，BUILD 笔刷纹理**（skia-python 未暴露 MakeDiscrete/Dash）。
- Skottie 未暴露 → L1 导入走 python-lottie，不走 Skia。

---

## 16. 工程目录结构（M0 起）

```
Spolvero/
├── pyproject.toml          # 依赖锁版本；extras: [lottie] / [ui] / [dev]
├── SPEC.md
├── README.md
├── src/spolvero/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py              # 薄壳：只解析参数并调用 api.py（UI 零业务逻辑）
│   ├── api.py              # 唯一稳定函数边界（CLI 与 Flask 共用；M6b 签名已定死）
│   ├── core/
│   │   ├── rng.py          # 派生式 RNG
│   │   ├── dmath.py        # 确定性 cos/sin（归约+象限折叠+小角核，误差 ≤1.15e-10）
│   │   ├── primitives.py   # 四原语 frozen 数据类（各含可选 color:#RRGGBB）
│   │   ├── transform.py    # 仿射变换
│   │   ├── component.py    # 构件体系：ParamSpec/Prototype/Instance/Library + PATTERN_REGISTRY
│   │   ├── scene.py        # 场景图拍平（局部 → 世界坐标）
│   │   └── types.py        # Point 等
│   ├── components/         # 构件库（可复用原型 + 内置构建模式）：lonely_boat.py
│   ├── scenes/             # 场景构图（本片实例）：lonely_boat.py
│   ├── render/
│   │   ├── backend.py      # 后端分发
│   │   ├── common.py       # gray_of / color_of（灰度与彩色统一入口）
│   │   ├── svg.py          # 零依赖 SVG 后端
│   │   └── skia.py         # Skia png 后端 + png_to_rgb（H.264 输入）
│   ├── dsl/                # M3：model / schema / parser（声明式工程资产 → 场景图）
│   ├── validation/         # M4：diagnostics / geometry / similarity / composition / validator
│   ├── animation/          # M5：easing / track / film（逐帧求值、mp4、快照）
│   ├── styles/             # M6a：asset / apply / presets / preview / io
│   ├── lottie/             # M6d：export(L0 烘焙) / importer(L1 归一化)
│   ├── transcribe/         # M6b：转录器包（待实现，签名见 api.py）
│   └── ui/                 # M6c（可选 extras [ui]）：Flask 薄壳，仅调用 api.py
├── projects/               # 工程资产（声明式）
│   ├── lonely_boat/        #   静态首片
│   ├── lonely_boat_film/   #   循环片（4s 满环无缝，96 帧）
│   └── lonely_boat_story/  #   故事片（10s 三幕叙事，300 帧，含 camera 与 tint）
├── styles/                 # M6a：可复用风格预设资产 <id>/{style.yaml,constraints.yaml,preview.png}
│   ├── eastern_minimal/    #   东方极简（灰度）
│   ├── vermilion/          #   朱砂点染（彩，克制的点缀）
│   └── azurite/            #   石青重彩（鲜亮，故事片默认；不设 color_area_max）
├── examples/               # 示例片、接触表、成片产出脚本
│   └── make_official_film.py   # 校验→金帧→mp4→Lottie→快照→manifest 一条命令走完
├── spike/                  # 可行性验证（§14）
├── tests/                  # M1–M6 共 110 项
└── .github/workflows/ci.yml   # ubuntu + macos，golden-frame hash
```
