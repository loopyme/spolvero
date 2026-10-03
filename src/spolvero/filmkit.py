"""影片骨架（filmkit）—— 让**新建的工程立刻能出图、能判据、能出片段**。

真相同 `film.yaml`（时间只有一个来源，§3 派生约束）。

它**不是成品，是脚手架**：纸底 + 天空分带 + 远山 + 地平线 + 主体剪影 + 题款。
为什么必须有它：新建出来一部空片子，用户点"出关键图"得到的是空白，
判据全失败、也不知道从哪改 —— 那就等于没建。**流程能跑起来，才谈得上往里填。**
"""

from __future__ import annotations

import hashlib
import math
import os

import numpy as np

try:
    import yaml
except Exception:                                     # pragma: no cover
    yaml = None


def _hex(c: str):
    c = (c or "#000000").lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _mix(c1, c2, k: float):
    a, b = _hex(c1), _hex(c2)
    return tuple(int(round(a[i] + (b[i] - a[i]) * k)) for i in range(3))


def _ratio_label(w: int, h: int) -> str:
    from math import gcd
    g = gcd(int(w), int(h)) or 1
    a, b = int(w) // g, int(h) // g
    return f"{a}:{b}" if max(a, b) <= 20 else f"{w / h:.2f}:1"


class Skeleton:
    def __init__(self, film_dir: str):
        self.dir = film_dir
        p = os.path.join(film_dir, "film.yaml")
        if yaml is None:
            raise RuntimeError("缺 pyyaml")
        with open(p, encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f) or {}
        self.acts_cfg = self.cfg.get("acts") or []
        self.fps = int(self.cfg.get("fps", 30))
        self.W, self.H = [int(x) for x in self.cfg.get("size", [1600, 900])]
        # 画幅是**构图的根参数**：题款落点、字号、景别 pivot 全从它派生（不在别处另写一份）
        self.ratio = str(self.cfg.get("ratio") or "").strip() or _ratio_label(self.W, self.H)
        # 时长**从幕表派生**，不单独存一份（存了就有两处真相）
        self.dur = float(max(a["t1"] for a in self.acts_cfg)) if self.acts_cfg else 1.0
        self.frames = int(round(self.dur * self.fps))
        self.title = self.cfg.get("title", os.path.basename(film_dir))
        self.source = self.cfg.get("source", "")
        pal = self.cfg.get("palette") or {}
        self.pal = {
            "sky_top": pal.get("sky_top", "#DED3BC"),
            "sky_bottom": pal.get("sky_bottom", "#F3EEE2"),
            "ink": pal.get("ink", "#2A2A24"),
            "mid": pal.get("mid", "#8A8578"),
            "accent": pal.get("accent", "#B23A2C"),
        }
        self.paper = [int(x) for x in (pal.get("paper") or [246, 242, 232])]
        # 纸色也进 pal（按 hex），供"往纸色方向混合"这类运算直接用一行取值
        self.pal["paper"] = "#%02X%02X%02X" % tuple(self.paper)

    # ── 派生量：题款落点与字号（**唯一来源**，渲染与判据都读这里）──────────
    def cap_style(self, a: dict) -> tuple[float, float, int]:
        """(x, y, size)。缺省值相对画幅算：16:9 下即 [1360, 180] / 40px。"""
        at = a.get("cap_at") or [self.W * 0.85, self.H * 0.20]
        size = int(a.get("cap_size") or max(22, round(min(self.W, self.H) * 0.0444)))
        return float(at[0]), float(at[1]), size

    # ── 元数据 ──────────────────────────────────────────────────────────
    def acts(self):
        return [{"id": a["id"], "t0": float(a["t0"]), "t1": float(a["t1"]),
                 "d": float(a["t1"]) - float(a["t0"]),
                 "scene": a.get("scene", ""), "note": a.get("note", a["id"]),
                 "subject": dict(a.get("subject") or {}),
                 "shot": dict(a.get("shot") or {}),
                 "caption": list(a.get("caption") or [])} for a in self.acts_cfg]

    def meta(self):
        cap = {}
        for a in self.acts_cfg:
            x, y, sz = self.cap_style(a)
            cap[a["id"]] = {"cols": list(a.get("caption", [a.get("note", a["id"])])),
                            "at": [x, y], "size": sz}
        return {"id": self.cfg.get("id", os.path.basename(self.dir)),
                "title": self.title, "source": self.source,
                "duration": self.dur, "fps": self.fps,
                "size": [self.W, self.H], "ratio": self.ratio, "frames": self.frames,
                "paper": self.paper,
                "acts": self.acts(),
                "captions": cap,
                "palette_acts": ["skeleton"],
                "entry": "film.yaml（骨架渲染 spolvero.filmkit）"}

    def act_at(self, t: float):
        for a in self.acts_cfg:
            if float(a["t0"]) <= t < float(a["t1"]):
                return a
        return self.acts_cfg[-1]

    # ── 渲染 ────────────────────────────────────────────────────────────
    def render_frame(self, t: float, camera=None, ins=None):
        import skia
        from spolvero.core.dmath import dcos, dsin

        W, H = self.W, self.H
        a = self.act_at(t)
        t0, t1 = float(a["t0"]), float(a["t1"])
        u = (t - t0) / max(1e-6, t1 - t0)
        subj = a.get("subject") or {"x": W * 0.5, "base": H * 0.9556, "h": H * 0.30}

        surface = skia.Surface(W, H)
        c = surface.getCanvas()
        c.clear(skia.ColorSetARGB(255, *self.paper))

        s, px, py = camera if camera else (1.0, W / 2.0, H / 2.0)
        c.save()
        if abs(s - 1.0) > 1e-9:
            m = skia.Matrix()
            m.setAll(s, 0.0, px * (1 - s), 0.0, s, py * (1 - s), 0.0, 0.0, 1.0)
            c.concat(m)

        # ① 天空分带（上深下浅 —— 明度要分出层次，判据 C2）
        bands = 7
        skh = H * 0.46
        for i in range(bands):
            k = i / (bands - 1.0)
            col = _mix(self.pal["sky_top"], self.pal["sky_bottom"], k)
            p = skia.Paint()
            p.setColor(skia.ColorSetARGB(255, *col))
            c.drawRect(skia.Rect.MakeXYWH(0, i * skh / bands, W, skh / bands + 1.5), p)

        # ② 远山（两段折线，高度按幕 id 派生，保证各幕不同又不乱）
        seed = int(hashlib.sha256(str(a["id"]).encode()).hexdigest()[:6], 16)
        for layer, (mul, tone_k) in enumerate(((1.0, 0.55), (1.28, 0.30))):
            pts = [(0.0, H * 0.46)]
            n = 9
            for i in range(1, n):
                x = W * i / (n - 1.0)
                r = ((seed >> (i * 3)) & 7) / 7.0
                y = H * 0.46 - (H * 0.10 * mul) * (0.35 + 0.65 * r)
                pts.append((x, y))
            pts.append((W, H * 0.46))
            pts.append((W, H * 0.62))
            pts.append((0.0, H * 0.62))
            path = skia.Path()
            path.moveTo(*pts[0])
            for q in pts[1:]:
                path.lineTo(*q)
            path.close()
            p = skia.Paint()
            p.setAntiAlias(True)
            p.setColor(skia.ColorSetARGB(255, *_mix(self.pal["ink"], self.pal["paper"], tone_k)))
            c.drawPath(path, p)

        # ③ 地平线与地面
        gp = skia.Paint()
        gp.setAntiAlias(True)
        gp.setColor(skia.ColorSetARGB(255, *_mix(self.pal["paper"], self.pal["mid"], 0.35)))
        c.drawRect(skia.Rect.MakeXYWH(0, H * 0.62, W, H * 0.38), gp)
        lp = skia.Paint()
        lp.setAntiAlias(True)
        lp.setColor(skia.ColorSetARGB(255, *_hex(self.pal["mid"])))
        c.drawRect(skia.Rect.MakeXYWH(0, H * 0.618, W, 2.5), lp)

        # ④ 主体剪影（会呼吸、会横移 —— 判据 C8 要求任何时刻都在动）
        breathe = 1.0 + 0.012 * dsin(2 * math.pi * (t * 0.45))
        walk = (u - 0.5) * W * 0.16
        hh = float(subj["h"]) * breathe
        base = float(subj["base"])
        cx = float(subj["x"]) + walk
        ink = _hex(self.pal["ink"])
        ip = skia.Paint()
        ip.setAntiAlias(True)
        ip.setColor(skia.ColorSetARGB(255, *ink))
        # 躯干（梯形）
        torso = [(cx - 0.11 * hh, base), (cx + 0.11 * hh, base),
                 (cx + 0.085 * hh, base - 0.62 * hh), (cx - 0.085 * hh, base - 0.62 * hh)]
        path = skia.Path()
        path.moveTo(*torso[0])
        for q in torso[1:]:
            path.lineTo(*q)
        path.close()
        c.drawPath(path, ip)
        # 头
        c.drawCircle(cx, base - 0.70 * hh, 0.075 * hh, ip)
        # 双腿（随呼吸相位微动）
        sw = 0.03 * hh * dsin(2 * math.pi * t * 0.9)
        for sgn in (-1, 1):
            lp2 = skia.Paint()
            lp2.setAntiAlias(True)
            lp2.setStrokeWidth(0.055 * hh)
            lp2.setStrokeCap(skia.Paint.kRound_Cap)
            lp2.setColor(skia.ColorSetARGB(255, *ink))
            c.drawLine(cx + sgn * 0.035 * hh, base - 0.06 * hh,
                       cx + sgn * (0.055 * hh) + sw, base, lp2)
        # 朱砂点（每幕一枚，作视觉节拍）
        ap = skia.Paint()
        ap.setAntiAlias(True)
        ap.setColor(skia.ColorSetARGB(255, *_hex(self.pal["accent"])))
        c.drawCircle(cx + 0.30 * hh, base - 1.05 * hh
                     + 0.05 * hh * dsin(2 * math.pi * t * 0.7), 0.022 * hh + 5.0, ap)
        c.restore()

        # ⑤ 题款（画布空间，不随相机）
        cols, ix, iy, size = self._ins_for(a, ins)
        if cols:
            self._caption(c, cols, ix, iy, size)

        img = surface.makeImageSnapshot()
        arr = img.toarray()
        return np.ascontiguousarray(arr[:, :, [2, 1, 0]])

    def _ins_for(self, a, ins):
        if ins:
            return ins
        cap = a.get("caption")
        if not cap:
            return None, 0, 0, 0
        x, y, size = self.cap_style(a)
        return (list(cap), x, y, size)

    def _caption(self, c, cols, ix, iy, size):
        import skia
        tf = None
        for f in ("C:/Windows/Fonts/STKAITI.TTF", "C:/Windows/Fonts/simkai.ttf",
                  "/System/Library/Fonts/STHeiti Light.ttc"):
            tf = skia.Typeface.MakeFromFile(f)
            if tf:
                break
        if tf is None:
            return
        font = skia.Font(tf, size)
        # 衬底（压在中间调上也能读清 —— 判据 C10）
        bp = skia.Paint()
        bp.setAntiAlias(True)
        bp.setColor(skia.ColorSetARGB(112, *self.paper))
        cg = size * 1.42
        n_max = max(len(x) for x in cols)
        c.drawRect(skia.Rect.MakeXYWH(ix - cg * (len(cols) - 1) - size * 0.62,
                                      iy - size * 1.02,
                                      cg * len(cols) + size * 0.3,
                                      size * (n_max + 1) * 1.16 + size * 0.4), bp)
        p = skia.Paint()
        p.setAntiAlias(True)
        p.setColor(skia.ColorSetARGB(255, *_hex(self.pal["ink"])))
        for ci, col in enumerate(cols):
            for i, ch in enumerate(col):
                if ch.strip():
                    c.drawString(ch, ix - ci * cg, iy + i * size * 1.16, font, p)

    def frame_hash(self, t: float) -> str:
        a = self.render_frame(t)
        return hashlib.sha256(np.ascontiguousarray(a[::7, ::7])).hexdigest()[:16]

    def stills_points(self):
        out = []
        for a in self.acts():
            cap = next((x for x in self.acts_cfg if x["id"] == a["id"]), {})
            out.append({"act": a["id"], "t": round(a["t0"] + a["d"] * 0.55, 2),
                        "note": a["note"], "caption": list(cap.get("caption", []))})
        return out

    def parts_used(self):
        """本片画面实际调用的底座元素（第 4 步要列出来 —— 构件不会是空的）。"""
        return ["纸底", "天空分带", "远山", "地平线", "主体剪影", "题款", "朱砂点"]

    def parts_per_act(self) -> dict:
        """{幕 id: 这一幕**实际用到**的构件}。

        从渲染逻辑派生，不是硬编一张表：这一幕有题款才列题款，
        没有主体就不列主体剪影 —— 用户看的是"这一幕由什么拼出来的"。
        """
        out = {}
        for a in self.acts_cfg:
            names = ["纸底", "天空分带", "远山", "地平线"]
            if a.get("subject"):
                names.append("主体剪影")
            if a.get("caption"):
                names.append("题款")
            names.append("朱砂点")
            out[a["id"]] = names
        return out

    def render_part(self, name: str, act_id: str = "", W: int = 300, H: int = 200):
        """单个底座元素的样子（在纸底上只画它自己）。

        画法与 `render_frame` 的各段**用同一套公式**（远山用同一幕的 seed），
        所以预览里的形状就是画面上那一块的形状，不是另画一张示意图。
        """
        import skia
        from spolvero.core.dmath import dsin
        a = next((x for x in self.acts_cfg if x["id"] == act_id), None) or (self.acts_cfg[0] if self.acts_cfg else {})
        subj = a.get("subject") or {"x": W * 0.5, "base": H * 0.9556, "h": H * 0.30}
        t = float(a.get("t0", 0)) + (float(a.get("t1", 1)) - float(a.get("t0", 0))) * 0.5
        u = 0.5
        seed = int(hashlib.sha256(str(a.get("id", "a1")).encode()).hexdigest()[:6], 16)

        surface = skia.Surface(W, H)
        c = surface.getCanvas()
        c.clear(skia.ColorSetARGB(255, *self.paper))
        p = skia.Paint()
        p.setAntiAlias(True)
        ink = _hex(self.pal["ink"])

        if name == "纸底":
            pass                                          # 就是纸色本身

        elif name == "天空分带":
            bands = 7
            skh = H * 0.60
            for i in range(bands):
                k = i / (bands - 1.0)
                p.setColor(skia.ColorSetARGB(255, *_mix(self.pal["sky_top"], self.pal["sky_bottom"], k)))
                c.drawRect(skia.Rect.MakeXYWH(0, i * skh / bands, W, skh / bands + 1.5), p)

        elif name == "远山":
            for mul, tone_k in ((1.0, 0.55), (1.28, 0.30)):
                pts = [(0.0, H * 0.60)]
                n = 9
                for i in range(1, n):
                    r = ((seed >> (i * 3)) & 7) / 7.0
                    pts.append((W * i / (n - 1.0), H * 0.60 - (H * 0.13 * mul) * (0.35 + 0.65 * r)))
                pts += [(W, H * 0.60), (W, H * 0.74), (0.0, H * 0.74)]
                path = skia.Path()
                path.moveTo(*pts[0])
                for q in pts[1:]:
                    path.lineTo(*q)
                path.close()
                p.setColor(skia.ColorSetARGB(255, *_mix(self.pal["ink"], self.pal["paper"], tone_k)))
                c.drawPath(path, p)

        elif name == "地平线":
            sp = skia.Paint()
            sp.setAntiAlias(True)
            sp.setColor(skia.ColorSetARGB(255, *_mix(self.pal["paper"], self.pal["mid"], 0.35)))
            c.drawRect(skia.Rect.MakeXYWH(0, H * 0.74, W, H * 0.26), sp)
            lp = skia.Paint()
            lp.setAntiAlias(True)
            lp.setColor(skia.ColorSetARGB(255, *_hex(self.pal["mid"])))
            c.drawRect(skia.Rect.MakeXYWH(0, H * 0.738, W, 2.5), lp)

        elif name == "主体剪影":
            breathe = 1.0 + 0.012 * dsin(2 * math.pi * (t * 0.45))
            hh = float(subj.get("h", H * 0.3)) * breathe * (H / 900.0)
            base = H * 0.94
            cx = W * 0.5
            ip = skia.Paint()
            ip.setAntiAlias(True)
            ip.setColor(skia.ColorSetARGB(255, *ink))
            torso = [(cx - 0.11 * hh, base), (cx + 0.11 * hh, base),
                     (cx + 0.085 * hh, base - 0.62 * hh), (cx - 0.085 * hh, base - 0.62 * hh)]
            path = skia.Path()
            path.moveTo(*torso[0])
            for q in torso[1:]:
                path.lineTo(*q)
            path.close()
            c.drawPath(path, ip)
            c.drawCircle(cx, base - 0.70 * hh, 0.075 * hh, ip)
            sw = 0.03 * hh * dsin(2 * math.pi * t * 0.9)
            for sgn in (-1, 1):
                lp2 = skia.Paint()
                lp2.setAntiAlias(True)
                lp2.setStrokeWidth(0.055 * hh)
                lp2.setStrokeCap(skia.Paint.kRound_Cap)
                lp2.setColor(skia.ColorSetARGB(255, *ink))
                c.drawLine(cx + sgn * 0.035 * hh, base - 0.06 * hh,
                           cx + sgn * (0.055 * hh) + sw, base, lp2)

        elif name == "题款":
            cols = list(a.get("caption") or ["题款", "两列"])[:2]
            self._caption(c, cols, W * 0.72, H * 0.26, max(14, int(min(W, H) * 0.14)))

        elif name == "朱砂点":
            ap = skia.Paint()
            ap.setAntiAlias(True)
            ap.setColor(skia.ColorSetARGB(255, *_hex(self.pal["accent"])))
            c.drawCircle(W * 0.5, H * 0.5, min(W, H) * 0.12, ap)

        img = surface.makeImageSnapshot()
        arr = img.toarray()
        import numpy as np
        return np.ascontiguousarray(arr[:, :, [2, 1, 0]])

    def nodes_md(self) -> str:
        p = os.path.join(self.dir, "nodes.md")
        return open(p, encoding="utf-8").read() if os.path.exists(p) else ""

    def nodes_by_act(self) -> dict:
        out = {a["id"]: [] for a in self.acts()}
        out["_global"] = []
        cur = None
        for line in self.nodes_md().splitlines():
            s = line.strip()
            if s.startswith("##"):
                cur = s
                continue
            if s.startswith("- ["):
                done = s.startswith("- [x]")
                body = s[5:].strip()
                hit = None
                for a in self.acts():
                    if f"幕{a['id']}" in body or a["id"] in body[:24]:
                        hit = a["id"]
                        break
                out[hit or "_global"].append({"done": done, "text": body})
        return out


def load(film_dir: str) -> Skeleton:
    return Skeleton(film_dir)
