/* Spolvero 工作台 —— 原生 JS，无构建。业务判断全在后端（/api/pipeline 给状态）。

   版面：顶栏＝七个阶段；左栏＝工程/幕/任务；中央＝当前阶段内容 + 大输入框；右栏＝现在该做/警告/日志。

   七步的顺序（前一步定死了才走下一步）：
     ① 立项    定画幅与帧率 —— 主体落点、题款字号、景别都由它派生
     ② 分幕    拆成幕 + 逐幕写清「讲什么」（剧本就在这里，不再单列一步）
     ③ 构件    造可复用的对象（人/器物/山石/房屋）
     ④ 关键图  每幕一张静帧 —— 先看静帧把构图定死
     ⑤ 视频    每幕动起来（**只看画面**）
     ⑥ 声音    配声轨与音效落点（时长从幕表派生）
     ⑦ 成片    各幕接成一条片，声画合一

   每一步都在界面上写明三件事：**这一步解决什么 / 你要看什么 / 脚本判什么**。
   人看的（构图、节奏、响度）与脚本判的（确定性、帧数、对齐）分开摆，互不冒充。

   纪律：不出现身份选择；不出现"点一下跑检验"（贴着产物自动跑）。 */
const $ = (s, r = document) => r.querySelector(s);
const el = (tag, cls, html) => { const n = document.createElement(tag); if (cls) n.className = cls; if (html != null) n.innerHTML = html; return n; };
const esc = s => String(s == null ? '' : s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
const txt = s => { const d = el('span'); d.textContent = s == null ? '' : String(s); return d.innerHTML; };

// ── 极简 Markdown（先转义再解析）──────────────────────────────────────
function md(src) {
  let t = esc(src || '');
  const stash = [];
  t = t.replace(/```[^\n]*\n?([\s\S]*?)```/g, (m, c) =>
    '\u0000S' + (stash.push('<pre class="code">' + esc(c.replace(/\s+$/, '')) + '</pre>') - 1) + '\u0000');
  t = t.replace(/(?:^|\n)(\|[^\n]*\|)\n[ \t]*\|[\s:|-]+\|[ \t]*\n((?:\|[^\n]*\|[ \t]*\n?)+)/g,
    (m, head, body) => {
      const cells = r => r.split('|').slice(1, -1).map(s => `<td>${s.trim()}</td>`).join('');
      const th = head.split('|').slice(1, -1).map(s => `<th>${s.trim()}</th>`).join('');
      const rows = body.replace(/\s+$/, '').split('\n').map(r => `<tr>${cells(r)}</tr>`).join('');
      return `\n<table>${th ? `<thead><tr>${th}</tr></thead>` : ''}<tbody>${rows}</tbody></table>\n`;
    });
  t = t.replace(/^######[ \t]+(.*)$/gm, '<h6>$1</h6>').replace(/^#####[ \t]+(.*)$/gm, '<h5>$1</h5>')
       .replace(/^####[ \t]+(.*)$/gm, '<h4>$1</h4>').replace(/^###[ \t]+(.*)$/gm, '<h3>$1</h3>')
       .replace(/^##[ \t]+(.*)$/gm, '<h2>$1</h2>').replace(/^#[ \t]+(.*)$/gm, '<h1>$1</h1>');
  t = t.replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>')
       .replace(/(^|[^*\w])\*([^*\n]+)\*/g, '$1<i>$2</i>')
       .replace(/`([^`\n]+)`/g, '<code>$1</code>')
       .replace(/\[([^\]\n]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  t = t.replace(/(?:^[ \t]*[-*][ \t]+.*\n?)+/gm, m =>
    '<ul>' + m.replace(/^[ \t]*[-*][ \t]+(.*)$/gm, '<li>$1</li>') + '</ul>');
  t = t.replace(/(?:^[ \t]*\d+\.[ \t]+.*\n?)+/gm, m =>
    '<ol>' + m.replace(/^[ \t]*\d+\.[ \t]+(.*)$/gm, '<li>$1</li>') + '</ol>');
  t = t.split(/\n{2,}/).map(p => {
    const s = p.trim();
    if (!s) return '';
    return /^<(h[1-6]|ul|ol|table|pre)/.test(s) ? s : `<p>${s.replace(/\n/g, '<br>')}</p>`;
  }).join('');
  return t.replace(/\u0000S(\d+)\u0000/g, (m, i) => stash[i]);
}

const STAGES = [
  { key: 'project', n: 1, name: '立项' },
  { key: 'story', n: 2, name: '分幕' },
  { key: 'parts', n: 3, name: '构件' },
  { key: 'stills', n: 4, name: '关键图' },
  { key: 'clips', n: 5, name: '视频' },
  { key: 'sound', n: 6, name: '声音' },
  { key: 'film', n: 7, name: '成片' },
];
const ASK_PH = {
  project: '要另起一部片，就在下面说',
  story: '说怎么调整分幕，例如「七幕压到五幕」「第二幕补一句：他吹灭了灯」',
  parts: '说造什么构件，例如「造一个江南民居，白墙黑瓦」',
  stills: '说这张图哪儿不对，例如「人太小」「题款压住主体」',
  clips: '说这段视频哪儿不对，例如「动得太快」「镜头太呆」',
  sound: '说声音哪儿不对，例如「第三幕没声音」「斧落下去那一拍要有声」',
  film: '说成片哪儿不对，例如「整体再压十秒」',
};

const S = {
  fid: null, pipe: null, films: [], ratios: [], styles: [], stage: null, act: null, nfRatio: '', nfStyle: '',
  res: {}, busy: false, queue: [], es: null, cur: null, jobs: [], log: [], watch: false,
  partsAuto: {},
};

// ═══════════ 启动 ═══════════
async function boot() {
  await loadRatios();
  await loadStyles();
  const sf = await (await fetch('/api/settings')).json();
  $('#keyDot').className = 'keydot' + (sf.has_key ? ' on' : '');
  await loadFilms();
  setInterval(pollJobs, 3500);
}
async function loadStyles() {
  try { S.styles = ((await (await fetch('/api/styles')).json()).styles) || []; } catch (e) { S.styles = []; }
}
async function loadRatios() {
  try { S.ratios = ((await (await fetch('/api/ratios')).json()).ratios) || []; } catch (e) { S.ratios = []; }
}
async function loadFilms() {
  const r = await (await fetch('/api/films')).json();
  S.films = r.films || [];
  const sel = $('#filmSel'); sel.innerHTML = '';
  if (!S.films.length) { S.fid = null; S.pipe = null; renderAll(); return; }
  S.films.forEach(f => {
    const o = el('option'); o.value = f.id; o.textContent = (f.title || f.id) + (f.error ? '（异常）' : '');
    sel.appendChild(o);
  });
  sel.onchange = () => openFilm(sel.value);
  await openFilm(S.fid && S.films.some(f => f.id === S.fid) ? S.fid : S.films[0].id);
}
async function openFilm(fid) {
  S.fid = fid; $('#filmSel').value = fid; S.act = null;
  await refresh();
}
async function refresh() {
  if (!S.fid) { renderAll(); return; }
  S.pipe = await (await fetch('/api/pipeline/' + S.fid)).json();
  const acts = (S.pipe && S.pipe.acts) || [];
  if (!S.act || !acts.some(a => a.id === S.act)) S.act = acts.length ? acts[0].id : null;
  if (!S.stage) S.stage = pickStage();
  renderAll();
  renderOps();
}
function pickStage() {
  const t = S.pipe && S.pipe.todo;
  if (!t || t === 'done') return 'story';
  return t === 'film' ? 'stills' : t;      // 该合成时，先让人回到画面上挑毛病
}
$('#btnRefresh').onclick = () => refresh();

/* 右栏分隔条：拖动调整「记录」的高度，免得记录一多，警告就被挤出屏幕 */
(function initSplitter() {
  const sp = $('#splitter'), rec = $('#recCard');
  if (!sp || !rec) return;
  let y0 = 0, h0 = 0, drag = false;
  sp.addEventListener('mousedown', e => {
    drag = true; y0 = e.clientY; h0 = rec.getBoundingClientRect().height;
    document.body.style.cursor = 'ns-resize';
    e.preventDefault();
  });
  window.addEventListener('mousemove', e => {
    if (!drag) return;
    const maxH = window.innerHeight - 260;
    rec.style.flex = '0 0 auto';
    rec.style.height = Math.max(90, Math.min(maxH, h0 + (e.clientY - y0))) + 'px';
  });
  window.addEventListener('mouseup', () => {
    drag = false; document.body.style.cursor = '';
  });
})();

// ═══════════ 渲染 ═══════════
function renderAll() { renderStages(); renderSide(); renderStage(); renderRight(); renderAsk(); }

function stepOf(key) { return ((S.pipe && S.pipe.steps) || []).find(s => s.key === key) || { n: 0, key, done: false }; }
function actOf(id) { return ((S.pipe && S.pipe.acts) || []).find(a => a.id === id) || null; }

function renderStages() {
  const nav = $('#stages'); nav.innerHTML = '';
  STAGES.forEach(s => {
    const d = stepOf(s.key);
    const b = el('button', 'stage-tab' + (d.done ? ' done' : '') + (d.stale ? ' stale' : '') + (S.stage === s.key ? ' on' : ''));
    b.innerHTML = `<span>${s.n} ${txt(s.name)}</span><i></i>`;
    b.onclick = () => { S.stage = s.key; renderAll(); };
    nav.appendChild(b);
  });
}

function renderSide() {
  const m = (S.pipe && S.pipe.meta) || null;
  $('#projInfo').innerHTML = m
    ? `<div class="nm">${txt(m.title)}</div>
       <div class="meta">${txt(m.ratio || '')} · ${m.size[0]}×${m.size[1]}</div>
       <div class="meta">${m.duration.toFixed(1)} 秒 · ${m.fps}fps</div>`
    : '<div class="muted small">还没有影片</div>';
  const box = $('#actPick'); box.innerHTML = '';
  const acts = (S.pipe && S.pipe.acts) || [];
  $('#actCount').textContent = acts.length ? acts.length + ' 幕' : '';
  const pa = {};
  ['stills', 'clips'].forEach(k => (stepOf(k).per_act || []).forEach(x => { pa[k + ':' + x.id] = x; }));
  acts.forEach((a, i) => {
    const st = pa['stills:' + a.id], cl = pa['clips:' + a.id];
    const cls = !st || !st.has ? 'none' : (st.fresh ? 'done' : 'stale');
    const b = el('button', 'actbtn' + (S.act === a.id ? ' on' : ''));
    b.innerHTML = `<b>${i + 1}</b><span class="nm">${txt(a.note)}</span><i class="${cls}"></i>`;
    b.title = `图：${st ? (st.has ? (st.fresh ? '最新' : '旧版') : '未出') : '—'} · 视频：${cl ? (cl.has ? (cl.fresh ? '最新' : '旧版') : '未出') : '—'}`;
    b.onclick = () => {
      S.act = a.id;
      if (!['stills', 'clips'].includes(S.stage)) S.stage = 'stills';
      renderAll();
    };
    box.appendChild(b);
  });
  renderJobs();
}

function renderJobs() {
  const box = $('#jobsBox');
  const live = (S.jobs || []).filter(j => ['running', 'pending'].includes(j.state));
  box.innerHTML = '';
  if (!live.length) { box.appendChild(el('div', 'muted small', '没有在跑的任务')); return; }
  live.forEach(j => {
    const pct = j.total ? Math.round(100 * j.done / j.total) : 0;
    const title = (j.kind_label || j.kind) + (j.note ? ' · ' + j.note : '');
    box.appendChild(el('div', 'jobrow',
      `<div class="t"><span>${txt(title)}</span><span class="muted">${pct}%</span></div>
       <div class="mini"><i style="width:${pct}%"></i></div>`));
  });
}

/* 右栏：现在该做什么 · 警告 · 日志 */
function renderRight() {
  const nb = $('#nextBox');
  nb.innerHTML = '';
  if (!S.pipe) {
    nb.appendChild(el('div', 'big', '建一部影片'));
    const b = el('button', 'primary', '去立项');
    b.onclick = () => { S.stage = 'project'; renderAll(); };
    nb.appendChild(b);
  } else {
    const g = next4();
    nb.appendChild(el('div', 'big', txt(g.t)));
    if (g.d) nb.appendChild(el('div', 'why', txt(g.d)));
    const b = el('button', 'primary', g.b);
    b.onclick = g.run;
    nb.appendChild(b);
  }
  // 警告
  const wb = $('#warnBox'); wb.innerHTML = '';
  // 自动检验只在这里报结果（中央不再重复一份）
  const c0 = (S.pipe.steps || []).map(s => s.checks).find(c => c && c.summary);
  if (c0) {
    const sm = c0.summary || {};
    wb.appendChild(el('div', 'chsum',
      `自动检验：通过 ${sm.pass || 0} · 警告 ${sm.warn || 0} · 失败 ${sm.fail || 0}`));
  }
  const warns = collectWarns();
  $('#warnCount').textContent = warns.length ? warns.length + ' 项' : '';
  if (!warns.length) wb.appendChild(el('div', 'muted small', '没有警告'));
  warns.forEach(w => {
    const r = el('div', 'wrow' + (w.kind === 'warn' ? ' b' : ''));
    r.innerHTML = `<b>${txt(w.title)}</b>` + (w.detail ? `<em>${txt(w.detail)}</em>` : '');
    if (w.go) { r.style.cursor = 'pointer'; r.onclick = w.go; }
    wb.appendChild(r);
  });
}

function collectWarns() {
  const out = [];
  (S.pipe.steps || []).forEach(s => {
    const p = (s.checks || {}).problems || [];
    p.forEach(i => out.push({
      kind: i.status, title: `${i.id} ${i.name}`, detail: (i.detail || '') + (i.fix ? '　改法：' + i.fix : ''),
      go: () => { S.stage = ['clips', 'sound', 'film'].includes(s.key) ? s.key : 'stills'; renderAll(); }
    }));
  });
  return out.slice(0, 12);
}

/* 现在该做：四选一的极简判断 */
function next4() {
  const d = S.pipe;
  const st = k => stepOf(k);
  if (!d.acts.length) return { t: '写一句故事', d: '还没有幕', b: '去分幕', run: () => { S.stage = 'story'; renderAll(); } };
  const needStills = (st('stills').need || []);
  if (needStills.length) {
    const a = actOf(needStills[0]);
    return {
      t: `出「${a ? a.note : needStills[0]}」的关键图`, d: `${needStills.length} 幕还没出`,
      b: '出关键图', run: () => startTask('stills')
    };
  }
  const needClips = (st('clips').need || []);
  if (needClips.length) {
    const a = actOf(needClips[0]);
    return {
      t: `渲染「${a ? a.note : needClips[0]}」的视频`, d: `${needClips.length} 幕还没渲染`,
      b: '逐幕渲染', run: () => enqueue((d.acts || []).map(x => ({ kind: 'clip', args: { act: x.id } })))
    };
  }
  if (!st('sound').done || st('sound').stale) {
    return { t: '配声音', d: '画面都齐了 —— 该给每一幕配声音了',
      b: '出声轨', run: () => startTask('sound') };
  }
  if (!st('film').done || st('film').stale) {
    return { t: '合并成片', d: '画面与声音都齐了', b: '去合并', run: () => { S.stage = 'film'; renderAll(); } };
  }
  return { t: '这一版完成了', d: '从左边挑一幕继续改', b: '看当前幕', run: () => { S.stage = 'stills'; renderAll(); } };
}

function renderAsk() {
  const p = ASK_PH[S.stage] || ASK_PH.story;
  const a = actOf(S.act);
  $('#askInput').placeholder = p + (a && ['stills', 'clips', 'script'].includes(S.stage)
    ? `　（当前：${a.note}）` : '') + '　Ctrl+Enter 发送';
}

$('#askSend').onclick = () => sendAsk();
$('#askInput').addEventListener('keydown', e => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sendAsk(); }
});
async function sendAsk(scopeOverride) {
  const ta = $('#askInput');
  const text = (ta.value || '').trim();
  if (!text) return;
  const scoped = scopeOverride !== undefined ? scopeOverride
    : (['stills', 'clips', 'story'].includes(S.stage) ? (S.act || '') : '');
  ta.value = '';
  S.res = { pending: true, text }; paintRes();
  let r;
  try {
    r = await (await fetch('/api/advise', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ film: S.fid, step: String(stepOf(S.stage).n || ''), act: scoped, text })
    })).json();
  } catch (e) { r = { ok: false, error: '网络错误：' + e }; }
  if (!r.ok) S.res = { error: r.error || '没能给出计划', text };
  else if (r.empty) S.res = { error: r.error || '没听懂这句意见', text };
  else S.res = { plan: r.plan, text, checked: {} };
  paintRes();
}

/* 某一幕是否已生成（关键图已出＝这一幕有了可改的底座）。
   改动清单里，stills / clip 这类"改某一幕"的项，若该幕没生成就不列出。 */
function actGenerated(actId) {
  if (!actId) return true;
  const st = (S.pipe && S.pipe.stills) || {};
  const e = (st.pa || []).find(x => x.id === actId);
  return !!(e && e.has);
}
function visiblePlanItems(plan) {
  return (plan.items || []).filter(it =>
    (it.kind === 'stills' || it.kind === 'clip') && it.scope
      ? actGenerated(it.scope) : true);
}

/* 计划：先摆出"要动哪几处"，勾选后再执行 */
function paintRes() {
  const out = $('#askOut'); out.innerHTML = '';
  const r = S.res || {};
  if (!Object.keys(r).length) return;
  if (r.pending) { out.appendChild(el('div', 'muted small', '正在制定改动计划…')); return; }
  if (r.error) { out.appendChild(el('div', 'errline', '⚠ ' + txt(r.error))); return; }
  if (r.done) { paintDone(out, r); return; }
  const p = r.plan || {};
  const items = visiblePlanItems(p);          // 某幕没生成就不进清单
  const card = el('div', 'plancard');
  if (p.understanding) card.appendChild(el('div', 'pu', '理解：' + txt(p.understanding)));
  else card.appendChild(el('div', 'pu', '计划'));
  if (!items.length) {
    card.appendChild(el('div', 'muted small', '这些改动涉及的幕还没生成关键图 —— 先去「关键图」环节把那一幕画出来，再来改。'));
    const no = el('button', 'ghost', '知道了');
    no.onclick = () => { S.res = {}; paintRes(); };
    card.appendChild(no);
    out.appendChild(card); return;
  }
  const list = el('div', 'planlist');
  items.forEach(it => {
    const row = el('label', 'planitem');
    const cb = el('input'); cb.type = 'checkbox';
    cb.checked = r.checked[it.id] !== false;        // 默认全勾
    cb.onchange = () => { r.checked[it.id] = cb.checked; paintRes(); };
    row.appendChild(cb);
    const one = it.kind === 'parts' ? it.name : (actNote(it.scope) || '');
    row.appendChild(el('span', 'k', txt(it.label + (one ? '' : ''))));
    row.appendChild(el('span', 'd', txt(it.detail || '')));
    list.appendChild(row);
  });
  card.appendChild(list);
  const chosen = items.filter(it => r.checked[it.id] !== false);
  const willClear = items.filter(it => r.checked[it.id] === false
    && ['stills', 'clip'].includes(it.kind) && it.scope);
  const foot = el('div', 'planfoot');
  foot.appendChild(el('span', 'muted small',
    `已勾 ${chosen.length} / ${p.items.length} 项` + (willClear.length ? ` · 不打勾的 ${willClear.length} 项会清空（那一幕先空着）` : '')));
  const go = el('button', 'primary', '执行');
  go.disabled = !chosen.length && !willClear.length;
  go.onclick = () => applyPlan(p, r);
  const no = el('button', 'ghost', '算了');
  no.onclick = () => { S.res = {}; paintRes(); };
  foot.appendChild(no); foot.appendChild(go);
  card.appendChild(foot);
  out.appendChild(card);
}
function actNote(id) {
  const a = actOf(id);
  return a ? a.note : '';
}
async function applyPlan(p, r) {
  const items = visiblePlanItems(p);          // 没生成的幕不下发，绝不会去改它
  const chosen = items.filter(it => r.checked[it.id] !== false).map(it => it.id);
  S.res = { pending: true }; paintRes();
  let j;
  try {
    j = await (await fetch('/api/apply', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ film: S.fid, plan: { ...p, items }, chosen })
    })).json();
  } catch (e) { j = { ok: false, error: String(e) }; }
  S.res = { done: true, text: r.text, res: j };
  paintRes();
  (j.jobs || []).forEach(id => openStream(id));
  await refresh();
  renderOps();
}
function paintDone(out, r) {
  const j = r.res || {};
  const box = el('div', 'plancard done');
  if (j.ok === false || j.error) { box.appendChild(el('div', 'errline', '⚠ ' + txt(j.error))); out.appendChild(box); return; }
  (j.done || []).forEach(d => box.appendChild(el('div', 'pdone', `${txt(d.label)} —— ${txt(d.note)}`)));
  (j.cleared || []).forEach(c => box.appendChild(el('div', 'pclear', `${txt(c.label)} 已清空（那一幕先空着）`)));
  (j.failed || []).forEach(f => box.appendChild(el('div', 'errline', `${txt(f.label)} 失败：${txt(f.error)}`)));
  const bar = el('div', 'row'); bar.style.marginTop = '8px';
  bar.appendChild(el('span', 'muted small', '可在右栏「操作」里退回这一次改动'));
  const no = el('button', 'ghost small', '知道了');
  no.onclick = () => { S.res = {}; paintRes(); };
  bar.appendChild(no);
  box.appendChild(bar);
  out.appendChild(box);
}

/* 右栏「记录」：一次意见＝一条 —— 做了什么、日志、退回，全在同一条里。
   （日志与回退本来就是同一件事的两面：谁在什么时候改了什么。） */
async function renderOps() {
  if (!S.fid) return;
  let r = {};
  try { r = await (await fetch('/api/ops/' + S.fid)).json(); } catch (e) { }
  const batches = (r.batches || []);
  const box = $('#recBox'); box.innerHTML = '';
  const live = (S.jobs || []).filter(j => ['running', 'pending'].includes(j.state));
  const actTitles = {};
  ((S.pipe && S.pipe.acts) || []).forEach(a => { actTitles[a.id] = a.note; });

  // 一条记录＝一个清晰的标题（做什么 · 哪一幕），不再堆细节
  const titleOf = it => {
    const k = KIND_CN[it.kind] || it.kind;
    const sc = it.scope && actTitles[it.scope] ? ' · ' + actTitles[it.scope] : '';
    return k + sc;
  };
  const batchTitle = x => {
    const items = (x.extra && x.extra.items) || [];
    if (items.length) {
      const t = [...new Set(items.map(titleOf))].join('、');
      return t.length > 34 ? t.slice(0, 34) + '…' : t;
    }
    return (x.note || '一次改动').slice(0, 34);
  };

  live.forEach(j => {
    const pct = j.total ? Math.round(100 * j.done / j.total) : 0;
    const title = (j.kind_label || j.kind) + (j.note ? ' · ' + j.note : '');
    const row = el('div', 'recrow live');
    row.innerHTML = `<div class="t"><span>${txt(title)}</span><span class="muted">${pct}%</span></div>
      <div class="mini"><i style="width:${pct}%"></i></div>`;
    box.appendChild(row);
  });

  $('#recCount').textContent = batches.length ? batches.length + ' 条' : '';
  if (!batches.length && !live.length) {
    box.appendChild(el('div', 'muted small', '还没有改动记录'));
    return;
  }
  batches.forEach(x => {
    const row = el('div', 'recrow');
    row.innerHTML = `<div class="t"><span>${txt(batchTitle(x))}</span><span class="muted">${txt((x.when || '').slice(5, 16))}</span></div>`;
    const back = el('button', 'ghost small', '退回');
    back.onclick = async () => {
      if (!confirm('退回这一次改动？')) return;
      const rr = await (await fetch('/api/ops/restore', {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ batch: x.id })
      })).json();
      toast(rr.ok ? '已退回' : ('退回失败：' + rr.error));
      await refresh(); renderOps();
    };
    row.appendChild(back);
    box.appendChild(row);
  });
}
const KIND_CN = { script: '改剧本', film_patch: '改幕参数', parts: '造构件',
  stills: '重画关键图', clip: '重渲视频', sound: '重出声轨', film: '重合成' };

// ═══════════ 中央：按阶段渲染 ═══════════
function renderStage() {
  const v = $('#stage'); v.innerHTML = '';
  if (!S.pipe) { v.appendChild(stageNew()); return; }
  ({ project: stageProject, story: stageStory, parts: stageParts,
     stills: stageStills, clips: stageClips, sound: stageSound, film: stageFilm }[S.stage] || stageStory)(v);
}

/* 风格选择条：只出现在「立项」新建时（整片基调在立项定死，后续不再设置）。 */
function styleChips(selected, onPick) {
  const box = el('div', 'stylepick');
  const styles = S.styles || [];
  if (!styles.length) { box.appendChild(el('div', 'muted small', '没有可选风格')); return box; }
  box.appendChild(el('div', 'flabel', '整片基调 · 选一套视觉风格（影响分幕 / 构件 / 关键图 / 视频 / 声音 / 成片）'));
  const chips = el('div', 'stylechips');
  styles.forEach(s => {
    const c = el('button', 'stylechip' + (s.id === selected ? ' on' : ''));
    const sw = el('span', 'sw');
    sw.style.background = `linear-gradient(135deg, ${s.paper} 0 33%, ${s.ink} 33% 66%, ${s.accent} 66% 100%)`;
    c.appendChild(sw);
    c.appendChild(el('span', 'sn', txt(s.name)));
    c.title = s.description || s.name;
    c.onclick = () => { if (onPick) onPick(s.id); };
    chips.appendChild(c);
  });
  box.appendChild(chips);
  return box;
}
function block(title, sub, stale) {
  const b = el('section', 'block' + (stale ? ' stale' : ''));
  if (title) b.appendChild(el('h2', '', `${txt(title)}${sub ? ` <span class="st">${txt(sub)}</span>` : ''}`));
  return b;
}
function row(children) { const r = el('div', 'row'); (children || []).forEach(c => r.appendChild(c)); return r; }
function btn(label, fn, cls) { const b = el('button', cls || 'ghost', label); b.onclick = fn; return b; }

// ── ① 立项 ──
function stageNew() {
  const b = block('立项 · 定画幅');
  const chips = el('div', 'chips'); chips.id = 'nfRatios';
  const custom = el('input'); custom.id = 'nfCustom'; custom.hidden = true;
  custom.placeholder = '自定义比例，如 2.35:1';
  custom.oninput = () => paintChips();
  b.appendChild(chips); b.appendChild(custom);
  const idea = el('textarea'); idea.id = 'nfIdea'; idea.rows = 3;
  idea.placeholder = '一句话故事，例如：一个书生夜里在灯下读书，抬头看见画里的女子走了下来';
  idea.style.cssText = 'width:100%;margin-top:10px;border:1px solid var(--line);border-radius:8px;padding:9px;background:#fff;line-height:1.6';
  b.appendChild(idea);
  const r2 = el('div', 'row2');
  r2.innerHTML = `<label>片名（可留空）<input id="nfTitle" placeholder="自动"></label>
    <label>总时长（秒）<input id="nfDur" type="number" value="30" min="6" step="1"></label>`;
  b.appendChild(r2);
  // 整片基调：立项时定死，只在这里选
  if (!S.nfStyle && (S.styles || []).length) S.nfStyle = S.styles[0].id;
  b.appendChild(styleChips(S.nfStyle, id => {
    S.nfStyle = id;
    b.querySelectorAll('.stylechip').forEach((c, i) => c.classList.toggle('on', S.styles[i].id === id));
  }));
  const msg = el('div', 'testline'); msg.id = 'nfMsg'; b.appendChild(msg);
  const go = el('button', 'primary big', '创建'); go.id = 'nfOk'; go.disabled = true; go.onclick = createFilm;
  const hint = el('span', 'muted small'); hint.id = 'nfHint';
  b.appendChild(row([go, hint]));
  setTimeout(paintChips, 0);
  return b;
}
function stageProject(v) {
  const m = S.pipe.meta, d = stepOf('project');
  const b = block('立项 · 画幅', d.note);
  b.appendChild(el('div', 'kv',
    `<b>影片</b><span>${txt(m.title)}（${txt(m.id)}）</span>
     <b>画幅</b><span>${txt(m.ratio || '')} · ${m.size[0]} × ${m.size[1]}</span>
     <b>时长</b><span>${m.duration.toFixed(1)} 秒 · ${m.frames} 帧 @ ${m.fps}fps</span>
     <b>出处</b><span>${txt(m.source || '—')}</span>`));
  const more = el('details', 'more');
  more.innerHTML = '<summary>新建另一部</summary>';
  more.appendChild(stageNew());
  b.appendChild(more);
  v.appendChild(b);
}
function paintChips() {
  const box = $('#nfRatios'); if (!box) return;
  box.innerHTML = '';
  S.ratios.forEach(r => {
    const b = el('button', 'chip' + (S.nfRatio === r.id ? ' on' : ''), `${txt(r.name)} ${txt(r.id)}`);
    b.type = 'button'; b.title = `${r.use} · ${r.w} × ${r.h} px`;
    b.onclick = () => { S.nfRatio = r.id; paintChips(); };
    box.appendChild(b);
  });
  const c = el('button', 'chip' + (S.nfRatio === 'custom' ? ' on' : ''), '自定义…');
  c.type = 'button'; c.onclick = () => { S.nfRatio = 'custom'; paintChips(); };
  box.appendChild(c);
  const cu = $('#nfCustom'); if (cu) cu.hidden = S.nfRatio !== 'custom';
  const ok = !!ratioValue();
  const go = $('#nfOk'); if (go) go.disabled = !ok;
  const h = $('#nfHint'); if (h) h.textContent = ok ? '' : '先选画幅比例';
}
function ratioValue() {
  if (!S.nfRatio) return '';
  return S.nfRatio === 'custom' ? ($('#nfCustom').value || '').trim() : S.nfRatio;
}
async function createFilm() {
  const box = $('#nfMsg'), ratio = ratioValue();
  if (!ratio) return;
  const body = {
    idea: ($('#nfIdea').value || '').trim(), ratio,
    duration: parseFloat($('#nfDur').value || '30'),
    title: ($('#nfTitle').value || '').trim(),
    style: S.nfStyle || '',
    id: 'f' + Date.now().toString(36),
  };
  box.className = 'testline running'; box.textContent = '排幕表…';
  const r = await (await fetch('/api/films', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body)
  })).json();
  if (!r.ok) { box.className = 'testline bad'; box.textContent = '创建失败：' + r.error; return; }
  toast(`已建《${r.meta.title}》· ${r.ratio} · ${(r.meta.acts || []).length} 幕 · 基调「${r.style || '默认'}」`);
  S.nfRatio = ''; S.nfStyle = ''; S.stage = 'story'; S.fid = r.meta.id;
  await loadFilms();
}

function actSetting(a) {
  const [W, H] = (S.pipe.meta.size || [1600, 900]);
  const out = [];
  const x = (a.subject || {}).x, h = (a.subject || {}).h;
  if (typeof x === 'number') out.push(`主体在画面${x < W * 0.4 ? '左' : x > W * 0.6 ? '右' : '中'}侧`);
  if (h) out.push(`高约画高的 ${Math.round(h / H * 100)}%`);
  out.push(`${a.d.toFixed(1)} 秒`);
  return out.join(' · ');
}
function realScript(a) {
  return (a.script || []).map(x => x.text || '')
    .filter(t => t && !t.startsWith('（') && !t.includes('写这一幕要表达'));
}

// ── ② 分幕 · 剧本：**拆几幕**与**每幕讲什么**是同一件事的两面，放在一屏里改 ──
// 拆成两步的后果：先排完幕表，再另开一屏写剧本 —— 中间隔着一步，
// 幕表一旦重排，刚写的剧本就对不上了（实测：剧本会留在旧幕上，看着像写过了其实没写）。
// ── ② 分幕 · 剧本：**这一个环节只做分幕**（构件还没齐备，不在这里造）。
//    顶部不再分别留「故事 / 时长」输入框 —— 只留底部一个总的构思框，AI 自动分幕、定每幕时长、起草剧本。
function stageStory(v) {
  const d = stepOf('story');
  const acts = S.pipe.acts || [];
  const b = block('分幕 · 剧本', d.note);

  if (!acts.length) {
    b.appendChild(el('div', 'muted small',
      '还没有幕 —— 在下面的「整体构思」写一句故事，AI 自动分幕、定每幕时长、起草剧本'));
  } else {
    const rows = el('div', 'actrows');
    acts.forEach((a, i) => {
      const r = el('div', 'actrow' + (S.act === a.id ? ' on' : ''));
      r.innerHTML = `<b>${i + 1}</b><span class="nm">${txt(a.note)}</span>
        <span class="tm">${a.t0.toFixed(1)}–${a.t1.toFixed(1)}s</span>
        <span class="cap">${txt((a.caption || []).join('　'))}</span>`;
      r.querySelector('.nm').onclick = () => { S.act = a.id; renderAll(); };
      r.appendChild(btn('改', () => openEditAct(a), 'ghost small'));
      rows.appendChild(r);
    });
    b.appendChild(rows);

    const c = block('每一幕讲什么', `${acts.length} 幕`);
    c.appendChild(el('div', 'flabel', '一行一件具体的事（谁做了什么、发生了什么变化）　写完自动保存'));
    const draft = btn('让 AI 起草剧本', () => {
      $('#askInput').value = '按现在的幕名与题款，把每一幕的剧本起草出来：每一幕 2–4 行，一行一件具体的事，不要写情绪。';
      sendAsk('');
    }, 'ghost small');
    const bar2 = el('div', 'row'); bar2.style.justifyContent = 'flex-end';
    bar2.appendChild(draft);
    c.appendChild(bar2);
    acts.forEach((a, i) => {
      const box = el('div', 'scriptblock' + (S.act === a.id ? ' on' : ''));
      const h = el('div', 'bh');
      h.innerHTML = `<b>${i + 1}. ${txt(a.note)}</b><span class="tm">${a.t0.toFixed(1)}–${a.t1.toFixed(1)}s</span>`;
      h.querySelector('b').onclick = () => { S.act = a.id; renderAll(); };
      h.appendChild(btn('改时长/题款', () => openEditAct(a), 'ghost small'));
      box.appendChild(h);
      const cap = (a.caption || []).length ? `　题款「${(a.caption || []).join('　')}」` : '';
      box.appendChild(el('div', 'setline', txt(actSetting(a) + cap)));
      const ta = el('textarea');
      ta.rows = 3;
      ta.value = realScript(a).join('\n');
      ta.placeholder = '这一幕讲什么，一行一件事（写完自动保存）';
      ta.style.cssText = 'width:100%;margin-top:8px;border:1px solid var(--line);border-radius:8px;' +
        'padding:9px 11px;background:#fff;line-height:1.7;resize:vertical';
      ta.onchange = async () => {
        ta.style.borderColor = '#b9ab8c';
        const r = await (await fetch('/api/script/' + S.fid, {
          method: 'PUT', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ act: a.id, text: ta.value })
        })).json();
        ta.style.borderColor = r.ok ? '' : '#e3c1bb';
        if (r.ok) { toast('剧本已存'); refresh(); } else toast('保存失败：' + r.error);
      };
      box.appendChild(ta);
      c.appendChild(box);
    });
    b.appendChild(c);
  }
  v.appendChild(b);

  // 一个总的输入框在下面：AI 自动生成分幕、时长、剧本
  const gen = block('整体构思', acts.length ? '重写会按新想法重新分幕、定每幕时长、起草剧本' : '一句话讲完这部片，AI 自动分幕、定每幕时长');
  const ta = el('textarea'); ta.id = 'stBrief'; ta.rows = 3;
  ta.placeholder = '整体构思，例如：一个书生在灯下读书，灯灭后又亮起，他看见画里的女子走了下来，最后女子回到画中';
  ta.style.cssText = 'width:100%;border:1px solid var(--line);border-radius:8px;padding:9px;background:#fff;line-height:1.6';
  gen.appendChild(ta);
  const go = btn(acts.length ? '按新构思重排幕表' : 'AI 生成幕表', async () => {
    const t = (ta.value || '').trim();
    if (!t) { toast('先写一句整体构思'); return; }
    go.disabled = true; go.textContent = '分幕中…';
    const r = await (await fetch('/api/story/' + S.fid, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ idea: t, duration: Math.round(S.pipe.meta.duration) })
    })).json();
    go.disabled = false; go.textContent = acts.length ? '按新构思重排幕表' : 'AI 生成幕表';
    if (!r.ok) { toast('失败：' + r.error); return; }
    toast(`已分幕：${r.acts} 幕 · ${r.duration.toFixed(0)} 秒`);
    await refresh();
  }, 'primary');
  gen.appendChild(row([go]));
  v.appendChild(gen);
}

// ── ④ 构件：**每个都摆出来**（像分幕一样铺开，不用点开才看得见）──
function stageParts(v) {
  const P = S.pipe.parts || { items: [], used: [], engine: [], styles: [], style: '' };
  const usedN = (P.used || []).length;
  const b = block('构件', `${usedN} 项在用${(P.engine || []).length ? ' · ' + (P.engine || []).length + ' 个引擎构件' : ''}`);
  b.appendChild(el('div', 'flabel', '下一步要造什么对象 —— AI 按这部片的幕与剧本建议并直接创作（造一次，后面每幕复用；不满意可删）'));
  const suggestBtn = btn('AI 自动建议并创作构件', () => suggestParts(), 'primary');
  suggestBtn.id = 'partsSuggest';
  b.appendChild(suggestBtn);

  const wall = (list) => {
    const g = el('div', 'partgrid');
    list.forEach(x => {
      const cell = el('div', 'partcell');
      if (x.img) {
        const im = el('img'); im.src = x.img; im.loading = 'lazy';
        im.onclick = () => zoom(x.img, 'img');
        im.onerror = () => { im.replaceWith(el('div', 'partnone', txt(String(x.name)))); };
        cell.appendChild(im);
      } else {
        cell.appendChild(el('div', 'partnone', txt(String(x.name).slice(0, 6))));
      }
      cell.appendChild(el('div', 'partname', txt(x.name)));
      if (x.note) cell.appendChild(el('div', 'partdesc', txt(x.note)));
      if (x.actions && x.actions.length) {
        const r = el('div', 'partacts');
        x.actions.forEach(a => r.appendChild(a));
        cell.appendChild(r);
      }
      g.appendChild(cell);
    });
    return g;
  };

  if (P.base_preview) {
    b.appendChild(el('div', 'flabel', '整体画面'));
    b.appendChild(wall([{ name: '这一帧', img: P.base_preview, note: (P.used_names || []).join(' · ') }]));
  }
  b.appendChild(el('div', 'flabel', '本片在用'));
  b.appendChild(wall((P.used || []).map(x => ({ name: x.name, img: x.preview }))));
  if ((P.engine || []).length) {
    b.appendChild(el('div', 'flabel', '引擎构件（可直接调用）'));
    b.appendChild(wall((P.engine || []).map(x => ({ name: x.name, img: x.preview }))));
  }

  // 自有构件：AI 一提就采纳（没有"待采纳"这一步）—— 每个都摆出预览图，可删。
  const owned = (P.items || []);
  b.appendChild(el('div', 'flabel', `自有构件${owned.length ? '（' + owned.length + '）' : ''}`));
  if (!owned.length) {
    b.appendChild(el('div', 'muted small', '还没有自造构件 —— 点上面的按钮让 AI 按本片幕与剧本直接创作'));
  } else {
    b.appendChild(wall(owned.map(it => {
      const acts = [btn('删除', async () => {
        if (!confirm('删除构件「' + it.name + '」？删除后用到它的关键图/视频会标为需重做。')) return;
        const r2 = await (await fetch('/api/parts/drop', {
          method: 'POST', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ name: it.name, state: it.state })
        })).json();
        toast(r2.ok ? '已删除 ' + it.name : '失败：' + (r2.error || ''));
        refresh();
      }, 'ghost small')];
      return {
        name: it.name,
        img: `/api/parts/used/${S.fid}/${encodeURIComponent(it.name)}.png`,
        note: (it.head || '') + (it.when ? ' · ' + it.when : ''),
        actions: acts,
      };
    })));
  }
  v.appendChild(b);

  // 进入构件环节：还没有自造构件就自动让 AI 建议一次（之后用户可手动再点）
  if (!(P.items || []).length && !S.partsAuto[S.fid]) {
    S.partsAuto[S.fid] = true;
    suggestParts();
  }
}

// AI 按分幕/剧本建议并创作构件（**直接采纳**，无待采纳环节）
async function suggestParts() {
  const btnEl = document.getElementById('partsSuggest');
  if (btnEl) { btnEl.disabled = true; btnEl.textContent = 'AI 建议中…'; }
  let r;
  try {
    r = await (await fetch('/api/advise', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ film: S.fid, step: String(stepOf('parts').n), act: '',
        text: '根据这部片的分幕与剧本，建议并直接创作本片需要的可复用构件（人、器物、山石、房屋、动植物等），'
            + '造一次后面每一幕复用；注意风格与整片基调一致。' })
    })).json();
  } catch (e) { r = { ok: false, error: '网络错误：' + e }; }
  if (btnEl) { btnEl.disabled = false; btnEl.textContent = 'AI 自动建议并创作构件'; }
  if (!r.ok) { toast('建议失败：' + (r.error || '未配置密钥')); return; }
  if (r.empty || !r.plan || !r.plan.items || !r.plan.items.length) {
    toast('AI 没建议出构件 —— 可在下面输入框说「造一个××」'); return;
  }
  const plan = r.plan;
  const chosen = plan.items.map(i => i.id);
  S.res = { pending: true }; paintRes();
  const j = await (await fetch('/api/apply', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ film: S.fid, plan, chosen })
  })).json();
  S.res = { done: true, text: '建议构件', res: j }; paintRes();
  (j.jobs || []).forEach(id => openStream(id));
  await refresh(); renderOps();
}

// ── ⑤ 关键图 ──
function stageStills(v) {
  const d = stepOf('stills'), a = actOf(S.act);
  const pa = (d.per_act || []).find(x => x.id === S.act) || { files: [], has: false, fresh: false };
  const b = block('关键图 · 每幕节点表', d.note, pa.has && !pa.fresh);
  const need = d.need || [];
  // 没有"该做"的幕时，按钮变「重画全部关键图」并强制重渲 —— 否则点了因为 todo 为空，什么都不发生（像没生成）。
  const items = [btn(need.length ? `出关键图（${need.length} 幕该做）` : '重画全部关键图',
    () => startTask('stills', need.length ? {} : { force: true }), 'primary')];
  if (a) {
    items.push(btn(`只出「${a.note}」`, () => startTask('stills', { acts: [a.id] })));
    items.push(btn('强制重画', () => startTask('stills', { acts: [a.id], force: true })));
  }
  b.appendChild(row(items));
  if (a) {
    b.appendChild(el('h2', '', `${txt(a.note)} <span class="st">${a.t0.toFixed(1)}–${a.t1.toFixed(1)}s${(a.caption || []).length ? ' · ' + txt((a.caption || []).join('　')) : ''}</span>`));
    // 这一幕的节点表（展示为关键图前的构成参数）
    const [W, H] = (S.pipe.meta.size || [1600, 900]);
    const sub = (a.subject || {});
    const node = el('div', 'nodetb');
    node.innerHTML = `<span><b>时段</b>${a.t0.toFixed(1)}–${a.t1.toFixed(1)}s</span>`
      + `<span><b>主体位置</b>${sub.x != null ? (sub.x < W * 0.4 ? '左' : sub.x > W * 0.6 ? '右' : '中') + '侧' : '—'}</span>`
      + `<span><b>主体高</b>${sub.h ? Math.round(sub.h / H * 100) + '% 画高' : '—'}</span>`
      + `<span><b>题款</b>${(a.caption || []).join('　') || '—'}</span>`
      + `<span><b>用到的构件</b>${(a.parts || []).join(' · ') || '底座'}</span>`;
    b.appendChild(node);
    if (pa.has) b.appendChild(media(pa.files, 'img'));
    else b.appendChild(el('div', 'muted small', '未出'));
    b.appendChild(thumbs());
  }
  v.appendChild(b);
}

// ── ⑤ 视频：**只看画面**（声音在下一步，混在一起调不清）──
function stageClips(v) {
  const d = stepOf('clips'), a = actOf(S.act);
  const pa = (d.per_act || []).find(x => x.id === S.act) || { files: [], has: false, fresh: false };
  const b = block('视频 · 只看画面', d.note, pa.has && !pa.fresh);
  const items = [btn(d.need && d.need.length ? `逐幕渲染（${d.need.length} 幕该做）` : '逐幕渲染',
    () => enqueue((S.pipe.acts || []).map(x => ({ kind: 'clip', args: { act: x.id } }))), 'primary')];
  if (a) {
    items.push(btn(`只渲「${a.note}」`, () => startTask('clip', { act: a.id })));
    items.push(btn('强制重渲', () => startTask('clip', { act: a.id, force: true })));
  }
  b.appendChild(row(items));
  if (a) {
    b.appendChild(el('h2', '', `${txt(a.note)} <span class="st">${a.t0.toFixed(1)}–${a.t1.toFixed(1)}s · ${a.d.toFixed(1)}s</span>`));
    if (pa.has) b.appendChild(media(pa.files, 'video'));
    else b.appendChild(el('div', 'muted small', '未渲染'));
  }
  v.appendChild(b);
}

// ── ⑥ 声音：**整轨 + 逐幕**一起看（整幕静音＝这一幕没配）──
function stageSound(v) {
  const d = stepOf('sound');
  const files = d.files || [];
  const b = block('声音', d.note, d.stale);
  b.appendChild(row([
    btn(files.length ? '重出声轨' : '出声轨', () => startTask('sound'), 'primary'),
    btn('强制重出', () => startTask('sound', { force: true })),
  ]));
  if (!files.length) {
    // 没出轨也要能先看到"打算配什么" —— 空着的一步等于没有这一步
    const cues = d.cues || [];
    if (cues.length) {
      b.appendChild(el('div', 'flabel', '打算这么配（按幕名与题款猜的，出轨后可听可改）'));
      const ul = el('ul', 'checklist');
      cues.forEach(c => ul.appendChild(el('li', '', `${txt(c.note)}：${txt(c.text || '—')}`)));
      b.appendChild(ul);
    }
    b.appendChild(el('div', 'muted small',
      '还没配声 —— 点上面「出声轨」；想换一种配法，在下面的输入框里说一句（例如「第三幕要有木鱼」）。'));
    v.appendChild(b);
    return;
  }
  const wave = files.find(f => (f.name || '').endsWith('wave.png'));
  if (wave) {
    const im = el('img', 'waveimg'); im.src = wave.url;
    im.onclick = () => zoom(wave.url, 'img');
    b.appendChild(im);
    b.appendChild(el('div', 'muted small', '波形：竖线是幕界，底部红条＝那一幕几乎无声'));
  }
  const wav = files.find(f => (f.name || '').endsWith('.wav'));
  if (wav) {
    const au = el('audio'); au.src = wav.url; au.controls = true; au.preload = 'metadata';
    au.style.cssText = 'width:100%;margin:8px 0';
    b.appendChild(au);
  }
  const per = d.per_act || [];
  if (per.length) {
    b.appendChild(el('div', 'flabel', '逐幕'));
    const tb = el('table', 'minitb');
    tb.innerHTML = '<thead><tr><th>幕</th><th>时长</th><th>响度</th><th>峰值</th><th>落点</th></tr></thead>';
    const bd = el('tbody');
    per.forEach(p => {
      const tr = el('tr');
      if (p.silent) tr.className = 'bad';
      const mark = p.silent ? ' · 几乎无声' : (p.events ? '' : ' · 无明显落点');
      tr.innerHTML = `<td>${txt(p.note)}</td><td>${(p.t1 - p.t0).toFixed(1)}s</td>
         <td>${(p.rms || 0).toFixed(3)}</td><td>${(p.peak || 0).toFixed(2)}</td>
         <td>${p.events || 0} 处${mark}</td>`;
      tr.onclick = () => { S.act = p.id; S.stage = 'clips'; renderAll(); };
      bd.appendChild(tr);
    });
    tb.appendChild(bd);
    b.appendChild(tb);
  }
  const snds = files.filter(f => (f.name || '').endsWith('_snd.mp4'));
  if (snds.length) {
    b.appendChild(el('div', 'flabel', '带声的画面'));
    b.appendChild(media(snds, 'video'));
  }
  v.appendChild(b);
}

// ── ⑦ 成片 ──
function stageFilm(v) {
  const d = stepOf('film');
  const b = block('成片', d.note);
  b.appendChild(row([
    btn(d.done ? '重新合成' : '合并出片', () => {
      if (confirm('渲染全片约 ' + Math.max(1, Math.round(S.pipe.meta.duration / 25)) + '–'
        + Math.max(2, Math.round(S.pipe.meta.duration / 12)) + ' 分钟，开始？')) startTask('film');
    }, 'primary'),
    btn('强制重合成', () => startTask('film', { force: true })),
  ]));
  if ((d.files || []).length) b.appendChild(media(d.files, 'video'));
  v.appendChild(b);
}

function media(files, kind) {
  const g = el('div', 'media');
  (files || []).forEach(f => {
    const fig = el('figure');
    if (kind === 'video') {
      const vd = el('video'); vd.src = f.url; vd.controls = true; vd.preload = 'metadata';
      fig.appendChild(vd);
    } else {
      const im = el('img'); im.src = f.url; im.loading = 'lazy'; im.onclick = () => zoom(f.url, 'img');
      fig.appendChild(im);
    }
    fig.appendChild(el('figcaption', '', txt((f.note || f.name) + (f.mb ? ` · ${f.mb} MB` : ''))));
    g.appendChild(fig);
  });
  return g;
}
function thumbs() {
  const box = el('div', 'thumbs');
  (stepOf('stills').per_act || []).forEach(x => {
    if (!x.has || !x.files.length) { box.appendChild(el('span', 'none', `${x.note}·未出`)); return; }
    const im = el('img');
    im.src = x.files[0].url; im.title = x.note;
    if (x.id === S.act) im.className = 'on';
    im.onclick = () => { S.act = x.id; renderAll(); };
    box.appendChild(im);
  });
  return box;
}
function checks(d) {
  const box = el('div', 'checks');
  const c = d.checks;
  if (!c) return box;
  const sm = c.summary || {}, bad = c.problems || [];
  box.appendChild(el('div', 'chline', `<b>自动检验</b>
    <span class="badge b-pass">通过 ${sm.pass || 0}</span>
    <span class="badge ${sm.warn ? 'b-warn' : 'b-skip'}">警告 ${sm.warn || 0}</span>
    <span class="badge ${sm.fail ? 'b-fail' : 'b-skip'}">失败 ${sm.fail || 0}</span>
    <span class="muted small">${txt(c.when || '')}</span>`));
  if (bad.length) {
    const l = el('div', 'chlist');
    bad.forEach(i => l.appendChild(el('div', 'chrow',
      `<span class="badge b-${i.status}">${i.status === 'fail' ? '失败' : '警告'}</span>
       <b>${txt(i.name)}</b><span>${txt(i.detail)}</span>` + (i.fix ? `<em>改法：${txt(i.fix)}</em>` : ''))));
    box.appendChild(l);
  }
  return box;
}

// ═══════════ 任务 ═══════════
function enqueue(items) {
  S.queue = (S.queue || []).concat(items);
  nextInQueue();
}
function nextInQueue() {
  if (S.busy || !S.queue.length) return;
  S.busy = true;
  const it = S.queue.shift();
  startTask(it.kind, it.args);
}
async function startTask(kind, args) {
  let r = {};
  try {
    r = await (await fetch(`/api/tasks/${S.fid}/${kind}`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(args || {})
    })).json();
  } catch (e) { r = { error: String(e) }; }
  if (r.error) { toast('启动失败：' + r.error); S.busy = false; setTimeout(nextInQueue, 400); return; }
  S.log = [];
  S.watch = true;                 // 让轮询兜底：任务全部结束后无论如何拉一次新产物
  openStream(r.id);
}
function openStream(jid) {
  if (S.es) S.es.close();
  S.cur = jid;
  S.es = new EventSource('/api/events?job=' + jid);
  S.es.addEventListener('progress', ev => onRun(JSON.parse(ev.data)));
  S.es.addEventListener('end', async ev => {
    onRun(JSON.parse(ev.data));
    S.busy = false;
    await refresh();
    nextInQueue();
  });
  S.es.onerror = () => { };
}
function onRun(d) {
  S.jobs = (S.jobs || []).filter(j => j.id !== d.id).concat([d]);
  if (d.log) S.log = d.log;
  renderJobs(); renderRight(); renderOps();
}
async function pollJobs() {
  try {
    const r = await (await fetch('/api/jobs')).json();
    const prev = S.jobs || [];
    S.jobs = r.jobs || [];
    renderJobs();
    const nowRun = (S.jobs || []).some(j => ['running', 'pending'].includes(j.state));
    if (nowRun) renderOps();
    // 有过任务、现在都结束了 → 兜底拉一次产物（S.watch 由 startTask 置位）。
    // 不能只靠 SSE 的 end：dev server 断流时会丢 → "任务跑完了、图却没出现"，要手动刷新才看得见。
    else if (S.watch) { S.watch = false; await refresh(); }
  } catch (e) { }
}

// ═══════════ 改这一幕 ═══════════
let eaId = null;
function openEditAct(a) {
  eaId = a.id;
  $('#eaNote').value = a.note || '';
  $('#eaDur').value = (a.d || 0).toFixed(1);
  $('#eaCap1').value = (a.caption || [])[0] || '';
  $('#eaCap2').value = (a.caption || [])[1] || '';
  const H = (S.pipe.meta.size || [1600, 900])[1];
  $('#eaHCanv').textContent = H;
  $('#eaH').min = Math.round(H * 0.09); $('#eaH').max = Math.round(H * 0.56);
  $('#eaH').value = Math.round((a.subject || {}).h || H * 0.3);
  $('#eaMsg').className = 'testline'; $('#eaMsg').textContent = '';
  $('#editAct').hidden = false;
}
$('#eaCancel').onclick = () => { $('#editAct').hidden = true; };
$('#editAct').addEventListener('click', e => { if (e.target.id === 'editAct') $('#editAct').hidden = true; });
$('#eaOk').onclick = async () => {
  const body = {
    note: $('#eaNote').value.trim(), dur: parseFloat($('#eaDur').value || '0'),
    caption: [$('#eaCap1').value.trim(), $('#eaCap2').value.trim()].filter(Boolean),
    h: parseFloat($('#eaH').value || '0'),
  };
  const r = await (await fetch(`/api/films/${S.fid}/acts/${eaId}`, {
    method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body)
  })).json();
  if (!r.ok) { $('#eaMsg').className = 'testline bad'; $('#eaMsg').textContent = '保存失败：' + r.error; return; }
  $('#editAct').hidden = true;
  toast('已改「' + body.note + '」');
  refresh();
};

// ═══════════ 设置 ═══════════
function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.hidden = false;
  clearTimeout(t._h); t._h = setTimeout(() => { t.hidden = true; }, 2600);
}
$('#btnSet').onclick = async () => {
  const st = await (await fetch('/api/settings')).json();
  $('#setBase').value = st.base_url || ''; $('#setModel').value = st.model || '';
  $('#setHint').textContent = st.has_key ? ('已配置密钥 ' + st.key_hint) : '未配置（手工模式）';
  $('#setTest').className = 'testline';
  $('#drawer').hidden = false;
};
const closeSet = () => { $('#drawer').hidden = true; };
$('#btnCloseSet').onclick = closeSet;
$('#drawer').addEventListener('click', e => { if (e.target.id === 'drawer') closeSet(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeSet(); $('#editAct').hidden = true; } });
$('#btnTestSet').onclick = async () => {
  const box = $('#setTest');
  const body = { base_url: $('#setBase').value.trim(), model: $('#setModel').value.trim() };
  const k = $('#setKey').value.trim(); if (k) body.api_key = k;
  box.className = 'testline running'; box.textContent = '测试中…';
  const r = await (await fetch('/api/settings/test', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body)
  })).json();
  box.className = 'testline ' + (r.ok ? 'ok' : 'bad');
  box.textContent = r.ok ? `通了 · ${r.model} · ${r.ms} ms` : `不通 · ${r.error}` + (r.detail ? `\n${r.detail}` : '');
};
$('#btnSaveSet').onclick = async () => {
  const body = { base_url: $('#setBase').value.trim(), model: $('#setModel').value.trim() };
  const k = $('#setKey').value.trim(); if (k) body.api_key = k;
  let msg = '';
  try {
    const r = await (await fetch('/api/settings', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body)
    })).json();
    msg = r.has_key ? '已保存' : '已保存（手工模式）';
    $('#keyDot').className = 'keydot' + (r.has_key ? ' on' : '');
    $('#setKey').value = '';
  } catch (e) { msg = '保存失败：' + e; } finally { closeSet(); toast(msg); }
};

// ── 图片/视频放大（浮层，不新开标签页）──
function zoom(url, kind) {
  const ov = $('#zoom');
  ov.innerHTML = '';
  let elx;
  if (kind === 'video') {
    elx = el('video'); elx.src = url; elx.controls = true; elx.autoplay = true;
    elx.style.maxWidth = '92vw'; elx.style.maxHeight = '88vh';
  } else {
    elx = el('img'); elx.src = url;
    elx.style.maxWidth = '92vw'; elx.style.maxHeight = '88vh'; elx.style.objectFit = 'contain';
  }
  ov.appendChild(elx);
  ov.hidden = false;
}
$('#zoom').onclick = () => { $('#zoom').hidden = true; };

boot();
