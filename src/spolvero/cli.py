"""Spolvero CLI（薄壳：只解析参数并调用 `api.py`，零业务逻辑）。

子命令：
  init      工程目录脚手架（M3）
  render    渲染工程为单帧图片（M3）
  check     三重校验：几何 / 相似度 / 构图（M4）
  film      渲染全片并合成 MP4（M5）
  snapshot  关键帧快照 + manifest（M5）
  style     风格预设资产管理：list / show / preview / export（M6a）
  lottie    Lottie 对接：export（L0）/ import（L1）（M6d）
"""

from __future__ import annotations

import argparse
import os

from spolvero import __version__

INIT_PROJECT = """\
# Spolvero 工程配置
seed: {seed}
width: 1600
height: 900
fps: 30
style: eastern_minimal
background: "#F7F5F0"
"""

INIT_STYLE = """\
schema_version: 1
id: eastern_minimal
name: eastern_minimal
description: 东方极简符号构成（留白、线条节奏、克制点染）
default_ink: 0.30
grayscale: true
"""

INIT_COMPONENTS = """\
# 构件库定义（声明式资产）。引用引擎内置 pattern；可自行追加。
# 示例（孤舟渡江首片构件，取消注释即可用）：
# - name: boat
#   pattern: boat
#   params:
#     - {name: length, default: 64.0, lo: 30.0, hi: 150.0, kind: float}
#     - {name: hull_ink, default: 0.32, lo: 0.10, hi: 0.85, kind: float}
#     - {name: has_canopy, default: true, kind: bool, p_true: 0.66}
"""

INIT_TIMELINE = """\
# 时序层：构件实例与裸原语。
items: []
"""


# ───────────────────────── init ─────────────────────────
def _cmd_init(args: argparse.Namespace) -> int:
    d = args.dir
    os.makedirs(d, exist_ok=True)
    seed = args.seed or "spolvero-project-v1"
    files = {
        "project.yaml": INIT_PROJECT.format(seed=seed),
        "style.yaml": INIT_STYLE,
        "components.yaml": INIT_COMPONENTS,
        "timeline.yaml": INIT_TIMELINE,
    }
    for name, content in files.items():
        path = os.path.join(d, name)
        if os.path.exists(path) and not args.force:
            print(f"skip 已存在: {path}（用 --force 覆盖）")
            continue
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"write {path}")
    print(f"工程已脚手架化于 {d}（参考 projects/lonely_boat 填写构件与实例）")
    return 0


# ───────────────────────── 公共 ─────────────────────────
def _load_or_fail(project_dir: str):
    from spolvero.api import load_project
    from spolvero.dsl.parser import DSLValidationError

    try:
        return load_project(project_dir)
    except DSLValidationError as e:
        print(f"DSL 校验失败：{e}")
        return None


def _resolve_style(style_id):
    if not style_id:
        return None
    from spolvero.api import get_style

    a = get_style(style_id)
    if a is None:
        print(f"未知风格预设: {style_id}（用 `spol style list` 查看可用项）")
    return a


def _write(path: str, data) -> None:
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    if isinstance(data, str):
        with open(path, "w", encoding="utf-8") as f:
            f.write(data)
    else:
        with open(path, "wb") as f:
            f.write(data)


def _parse_size(s: str):
    parts = str(s).lower().replace(" ", "").split("x")
    if len(parts) != 2:
        raise SystemExit(f"--size 需形如 720x480，收到 {s!r}")
    return int(parts[0]), int(parts[1])


# ───────────────────────── render ─────────────────────────
def _cmd_render(args: argparse.Namespace) -> int:
    from spolvero.api import render_project

    proj = _load_or_fail(args.project)
    if proj is None:
        return 2
    style = _resolve_style(args.style or proj.style)

    out = args.out or os.path.join(args.project, "render.svg")
    if out.endswith(".svg"):
        backend = "svg"
    elif out.endswith(".png"):
        backend = "skia"
    else:
        backend = args.backend
        out = f"{out}.{'svg' if backend == 'svg' else 'png'}"

    data = render_project(proj, backend=backend, style=style)
    _write(out, data)
    tag = f" style={style.id}" if style else ""
    print(
        f"rendered {out} ({len(data)} {'chars' if backend == 'svg' else 'bytes'})"
        f"  seed={proj.seed}{tag}"
    )
    return 0


# ───────────────────────── check ─────────────────────────
def _cmd_check(args: argparse.Namespace) -> int:
    import json

    from spolvero.api import check_project

    proj = _load_or_fail(args.project)
    if proj is None:
        return 2

    report = check_project(proj)
    if args.json:
        print(json.dumps([i.to_dict() for i in report.issues], ensure_ascii=False, indent=2))
    else:
        print(report.render_text())
    return 0 if report.passed else 1


# ───────────────────────── film ─────────────────────────
def _cmd_film(args: argparse.Namespace) -> int:
    from spolvero.api import encode_film

    proj = _load_or_fail(args.project)
    if proj is None:
        return 2
    style = _resolve_style(args.style or proj.style)
    if proj.duration <= 0:
        print("工程未定义 duration（project.yaml 里写 duration: <秒>），无法成片")
        return 2

    out = args.out or os.path.join(args.project, "film.mp4")
    info = encode_film(proj, out, style=style, fps=args.fps, duration=args.duration, crf=args.crf)
    print(
        f"film {info['path']}  {info['frames']} 帧 @ {info['fps']}fps  "
        f"{info['size'][0]}x{info['size'][1]}  {info['bytes'] / 1024:.0f} KiB  "
        f"循环闭合={info['loop_closed']}"
    )
    print(
        f"  first_frame={info['first_frame_hash'][:16]}…  "
        f"last_frame={info['last_frame_hash'][:16]}…"
    )
    return 0


# ───────────────────────── snapshot ─────────────────────────
def _cmd_snapshot(args: argparse.Namespace) -> int:
    from spolvero.api import snapshot_frames

    proj = _load_or_fail(args.project)
    if proj is None:
        return 2
    style = _resolve_style(args.style or proj.style)
    times = [float(x) for x in str(args.times).split(",") if x.strip() != ""]
    out = args.out or os.path.join(args.project, "snapshots")
    manifest = snapshot_frames(proj, out, times, style=style, label=args.label)
    print(f"snapshot -> {out}  {len(manifest['frames'])} 帧  label={manifest['label']}")
    for fr in manifest["frames"]:
        print(f"  t={fr['t']:.3f}  {fr['file']}  {fr['sha256'][:16]}…")
    return 0


# ───────────────────────── style ─────────────────────────
def _cmd_style(args: argparse.Namespace) -> int:
    import json

    from spolvero.api import list_styles, render_preview, render_preview_png, save_style
    from spolvero.styles import get_style as _get

    root = args.root
    if args.style_cmd == "list":
        assets = list_styles(root)
        if not assets:
            print(f"（{root}/ 下暂无预设，且无内置预设）")
            return 0
        for a in assets:
            print(a.summary())
            if a.description:
                print(f"    {a.description}")
        return 0

    if args.style_cmd == "show":
        a = _get(args.id, root)
        if a is None:
            print(f"未知风格: {args.id}")
            return 2
        print(json.dumps({"style": a.style_dict(), "constraints": a.constraints_dict()},
                         ensure_ascii=False, indent=2))
        return 0

    if args.style_cmd == "preview":
        a = _get(args.id, root)
        if a is None:
            print(f"未知风格: {args.id}")
            return 2
        w, h = _parse_size(args.size)
        out = args.out or os.path.join(root, a.id, "preview.svg")
        if out.endswith(".png"):
            _write(out, render_preview_png(a, size=(w, h)))
        else:
            _write(out, render_preview(a, size=(w, h)))
        print(f"preview {a.id} -> {out}")
        return 0

    if args.style_cmd == "export":
        # 必须导**引擎内置基线**，不能走 list_styles——list_styles 会让 styles/ 里的落盘版
        # 覆盖同 id 的内置版，于是"导出"只是把旧文件原样写回，新预设永远出不来（自我循环）。
        from spolvero.styles.presets import builtin_styles

        n = 0
        for sid, a in sorted(builtin_styles().items()):
            if args.id and args.id != sid:
                continue
            save_style(a, root)
            print(f"wrote {root}/{sid}/style.yaml, constraints.yaml, preview.png")
            n += 1
        print(f"导出 {n} 套内置预设到 {root}/")
        return 0 if n else 2

    return 2


# ───────────────────────── lottie ─────────────────────────
def _cmd_lottie(args: argparse.Namespace) -> int:
    if args.lottie_cmd == "export":
        from spolvero.api import export_lottie

        proj = _load_or_fail(args.project)
        if proj is None:
            return 2
        style = _resolve_style(args.style or proj.style)
        out = args.out or os.path.join(args.project, "film.json")
        info = export_lottie(proj, out, style=style)
        print(
            f"lottie {out}  layers={info['layers']}  {info['frames']} 帧  "
            f"{info['size'][0]}x{info['size'][1]}  {info['bytes'] / 1024:.0f} KiB"
        )
        return 0

    if args.lottie_cmd == "import":
        from spolvero.api import import_lottie
        from spolvero.core.scene import flatten_all
        from spolvero.render.backend import render

        try:
            nodes = import_lottie(args.path)
        except Exception as e:  # noqa: BLE001 — 导入失败需给用户可读信息
            print(f"Lottie 导入失败：{e}")
            return 2
        out = args.out or os.path.splitext(args.path)[0] + ".png"
        _write(out, render(nodes, backend="skia"))
        print(f"imported {args.path} -> {out}  nodes={len(nodes)} leaves={len(flatten_all(nodes))}")
        return 0

    return 2


_COMMANDS = {
    "init": _cmd_init,
    "render": _cmd_render,
    "check": _cmd_check,
    "film": _cmd_film,
    "snapshot": _cmd_snapshot,
    "style": _cmd_style,
    "lottie": _cmd_lottie,
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="spol",
        description="Spolvero — 判据驱动的确定性动画工作台（人机交互入口：spol studio）",
    )
    p.add_argument("--version", action="version", version=f"spolvero {__version__}")
    sub = p.add_subparsers(dest="cmd")

    pi = sub.add_parser("init", help="工程目录脚手架")
    pi.add_argument("dir", help="目标工程目录")
    pi.add_argument("--seed", default=None, help="全局随机种子")
    pi.add_argument("--force", action="store_true", help="覆盖已存在文件")

    pr = sub.add_parser("render", help="渲染工程为单帧图片")
    pr.add_argument("--project", required=True)
    pr.add_argument("--backend", default="skia", choices=["svg", "skia"])
    pr.add_argument("--out", default=None, help="输出路径（.svg/.png）")
    pr.add_argument("--style", default=None, help="风格预设 id（默认为工程 style 字段）")

    pc = sub.add_parser("check", help="三重校验（几何/相似度/构图）")
    pc.add_argument("--project", required=True)
    pc.add_argument("--json", action="store_true", help="输出结构化 Issue JSON（供自纠回灌）")

    pf = sub.add_parser("film", help="渲染全片并合成 MP4")
    pf.add_argument("--project", required=True)
    pf.add_argument("--out", default=None)
    pf.add_argument("--style", default=None)
    pf.add_argument("--fps", type=int, default=None)
    pf.add_argument("--duration", type=float, default=None)
    pf.add_argument("--crf", type=int, default=18)

    ps = sub.add_parser("snapshot", help="关键帧快照 + manifest")
    ps.add_argument("--project", required=True)
    ps.add_argument("--out", default=None)
    ps.add_argument("--times", default="0", help="逗号分隔的时刻（秒）")
    ps.add_argument("--style", default=None)
    ps.add_argument("--label", default="")

    pst = sub.add_parser("style", help="风格预设资产管理")
    pst.add_argument("--root", default="styles")
    ssub = pst.add_subparsers(dest="style_cmd")
    ssub.add_parser("list", help="列出可用预设")
    ss = ssub.add_parser("show", help="打印预设 YAML/JSON")
    ss.add_argument("id")
    sp = ssub.add_parser("preview", help="渲染预设缩略图（.png 或 .svg）")
    sp.add_argument("id")
    sp.add_argument("--out", default=None)
    sp.add_argument("--size", default="720x480")
    se = ssub.add_parser("export", help="把内置预设导出到 styles/")
    se.add_argument("--id", default=None, help="仅导出指定 id")

    pl = sub.add_parser("lottie", help="Lottie 对接（L0 导出 / L1 导入）")
    lsub = pl.add_subparsers(dest="lottie_cmd")
    le = lsub.add_parser("export", help="DSL 工程 → Lottie JSON")
    le.add_argument("--project", required=True)
    le.add_argument("--out", default=None)
    le.add_argument("--style", default=None)
    li = lsub.add_parser("import", help="Lottie JSON → 四原语场景 → 渲染")
    li.add_argument("path")
    li.add_argument("--out", default=None)

    pst2 = sub.add_parser("studio", help="启动 Web 控制台（人机交互的唯一入口）")
    pst2.add_argument("--host", default="127.0.0.1")
    pst2.add_argument("--port", type=int, default=8760)
    pst2.add_argument("--debug", action="store_true")

    pj = sub.add_parser("judge", help="跑影片工程包的判据（结构层 + 构成层）")
    pj.add_argument("film", help="工程包 id，如 laoshan")
    pj.add_argument("--scope", default="full", choices=["static", "sound", "full"],
                    help="static 秒级（不含逐幕重项）；sound 含声音三条；full 全跑")

    return p


def _cmd_studio(args) -> int:
    from .webapp.app import main as studio_main
    return studio_main(host=args.host, port=args.port, debug=args.debug)


def _cmd_judge(args) -> int:
    from .webapp import judges as J
    r = J.run(args.film, scope=args.scope,
              progress=lambda d, t, n: print(f"  [{d}/{t}] {n}", flush=True))
    s = r["summary"]
    print(f"\n通过 {s['pass']} · 警告 {s['warn']} · 失败 {s['fail']} · 未实现 {s['skip']}"
          f"（{r['elapsed_s']}s / {r['renders']} 帧）")
    for i in r["items"]:
        if i["status"] in ("fail", "warn"):
            print(f"  [{i['status']}] {i['id']} {i['name']} —— {i['detail']}")
    return 1 if s["fail"] else 0


_COMMANDS["studio"] = _cmd_studio
_COMMANDS["judge"] = _cmd_judge


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd is None:
        parser.print_help()
        return 0
    return _COMMANDS[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
