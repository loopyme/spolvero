# Spolvero · 工程规范（SPEC）

> Symbol Composition Animator — 矢量动画的确定性编译层
> 本文件是 Spolvero 的权威工程规范。所有代码、DSL、CI、文档以本文件为基准。
> 状态：可行性已 spike 验证（§14），M0–M3 已完成（25 项测试全绿），下一步 M4 三重校验。

---

## 0. 与原始需求文档的关系

原始《SymbolCompose Animator 项目官方需求文档》（用户与豆包对话产出）是**愿景与红线来源**。本 SPEC 是经可行性验证后的**落地约束**，对原始文档有 4 处修正（§2）与 3 条技术命门（§3），并补全了原始文档缺失的工程细节（确定性分级、Lottie 定位、AI 层闭环、API 实测结论）。

---

## 1. 项目身份与生态位

- **名称**：Spolvero（CLI 短名 `spol`；长名 Symbol Composition Animator）
- **命名考据**：spolvero 是文艺复兴壁画标准工序——把全尺寸设计稿（cartoon）沿轮廓扎针孔，用炭粉袋扑打，粉末透过针孔在湿灰泥上留下**点状轮廓线**作绘制引导。唐代敦煌莫高窟已有实物证据。与本项目工作逻辑同构：cartoon=构件原型、针孔=参数化控制点、扑粉转印=实例化、一稿多印=模板复用、转印后手改=实例 override、点状轮廓=`ink_dot`。
- **一句话定位**：矢量动画的**确定性编译层**。
- **生态位**：上游吃模型（OmniLottie）/ LottieFiles / SVG 素材，下游吐 Lottie / SVG / MP4；独占**构件原型 + 实例差分 + 构图校验**这段确定性约束层，模型越发达越需要它。不做模型、不竞争产生，只做收敛与交付。

---

## 2. 对原始需求文档的 4 处修正（已决）

| # | 原文 | 问题 | 本 SPEC 决策 |
|---|---|---|---|
| 1 | 校验不通过禁止渲染 | 与"自由拓展"冲突，实用中反复卡死 | 分级 `error`（阻断）/ `warning`（放行+报告），阈值写在工程配置，可配 |
| 2 | 禁止 LLM 生成代码/SVG | 只说禁、没给替代闭环 | LLM 唯一输出契约＝**结构化 DSL/资产**；校验诊断结构化回灌 LLM 自纠（§11） |
| 3 | 第八节音频 | 工作量被严重低估 | 首版只做时序轨 + 触发事件，出声后置 M9 |
| 4 | 全局线条质感（干笔/飞白/毛涩） | 纯矢量画不出"墨" | 独立光栅笔刷模块（M7）；**实测 skia-python 未暴露 `PathEffect.MakeDiscrete/MakeDash`，须自研路径重采样+扰动实现**，非白送 |

---

## 3. 永久架构红线（原始 11 条 + 3 条技术命门 + 1 条派生约束）

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

**派生约束（spike 实测暴露，原始文档缺失）**
- **布局坐标必须是 `(seed, instance_id)` 的纯函数**，绝不依赖数组顺序/索引。首版 A 测试用列表索引算网格坐标 → 插入实例后后续坐标全变（误报 FAIL），修正后漂移归零。真实引擎中实例自带 transform，场景图增删不打扰其他节点。

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
| `python-lottie` | `>=0.9`（M6 起） | Lottie 导入解析 | BUY（L1 导入用） |

**自研模块（不引库）**：派生 RNG、仿射变换、缓动曲线、SVG 后端、笔刷质感、CLI（stdlib `argparse`）。

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
project.yaml    seed / width / height / fps / style / background(#RRGGBB)
style.yaml      name / description / default_ink / grayscale / palette{#RRGGBB 调色板}
components.yaml  [ {name, pattern, params:[{name,default,lo,hi,kind,p_true}]} ]  ← 构件*定义*为声明式资产
timeline.yaml   items: [ {component,iid,overrides,transform} | {primitive,iid,points/ring/pos,...} ]
```

- **构件以 `pattern` 键引用引擎内置构建模式**（`core/component.PATTERN_REGISTRY`），AI 只产出声明式 `components.yaml`（参数表 + pattern 键），**绝不持有构建代码**——既满足红线性（§3 红线 6），又让构件定义成为可 diff / 可版本化的资产。
- **裸原语模式**：`primitive: line|shape|dot` 直接声明四原语之一，`points/ring/pos` 为绝对坐标，可选 `color: #RRGGBB`。
- **颜色支持（按用户要求就绪，主题场景后续接入）**：四原语均有可选 `color` 字段（`#RRGGBB`），渲染时优先于 `ink` 灰度（`render/common.color_of`）；首片仍为灰度，彩色主题经 `style.palette` 着色后续接入。架构已打通，无需改数据模型。

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
| L0 导出 | DSL → Lottie / dotLottie JSON（烘焙结果，丢参数化） | 做（M6） | 自研 DSL→Lottie 序列化 |
| L1 导入 | Lottie / SVG → 构件原型 | 做（M6） | **python-lottie 解析 → shapely 几何化 → 控制点归一化 → 四原语**（Skia Skottie 未暴露，非走 Skia） |
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
| M4 | 三重校验：语法/几何/艺术相似度 + 结构化诊断 | 故意造相似形体被拦 |
| M5 | 时序动画、缓动、group 变换、帧序列、ffmpeg 合成、快照(含哈希) | 单镜头 4 秒可循环成片 |
| M6 | 风格预设插件、两套官方风格、留白/彩面积/密度/堆积四约束、Lottie L0/L1 | 官方示例片达标 |
| M7 | 光栅笔刷渲染器（干笔/飞白/毛涩，自研路径重采样+扰动） | 质感对比图 |
| M8 | 静态构图预览、甘特图、插值曲线可视化 | 预览面板 |
| M9 | 双轨音频、混音限幅、音画联动 | 带声成片 |
| M10 | AI 适配器：四段 prompt + 自纠回灌 + sha 缓存 + 审核闸门 | 全 AI 驱动成片 |

M1→M5 为最小垂直切片，先出一条成片再横向扩。

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

---

## 15. 库使用纪律（build vs buy 评估，强制）

- 调用任何第三方库前，**先读其 API 文档/内省实际接口**，禁止盲目 trial-and-error。
- 已决评估（详见 §4 表）：RNG/仿射/缓动/SVG/笔刷/CLI 自研；skia/shapely/pyyaml/jsonschema/imageio-ffmpeg/python-lottie BUY。
- 笔刷质感（M7）定位变更：**BUY Skia 做光栅，BUILD 笔刷纹理**（skia-python 未暴露 MakeDiscrete/Dash）。
- Skottie 未暴露 → L1 导入走 python-lottie，不走 Skia。

---

## 16. 工程目录结构（M0 起）

```
Spolvero/
├── pyproject.toml
├── SPEC.md
├── README.md
├── src/spolvero/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── core/
│   │   ├── rng.py          # 派生式 RNG
│   │   ├── dmath.py        # 确定性 cos/sin（不碰 libm）
│   │   ├── primitives.py   # 四原语 frozen 数据类（各含可选 color:#RRGGBB）
│   │   ├── transform.py    # 仿射变换
│   │   ├── component.py    # 构件体系：ParamSpec/Prototype/Instance/Library + PATTERN_REGISTRY
│   │   └── types.py        # Point 等
│   ├── components/         # 构件库（可复用原型 + 内置构建模式）：lonely_boat.py
│   ├── scenes/             # 场景构图（本片实例）：lonely_boat.py
│   ├── render/
│   │   ├── backend.py      # 后端分发
│   │   ├── common.py       # gray_of / color_of（灰度与彩色统一入口）
│   │   ├── svg.py          # 零依赖 SVG 后端
│   │   └── skia.py         # Skia png 后端
│   ├── dsl/                # M3：model / schema / parser（声明式工程资产 → 场景图）
│   └── ...
├── projects/               # 工程资产（声明式）：lonely_boat/{project,style,components,timeline}.yaml
├── examples/               # 示例片与接触表
├── tests/
└── .github/workflows/ci.yml   # ubuntu + macos，golden-frame hash
```
