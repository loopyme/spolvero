# AGENT.md — Spolvero (for AI coding agents / WorkBuddy)

This file is written **for other AI agents** that assist a user in making animated
videos with Spolvero. It tells you how the project is structured, which path is
reliable, how to write a programmatic scene script, and how to help the user debug.

> Spolvero is a **deterministic symbolic-composition animator**. You compose a scene
> from primitive ink shapes (dots / lines / polygons) and component prototypes, then
> either render a still or encode an MP4. Randomness is derived from `(seed, iid)`,
> never from a mutable RNG stream — same inputs always produce the same frames.

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
