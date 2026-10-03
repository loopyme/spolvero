"""Flask 控制台路由（SPEC §17）。

薄壳：只做「读工程 / 建任务 / 读进度 / 送对话」，**零业务逻辑**
（造型、时序、判据全在 webapp 的其他模块与 engine 里）。
"""

from __future__ import annotations

import json
import os
import time

from flask import Flask, Response, jsonify, request, send_file, send_from_directory

from . import films as fl
from . import jobs as J
from . import llm
from . import ops as OPS
from . import partpreview as PREVIEW
from . import pipeline as P
from . import plan as PLAN

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))

app = Flask(__name__, template_folder=os.path.join(_HERE, "templates"),
            static_folder=os.path.join(_HERE, "static"))


@app.get("/")
def index():
    return send_from_directory(app.template_folder, "studio.html")


@app.after_request
def _no_cache_frontend(resp):
    """前端静态文件不缓存 —— 否则改了 JS/CSS 用户刷新还是老页面，看起来像"改了没用"。"""
    if request.path.startswith("/static/") or request.path == "/":
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
    return resp


# ── 工程 ────────────────────────────────────────────────────────────────
@app.get("/api/films")
def api_films():
    return jsonify({"films": fl.all_meta()})


@app.get("/api/ratios")
def api_ratios():
    """可选的画幅比例（**立项必填项**）。像素也一并给前端，用户能看清选的是什么。"""
    return jsonify({"ratios": fl.ratios()})


@app.post("/api/films")
def api_film_new():
    """新建影片。**只给一句想法也行** —— 幕表由 AI 生成，缺 AI 则规则降级。

    画幅比例在这里被**强制解析成像素**：后面所有构图参数都从它派生，
    没有"先建后补"的口子（补一次等于全部幕重排）。
    """
    b = request.get_json(silent=True) or {}
    try:
        idea = (b.get("idea") or "").strip()
        duration = float(b.get("duration") or 24.0)
        n_acts = int(b.get("n_acts") or 0)
        title = (b.get("title") or "").strip()
        source = (b.get("source") or "").strip()
        style = (b.get("style") or "").strip()
        (W, H), rname = fl.resolve_size(b.get("ratio") or b.get("size"))
        plan = None
        if idea:
            plan = llm.plan_film(idea, duration, n_acts, size=(W, H), ratio=rname)
            title = title or plan.get("title", "")
            source = source or idea[:40]
        m = fl.create_film(b.get("id", ""), title, source, size=(W, H),
                           duration=duration, n_acts=n_acts or 4, fps=int(b.get("fps", 30)),
                           acts=(plan or {}).get("acts"), idea=idea)
        # 整片基调（风格）在立项时定死：选了就写进 film.yaml，影响后续所有环节。
        if style:
            try:
                m = fl.set_style(b.get("id", m.get("id", "")) or m["id"], style)
            except Exception:
                pass
        return jsonify({"ok": True, "meta": m, "ratio": rname, "style": fl.style_of(m["id"]),
                        "plan_source": (plan or {}).get("source", "manual")})
    except ValueError as e:                     # 参数问题：直接把话说给用户看，别套类型名
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 400


@app.put("/api/films/<fid>/acts/<aid>")
def api_act_update(fid: str, aid: str):
    """改某一幕：幕名 / 题款 / 时长 / 主体高度。改时长会顺延后续幕。

    改完立刻**把不算数的产物清掉** —— 那一刻的旧图/旧视频留着只会误导。
    """
    b = request.get_json(silent=True) or {}
    try:
        m = fl.update_act(fid, aid, b)
        P.sweep(fid)
        return jsonify({"ok": True, "meta": m})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 400


@app.get("/api/films/<fid>")
def api_film(fid: str):
    try:
        m = fl.meta(fid)
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    rep = None
    p = os.path.join(fl.out_dir(fid), "judges.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                rep = json.load(f)
        except Exception:
            rep = None
    try:
        mod = fl.load(fid)
        nodes = mod.nodes_md()
        nodes_act = mod.nodes_by_act() if hasattr(mod, "nodes_by_act") else {}
    except Exception:
        nodes, nodes_act = "", {}
    return jsonify({"meta": m, "judges": rep, "nodes": nodes, "nodes_by_act": nodes_act,
                    "artifacts": _artifacts(fid)})


@app.get("/api/nodes/<fid>")
def api_nodes(fid: str):
    try:
        return jsonify({"md": fl.load(fid).nodes_md()})
    except Exception as e:
        return jsonify({"md": "", "error": str(e)})


# ── 七步流水线（界面只渲染这里给的状态）────────────────────────────────
@app.get("/api/pipeline/<fid>")
def api_pipeline(fid: str):
    try:
        return jsonify(P.describe(fid))
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 400


@app.post("/api/story/<fid>")
def api_story(fid: str):
    """第 2 步：故事 → 自动分幕（重排幕表与剧本，并把不算数的下游产物清掉）。"""
    b = request.get_json(silent=True) or {}
    try:
        r = llm.replan_film(fid, (b.get("idea") or "").strip(),
                            float(b.get("duration") or 0), int(b.get("n_acts") or 0))
        P.sweep(fid)
        return jsonify(r)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 400


@app.get("/api/parts/preview/<name>")
def api_part_preview(name: str):
    """引擎构件预览：用引擎自己的四原语几何画出来（与成片同源）。"""
    n = os.path.basename(name).replace(".svg", "")
    try:
        svg = PREVIEW.engine_svg(n)
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 404
    return Response(svg, mimetype="image/svg+xml",
                    headers={"Cache-Control": "no-store"})


@app.get("/api/parts/base/<fid>")
def api_part_base(fid: str):
    """本片在用底座的预览：直接渲染该片一帧。"""
    fid = fid.replace(".png", "")          # 容错：URL 里多写个后缀也别 404
    try:
        png = PREVIEW.base_preview_png(fid)
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 404
    return Response(png, mimetype="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/parts/used/<fid>/<path:name>")
def api_part_used(fid: str, name: str):
    """单个底座元素的样子（第 4 步里每个构件都摆出来看）。"""
    try:
        png = PREVIEW.used_png(fid.replace(".png", ""), name.replace(".png", ""))
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 404
    return Response(png, mimetype="image/png", headers={"Cache-Control": "no-store"})


@app.put("/api/script/<fid>")
def api_script(fid: str):
    """第 2 步：改某一幕的剧本（自然语言，一行一句）。只动这一幕的段落。"""
    b = request.get_json(silent=True) or {}
    try:
        return jsonify(fl.write_script(fid, str(b.get("act") or ""),
                                       b.get("items"), str(b.get("text") or "")))
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 400


@app.get("/api/parts")
def api_parts():
    return jsonify(P.parts())


@app.post("/api/parts/approve")
def api_part_approve():
    """采纳构件 → 同时清掉靠旧构件产出的画面（依赖变了，那些画面就不算数了）。"""
    b = request.get_json(silent=True) or {}
    try:
        r = P.approve_part(b.get("name", ""))
        for fid in fl.film_ids():
            P.sweep(fid)
        return jsonify(r)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.post("/api/parts/drop")
def api_part_drop():
    b = request.get_json(silent=True) or {}
    try:
        r = P.drop_part(b.get("name", ""), b.get("state", "pending"))
        for fid in fl.film_ids():
            P.sweep(fid)
        return jsonify(r)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.get("/api/styles")
def api_styles():
    """内置风格预设（给「构件」页选择）。"""
    return jsonify({"styles": P.styles()})


@app.put("/api/films/<fid>/style")
def api_film_style(fid: str):
    """选风格：把调色板写进 film.yaml，并把不算数的画面清掉（旧画面套新底色＝没换）。"""
    b = request.get_json(silent=True) or {}
    try:
        m = fl.set_style(fid, str(b.get("style") or "").strip())
        P.sweep(fid)
        return jsonify({"ok": True, "meta": m, "style": fl.style_of(fid)})
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 400


# 每一步在对话里"是什么语境" —— 决定 AI 怎么理解一句大白话。
# 关键：说清**人在这一步看什么、会对什么提意见**，AI 才知道该改哪个参数。
STEP_CTX = {
    "1": "第 1 步（立项）。画幅已定；若用户想改画幅，说明等于全部幕重排，建议新建一部片。",
    "2": "第 2 步（分幕 · 剧本）。人在看：幕是不是按事件切、每一幕讲什么说不说得清、题款是不是点睛、幕长分配。改时长会顺延后面所有幕。",
    "3": "第 3 步（构件 · 生成）。用户要造新对象（人、器物、山石、房屋）。用 propose_part 交实现。",
    "4": "第 4 步（每幕关键图）。人在看静帧：主体够不够大（≥画高 1/4）、焦点是不是只有一个、题款有没有压住主体、留白、这一幕讲的事看不看得出来。",
    "5": "第 5 步（每幕视频 · 只看画面）。人在看：动幅（以画布宽度为度量）、镜头是否呆滞、有没有跳帧、起—做—收的节奏。",
    "6": "第 6 步（声音）。人在听：每一幕有没有该有的声音、落点对不对、响度、首尾。声轨时长必须从幕表派生，不许写死秒数。",
    "7": "第 7 步（成片）。人在看：幕与幕的接缝、整片节奏、声画有没有错位。",
}


def _advise_context(fid: str, step: str, act: str) -> str:
    """把"现在在哪一步、看到什么、检验挂在哪"拼成一句话给 AI。

    **用户只说大白话**（"这个太白""人太小"），定位必须由系统完成 ——
    让用户先选身份/先选幕，就是把系统的活推给人的活。
    """
    d = P.describe(fid)
    m = d["meta"]
    lines = [f'【当前步骤】{STEP_CTX.get(step, "")}',
             f'【影片】《{m["title"]}》id={fid} · 画幅 {m.get("ratio", "")} '
             f'{m["size"][0]}×{m["size"][1]} · {m["duration"]:.1f} 秒 · {m["fps"]}fps']
    for a in d["acts"]:
        scr = " / ".join(x["text"] for x in (a.get("script") or [])[:3])
        cap = "　".join(a.get("caption") or [])
        line = f'· {a["id"]} {a["note"]}（{a["t0"]:.1f}–{a["t1"]:.1f}s'
        line += f'，题款「{cap}」' if cap else ''
        line += f'，剧本：{scr}' if scr else '，剧本：（还没写）'
        lines.append(line + '）')
    if act:
        lines.append(f'【用户正在看】{act}')
    probs = []
    for s in d["steps"]:
        for p in ((s.get("checks") or {}).get("problems") or []):
            probs.append(f'{p["id"]} {p["name"]}：{p["detail"]}')
    if probs:
        lines.append("【自动检验未过项】" + "；".join(probs[:6]))
    if d["parts"]["items"]:
        lines.append("【构件库】" + "、".join(f'{i["name"]}（{i["state"]}）' for i in d["parts"]["items"][:10]))
    return "\n".join(lines)


@app.post("/api/advise")
def api_advise():
    """一句意见 → **改动计划**（两阶段的第一阶段，不执行）。

    执行要人来勾选确认（`/api/apply`）—— 一句话往往牵连好几样东西，
    先把后果摆出来，比闷头改完再让人去发现强。
    """
    b = request.get_json(silent=True) or {}
    fid = (b.get("film") or "").strip()
    step = str(b.get("step") or "")
    act = (b.get("act") or "").strip()
    text = (b.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "空意见"}), 400
    try:
        ctx = _advise_context(fid, step, act) if fid else ""
    except Exception as e:
        ctx = f"【上下文读取失败】{type(e).__name__}: {e}"
    r = llm.plan_advice(ctx, text, fid=fid)
    if not r.get("ok"):
        return jsonify({"ok": False, "error": r.get("error", "没能给出计划"), "mode": r.get("mode")})
    plan = PLAN.normalize(r["plan"], fid)
    if not plan["items"]:
        return jsonify({"ok": True, "empty": True, "understanding": plan["understanding"],
                        "plan": plan, "text": text,
                        "error": "没听懂这句意见 —— 换一种说法，或说得更具体一点（哪一幕、改什么）"})
    plan["film"] = fid
    plan["text"] = text
    plan["step"] = step
    plan["act"] = act
    return jsonify({"ok": True, "plan": plan, "understanding": plan["understanding"]})


@app.post("/api/apply")
def api_apply():
    """两阶段的第二阶段：按勾选执行（没勾的 stills/clip 项 = 那一幕先空着）。"""
    b = request.get_json(silent=True) or {}
    fid = (b.get("film") or "").strip()
    plan = b.get("plan") or {}
    chosen = b.get("chosen")
    try:
        r = PLAN.apply_plan(fid, plan, chosen)
        P.sweep(fid)                       # 参数改过之后，不算数的产物立刻清掉
        return jsonify(r)
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 400


@app.get("/api/ops/<fid>")
def api_ops(fid: str):
    """操作批次（右栏"操作"卡片的数据源）。"""
    return jsonify({"batches": OPS.list_batches(fid)})


@app.post("/api/ops/restore")
def api_ops_restore():
    b = request.get_json(silent=True) or {}
    try:
        return jsonify(OPS.restore(str(b.get("batch") or "")))
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 400


@app.get("/api/checks/<fid>")
def api_checks(fid: str):
    """最近的自动检验报告全文（默认折叠在产物下面，需要时展开看）。"""
    p = os.path.join(fl.out_dir(fid), "judges.json")
    if not os.path.exists(p):
        return jsonify({"error": "还没跑过检验"}), 404
    with open(p, encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.post("/api/checks/<fid>")
def api_checks_run(fid: str):
    """重新检验（自动检验之外的手动补跑）。"""
    scope = (request.get_json(silent=True) or {}).get("scope", "static")
    try:
        return jsonify(J.MANAGER.start("judges", fid, {"scope": scope}))
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 400


KIND_LABEL = {"stills": "关键图", "sheet": "分镜格", "judges": "判据报告",
              "clip": "渲染片段", "film": "渲染全片", "part_check": "构件检验"}


def _artifacts(fid: str) -> dict:
    """产物分两段：**当前**（由 out/current.json 指针决定）与**历史**（按批次倒序）。

    为什么必须分：产物若都用固定文件名，一覆盖上一次就没了，
    界面上全混在一起 —— 用户分不清"我现在看的是哪一版"。
    现在每次任务落进 `out/runs/<任务号>_<类型>/`，历史实体保留、当前有明确指针。
    """
    o = fl.out_dir(fid)
    cur = {}
    p = os.path.join(o, "current.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                cur = json.load(f)
        except Exception:
            cur = {}
    current = []
    for kind, rec in cur.items():
        files = []
        for it in rec.get("files", []):
            fp = os.path.join(o, it["file"])
            if os.path.exists(fp):
                it = dict(it)
                it["url"] = f"/out/{fid}/{it['file']}"
                it["mb"] = round(os.path.getsize(fp) / 1048576, 2)
                files.append(it)
        if files:
            current.append({"kind": kind, "label": KIND_LABEL.get(kind, kind),
                            "when": rec.get("when", ""), "job": rec.get("job", ""),
                            "files": files})

    runs = []
    rd = os.path.join(o, "runs")
    if os.path.isdir(rd):
        for name in sorted(os.listdir(rd), reverse=True):
            d = os.path.join(rd, name)
            if not os.path.isdir(d):
                continue
            files = []
            for fn in sorted(os.listdir(d)):
                if fn.endswith((".png", ".mp4", ".json")):
                    rel = f"runs/{name}/{fn}"
                    files.append({"file": rel, "name": fn,
                                  "url": f"/out/{fid}/{rel}",
                                  "mb": round(os.path.getsize(os.path.join(d, fn)) / 1048576, 2)})
            if files:
                kind = name.split("_", 1)[1] if "_" in name else ""
                runs.append({"run": name, "kind": kind,
                             "label": KIND_LABEL.get(kind, kind), "files": files})
    return {"current": current, "history": runs}


@app.get("/out/<fid>/<path:rel>")
def out_file(fid: str, rel: str):
    o = fl.out_dir(fid)
    full = os.path.normpath(os.path.join(o, rel))
    if not full.startswith(os.path.normpath(o)):
        return jsonify({"error": "路径越界"}), 403
    if not os.path.exists(full):
        return jsonify({"error": "不存在"}), 404
    return send_file(full)


# ── 任务 ────────────────────────────────────────────────────────────────
@app.post("/api/tasks/<fid>/<kind>")
def api_task(fid: str, kind: str):
    args = request.get_json(silent=True) or {}
    try:
        if kind in ("film", "clip"):
            pass
        j = J.MANAGER.start(kind, fid, args)
        return jsonify(j)
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 400


@app.get("/api/jobs")
def api_jobs():
    return jsonify({"jobs": J.MANAGER.list()})


@app.get("/api/jobs/<jid>")
def api_job(jid: str):
    return jsonify(J.MANAGER.info(jid))


@app.post("/api/jobs/<jid>/cancel")
def api_cancel(jid: str):
    return jsonify(J.MANAGER.cancel(jid))


@app.get("/api/events")
def api_events():
    """SSE：把任务的进度与日志推给界面。"""
    jid = request.args.get("job", "")
    if not jid:
        return jsonify({"error": "缺少 job"}), 400

    def gen():
        last = None
        idle = 0
        while True:
            try:
                info = J.MANAGER.info(jid)
            except Exception as e:
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
                return
            key = (info.get("done"), info.get("total"), info.get("state"),
                   info.get("note"), len(info.get("log") or []))
            if key != last:
                last = key
                yield "event: progress\ndata: " + json.dumps(info, ensure_ascii=False) + "\n\n"
                idle = 0
            else:
                idle += 1
                if idle % 30 == 0:                       # 心跳，防代理断流
                    yield ": ping\n\n"
            if info.get("state") in ("done", "error", "canceled"):
                yield "event: end\ndata: " + json.dumps(info, ensure_ascii=False) + "\n\n"
                return
            time.sleep(0.45)

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── AI ──────────────────────────────────────────────────────────────────
@app.post("/api/chat")
def api_chat():
    body = request.get_json(silent=True) or {}
    msgs = body.get("messages") or []
    role = body.get("role") or "storyboard"
    if not msgs:
        return jsonify({"error": "空消息"}), 400
    return jsonify(llm.chat(msgs, role=role, fid=(body.get("film") or "").strip()))


@app.get("/api/settings")
def api_settings_get():
    return jsonify(llm.public_conf())


@app.post("/api/settings")
def api_settings_post():
    b = request.get_json(silent=True) or {}
    if "api_key" in b and b["api_key"] == "":
        b.pop("api_key")                                  # 空字符串＝不改，清空要显式 clear
    if b.pop("clear_key", False):
        b["api_key"] = ""
    return jsonify(llm.save_conf(b))


@app.post("/api/settings/test")
def api_settings_test():
    """测试连接：用输入框里的密钥优先，否则用已保存的。**只在用户主动点击时发生。**"""
    b = request.get_json(silent=True) or {}
    return jsonify(llm.probe(b.get("base_url", ""), b.get("model", ""), b.get("api_key", "")))


@app.get("/api/prompts")
def api_prompts():
    return jsonify(llm.P.PROMPTS)


def main(host: str = "127.0.0.1", port: int = 8760, debug: bool = False) -> int:
    print(f"Spolvero 控制台 → http://{host}:{port}/")
    print(f"  影片工程包目录：{fl.FILMS_DIR}")
    app.run(host=host, port=port, debug=debug, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
