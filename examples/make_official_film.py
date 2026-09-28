"""产出 Spolvero 官方示例片（M4–M6 验收脚本，可反复重跑）。

一次交付两件，分工明确：

  A. 故事片 `lonely_boat_story`  —— 10s @30fps，300 帧，石青重彩。**三幕叙事，非循环**：
       主舟自画外入画、横穿近整幅画布；群鸟横越拉出纵深；相机绕画布中心推轨 0.92→1.09→1.04。
       这是「像动漫一样讲故事」的那一件。
  B. 循环片 `lonely_boat_film`   —— 4s @24fps，96 帧，东方极简灰度。满环无缝，
       用来证明引擎的**确定性循环**能力。

每条链都走：校验 → 金帧 → H.264 → Lottie L0 → 关键帧/分镜格 → manifest。
全部经 `spolvero.api` 调用——与 CLI、未来的 Flask 界面同一条路径（SPEC §3 派生约束）。

用法：  python examples/make_official_film.py
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
from spolvero.validation.validator import validate_project  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, "examples")

# (工程目录名, 产物前缀, 风格, 海报帧时刻, 分镜格时刻, 是否循环片)
JOBS = [
    ("lonely_boat_story", "lonely_boat_story", "azurite", 7.0,
     (0.7, 1.5, 2.4, 3.4, 5.0, 7.0, 9.9), False),
    ("lonely_boat_film", "lonely_boat_film", "eastern_minimal", 0.0,
     (0.0, 1.0, 2.0, 3.0), True),
]

# 故事片检查的采样时刻：构图会随镜头变化，只卡基准姿态没有意义
CHECK_TIMES = (None, 2.5, 5.0, 7.5)


def _sha(b) -> str:
    raw = b.encode("utf-8") if isinstance(b, str) else b
    return hashlib.sha256(raw).hexdigest()


def render_svg_frame(project, t: float, style) -> str:
    """SVG 海报帧：走 api 的着色/取景逻辑，但 SVG 后端不加光栅质感层（见 render.backend 说明）。"""
    from spolvero.api import _bg_of, _styled_groups
    from spolvero.render.backend import render

    return render(
        _styled_groups(project, style, t),
        backend="svg",
        width=int(project.width),
        height=int(project.height),
        bg=_bg_of(project, style),
    )


def _check_across_time(proj) -> dict:
    rows = []
    total_e = total_w = 0
    for t in CHECK_TIMES:
        rep = validate_project(proj, t)
        rows.append({
            "t": t,
            "passed": rep.passed,
            "errors": len(rep.errors()),
            "warnings": len(rep.warnings()),
            "issues": [i.to_dict() for i in rep.issues],
        })
        total_e += len(rep.errors())
        total_w += len(rep.warnings())
    return {"samples": rows, "errors": total_e, "warnings": total_w, "passed": total_e == 0}


def _run_job(dirname: str, prefix: str, style_id: str, poster_t: float,
             key_times, is_loop: bool) -> dict:
    project_dir = os.path.join(ROOT, "projects", dirname)
    proj = load_project(project_dir)
    style = get_style(style_id, os.path.join(ROOT, "styles"))
    assert style is not None, f"未找到风格预设 {style_id}"

    kind = "循环片" if is_loop else "故事片"
    print("\n" + "=" * 78)
    print(f"【{kind}】{dirname}")
    print(f"  seed={proj.seed}  {proj.width}x{proj.height}  {proj.fps}fps  {proj.duration}s  "
          f"style={style.id}({style.name})")
    print(f"  实例={len(proj.groups)}  动画轨={len(proj.anims)}  实例色调={len(proj.tints)}  "
          f"相机轨={len(getattr(proj.camera, 'tracks', ()) or ())}  "
          f"帧数={int(round(proj.duration * proj.fps))}")
    print("=" * 78)

    # 1. 校验（沿时间采样）
    chk = _check_across_time(proj)
    print(f"\n[1/6] 三重校验  (采样 t = {', '.join('base' if r['t'] is None else str(r['t']) for r in chk['samples'])})")
    for r in chk["samples"]:
        tag = "base" if r["t"] is None else f"t={r['t']}s"
        print(f"      {tag:8s} {'通过' if r['passed'] else '未通过'}  "
              f"{r['errors']} error / {r['warnings']} warning")
        for i in r["issues"]:
            print(f"        - {i['severity']} {i['code']}: {i['message']}")
    if not chk["passed"]:
        print("  ✗ 存在 error，中止该片交付")

    # 2. 海报帧（挑叙事最强的一刻）
    print(f"\n[2/6] 海报帧 t={poster_t}s")
    from spolvero.api import render_frame_at

    poster_png = render_frame_at(proj, poster_t, "skia", style)
    poster_svg = render_svg_frame(proj, poster_t, style)
    png_path = os.path.join(EXAMPLES, f"{prefix}.png")
    svg_path = os.path.join(EXAMPLES, f"{prefix}.svg")
    with open(png_path, "wb") as f:
        f.write(poster_png)
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(poster_svg)
    print(f"      {png_path}  {len(poster_png)} bytes  sha256={_sha(poster_png)[:24]}…")
    print(f"      {svg_path}  {len(poster_svg)} chars")

    # 3. 成片
    print("\n[3/6] H.264 成片")
    mp4 = os.path.join(EXAMPLES, f"{prefix}.mp4")
    film = encode_film(proj, mp4, style=style)
    print(f"      {film['path']}")
    print(f"      {film['frames']} 帧 @ {film['fps']}fps  {film['size'][0]}x{film['size'][1]}  "
          f"{film['bytes'] / 1024:.0f} KiB  时长 {film['duration']:.3f}s")
    print(f"      首帧 sha256={film['first_frame_hash'][:24]}…")
    print(f"      末帧({film['frames'] - 1}, t={film['duration'] - 1 / film['fps']:.3f}s) "
          f"sha256={film['last_frame_hash'][:24]}…")
    if is_loop:
        print(f"      满环闭合（t=duration 姿态 == t=0）= {film['loop_closed']} → 播放器回卷无缝")
    else:
        uniq = len(set(film["frame_hashes"]))
        print(f"      互异帧 {uniq}/{film['frames']}（叙事片不做循环，末帧与首帧应不同）")

    # 4. Lottie L0
    print("\n[4/6] Lottie L0 导出")
    lot = os.path.join(EXAMPLES, f"{prefix}.json")
    linfo = export_lottie(proj, lot, style=style)
    print(f"      {linfo['path']}  layers={linfo['layers']}  frames={linfo['frames']}  "
          f"{linfo['bytes'] / 1024:.0f} KiB")

    # 5. 分镜格（供人工审阅叙事节奏）
    print("\n[5/6] 分镜格")
    snap_dir = os.path.join(EXAMPLES, "story_snapshots" if not is_loop else "film_snapshots")
    snap = snapshot_frames(proj, snap_dir, key_times, style=style, label=prefix)
    for fr in snap["frames"]:
        print(f"      t={fr['t']:>5.1f}s  {fr['file']}  sha256={fr['sha256'][:16]}…")

    # 6. manifest
    print("\n[6/6] manifest")
    manifest = {
        "project": f"projects/{dirname}",
        "kind": "loop" if is_loop else "narrative",
        "seed": proj.seed,
        "style": style.id,
        "size": [proj.width, proj.height],
        "fps": proj.fps,
        "duration": proj.duration,
        "frames": film["frames"],
        "instances": len(proj.groups),
        "camera_tracks": len(getattr(proj.camera, "tracks", ()) or ()),
        "loop_closed": film["loop_closed"],
        "unique_frames": len(set(film["frame_hashes"])),
        "validation": chk,
        "artifacts": {
            "film": {"file": f"{prefix}.mp4", "bytes": film["bytes"]},
            "lottie": {"file": f"{prefix}.json", "layers": linfo["layers"], "bytes": linfo["bytes"]},
            "poster_png": {"file": f"{prefix}.png", "t": poster_t, "sha256": _sha(poster_png)},
            "poster_svg": {"file": f"{prefix}.svg", "sha256": _sha(poster_svg)},
            "storyboard": snap["frames"],
        },
        "first_frame_hash": film["first_frame_hash"],
        "last_frame_hash": film["last_frame_hash"],
    }
    man = os.path.join(EXAMPLES, f"{prefix}_manifest.json")
    with open(man, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"      {man}")

    return {
        "prefix": prefix,
        "mp4": mp4,
        "png": png_path,
        "film": film,
        "validation": chk,
        "storyboard": snap["frames"],
        "storyboard_dir": snap_dir,
    }


def main() -> int:
    os.makedirs(EXAMPLES, exist_ok=True)
    results = [_run_job(*job) for job in JOBS]

    print("\n" + "=" * 78)
    print("交付汇总")
    print("=" * 78)
    ok = True
    for r in results:
        v = r["validation"]
        ok = ok and v["passed"]
        print(f"  {r['prefix']:22s} {r['film']['frames']:>3d} 帧  "
              f"{r['film']['bytes'] / 1024:>5.0f} KiB  校验 "
              f"{'通过' if v['passed'] else '未通过'}  ({v['errors']}e/{v['warnings']}w)")
        print(f"    {r['mp4']}")
        print(f"    分镜格目录: {r['storyboard_dir']}")
    print("\n⚠ 视频与画面请**人工**过目一次：自动校验只能保证几何/构图/确定性，")
    print("  节奏、动幅手感、色彩浓淡属审美判断，必须人眼确认。")
    print("=" * 78)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
