"""产出「孤舟渡江」官方示例片（M4–M6 验收脚本，可反复重跑）。

一条命令走完交付链：
    校验 → 金帧(PNG/SVG) → H.264 成片 → Lottie L0 导出 → 关键帧快照 → manifest

用法：  python examples/make_official_film.py
产物：  examples/lonely_boat_film.{mp4,json,png,svg}
        examples/lonely_boat_film_manifest.json
        examples/film_snapshots/t*.png + manifest.json

设计说明：脚本本身不含业务逻辑，全部经 `spolvero.api` 边界调用——
与 CLI、未来的 Flask 界面走同一条路径（SPEC §3 派生约束「UI 层零业务逻辑」）。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from spolvero.api import (  # noqa: E402
    check_project,
    encode_film,
    export_lottie,
    get_style,
    load_project,
    render_project,
    snapshot_frames,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = os.path.join(ROOT, "projects", "lonely_boat_film")
EXAMPLES = os.path.join(ROOT, "examples")
STYLE_ID = "eastern_minimal"
KEY_TIMES = (0.0, 1.0, 2.0, 3.0)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main() -> int:
    os.makedirs(EXAMPLES, exist_ok=True)
    proj = load_project(PROJECT)
    style = get_style(STYLE_ID, os.path.join(ROOT, "styles"))
    assert style is not None, f"未找到风格预设 {STYLE_ID}"

    print("=" * 72)
    print(f"Spolvero 官方示例片 · {os.path.basename(PROJECT)}")
    print(f"  seed={proj.seed}  {proj.width}x{proj.height}  {proj.fps}fps  "
          f"{proj.duration}s  style={style.id}  实例={len(proj.groups)}  动画轨={len(proj.anims)}")
    print("=" * 72)

    # ── 1. 三重校验（error 必须为 0）──
    report = check_project(proj)
    print("\n[1/6] 三重校验")
    print("      " + report.render_text().replace("\n", "\n      "))
    if not report.passed:
        print("  ✗ 校验未通过，中止交付")
        return 1

    # ── 2. 金帧 ──
    print("\n[2/6] 金帧（t=0）")
    frame_png = render_project(proj, "skia", style=style)
    frame_svg = render_project(proj, "svg", style=style)
    p_png = os.path.join(EXAMPLES, "lonely_boat_film.png")
    p_svg = os.path.join(EXAMPLES, "lonely_boat_film.svg")
    with open(p_png, "wb") as f:
        f.write(frame_png)
    with open(p_svg, "w", encoding="utf-8") as f:
        f.write(frame_svg)
    print(f"      {p_png}  {len(frame_png)} bytes  sha256={_sha(frame_png)[:24]}…")
    print(f"      {p_svg}  {len(frame_svg)} chars  sha256={_sha(frame_svg.encode())[:24]}…")

    # ── 3. 成片 ──
    print("\n[3/6] H.264 成片")
    mp4 = os.path.join(EXAMPLES, "lonely_boat_film.mp4")
    film = encode_film(proj, mp4, style=style)
    print(f"      {film['path']}")
    print(f"      {film['frames']} 帧 @ {film['fps']}fps  {film['size'][0]}x{film['size'][1]}  "
          f"{film['bytes'] / 1024:.0f} KiB  时长 {film['duration']:.3f}s")
    print(f"      首帧(i=0, t=0.000s)  sha256={film['first_frame_hash'][:24]}…")
    print(f"      末帧(i={film['frames'] - 1}, t={film['duration'] - 1 / film['fps']:.3f}s)  "
          f"sha256={film['last_frame_hash'][:24]}…")
    print(f"      ⚠ 末帧≠首帧是按帧序自然结果：末帧取 i=n-1，不含重复的 t=duration。")
    print(f"      满环闭合（t=duration 姿态 == t=0 姿态，故播放器回卷无缝）= {film['loop_closed']}")

    # ── 4. Lottie L0 ──
    print("\n[4/6] Lottie L0 导出")
    lot = os.path.join(EXAMPLES, "lonely_boat_film.json")
    linfo = export_lottie(proj, lot, style=style)
    print(f"      {linfo['path']}  layers={linfo['layers']}  frames={linfo['frames']}  "
          f"{linfo['bytes'] / 1024:.0f} KiB")

    # ── 5. 关键帧快照 ──
    print("\n[5/6] 关键帧快照")
    snap = snapshot_frames(proj, os.path.join(EXAMPLES, "film_snapshots"), KEY_TIMES,
                           style=style, label="lonely_boat_film")
    for fr in snap["frames"]:
        print(f"      t={fr['t']:.1f}s  {fr['file']}  sha256={fr['sha256'][:16]}…")

    # ── 6. manifest ──
    print("\n[6/6] manifest")
    manifest = {
        "project": os.path.relpath(PROJECT, ROOT).replace("\\", "/"),
        "seed": proj.seed,
        "style": style.id,
        "size": [proj.width, proj.height],
        "fps": proj.fps,
        "duration": proj.duration,
        "frames": film["frames"],
        "loop_closed": film["loop_closed"],
        "validation": {
            "passed": report.passed,
            "errors": len(report.errors()),
            "warnings": len(report.warnings()),
        },
        "artifacts": {
            "film": {"file": "lonely_boat_film.mp4", "bytes": film["bytes"]},
            "lottie": {"file": "lonely_boat_film.json", "layers": linfo["layers"],
                       "bytes": linfo["bytes"]},
            "frame_png": {"file": "lonely_boat_film.png", "sha256": _sha(frame_png)},
            "frame_svg": {"file": "lonely_boat_film.svg", "sha256": _sha(frame_svg.encode())},
            "snapshots": snap["frames"],
        },
        "first_frame_hash": film["first_frame_hash"],
        "last_frame_hash": film["last_frame_hash"],
    }
    man = os.path.join(EXAMPLES, "lonely_boat_film_manifest.json")
    with open(man, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"      {man}")

    print("\n" + "=" * 72)
    print("交付完成：校验 0 error，成片满环闭合。")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
