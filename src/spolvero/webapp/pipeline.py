"""七步流水线的状态聚合（SPEC §17）—— **界面只读这里，不自己拼业务判断**。

为什么要单独一层：界面上每一步要显示的"做完了没有、产物在哪、检验过没有、
有没有因为构件改动而失效"，都是**派生状态**。如果让前端自己拼，
就会散出七八处"两个地方各算一遍"的缺陷（§3 派生约束）。

七步 —— 每一步都回答三件事：**这一步解决什么 / 人在这里看什么 / 脚本判什么**。
  1 立项 · 画幅     定死画幅（构图参数的根）
  2 分幕 · 剧本     拆成幕 + 逐幕写清"讲什么"（剧本并进分幕，不再单列一步）
  3 构件 · 生成     造可复用的对象
  4 关键图          每幕一张静帧，先把构图定死
  5 视频            每幕动起来（只看画面）
  6 声音            配声轨与音效落点（时长从幕表派生）
  7 成片            各幕接成一条片，声画合一

顺序为什么是这样：**先定尺子（画幅）→ 再定讲什么（幕/剧本）→ 再造零件（构件）
→ 再看静帧（构图）→ 再让它动（画面）→ 再配声（声音）→ 最后合成**。
前一步没定死就往下走，等于把返工推迟到更贵的地方（改画幅＝全部幕重排；
构图没定就渲染，等于用 30 倍的时间看同一个错误）。
"""

from __future__ import annotations

import hashlib
import json
import os
import time

from . import films as fl

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
PARTS_DIR = os.path.join(_ROOT, "parts")
PENDING = os.path.join(PARTS_DIR, "pending")
CUSTOM = os.path.join(PARTS_DIR, "custom")

# 每一步三件事：**goal 这一步解决什么 / human 人在这里看什么 / check 脚本判什么**。
# check 里写的是判据编号与名字，界面直接显示 —— 让人知道"自动检验到底在查什么"。
STEPS = [
    {"n": 1, "key": "project", "name": "立项",
     "goal": "定死画幅与帧率 —— 主体落点、题款字号、景别全部由它派生",
     "human": ["画幅对不对（横屏 / 竖屏 / 宽银幕 / 斗方）",
               "总时长够不够讲完这件事",
               "片名与出处写对没有"],
     "check": ["画幅比例与像素一致（改画幅＝全部幕重排）"],
     "ask": "画幅一改等于全部幕重排，只在另起一部片时回这一步"},
    {"n": 2, "key": "story", "name": "分幕",
     "goal": "把故事拆成幕，并逐幕写清「这一幕讲什么」—— 分几幕与每幕讲什么是同一件事",
     "human": ["幕是不是按事件切（不是把时间均分）",
               "每一幕讲什么，能不能一句话说清",
               "题款两句是不是这一幕的点睛，而不只是标题",
               "幕长分配：重音的幕该长，过场的幕该短"],
     "check": ["C13 叙事节点齐备：剧本里的事，画面上有没有"],
     "ask": "幕数/时长不对，或某一幕讲什么没写清"},
    {"n": 3, "key": "parts", "name": "构件",
     "goal": "造可复用的对象（人 / 器物 / 山石 / 房屋）—— 造一次，同类一次成",
     "human": ["画面上还缺什么对象（缺了就造，别用现成的糊）",
               "造出来的形对不对（看几何预览）",
               "采纳前想清楚：它会被后面每一幕复用"],
     "check": ["脚本不判形状好坏 —— 只保证构件可被渲染与预览"],
     "ask": "要造画面上还没有的新对象"},
    {"n": 4, "key": "stills", "name": "关键图",
     "goal": "每幕一张静帧 —— 在看动画之前，先把构图定死",
     "human": ["主体够不够大：占画高 1/4 以上才读得出在干什么",
               "一眼看过去，焦点是不是只有一个（墨量铺匀＝没焦点）",
               "题款有没有压住主体、看不看得清",
               "留白是空得没东西，还是空得有意味",
               "这一幕要讲的那件事，图上能不能看出来"],
     "check": ["S3 帧互异", "S4 确定性", "S5 时长与帧数", "S7 亮度闪烁",
               "C1 深色存在性", "C2 明度分层", "C10 题款可读", "C13 叙事节点齐备"],
     "ask": "看图说话：人太小、太白、题款压住主体、看不懂在干什么"},
    {"n": 5, "key": "clips", "name": "视频",
     "goal": "每幕动起来 —— 这一步只看画面，声音在下一步",
     "human": ["动幅够不够（位移以画布宽度为度量，不做像素级微动）",
               "镜头推进是不是呆滞（匀速、无停顿、轴心不动＝呆）",
               "有没有跳帧、闪一下、边缘抖得脏",
               "这一幕的节奏：起 — 做 — 收，清不清楚"],
     "check": ["C3 主体尺度（逐幕）", "C8 帧间连续性（逐幕）", "C9 视觉节拍"],
     "ask": "动得太快/太慢、镜头呆滞、跳帧"},
    {"n": 6, "key": "sound", "name": "声音",
     "goal": "配声轨与音效落点 —— 时长从幕表派生，不写死秒数",
     "human": ["每一幕有没有该有的声音（整幕静音＝这一幕没配）",
               "声音落点对不对（斧落下去的那一拍要有声）",
               "响度：听不听得见，有没有爆音",
               "开头不突然、结尾收得住"],
     "check": ["S6 声轨时长＝幕表时长", "S8 响度与削顶", "S9 声画帧数一致"],
     "ask": "哪一幕该有什么声音、声音太大/太小、落点不对"},
    {"n": 7, "key": "film", "name": "成片",
     "goal": "各幕接成一条片，声画合一",
     "human": ["幕与幕的接缝生不生硬",
               "整片的节奏：哪一段拖、哪一段赶",
               "声音与画面有没有错位（落点而非口型）"],
     "check": ["全部结构层与构成层判据", "S6 / S8 / S9 声画同步"],
     "ask": "整体节奏、段落衔接、要不要压几秒"},
]

# 判据归到哪一步 —— 检验结果**贴着产物显示**，不是另开一个面板。
# 注意：这里只列**脚本能判死**的项；上面每步的 `human` 是人工看的，脚本不判。
CHECK_OF = {
    "2": ("C13",),
    "4": ("S3", "S4", "S5", "S7", "C1", "C2", "C10", "C13"),
    "5": ("C3", "C8", "C9"),
    "6": ("S6", "S8", "S9"),
    "7": ("S3", "S4", "S5", "S7", "S6", "S8", "S9", "C1", "C2", "C3", "C8", "C9", "C10", "C13"),
}


# ── 小工具 ──────────────────────────────────────────────────────────────
def _read_json(p: str, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(p: str, obj) -> None:
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _size_of(fid: str, rel: str) -> float:
    p = os.path.join(fl.out_dir(fid), rel)
    try:
        return round(os.path.getsize(p) / 1048576, 2)
    except Exception:
        return 0.0


def _exists(fid: str, rel: str) -> bool:
    return os.path.exists(os.path.join(fl.out_dir(fid), rel))


# ── 构件：指纹与失效传播 ────────────────────────────────────────────────
def parts_fingerprint() -> str:
    """构件库指纹（名字 + 修改时间 + 大小）。

    用途只有一个：**判断"已有产物是不是靠旧构件画出来的"**。
    构件一改，靠它画的关键图/视频就都不算数了 —— 这一步必须自动发生，
    不能指望用户记得"我改过构件，得重出图"。
    """
    h = hashlib.sha256()
    if os.path.isdir(PARTS_DIR):
        for root, _dirs, files in os.walk(PARTS_DIR):
            for fn in sorted(files):
                if not fn.endswith(".py") or fn.startswith("_"):
                    continue
                p = os.path.join(root, fn)
                h.update(os.path.relpath(p, PARTS_DIR).replace("\\", "/").encode())
                h.update(str(int(os.path.getmtime(p))).encode())
                h.update(str(os.path.getsize(p)).encode())
    return h.hexdigest()[:12]


def _mtime_of(p: str) -> int:
    try:
        return int(os.path.getmtime(p))
    except Exception:
        return 0


# 渲染器版本号：**改了画面怎么画就把它加一**。
# 不用文件 mtime，是因为给渲染器加一个只读接口（不改变任何像素）也会让 mtime 变，
# 那会把所有已有画面无辜清掉 —— 指纹只该对"真正会改变画面的东西"敏感。
ENGINE_REV = 3


def engine_fingerprint(fid: str = "") -> str:
    """渲染器指纹：**显式版本号**。画面画法变了就把 `ENGINE_REV` 加一，
    已有的关键图与视频会立刻自动失效，不会出现"看着是最新的、其实是旧画法"。
    """
    return f"rev{ENGINE_REV}"


def _part_head(p: str) -> str:
    """取构件文件头的说明行（第一段非空注释），给界面看"它是干什么的"。"""
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            txt = f.read(600)
    except Exception:
        return ""
    for line in txt.splitlines():
        s = line.strip().strip('"').strip()
        if s and not s.startswith(("from", "import", "#!", '"""')):
            return s[:80]
    return ""


def engine_parts() -> list[dict]:
    """引擎里已注册的构件（`PATTERN_REGISTRY`）。

    **不可能"没有构件"**：画面上的远山、水、月、舟都是构件级的元素，
    只是它们是引擎内置的。列出来用户才知道手上有什么、能改什么。
    """
    try:
        import spolvero.components          # noqa: F401  触发内置构件注册
        from spolvero.core.component import PATTERN_REGISTRY
        return [{"name": k, "kind": "engine"} for k in sorted(PATTERN_REGISTRY)]
    except Exception:
        return []


def used_parts(fid: str) -> list[str]:
    """本片渲染**实际调用**的底座元素（由 adapter 自报，缺省用骨架那份）。"""
    base = ["纸底", "天空分带", "远山", "地平线", "主体剪影", "题款", "朱砂点"]
    try:
        mod = fl.load(fid)
        if hasattr(mod, "parts_used"):
            v = mod.parts_used()
            if v:
                return list(v)
    except Exception:
        pass
    return base


def act_parts(fid: str, aid: str) -> list[str]:
    """这一幕用到的构件（由 adapter 按渲染逻辑自报，缺省退回底座清单）。"""
    try:
        mod = fl.load(fid)
        fn = getattr(mod, "parts_per_act", None)
        if callable(fn):
            v = fn()
            if isinstance(v, dict) and v.get(aid):
                return list(v[aid])
    except Exception:
        pass
    return used_parts(fid)


# 工作台只暴露 2 个内置风格：「当前的」(eastern_minimal/彩色水墨) 与「参照的」(film15s/蚀刻梦境)。
# 风格 = 一段注入 AI 顾问提示词的美学 brief（见 llm.py _with_style），也驱动整片调色板。
# styles/ 目录里其余风格数据仍在（核心渲染器的内置预设也引用它们），不破测试，只是工作台不展示。
WORKBENCH_PRESETS = ["eastern_minimal", "film15s"]


def styles() -> list[dict]:
    """工作台内置风格预设（白名单收敛为 2）。

    风格是整片视觉基调 + 一段注入 AI 顾问的美学 brief。选了即影响所有环节的生成与配色。
    """
    ids = set(fl.style_ids())
    return [fl.style_summary(s) for s in WORKBENCH_PRESETS if s in ids]


def parts(fid: str = "") -> dict:
    items = []
    for state, d in (("pending", PENDING), ("custom", CUSTOM)):
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".py") or fn.startswith("_"):
                continue
            p = os.path.join(d, fn)
            items.append({
                "name": fn[:-3], "state": state,
                "file": f"parts/{state}/{fn}", "head": _part_head(p),
                "bytes": os.path.getsize(p),
                "when": time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(p))),
            })
    eng = engine_parts()
    for e in eng:
        e["preview"] = f"/api/parts/preview/{e['name']}.svg"      # 引擎构件：几何预览
    used = used_parts(fid) if fid else []
    # 单元素预览：渲染器若提供 render_part 就用它；否则回退到代表性缩略图（partpreview.used_png）。
    # 无论如何都给 URL，前端不再出现"只有名字没图"的死格。
    cur_style = fl.style_of(fid) if fid else ""
    return {"items": items, "fingerprint": parts_fingerprint(),
            "engine": eng,
            "styles": styles(), "style": cur_style,
            "used": [{"name": n, "preview": f"/api/parts/used/{fid}/{n}.png"}
                     for n in used],
            "used_names": used,
            "base_preview": f"/api/parts/base/{fid}" if fid else "",
            "dir": os.path.relpath(PARTS_DIR, _ROOT)}


def approve_part(name: str) -> dict:
    """采纳构件：pending → custom，并**作废所有靠旧构件产出的画面**。"""
    name = os.path.basename(str(name)).replace(".py", "")
    src = os.path.join(PENDING, name + ".py")
    if not os.path.exists(src):
        raise KeyError(f"没有这个待采纳构件：{name}")
    os.makedirs(CUSTOM, exist_ok=True)
    dst = os.path.join(CUSTOM, name + ".py")
    os.replace(src, dst)
    # 依赖它的产物**自动重置**（不删文件，只作废指针：历史仍可查，但"当前"不再是它）
    touched = []
    for fid in fl.film_ids():
        if _invalidate(fid)[0]:
            touched.append(fid)
    return {"ok": True, "name": name, "file": os.path.relpath(dst, _ROOT),
            "invalidated_films": touched}


def drop_part(name: str, state: str = "pending") -> dict:
    name = os.path.basename(str(name)).replace(".py", "")
    d = PENDING if state == "pending" else CUSTOM
    p = os.path.join(d, name + ".py")
    if not os.path.exists(p):
        raise KeyError(f"没有这个构件：{name}")
    os.replace(p, p + ".dropped")          # 改名保留，不硬删（用户可能只是想先放一边）
    touched = []
    for fid in fl.film_ids():
        if _invalidate(fid)[0]:
            touched.append(fid)
    return {"ok": True, "name": name, "invalidated_films": touched}


def _invalidate(fid: str) -> tuple[bool, dict]:
    """构件变了：给这部片记一条说法。

    **真正的失效判断不在这里** —— `act_signature` 里有构件指纹，构件一改指纹就对不上，
    界面自然显示该重做。这里只负责留一句人话给用户看。
    """
    d = read_deps(fid)
    if not any(k in d for k in ("stills", "clip", "film", "sound")):
        return False, d
    invalidate_all(fid, "构件库已改动，靠它画的关键图与视频需要重做")
    return True, read_deps(fid)


# ── 状态聚合 ────────────────────────────────────────────────────────────
def _files_of(fid: str, cur: dict, kind: str, act_aware: bool = True) -> list[dict]:
    rec = cur.get(kind) or {}
    out = []
    for it in rec.get("files", []):
        if not _exists(fid, it["file"]):
            continue
        out.append({"file": it["file"], "url": f"/out/{fid}/{it['file']}",
                    "name": it.get("name", os.path.basename(it["file"])),
                    "act": it.get("act", "") if act_aware else "",
                    "note": it.get("note", ""), "t": it.get("t"),
                    "mb": _size_of(fid, it["file"]),
                    "when": rec.get("when", "")})
    return out


def _checks(rep: dict | None, keys: tuple) -> dict | None:
    if not rep:
        return None
    items = [i for i in (rep.get("items") or []) if i.get("id") in keys]
    bad = [i for i in items if i["status"] in ("fail", "warn")]
    return {"when": rep.get("when"), "scope": rep.get("scope"),
            "summary": rep.get("summary"), "items": items, "problems": bad}


def _ratio(size) -> str:
    """老影片没写 ratio 时，从像素回推一个可读的比例名（不逼用户去补字段）。"""
    try:
        return fl._ratio_label(int(size[0]), int(size[1]))
    except Exception:
        return ""


def _film_cfg(fid: str) -> dict:
    p = os.path.join(fl.film_dir(fid), "film.yaml")
    if not os.path.exists(p):
        return {}
    try:
        import yaml
        with open(p, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def act_signature(fid: str, kind: str, aid: str) -> str:
    """**这一幕这里的这一版**的输入指纹。

    含什么：该幕的参数（时段/题款/主体）、题款落点、画幅与 fps、色板、构件指纹、渲染器指纹。
    不含什么：别的幕的任何东西 —— 改第三幕不该让第一幕重渲。

    这就是"不要增加工作量"的落点：**依赖没变就复用，一个字都不多渲。**
    """
    m = fl.meta(fid)
    a = next((x for x in (m.get("acts") or []) if x["id"] == aid), {})
    cap = (m.get("captions") or {}).get(aid, {})
    payload = {
        "film": fid, "kind": kind, "act": a, "cap": cap,
        "size": m.get("size"), "fps": m.get("fps"),
        "palette": _film_cfg(fid).get("palette") or {},
        "parts": parts_fingerprint(),
        "engine": engine_fingerprint(fid),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     default=str).encode()).hexdigest()[:16]


def film_signature(fid: str, kind: str = "film") -> str:
    """整片：所有幕的指纹之和（改动任何一幕，整片就该重合成）。"""
    ids = [a["id"] for a in (fl.meta(fid).get("acts") or [])]
    return hashlib.sha256("|".join(act_signature(fid, kind, i) for i in ids).encode()).hexdigest()[:16]


def film_sig(fid: str, kind: str = "film") -> str:
    """整片级产物（成片 / 声轨）登记在 `deps[kind]["film"]["sig"]` 下 —— 只有一处真相。

    踩过的坑：`mark_film()` 写在 `"film"` 子键里，而读的地方写成了 `deps[kind]["sig"]`，
    两处对不上 → 声轨永远"不算数"，每点一次就重出一遍。读法只在这里定义一次。
    """
    return ((read_deps(fid).get(kind) or {}).get("film") or {}).get("sig", "")


def is_film_fresh(fid: str, kind: str = "film", files: list | None = None) -> bool:
    sig = film_sig(fid, kind)
    if not sig or sig != film_signature(fid, kind):
        return False
    return True if files is None else bool(files)


def deps_path(fid: str) -> str:
    return os.path.join(fl.out_dir(fid), "deps.json")


def read_deps(fid: str) -> dict:
    return _read_json(deps_path(fid), {})


def mark_act(fid: str, kind: str, aid: str, extra: dict | None = None) -> None:
    """产物落盘时登记：**这一幕这一版是靠什么画出来的**。"""
    d = read_deps(fid)
    d["version"] = 2
    node = d.setdefault(kind, {})
    node.pop("invalid", None)            # 老格式的字段清掉，避免两处真相
    node.pop("parts_fp", None)
    acts = node.setdefault("acts", {})
    rec = {"sig": act_signature(fid, kind, aid),
           "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    rec.update(extra or {})
    acts[aid] = rec
    _write_json(deps_path(fid), d)


def mark_film(fid: str, kind: str = "film", extra: dict | None = None) -> None:
    d = read_deps(fid)
    d["version"] = 2
    rec = {"sig": film_signature(fid, kind), "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    rec.update(extra or {})
    d.setdefault(kind, {})["film"] = rec
    _write_json(deps_path(fid), d)


def is_fresh(fid: str, kind: str, aid: str, files: list | None = None) -> bool:
    """这一幕的这一版还算数吗？—— 指纹对得上，而且东西还在。"""
    rec = ((read_deps(fid).get(kind) or {}).get("acts") or {}).get(aid)
    if not rec or rec.get("sig") != act_signature(fid, kind, aid):
        return False
    if files is not None and not files:
        return False
    return True


def fresh_map(fid: str, kind: str) -> dict:
    """{幕 id: 还算不算数}（界面与任务都读它，不各自算一遍）。"""
    return {a["id"]: is_fresh(fid, kind, a["id"]) for a in (fl.meta(fid).get("acts") or [])}


def clear_act(fid: str, kind: str, aid: str) -> dict:
    """清空某一幕的某一版产物（取消勾选时用）。

    为什么是"清空"而不是"留着旧的"：用户取消勾选，意思往往是
    **"这一幕先空着，等我调完构件再说"** —— 留着一张过时的图，
    反而会被当成"已经做好了"。所以把指针和依赖记录一起撤掉，界面显示"未出"。
    """
    o = fl.out_dir(fid)
    # ① 当前指针里去掉这一幕
    p = os.path.join(o, "current.json")
    cur = _read_json(p, {})
    rec = cur.get(kind) or {}
    keep = [x for x in (rec.get("files") or []) if x.get("act") != aid]
    if rec:
        rec["files"] = keep
        cur[kind] = rec
        _write_json(p, cur)
    # ② 依赖记录里去掉这一幕
    dp = deps_path(fid)
    d = read_deps(fid)
    node = d.get(kind) or {}
    if (node.get("acts") or {}).pop(aid, None) is not None:
        _write_json(dp, d)
    return {"ok": True, "act": aid, "kind": kind, "kept": len(keep)}


def sweep(fid: str) -> dict:
    """把**已经不算数**的产物清掉（不是留着标"该重做"）。

    用户改了一幕的时长，那一刻的旧图就是废的：留在界面上只会让人以为"已经有了"。
    所以凡是依赖变了的，一律从"当前"里撤掉（文件仍留在 `out/runs/` 的历史批次里，可查但不冒充当前）。
    """
    gone = []
    for kind in ("stills", "clip"):
        for aid in (fl.meta(fid).get("acts") and [a["id"] for a in fl.meta(fid)["acts"]] or []):
            rec = ((read_deps(fid).get(kind) or {}).get("acts") or {}).get(aid)
            if rec and rec.get("sig") != act_signature(fid, kind, aid):
                clear_act(fid, kind, aid)
                gone.append(f"{kind}:{aid}")
    d = read_deps(fid)
    # 整片级：声轨与成片都是"所有幕之和"，任一幕改了就该重做
    for kind in ("film", "sound"):
        if film_sig(fid, kind) and not is_film_fresh(fid, kind):
            o = fl.out_dir(fid)
            cur = _read_json(os.path.join(o, "current.json"), {})
            cur.pop(kind, None)
            _write_json(os.path.join(o, "current.json"), cur)
            d.pop(kind, None)
            _write_json(deps_path(fid), d)
            gone.append(kind)
    return {"ok": True, "cleared": gone}


def mark_built(fid: str, kind: str, extra: dict | None = None) -> None:
    """兼容旧调用：不指名幕时，按"整片"登记。"""
    mark_film(fid, kind, extra)


def invalidate_all(fid: str, reason: str) -> dict:
    """显式作废（幕表重排时用）。

    注意：多数情况下**不需要它** —— 幕表一改，`act_signature` 自然就对不上了。
    留着是为了让"重排幕表"这件事在界面上有个明确的说法（红栏里写明原因）。
    """
    p = deps_path(fid)
    d = read_deps(fid)
    d.setdefault("notes", {})["invalidated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    d["notes"]["invalid_reason"] = reason
    _write_json(p, d)
    return {"ok": True, "reason": reason}


def invalidate_reason(fid: str) -> str:
    return ((read_deps(fid).get("notes") or {}).get("invalid_reason")) or ""


def _adopt_legacy(fid: str) -> list[str]:
    """存量产物没有依赖记录时，按当前状态**认账一次**。

    不这么做，老片每次打开都显示"旧版/该重做"，用户会以为必须全渲一遍。
    认账之后，任何**真实**的改动仍然会正确失效（指纹从这一刻起才有效）。
    """
    cur = _read_json(os.path.join(fl.out_dir(fid), "current.json"), {})
    d = read_deps(fid)
    out = []
    for kind in ("stills", "clip"):
        node = d.get(kind) or {}
        if node.get("acts"):
            continue
        files = (cur.get(kind) or {}).get("files") or []
        for aid in sorted({f.get("act") for f in files if f.get("act")}):
            f0 = next((f for f in files if f.get("act") == aid), {})
            mark_act(fid, kind, aid, {"file": f0.get("file", ""), "adopted": True})
        if files:
            out.append(kind)
    for kind in ("film", "sound"):
        if not film_sig(fid, kind):
            fs = (cur.get(kind) or {}).get("files") or []
            if fs:
                mark_film(fid, kind, {"file": fs[0].get("file", ""), "adopted": True})
                out.append(kind)
    return out


def describe(fid: str) -> dict:
    """七步状态 + **逐幕**的"还算不算数"。界面只渲染这个，不自己算。"""
    adopted = _adopt_legacy(fid)
    m = fl.meta(fid)
    cur = _read_json(os.path.join(fl.out_dir(fid), "current.json"), {})
    rep = _read_json(os.path.join(fl.out_dir(fid), "judges.json"), None)
    P = parts(fid)

    stills = _files_of(fid, cur, "stills")
    clips = _files_of(fid, cur, "clip")
    sounds = _files_of(fid, cur, "sound", act_aware=False)
    films = _files_of(fid, cur, "film", act_aware=False)
    snd = sound_stats(fid, sounds)

    def per_act(files: list[dict], kind: str) -> list[dict]:
        """每一幕：出没出、还算不算数、东西在哪（位置/时长/题款都带上）。"""
        by = {}
        for f in files:
            by.setdefault(f.get("act") or "", []).append(f)
        out = []
        for a in (m.get("acts") or []):
            fs = by.get(a["id"], [])
            out.append({"id": a["id"], "n": a.get("n", a["id"]), "note": a.get("note", a["id"]),
                        "t0": a["t0"], "t1": a["t1"], "d": a["d"],
                        "caption": a.get("caption") or [], "subject": a.get("subject") or {},
                        "has": bool(fs), "fresh": is_fresh(fid, kind, a["id"], fs),
                        "files": fs})
        return out

    pa_stills = per_act(stills, "stills")
    pa_clips = per_act(clips, "clip")
    film_fresh = is_film_fresh(fid, "film", films)
    sound_fresh = is_film_fresh(fid, "sound", sounds)
    scripts_now = fl.script_of(fid)
    n_act = len(m.get("acts") or [])
    steps = [
        {"n": 1, "key": "project", "done": True,
         "note": f'{m.get("ratio") or _ratio(m["size"])} · {m["size"][0]}×{m["size"][1]} · {m["fps"]}fps'},
        # ② 分幕与剧本是同一件事的两面：**分几幕**与**每幕讲什么**，拆开写就会写出空幕。
        # 有分幕即算"这一步有了着落"（剧本条数写在 note 里，不挡绿）。
        {"n": 2, "key": "story", "done": n_act > 0,
         "note": (f'{n_act} 幕 · {m["duration"]:.1f} 秒 · 剧本 {_script_n(scripts_now)} 条'
                  if n_act else "还没有幕"),
         "checks": _checks(rep, CHECK_OF["2"])},
        # ③ 构件：引擎内置底座（山/水/月/舟）也算"有构件"；自有构件一采纳即绿。
        {"n": 3, "key": "parts", "done": bool(P["items"]) or bool(P["engine"]),
         "note": (f'{len(P["items"])} 个自有构件' if P["items"]
                  else (f'{len(P["engine"])} 个引擎构件' if P["engine"] else "骨架渲染先用内置底座"))},
        {"n": 4, "key": "stills", "done": bool(stills), "per_act": pa_stills,
         "stale": any(x["has"] and not x["fresh"] for x in pa_stills),
         "need": [x["id"] for x in pa_stills if not x["has"] or not x["fresh"]],
         "note": _howmany(pa_stills, "张"),
         "files": stills, "checks": _checks(rep, CHECK_OF["4"])},
        {"n": 5, "key": "clips", "done": bool(clips), "per_act": pa_clips,
         "stale": any(x["has"] and not x["fresh"] for x in pa_clips),
         "need": [x["id"] for x in pa_clips if not x["has"] or not x["fresh"]],
         "note": _howmany(pa_clips, "段"),
         "files": clips, "checks": _checks(rep, CHECK_OF["5"])},
        # ⑥ 声音：整片一条声轨，但**逐幕**都要有东西（整幕静音＝这一幕没配）
        {"n": 6, "key": "sound", "done": bool(sounds), "stale": bool(sounds) and not sound_fresh,
         "note": _sound_note(snd, m), "files": sounds, "stats": snd,
         "cues": snd_cues(fid),
         "per_act": snd.get("per_act") or [], "checks": _checks(rep, CHECK_OF["6"])},
        {"n": 7, "key": "film", "done": bool(films), "stale": bool(films) and not film_fresh,
         "note": f"{len(films)} 个文件" if films else "还没合成",
         "files": films, "checks": _checks(rep, CHECK_OF["7"])},
    ]
    ids = [a["id"] for a in (m.get("acts") or [])]
    todo = ("stills" if any(not x["has"] for x in pa_stills) else
            "clips" if any(not x["has"] for x in pa_clips) else
            "sound" if not sounds else
            "film" if not films else "done")
    named = {s["key"]: s for s in STEPS}
    out_steps = [{**named.get(s["key"], {}), **s} for s in steps]
    reason = invalidate_reason(fid)
    for s in out_steps:
        if s.get("stale"):
            s["stale_reason"] = reason or "依赖变了（构件/幕参数/渲染器），下面这版该重做"
    scripts = fl.script_of(fid)
    acts_out = [{"id": a["id"], "note": a.get("note", a["id"]), "t0": a["t0"], "t1": a["t1"],
                 "d": a["d"], "caption": a.get("caption") or [],
                 "subject": a.get("subject") or {},
                 "parts": act_parts(fid, a["id"]),
                 "script": scripts.get(a["id"], [])}
                for a in (m.get("acts") or [])]
    return {"film": fid, "meta": m, "steps": out_steps, "parts": P, "ids": ids,
            "acts": acts_out, "todo": todo, "when": time.strftime("%Y-%m-%d %H:%M:%S")}


def _script_n(scripts: dict) -> int:
    """剧本条数（占位行不算 —— 新片的初稿就是占位，那是"没写"不是"写错了"）。"""
    items = [x for v in (scripts or {}).values() for x in (v or [])]
    return sum(1 for x in items
               if (x.get("text") or "").strip() and not x["text"].startswith("（")
               and "写这一幕要表达" not in x["text"])


def _script_note(scripts: dict) -> str:
    n = _script_n(scripts)
    return f"{n} 条 · 已勾 {sum(1 for v in (scripts or {}).values() for x in (v or []) if x.get('done'))}" if n else "还没写"


def snd_cues(fid: str) -> list[dict]:
    """每一幕**打算**配什么声音（还没出轨时也有 —— 界面要能先看到设计再出轨）。"""
    try:
        from . import sound as SND
        return SND.cues(fid)
    except Exception:
        return []


def sound_stats(fid: str, files: list[dict]) -> dict:
    """声轨的实测数据（由出声轨那一批次的 `sound.json` 给出，不在这里重算）。

    为什么不现算：算一次要解码整条 WAV（几十 MB），而它只在该批次产出时变。
    """
    for f in (files or []):
        if os.path.basename(f.get("file", "")) != "sound.json":
            continue
        d = _read_json(os.path.join(fl.out_dir(fid), f["file"]), {})
        if d:
            return d
    return {}


def _sound_note(snd: dict, m: dict) -> str:
    if not snd:
        return "还没配声"
    dur = float(snd.get("duration") or 0)
    gap = dur - float(m.get("duration") or 0)
    txt = f'{dur:.1f}s · 峰值 {float(snd.get("peak") or 0):.2f}'
    if abs(gap) > 0.15:
        txt += f' · **与幕表差 {gap:+.1f}s**'
    mute = [x["note"] for x in (snd.get("per_act") or []) if x.get("silent")]
    if mute:
        txt += f' · {len(mute)} 幕几乎无声（{"、".join(mute[:2])}）'
    else:
        flat = [x["note"] for x in (snd.get("per_act") or []) if x.get("flat")]
        if flat:
            txt += f' · {len(flat)} 幕没有明显落点（{"、".join(flat[:2])}）'
    return txt


def _howmany(per_act: list[dict], unit: str) -> str:
    n = sum(1 for x in per_act if x["has"])
    f = sum(1 for x in per_act if x["has"] and x["fresh"])
    if not n:
        return "还没出"
    return f"{n} {unit}（{f} 项依赖未变可跳过）" if f < n else f"{n} {unit} · 全部最新"


def _group(files: list[dict]) -> list[dict]:
    """按幕归组 —— 界面按幕一栏一栏看，而不是一锅图。"""
    out: list[dict] = []
    idx: dict[str, dict] = {}
    for f in files:
        k = f.get("act") or "_"
        if k not in idx:
            idx[k] = {"act": k, "files": []}
            out.append(idx[k])
        idx[k]["files"].append(f)
    return out

