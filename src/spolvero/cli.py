"""Spolvero CLI。

子命令：
  init      工程目录脚手架（M3）
  render    渲染工程目录为图片（M3 基础版；完整管线 M5）
  check     三重校验（M4）
  snapshot  快照存档（M5）
  review    人工审核闸门（M10）
  approve   审核通过（M10）
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
name: eastern_minimal
description: 东方极简符号构成（留白、线条节奏、克制点染）
default_ink: 0.30
grayscale: true
palette:
  ink: "#1a1a1a"
  paper: "#F7F5F0"
  accent: "#9a3b30"
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


def _cmd_render(args: argparse.Namespace) -> int:
    from spolvero.dsl.parser import DSLValidationError, load_project
    from spolvero.render.backend import render

    try:
        proj = load_project(args.project)
    except DSLValidationError as e:
        print(f"DSL 校验失败：{e}")
        return 2

    backend = args.backend
    out = args.out
    if out is None:
        out = os.path.join(args.project, f"render.{'svg' if backend == 'svg' else 'png'}")
    if out.endswith(".svg"):
        backend = "svg"
    elif out.endswith(".png"):
        backend = "skia"

    data = render(
        proj.groups,
        backend=backend,
        width=proj.width,
        height=proj.height,
        bg=proj.background,
    )
    mode = "w" if backend == "svg" else "wb"
    with open(out, mode) as f:
        f.write(data)
    ext = "chars" if backend == "svg" else "bytes"
    print(f"rendered {out} ({len(data)} {ext})  seed={proj.seed}")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    """三重校验（M4）：几何拓扑 / 艺术相似度 / 构图四约束。

    退出码：0 通过（允许含 warning）；1 存在 error（阻断渲染）；2 DSL 非法。
    --json 输出结构化 Issue 列表，供 AI 自纠闭环回灌（SPEC §8 / §11）。
    """
    import json

    from spolvero.dsl.parser import DSLValidationError, load_project
    from spolvero.validation.validator import validate_project

    try:
        proj = load_project(args.project)
    except DSLValidationError as e:
        print(f"DSL 校验失败：{e}")
        return 2

    report = validate_project(proj)
    if args.json:
        print(json.dumps([i.to_dict() for i in report.issues], ensure_ascii=False, indent=2))
    else:
        print(report.render_text())
    return 0 if report.passed else 1


def _cmd_snapshot(_args: argparse.Namespace) -> int:
    print("snapshot: (stub) 快照存档待 M5 实现")
    return 0


_COMMANDS = {
    "init": _cmd_init,
    "render": _cmd_render,
    "check": _cmd_check,
    "snapshot": _cmd_snapshot,
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="spol",
        description="Spolvero — Symbol Composition Animator（矢量动画确定性编译层）",
    )
    p.add_argument("--version", action="version", version=f"spolvero {__version__}")
    sub = p.add_subparsers(dest="cmd")

    pi = sub.add_parser("init", help="工程目录脚手架")
    pi.add_argument("dir", help="目标工程目录")
    pi.add_argument("--seed", default=None, help="全局随机种子")
    pi.add_argument("--force", action="store_true", help="覆盖已存在文件")

    pr = sub.add_parser("render", help="渲染工程目录为图片")
    pr.add_argument("--project", required=True, help="工程目录（含 project.yaml 等）")
    pr.add_argument("--backend", default="skia", choices=["svg", "skia"])
    pr.add_argument("--out", default=None, help="输出文件路径（.svg/.png）")

    pc = sub.add_parser("check", help="三重校验（几何/相似度/构图）")
    pc.add_argument("--project", required=True, help="工程目录")
    pc.add_argument("--json", action="store_true", help="输出结构化 Issue JSON（供自纠回灌）")

    sub.add_parser("snapshot")

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd is None:
        parser.print_help()
        return 0
    return _COMMANDS[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
