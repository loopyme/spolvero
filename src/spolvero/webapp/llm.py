"""DeepSeek 客户端 + AI 工具集（SPEC §11）。

零新依赖：HTTP 走 stdlib `urllib.request`。
密钥只存本地 `.spolvero/secrets.json`，日志与提示词里**永不回显**。
无密钥 / 断网 → 控制台进入手工模式，**任何核心功能不得因此不可用**。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request

from . import films as fl
from . import prompts as P

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
CONF_DIR = os.path.join(_ROOT, ".spolvero")
CONF_PATH = os.path.join(CONF_DIR, "secrets.json")
AI_LOG = os.path.join(_ROOT, "logs", "ai")
DEFAULT_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


# ── 配置 ────────────────────────────────────────────────────────────────
def load_conf() -> dict:
    try:
        with open(CONF_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_conf(d: dict) -> dict:
    os.makedirs(CONF_DIR, exist_ok=True)
    cur = load_conf()
    cur.update({k: v for k, v in d.items() if v is not None})
    with open(CONF_PATH, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=2)
    return public_conf()


def public_conf() -> dict:
    """给 UI 的配置视图 —— **只报"有没有密钥"，不回显密钥本身**。"""
    c = load_conf()
    key = c.get("api_key", "")
    return {"base_url": c.get("base_url", DEFAULT_BASE),
            "model": c.get("model", DEFAULT_MODEL),
            "has_key": bool(key),
            "key_hint": (key[:4] + "…" + key[-4:]) if len(key) > 10 else ""}


# ── HTTP ────────────────────────────────────────────────────────────────
def _post(url: str, payload: dict, key: str, timeout: int = 180) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url.rstrip("/") + "/chat/completions", data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _cache_key(payload: dict) -> str:
    core = {k: payload[k] for k in ("model", "messages", "tools", "temperature") if k in payload}
    return hashlib.sha256(json.dumps(core, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _cache_get(k: str):
    p = os.path.join(AI_LOG, "cache", k + ".json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _cache_put(k: str, v: dict) -> None:
    d = os.path.join(AI_LOG, "cache")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, k + ".json"), "w", encoding="utf-8") as f:
        json.dump(v, f, ensure_ascii=False)


def _log(rec: dict) -> None:
    os.makedirs(AI_LOG, exist_ok=True)
    p = os.path.join(AI_LOG, time.strftime("%Y%m%d-%H%M%S-") + rec.get("kind", "call") + ".json")
    rec = {**rec, "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)


# ── 工具集（AI 唯一的手脚，SPEC §11.4）──────────────────────────────────
TOOLS = [
    {"type": "function", "function": {
        "name": "read_project",
        "description": "读当前影片工程：题旨、时长、幕表、色板、题款、原文节点表未完成项",
        "parameters": {"type": "object", "properties": {
            "film": {"type": "string", "description": "影片 id"}}, "required": ["film"]}}},
    {"type": "function", "function": {
        "name": "read_judges",
        "description": "读最近一次判据报告（含三层分类与逐条证据）",
        "parameters": {"type": "object", "properties": {
            "film": {"type": "string"}}, "required": ["film"]}}},
    {"type": "function", "function": {
        "name": "run_judges",
        "description": "跑判据（结构层 + 构成层）。耗时约 1–5 分钟，异步执行，返回任务 id",
        "parameters": {"type": "object", "properties": {
            "film": {"type": "string"}}, "required": ["film"]}}},
    {"type": "function", "function": {
        "name": "render_stills",
        "description": "出关键静帧（真景别 + 题款），返回任务 id；完成后图片会出现在对话里",
        "parameters": {"type": "object", "properties": {
            "film": {"type": "string"}}, "required": ["film"]}}},
    {"type": "function", "function": {
        "name": "render_clip",
        "description": "渲染一个时段的片段（带声），用于快速审某几幕",
        "parameters": {"type": "object", "properties": {
            "film": {"type": "string"},
            "t0": {"type": "number"}, "t1": {"type": "number"}},
            "required": ["film", "t0", "t1"]}}},
    {"type": "function", "function": {
        "name": "patch_film",
        "description": "提交影片工程补丁（幕表/色板/题款/参数）。**必须人确认后才落盘**",
        "parameters": {"type": "object", "properties": {
            "film": {"type": "string"},
            "ops": {"type": "array", "items": {"type": "object"},
                    "description": "JSON Patch 风格：{op:set|add|remove, path, value}"},
            "why": {"type": "string", "description": "一句话说明依据"}},
            "required": ["film", "ops", "why"]}}},
    {"type": "function", "function": {
        "name": "propose_part",
        "description": "提交新构件实现 → parts/pending/，需过检验台四项 + 人采纳",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}, "purpose": {"type": "string"},
            "code": {"type": "string"}}, "required": ["name", "purpose", "code"]}}},
    {"type": "function", "function": {
        "name": "propose_judge",
        "description": "提交新判据实现 → judges/pending/，需先在当前片子跑一遍并展示结果",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}, "rationale": {"type": "string"},
            "code": {"type": "string"}}, "required": ["name", "rationale", "code"]}}},
]


def _nodes_todo(fid: str) -> list[str]:
    try:
        md = fl.load(fid).nodes_md()
    except Exception:
        return []
    return [ln.strip()[5:].strip() for ln in md.splitlines() if ln.strip().startswith("- [ ]")]


def dispatch(name: str, args: dict) -> dict:
    """执行一次工具调用。返回给模型看的结果（**必须是可读的 JSON**）。"""
    fid = args.get("film", "")
    if name == "read_project":
        m = fl.meta(fid)
        return {"title": m["title"], "duration": m["duration"], "fps": m["fps"],
                "acts": [{"id": a["id"], "t0": a["t0"], "t1": a["t1"], "note": a["note"]}
                         for a in m["acts"]],
                "captions": {k: v["cols"] for k, v in (m.get("captions") or {}).items()},
                "nodes_todo": _nodes_todo(fid)}
    if name == "read_judges":
        p = os.path.join(fl.out_dir(fid), "judges.json")
        if not os.path.exists(p):
            return {"error": "还没有判据报告，先调 run_judges"}
        with open(p, encoding="utf-8") as f:
            r = json.load(f)
        bad = [{"id": i["id"], "name": i["name"], "status": i["status"],
                "detail": i["detail"], "fix": i.get("fix", "")}
               for i in r["items"] if i["status"] in ("fail", "warn")]
        return {"summary": r["summary"], "when": r["when"], "problems": bad[:20]}
    if name == "run_judges":
        from .jobs import MANAGER
        j = MANAGER.start("judges", fid, {})
        return {"job": j["id"], "state": "已排入后台，完成后会通知"}
    if name == "render_stills":
        from .jobs import MANAGER
        j = MANAGER.start("stills", fid, {})
        return {"job": j["id"], "state": "已排入后台"}
    if name == "render_clip":
        from .jobs import MANAGER
        j = MANAGER.start("clip", fid, {"t0": float(args["t0"]), "t1": float(args["t1"])})
        return {"job": j["id"], "state": "已排入后台"}
    if name == "patch_film":
        d = os.path.join(_ROOT, "logs", "patches")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, time.strftime("%Y%m%d-%H%M%S") + "-film.json")
        rec = {"film": fid, "ops": args.get("ops", []), "why": args.get("why", ""),
               "state": "pending", "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
        with open(p, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
        return {"state": "已提交待确认", "ops": len(rec["ops"]), "file": os.path.basename(p),
                "note": "人在控制台点「确认」后才落盘"}
    if name == "propose_part":
        d = os.path.join(_ROOT, "parts", "pending")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, str(args["name"]) + ".py")
        with open(p, "w", encoding="utf-8") as f:
            f.write(f'"""构件 {args["name"]} —— 用途：{args.get("purpose","")}\n'
                    f'（AI 提议，待构件检验台四项 + 人采纳）"""\n\n{args.get("code","")}\n')
        return {"state": "已提交待检验", "file": os.path.relpath(p, _ROOT)}
    if name == "propose_judge":
        d = os.path.join(_ROOT, "judges", "pending")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, str(args["name"]) + ".py")
        with open(p, "w", encoding="utf-8") as f:
            f.write(f'"""判据 {args["name"]} —— 依据：{args.get("rationale","")}\n'
                    f'（AI 提议，需先在当前片子跑一遍并展示结果）"""\n\n{args.get("code","")}\n')
        return {"state": "已提交待验证", "file": os.path.relpath(p, _ROOT)}
    return {"error": f"未知工具 {name}"}


# ── 对话（含工具循环）───────────────────────────────────────────────────
def _system_for(role: str) -> str:
    return P.get({"storyboard": "storyboard", "review": "review",
                  "part": "part", "aesthetic": "aesthetic"}.get(role, "storyboard"))


# ── 风格 brief 注入 ──────────────────────────────────────────────────────
# 风格是一段「美学 brief」（写在 styles/<id>/style.yaml 的 prompt: 字段）。
# 选了风格，这一段就追加进所有 AI 顾问的系统提示词，让 AI 在分幕/构件/关键图/视频/
# 声音/成片各环节都按这套美学生成。它的优先级高于上面的通用约束。
def _style_brief(fid: str) -> str:
    if not fid:
        return ""
    try:
        sid = fl.style_of(fid)
        if not sid:
            return ""
        st = fl.load_style(sid) or {}
        return (st.get("prompt") or "").strip()
    except Exception:
        return ""


def _with_style(base: str, fid: str) -> str:
    b = _style_brief(fid)
    if not b:
        return base
    return base.rstrip() + "\n\n【本片风格 · 这条指令高于上面的通用约束，所有生成都按它来】\n" + b + "\n"


def probe(base_url: str = "", model: str = "", api_key: str = "") -> dict:
    """最小连通性探测：发一句 `ping`、`max_tokens=1`。

    只在用户**主动点「测试连接」**时调用（不写缓存、不进留痕），
    否则"测试"本身就会悄悄花钱。密钥只用于本次请求，不落盘、不回显。
    """
    conf = load_conf()
    key = api_key or conf.get("api_key", "")
    base = base_url or conf.get("base_url", DEFAULT_BASE)
    mdl = model or conf.get("model", DEFAULT_MODEL)
    if not key:
        return {"ok": False, "error": "还没有密钥：填进输入框再测，或先保存。"}
    t0 = time.perf_counter()
    payload = {"model": mdl, "messages": [{"role": "user", "content": "ping"}],
               "max_tokens": 1, "stream": False}
    try:
        r = _post(base, payload, key, timeout=20)
    except urllib.error.HTTPError as e:
        code = e.code
        hint = {400: "请求格式不对（模型名？）", 401: "密钥无效或已过期", 402: "余额不足",
                403: "无权访问该模型", 404: "base_url 或模型名不对", 429: "请求过频"}.get(code, "")
        if not hint and 500 <= code < 600:
            hint = "上游不可达（base_url 写错？网络或代理问题？）"
        detail = e.read().decode("utf-8", "ignore")[:200]
        return {"ok": False, "error": f"HTTP {code} {hint}".strip(), "detail": detail, "base_url": base}
    except Exception as e:
        return {"ok": False, "error": f"连不上：{type(e).__name__}: {e}", "base_url": base}
    ms = (time.perf_counter() - t0) * 1000
    ch = (r.get("choices") or [{}])[0]
    return {"ok": True, "model": r.get("model", mdl), "ms": round(ms),
            "reply": (ch.get("message") or {}).get("content", "")[:32],
            "usage": r.get("usage"), "base_url": base}


PLAN_SYSTEM = """你是动画导演与分镜师，为一部**水墨风格的程序化短片**排幕表。

用户只会给一句想法（可能很短、很粗糙）。你要把它变成可执行的幕表。

画幅：宽 {W} × 高 {H} 像素，比例 {RATIO}。{HINT}

只输出一个 JSON 对象，不要输出任何其它文字、不要 Markdown 代码块：
{"title": "片名（4-10 字）",
 "acts": [{"note": "幕名（2-5 字）", "caption": ["上句（4-6 字）", "下句（4-6 字）"],
           "script": ["这一幕要讲的节点", "一句话一个，2-4 条"],
           "dur": 秒数（浮点）, "subject": {"x": {XLO}-{XHI} 的数, "h": {HLO}-{HHI} 的数}}]}

硬约束：
1. 幕数 3–8 幕；每幕 dur ≥ 3 秒；所有 dur 之和 ≈ 目标时长（误差 < 1 秒）。
2. 叙事上要**有起承转合**：第 1 幕交代地点与人，中间 1-2 幕是事件，最后一幕是落点。
   **每一幕都必须有"发生了什么"**，不要出现纯景物幕。
3. **script 是这一幕的剧本**：一条一个具体事件（谁做了什么、发生了什么变化），
   每条 6–16 字，2–4 条；不要写情绪感受、不要写"画面优美"这类评价。
   这是后面画图与剪辑的依据，**漏掉关键事件观众就看不懂**。
4. caption 是题款（文人画式的两列短句），要能提示这一幕的内容，不要写成解说。
5. subject.x 是主体在 {W} 宽画布上的横向位置（左右要有变化，不要都居中）；
   subject.h 是主体高度像素（{H} 高画布，{HLO}–{HHI} 之间）。
6. 不要输出解释、不要输出多余字段。
"""


ADVISE_SYSTEM = """你是这部水墨短片的执行导演。用户刚对**当前这一步**提了意见，你要给出**改动计划**。

只输出一个 JSON 对象，不要输出任何其它文字、不要 Markdown 代码块：
{"understanding": "一句话复述用户要什么（20 字内）",
 "items": [{"kind": "…", "scope": "a3", "detail": "一句人话说清这一项要做什么",
            "patch": {"dur": 8.0}, "text": "改完的剧本内容", "name": "构件名", "code": "python 代码"}]}

kind 只能取这七种，不得自创：
- "script"     改某一幕的剧本 → 必须给 scope 与 text（改完的整段剧本，一行一句）
- "film_patch" 改某一幕的节点表/参数 → 必须给 scope 与 patch。patch 可含：
               dur(秒) / note(幕名) / caption([上句,下句]) /
               h(主体高度像素，即节点表 subject.h) / x(主体横向位置像素，即节点表 subject.x)
- "parts"      造一个可复用构件 → 必须给 name（英文小写）与 code（python）
- "stills"     重画某一幕的关键图 → 必须给 scope
- "clip"       重渲某一幕的视频 → 必须给 scope
- "sound"      重出声轨（整片一条，不指名幕）
- "film"       重新合成全片

规矩：
1. **只列确实要动的项**。用户只说了一处，就别顺带改别的幕。
2. 凡改了某一幕的画面相关参数（剧本/节点表/构件），**必须同时**列出该幕的 stills（关键图会过时）；
   若用户明确要看视频，再加 clip。
2a. **在「关键图」这一步提的构图意见（人太小 / 题款压住主体 / 焦点不清 / 位置不对 / 留白不对），
    必须同时给两件事**：① 改这一幕的「节点表」—— film_patch 带 h（主体更高）或 x（主体挪位）或
    caption（题款移开主体）；② 重画这一幕 —— stills。**只重画不改节点表等于没改**：
    重画用的是同一套节点参数，画出来还是老样子。
2b. 凡改了幕长（film_patch 带 dur），声轨落点会全变 → **必须同时**列 sound。
2c. **在「视频」这一步提的构图意见，除了 stills 还要加 clip** —— 视频用的也是旧构图，
    只重画关键图不重渲视频＝视频还是老样子。
3. detail 是给人读的一句话，不要写"我将要""建议"之类的话，直接说做什么。
4. 改动要落到**具体幕 id**（a1、a2…）上，不要写"全部幕"。
5. 拿不准就不要列这一项；宁少不多。
"""


def plan_advice(ctx: str, text: str, fid: str = "") -> dict:
    """一句意见 → 改动计划（**不执行**）。没密钥时返回可解释的空计划。"""
    conf = load_conf()
    key = conf.get("api_key", "")
    if not key:
        return {"ok": False, "mode": "manual",
                "error": "未配置 AI 密钥 —— 手工模式下请直接改剧本/幕表，或用右侧的阶段按钮。"}
    payload = {"model": conf.get("model", DEFAULT_MODEL),
               "messages": [{"role": "system", "content": _with_style(ADVISE_SYSTEM, fid)},
                            {"role": "user", "content": ctx + "\n\n用户的意见：\n" + text}],
               "temperature": 0.3, "response_format": {"type": "json_object"}}
    try:
        r = _post(conf.get("base_url", DEFAULT_BASE), payload, key, timeout=120)
        _log({"kind": "advise", "usage": r.get("usage")})
        data = _loads(((r.get("choices") or [{}])[0].get("message") or {}).get("content", ""))
        return {"ok": True, "plan": data}
    except Exception as e:
        return {"ok": False, "error": f"没能给出计划：{type(e).__name__}: {str(e)[:160]}"}


def _size_hint(W: int, H: int) -> str:
    """把画幅翻译成构图指令 —— 同一部片子在竖屏与宽银幕上是两种构图。"""
    r = W / max(1.0, float(H))
    if r < 0.9:
        return ("这是**竖屏**：横向空间窄，主体 x 只能在画面中段小幅变化（别指望左右大横移），"
                "层次靠上下远近叠压来分；题款落在画面上部。")
    if r < 1.3:
        return "这是接近**方形**的画幅：主体居中或偏侧都可以，注意四边不要顶满。"
    if r > 2.0:
        return ("这是**宽银幕**：横向长卷，主体可以横向拉开很大距离，"
                "左右两端适合留白，纵向别堆东西。")
    return "这是**常规横屏**：主体可在左右 2/3 的范围内移动，横向留白与主体对歌。"


def _plan_system(W: int, H: int, ratio: str) -> str:
    return (PLAN_SYSTEM
            .replace("{W}", str(int(W))).replace("{H}", str(int(H)))
            .replace("{RATIO}", ratio or f"{int(W)}:{int(H)}")
            .replace("{HINT}", _size_hint(W, H))
            .replace("{XLO}", str(int(W * 0.075))).replace("{XHI}", str(int(W * 0.925)))
            .replace("{HLO}", str(int(H * 0.17))).replace("{HHI}", str(int(H * 0.44))))


def plan_film(idea: str, duration: float, n_acts: int = 0,
              size=(1600, 900), ratio: str = "", fid: str = "") -> dict:
    """把一句想法变成幕表。有 AI 用 AI，没 AI 走规则降级 —— **功能不得因缺 AI 而不可用**。

    `size` 必传：AI 排的是**这个画幅下**的幕表 —— 主体位置与主体高度都不是无量纲的数，
    换个画幅同一套数字就不再成立。
    """
    W, H = int(size[0]), int(size[1])
    conf = load_conf()
    key = conf.get("api_key", "")
    hint = f"目标时长 {duration:.0f} 秒。" + (f"幕数约 {n_acts} 幕。" if n_acts else "")
    if key:
        payload = {"model": conf.get("model", DEFAULT_MODEL),
                   "messages": [{"role": "system", "content": _with_style(_plan_system(W, H, ratio), fid)},
                                {"role": "user", "content": f"想法：{idea}\n{hint}"}],
                   "temperature": 0.7, "response_format": {"type": "json_object"}}
        try:
            r = _post(conf.get("base_url", DEFAULT_BASE), payload, key, timeout=120)
            _log({"kind": "plan", "usage": r.get("usage"), "size": [W, H]})
            text = ((r.get("choices") or [{}])[0].get("message") or {}).get("content", "")
            data = _loads(text)
            acts = _sanitize(data.get("acts") or [], duration, n_acts, W, H)
            if acts:
                return {"ok": True, "source": "ai", "title": (data.get("title") or "").strip(),
                        "acts": acts}
        except Exception as e:
            _log({"kind": "plan", "error": str(e)[:200]})
    return {"ok": True, "source": "rule", **_rule_plan(idea, duration, n_acts, W, H)}


def _loads(text: str) -> dict:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("```")[1]
        t = t[t.find("{"):]
    i, j = t.find("{"), t.rfind("}")
    return json.loads(t[i:j + 1]) if i >= 0 and j > i else {}


def replan_film(fid: str, idea: str, duration: float = 0.0, n_acts: int = 0) -> dict:
    """重排已有影片的幕表（第 2 步「故事 → 自动分幕」的入口）。

    **幕表一改，时间轴就变了**：已有的关键图/视频全部作废（时刻对不上）。
    所以这里排完幕表会自动把下游产物标为失效，而不是留一堆对不上的旧图。
    """
    from . import pipeline as P
    m = fl.meta(fid)
    W, H = m["size"]
    ratio = m.get("ratio", "")
    dur = float(duration or m["duration"] or 24.0)
    plan = plan_film(idea, dur, n_acts, size=(W, H), ratio=ratio, fid=fid)
    acts = plan.get("acts") or []
    if not acts:
        raise ValueError("没能排出幕表")
    fl.write_acts(fl.film_dir(fid), acts, title=m["title"], source=m.get("source", ""),
                  fps=m["fps"], size=(W, H), ratio=ratio)
    fl.write_nodes(fl.film_dir(fid), m["title"], acts, idea=idea)   # 每幕的剧本跟着重排
    P.invalidate_all(fid, "幕表已重排，时间轴变了")
    return {"ok": True, "source": plan.get("source"), "acts": len(acts),
            "duration": sum(float(a["dur"]) for a in acts), "meta": fl.meta(fid)}


def _rule_plan(idea: str, duration: float, n_acts: int, W: int = 1600, H: int = 900) -> dict:
    """无 AI 时的降级：按"起承转合"切，并把想法里的短句用作幕名。"""
    import re
    if n_acts <= 0:
        n_acts = max(3, min(8, int(round(duration / 6.0))))
    parts = [s.strip() for s in re.split(r"[，,。；;、\s]+", idea or "") if s.strip()]
    default_notes = ["起", "承", "转", "合", "再转", "再合", "收", "尾"]
    acts = []
    for i in range(n_acts):
        note = (parts[i][:5] if i < len(parts) and len(parts[i]) <= 8 else default_notes[i % len(default_notes)])
        # 没有 AI 时，剧本用故事里对应的那句顶上 —— 至少不是空的
        scr = [parts[i][:20]] if i < len(parts) and parts[i] else []
        acts.append({"note": note or default_notes[i % len(default_notes)],
                     "caption": [note or default_notes[i], f"第{i + 1}段"],
                     "script": scr,
                     "dur": round(duration / n_acts, 2),
                     "subject": {"x": W * [0.31, 0.50, 0.69, 0.50][i % 4],
                                 "base": H * 0.9556,
                                 "h": H * (0.27 + 0.03 * (i % 4))}})
    return {"title": (parts[0][:10] if parts else "未命名"), "acts": acts}


def _sanitize(acts: list, duration: float, n_acts: int, W: int = 1600, H: int = 900) -> list:
    """把 AI 返回的幕表收拾成合法值：**时长必须归一化到目标总长**，否则片长会跑掉。

    位置与高度的合法区间按**当前画幅**算 —— 竖屏把 x 限制在 120–1480
    就等于允许主体跑到画外去。
    """
    xlo, xhi = W * 0.075, W * 0.925
    hlo, hhi = H * 0.17, H * 0.44
    out = []
    for k, a in enumerate(acts[:8]):
        try:
            d = float(a.get("dur", 0) or 0)
        except Exception:
            d = 0.0
        if d < 3.0:
            d = 3.0
        sub = a.get("subject") or {}
        try:
            x = float(sub.get("x", W * 0.5))
        except Exception:
            x = W * 0.5
        try:
            hh = float(sub.get("h", H * 0.28))
        except Exception:
            hh = H * 0.28
        cap = a.get("caption") or []
        cap = [str(c)[:8] for c in cap[:2]] or [str(a.get("note", ""))[:6], f"第{k + 1}段"]
        scr = [str(x).strip()[:20] for x in (a.get("script") or []) if str(x).strip()][:4]
        out.append({"note": str(a.get("note", f"第{k + 1}段"))[:8],
                    "caption": cap, "script": scr, "dur": d,
                    "subject": {"x": min(xhi, max(xlo, x)),
                                "base": H * 0.9556,
                                "h": min(hhi, max(hlo, hh))}})
    if not out:
        return []
    total = sum(a["dur"] for a in out)
    if total <= 0:
        return []
    k = duration / total                      # 归一化：总长必须等于目标
    for a in out:
        a["dur"] = round(a["dur"] * k, 2)
    return out


def guess_role(messages: list[dict]) -> str:
    """role="auto" 时的规则判断（不额外花钱、不需要模型自己选）。

    判据很粗，但**够用且可预期**：用户说"哪儿不对"就是要复盘，
    说"造个东西"就是要构件，说"看看"就是要审片，其余默认分镜。
    """
    text = " ".join(str(m.get("content", "")) for m in messages
                    if m.get("role") == "user")[-900:]
    if any(k in text for k in ("判据", "失败", "不对", "太快", "太慢", "没表达", "遮住",
                              "太小", "重叠", "跳", "断", "改一下", "调一下", "修")):
        return "review"
    if any(k in text for k in ("构件", "造一个", "加一个道具", "新画", "怎么画", "重画")):
        return "part"
    if any(k in text for k in ("看看", "形容", "描述", "你觉得", "评价")):
        return "aesthetic"
    return "storyboard"


def chat(messages: list[dict], role: str = "storyboard", max_tool_rounds: int = 3,
         fid: str = "") -> dict:
    """一次对话（内部最多 3 轮工具调用）。返回 {ok, content, tool_calls, error}。"""
    if role == "auto":
        role = guess_role(messages)
    conf = load_conf()
    key = conf.get("api_key", "")
    model = conf.get("model", DEFAULT_MODEL)
    base = conf.get("base_url", DEFAULT_BASE)
    msgs = [{"role": "system", "content": _with_style(_system_for(role), fid)}] + list(messages)
    if not key:
        return {"ok": False, "error": "未配置 API 密钥 —— 控制台处于手工模式，"
                                      "分镜表可直接在网页上编辑，判据与渲染照常可用。",
                "content": "", "tool_calls": [], "mode": "manual"}
    calls: list[dict] = []
    for rnd in range(max_tool_rounds):
        payload = {"model": model, "messages": msgs, "tools": TOOLS,
                   "tool_choice": "auto", "temperature": 0.4}
        ck = _cache_key(payload)
        resp = _cache_get(ck)
        if resp is None:
            try:
                resp = _post(base, payload, key)
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "ignore")[:300]
                return {"ok": False, "error": f"API {e.code}：{detail}", "content": "", "tool_calls": calls}
            except Exception as e:
                return {"ok": False, "error": f"网络错误：{e}", "content": "", "tool_calls": calls}
            _cache_put(ck, resp)
        _log({"kind": role, "round": rnd, "model": model,
              "usage": resp.get("usage"), "tool_calls": len(calls)})
        msg = (resp.get("choices") or [{}])[0].get("message") or {}
        tcs = msg.get("tool_calls") or []
        if not tcs:
            return {"ok": True, "content": msg.get("content", ""), "tool_calls": calls}
        msgs.append({"role": "assistant", "content": msg.get("content") or "",
                     "tool_calls": tcs})
        for tc in tcs:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            try:
                a = json.loads(fn.get("arguments") or "{}")
            except Exception:
                a = {}
            try:
                result = dispatch(name, a)
            except Exception as e:
                result = {"error": f"{type(e).__name__}: {e}"}
            calls.append({"name": name, "args": a, "result": result})
            msgs.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                         "content": json.dumps(result, ensure_ascii=False)[:4000]})
    return {"ok": True, "content": "（已达工具调用轮次上限，先看上面几张卡的结果再继续）",
            "tool_calls": calls}
