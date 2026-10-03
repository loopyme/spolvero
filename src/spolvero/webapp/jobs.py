"""任务与进度（SPEC §17.3）。

原则：**长任务一律子进程 + 进度文件**，父进程只读进度，绝不在请求线程里同步跑。
进度文件原子写（临时文件 + os.replace），所以读的时候永不会读到半截 JSON。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
LOG_DIR = os.path.join(_ROOT, "logs", "jobs")

KINDS = {
    "stills": "出关键图",
    "sheet": "出分镜格",
    "judges": "跑判据",
    "clip": "渲染片段",
    "sound": "出声轨",
    "film": "渲染全片",
    "part_check": "构件检验",
}


def _ensure(p: str) -> str:
    os.makedirs(p, exist_ok=True)
    return p


def new_id() -> str:
    return time.strftime("%m%d-%H%M%S-") + uuid.uuid4().hex[:4]


def job_dir(jid: str) -> str:
    return _ensure(os.path.join(LOG_DIR, jid))


def progress_path(jid: str) -> str:
    return os.path.join(job_dir(jid), "progress.json")


def read_progress(jid: str) -> dict:
    p = progress_path(jid)
    if not os.path.exists(p):
        return {"state": "pending", "done": 0, "total": 0, "unit": "", "note": "排队中"}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"state": "pending", "done": 0, "total": 0, "unit": "", "note": "读取中"}


def write_progress(jid: str, **kw) -> None:
    p = progress_path(jid)
    cur = read_progress(jid)
    cur.update(kw)
    cur["updated"] = time.time()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False)
    os.replace(tmp, p)


def log_tail(jid: str, n: int = 40) -> list[str]:
    p = os.path.join(job_dir(jid), "log.txt")
    if not os.path.exists(p):
        return []
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            return f.read().splitlines()[-n:]
    except Exception:
        return []


class Manager:
    """进程内的任务表（单用户本地控制台，不做持久化队列）。"""

    def __init__(self):
        self.procs: dict[str, subprocess.Popen] = {}
        self.kind: dict[str, str] = {}
        self.film: dict[str, str] = {}
        self.created: dict[str, float] = {}

    def start(self, kind: str, fid: str, args: dict | None = None) -> dict:
        if kind not in KINDS:
            raise KeyError(f"未知任务类型：{kind}")
        # 同时只允许一个渲染类任务，避免把机器打满（§17.3）
        if kind in ("film", "clip"):
            for jid, k in self.kind.items():
                if k in ("film", "clip") and self.alive(jid):
                    raise RuntimeError("已有渲染任务在跑，先等它完成或中断")
        jid = new_id()
        _ensure(job_dir(jid))
        spec = {"id": jid, "kind": kind, "film": fid, "args": args or {},
                "root": _ROOT, "pid": os.getpid()}
        sp = os.path.join(job_dir(jid), "job.json")
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False, indent=2)
        write_progress(jid, state="running", done=0, total=0, unit="", note="启动中",
                       kind=kind, film=fid, started=time.time())
        logf = open(os.path.join(job_dir(jid), "log.txt"), "w", encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = os.path.join(_ROOT, "src") + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            [sys.executable, "-m", "spolvero.webapp.runner", sp],
            cwd=_ROOT, stdout=logf, stderr=subprocess.STDOUT, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.procs[jid] = proc
        self.kind[jid] = kind
        self.film[jid] = fid
        self.created[jid] = time.time()
        return self.info(jid)

    def alive(self, jid: str) -> bool:
        p = self.procs.get(jid)
        return p is not None and p.poll() is None

    def info(self, jid: str) -> dict:
        pr = read_progress(jid)
        p = self.procs.get(jid)
        rc = p.poll() if p is not None else None
        st = pr.get("state", "pending")
        if rc is not None and st == "running":
            st = "done" if rc == 0 else "error"
            pr["state"] = st
            if rc != 0:
                pr["error"] = "子进程退出码 %s（见日志尾部）" % rc
        if p is None and st in ("running", "pending"):
            # 不是本进程启动的（控制台重启过，或启动它的进程已经退出）：
            # 只能看心跳 —— 进度文件很久没动，就说明那个子进程已经不在了。
            # 否则界面会一直显示"进行中"，而永远不会有结果。
            age = time.time() - float(pr.get("updated") or 0)
            if age > 45:
                st = "lost"
                pr["state"] = st
                pr["note"] = "已失联（控制台重启或进程退出）—— 重跑即可，已出的帧会跳过"
        return {**pr, "id": jid, "kind": self.kind.get(jid, pr.get("kind", "")),
                "film": self.film.get(jid, pr.get("film", "")),
                "kind_label": KINDS.get(self.kind.get(jid, pr.get("kind", "")), ""),
                "alive": self.alive(jid), "rc": rc,
                "log": log_tail(jid, 12), "created": self.created.get(jid, 0)}

    def list(self) -> list[dict]:
        out = []
        for jid in sorted(self.created, key=lambda j: -self.created[j]):
            out.append(self.info(jid))
        return out

    def cancel(self, jid: str) -> dict:
        p = self.procs.get(jid)
        if p is None or p.poll() is not None:
            return self.info(jid)
        p.terminate()
        try:
            p.wait(timeout=8)
        except Exception:
            p.kill()
        write_progress(jid, state="canceled", note="已中断（已出的帧保留，重跑会跳过）")
        return self.info(jid)


MANAGER = Manager()
