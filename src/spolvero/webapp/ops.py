"""操作批次与回退（SPEC §17.4）。

一条用户意见往往会改好几样东西：幕参数、剧本、构件，然后重画/重渲若干幕。
这些改动**必须能一次退回去** —— 否则"试一下"的成本太高，人就不敢动了。

做法：执行前把**会被改动的源文件**（film.yaml / nodes.md / parts/）整份快照到
`logs/ops/<批次号>/`，并记一条人话摘要。恢复＝把快照写回。

产物（关键图/视频）**不进快照** —— 它们的有效性是从源文件派生的（§17.2.2 的 `act_signature`）：
源文件退回去了，指纹自然跟着回去，那些幕就自动重新"还算数"。
这就是"不存第二份真相"的好处：回退只需要退文件。
"""

from __future__ import annotations

import json
import os
import shutil
import time

from . import films as fl

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
OPS_DIR = os.path.join(_ROOT, "logs", "ops")
KEEP = 5                      # 只留最近 5 条（用户明确要求的上限）

# 会被一次意见改动的源文件（相对工程目录）。
# **产物指针与依赖记录也进快照**：不然"退回"只退了文件，被清空的那一幕回不来。
SOURCES = ("film.yaml", "nodes.md", "out/current.json", "out/deps.json")


def _batch_dir(bid: str) -> str:
    return os.path.join(OPS_DIR, bid)


def snapshot(fid: str, note: str, extra: dict | None = None) -> str:
    """执行前留一份快照。返回批次号。"""
    import uuid
    # 加随机尾巴：同一秒里连着改几次，批次号不能撞（撞了就是互相覆盖，回退点丢一半）
    bid = time.strftime("%m%d-%H%M%S-") + uuid.uuid4().hex[:4] + "-" + fid[:8]
    d = _batch_dir(bid)
    os.makedirs(d, exist_ok=True)
    fd = fl.film_dir(fid)
    for name in SOURCES:
        src = os.path.join(fd, name.replace("/", os.sep))
        dst = os.path.join(d, name.replace("/", os.sep))
        if os.path.exists(src):
            os.makedirs(os.path.dirname(dst) or d, exist_ok=True)
            shutil.copy2(src, dst)
    parts = os.path.join(_ROOT, "parts")
    if os.path.isdir(parts):
        shutil.copytree(parts, os.path.join(d, "parts"), dirs_exist_ok=True)
    meta = {"id": bid, "film": fid, "note": note, "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "files": [n for n in SOURCES if os.path.exists(os.path.join(d, n.replace("/", os.sep)))]
                     + ["parts/"],
            "extra": extra or {}}
    with open(os.path.join(d, "batch.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    prune(fid)
    return bid


def prune(fid: str) -> None:
    """只留最近 KEEP 条（同一部片的）。"""
    mine = [b for b in list_batches(fid)]
    for b in mine[KEEP:]:
        shutil.rmtree(_batch_dir(b["id"]), ignore_errors=True)


def list_batches(fid: str = "") -> list[dict]:
    if not os.path.isdir(OPS_DIR):
        return []
    out = []
    for name in sorted(os.listdir(OPS_DIR), reverse=True):
        p = os.path.join(OPS_DIR, name, "batch.json")
        if not os.path.exists(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                m = json.load(f)
        except Exception:
            continue
        if fid and m.get("film") != fid:
            continue
        m["restorable"] = True
        out.append(m)
    return out


def restore(bid: str) -> dict:
    """把这一批之前的状态写回去。产物不用管：指纹会跟着源文件自动回落。"""
    d = _batch_dir(os.path.basename(bid))
    p = os.path.join(d, "batch.json")
    if not os.path.exists(p):
        raise KeyError(f"没有这条操作记录：{bid}")
    with open(p, encoding="utf-8") as f:
        m = json.load(f)
    fid = m.get("film", "")
    fd = fl.film_dir(fid)
    back = []
    for name in SOURCES:
        src = os.path.join(d, name.replace("/", os.sep))
        if os.path.exists(src):
            dst = os.path.join(fd, name.replace("/", os.sep))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            back.append(name)
    pd = os.path.join(d, "parts")
    if os.path.isdir(pd):
        root = os.path.join(_ROOT, "parts")
        for sub in ("pending", "custom"):
            s2 = os.path.join(pd, sub)
            t2 = os.path.join(root, sub)
            if not os.path.isdir(t2):
                os.makedirs(t2, exist_ok=True)
            # 恢复成快照时的样子：多出来的删掉，缺的补回来
            for fn in os.listdir(t2):
                if fn.endswith((".py", ".dropped")) and not os.path.exists(os.path.join(s2, fn)):
                    os.remove(os.path.join(t2, fn))
            if os.path.isdir(s2):
                for fn in os.listdir(s2):
                    shutil.copy2(os.path.join(s2, fn), os.path.join(t2, fn))
        back.append("parts/")
    fl._CACHE.pop(fid, None)
    return {"ok": True, "batch": m, "restored": back,
            "note": "已退回这一批之前：受影响的幕会自动变回该重做（或自动恢复为最新）"}
