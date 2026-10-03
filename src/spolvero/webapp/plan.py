"""意见 → 计划 → 执行（SPEC §17.1 的两阶段）。

用户提一句意见，**先出计划给人看**（改哪几处、重画哪几幕、重渲哪一幕），勾选后再执行。
为什么必须两阶段：
1. 一句话可能牵连好几样东西（改幕参数 → 这一幕的图与视频都过时），
   直接闷头执行，用户不知道发生了什么；
2. 计划就是"把后果摆在明面上"——**取消勾选**还能表达"这一幕先空着"。

计划项 kind 只有七种（都在这里落地，AI 不得自创）：
  script 改该幕剧本 · film_patch 改该幕参数 · parts 造构件
  stills 重画 · clip 重渲 · sound 重出声轨 · film 重合成
"""

from __future__ import annotations

import os
import time

from . import films as fl
from . import ops
from . import pipeline as P

KINDS = ("script", "film_patch", "parts", "stills", "clip", "sound", "film")
LABEL = {"script": "改剧本", "film_patch": "改幕参数", "parts": "造构件",
         "stills": "重画关键图", "clip": "重渲视频", "sound": "重出声轨",
         "film": "重合成全片"}


def normalize(plan: dict, fid: str) -> dict:
    """把模型给的计划收拾成**可执行、可勾选**的清单（非法项一律丢掉）。"""
    acts = {a["id"]: a for a in (fl.meta(fid).get("acts") or [])}
    items = []
    for k, it in enumerate(plan.get("items") or []):
        if not isinstance(it, dict):
            continue
        kind = str(it.get("kind") or "").strip()
        if kind not in KINDS:
            continue
        scope = str(it.get("scope") or "").strip()
        if kind in ("script", "film_patch", "stills", "clip") and scope not in acts:
            continue
        label = f'{LABEL[kind]}'
        if scope in acts:
            label += f'「{acts[scope]["note"]}」'
        detail = str(it.get("detail") or "").strip()[:160]
        row = {"id": f"i{k + 1}", "kind": kind, "scope": scope,
               "label": label, "detail": detail, "default": True}
        if kind == "film_patch":
            row["patch"] = it.get("patch") or {}
        if kind == "parts":
            row["name"] = str(it.get("name") or "").strip()[:32]
            row["code"] = str(it.get("code") or "")
            if not row["name"] or not row["code"]:
                continue
        if kind == "script":
            row["text"] = str(it.get("text") or it.get("detail") or "").strip()
            if not row["text"]:
                continue
        items.append(row)
    return {"understanding": str(plan.get("understanding") or "").strip()[:200], "items": items}


def apply_plan(fid: str, plan: dict, chosen: list | None = None) -> dict:
    """执行计划。`chosen` 是勾选项 id 列表；**没勾的项会被当作"先空着"**。

    取消勾选一个 stills/clip 项 = 清空那一幕的该产物（不是保留旧的）。
    """
    from .jobs import MANAGER
    items = plan.get("items") or []
    pick = set(chosen) if chosen is not None else {i["id"] for i in items if i.get("default")}
    bid = ops.snapshot(fid, note=plan.get("understanding") or "一次意见",
                       extra={"items": [{"kind": i["kind"], "scope": i.get("scope", "")} for i in items]})
    done, jobs, cleared, failed = [], [], [], []
    for it in items:
        kind, scope = it["kind"], it.get("scope", "")
        label = it.get("label") or LABEL.get(kind, kind)
        if it["id"] not in pick:
            if kind in ("stills", "clip") and scope:
                P.clear_act(fid, "stills" if kind == "stills" else "clip", scope)
                cleared.append({"kind": kind, "scope": scope, "label": label})
            continue
        try:
            if kind == "script":
                fl.write_script(fid, scope, text=it.get("text") or it.get("detail") or "")
                done.append({"kind": kind, "scope": scope, "label": label, "note": "剧本已改"})
            elif kind == "film_patch":
                fl.update_act(fid, scope, it.get("patch") or {})
                done.append({"kind": kind, "scope": scope, "label": label, "note": "幕参数已改"})
            elif kind == "parts":
                # **直接采纳**：AI 提议的构件一落盘就进 custom（已采纳），不再有"待采纳"环节。
                # 工作台上只看、只删 —— 少一步"再点一次采纳"，就不会有"采纳后它去哪了"。
                os.makedirs(P.CUSTOM, exist_ok=True)
                p = os.path.join(P.CUSTOM, it["name"] + ".py")
                with open(p, "w", encoding="utf-8") as f:
                    f.write(f'"""构件 {it["name"]} —— 用途：{it.get("detail", "")}\n（AI 提议，已采纳）"""\n\n{it["code"]}\n')
                done.append({"kind": kind, "scope": "", "label": label, "note": "构件已采纳"})
            elif kind == "stills":
                j = MANAGER.start("stills", fid, {"acts": [scope], "force": True})
                jobs.append(j["id"])
                done.append({"kind": kind, "scope": scope, "label": label, "note": "已排队重画"})
            elif kind == "clip":
                j = MANAGER.start("clip", fid, {"act": scope, "force": True})
                jobs.append(j["id"])
                done.append({"kind": kind, "scope": scope, "label": label, "note": "已排队重渲"})
            elif kind == "sound":
                j = MANAGER.start("sound", fid, {"force": True})
                jobs.append(j["id"])
                done.append({"kind": kind, "scope": "", "label": label, "note": "已排队重出声轨"})
            elif kind == "film":
                j = MANAGER.start("film", fid, {"force": True})
                jobs.append(j["id"])
                done.append({"kind": kind, "scope": "", "label": label, "note": "已排队重合成"})
        except Exception as e:
            failed.append({"kind": kind, "label": label, "error": f"{type(e).__name__}: {e}"})
    return {"ok": True, "batch": bid, "done": done, "jobs": jobs,
            "cleared": cleared, "failed": failed,
            "when": time.strftime("%Y-%m-%d %H:%M:%S")}
