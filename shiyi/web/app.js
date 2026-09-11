/* 拾遗 —— 前端。无框架、无构建、无外链，断网也能跑。 */
'use strict';

const ROOT = document.documentElement;
const TOKEN = ROOT.dataset.token;
const VERSION = ROOT.dataset.version;
const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => [...(r || document).querySelectorAll(s)];

/* 后端用这两个哨兵字符标出命中位置，转义之后再换成 <mark>，顺序不能反 */
const MK_A = String.fromCharCode(2), MK_B = String.fromCharCode(3);

/* ─────────────────────────────────────────────── 基础 */
const api = async (path, body) => {
  const opt = body
    ? { method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Shiyi-Token': TOKEN },
        body: JSON.stringify(body) }
    : {};
  const r = await fetch('/api/' + path, opt);
  const j = await r.json().catch(() => ({ error: '返回的不是 JSON' }));
  if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
  return j;
};

const esc = s => String(s ?? '').replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const hl = s => esc(s).replaceAll(MK_A, '<mark>').replaceAll(MK_B, '</mark>');

const size = n => {
  if (n == null) return '';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (n >= 1024 && i < 4) { n /= 1024; i++; }
  return (i === 0 ? n : n.toFixed(n < 10 ? 1 : 0)) + u[i];
};

const when = ts => {
  if (!ts) return '';
  const d = new Date(ts * 1000), now = new Date();
  const days = Math.floor((now - d) / 86400000);
  if (days === 0) return '今天 ' + d.toTimeString().slice(0, 5);
  if (days === 1) return '昨天';
  if (days < 7) return days + ' 天前';
  const pad = n => String(n).padStart(2, '0');
  if (d.getFullYear() === now.getFullYear())
    return (d.getMonth() + 1) + '月' + d.getDate() + '日';
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
};

const KIND_CN = { doc: '文档', slide: '幻灯', sheet: '表格', pdf: 'PDF', code: '代码',
                  image: '图片', video: '视频', audio: '音频', archive: '压缩包',
                  app: '程序', font: '字体', other: '其他' };

/* 你写的东西排前面，机器产生的排后面。按数量排会让「其他 10 万」霸占第一格。 */
const KIND_ORDER = ['doc', 'slide', 'pdf', 'sheet', 'code', 'image',
                    'video', 'audio', 'archive', 'app', 'font', 'other'];

const ICONS = {
  search: '<circle cx="7.5" cy="7.5" r="5.5"/><path d="M11.6 11.6 15 15"/>',
  grid: '<rect x="2" y="2" width="5.4" height="5.4" rx="1"/><rect x="9.6" y="2" width="5.4" height="5.4" rx="1"/><rect x="2" y="9.6" width="5.4" height="5.4" rx="1"/><rect x="9.6" y="9.6" width="5.4" height="5.4" rx="1"/>',
  stack: '<path d="M8.5 1.8 15 5.2 8.5 8.6 2 5.2z"/><path d="M2 8.5l6.5 3.4L15 8.5"/><path d="M2 11.8l6.5 3.4L15 11.8"/>',
  clock: '<circle cx="8.5" cy="8.5" r="6.5"/><path d="M8.5 4.6v4.2l2.8 1.7"/>',
  gear: '<circle cx="8.5" cy="8.5" r="2.6"/><path d="M8.5 1.6v2M8.5 13.4v2M15.4 8.5h-2M3.6 8.5h-2M13.4 3.6l-1.4 1.4M5 12l-1.4 1.4M13.4 13.4 12 12M5 5 3.6 3.6"/>',
  info: '<circle cx="8.5" cy="8.5" r="6.6"/><path d="M8.5 7.6v4.2"/><circle cx="8.5" cy="5.2" r=".9" fill="currentColor" stroke="none"/>',
};

const toast = (() => {
  const el = $('#toast');
  let t;
  return (msg, ms) => {
    el.textContent = msg;
    el.classList.add('on');
    clearTimeout(t);
    t = setTimeout(() => el.classList.remove('on'), ms || 2400);
  };
})();

/* 一个 Promise 化的确认框，比 window.confirm 好看，也能带说明 */
function confirmBox(title, body, { okText = '确定', danger = false, extra = '' } = {}) {
  return new Promise(resolve => {
    const m = $('#modal');
    $('#mTitle').textContent = title;
    $('#mBody').innerHTML = body;
    $('#mExtra').innerHTML = extra;
    const ok = $('#mOk');
    ok.textContent = okText;
    ok.classList.toggle('danger', danger);
    m.classList.remove('hidden');
    const done = v => {
      m.classList.add('hidden');
      ok.onclick = $('#mCancel').onclick = m.onclick = null;
      resolve(v ? ($('#mExtra input[type=checkbox]')?.checked ?? true) : false);
    };
    ok.onclick = () => done(true);
    $('#mCancel').onclick = () => done(false);
    m.onclick = e => { if (e.target === m) done(false); };
  });
}

const open = async (path, reveal) => {
  try { await api('open', { path, reveal: !!reveal }); }
  catch (e) { toast('打不开：' + e.message); }
};

/* ─────────────────────────────────────────────── 状态 */
const S = {
  view: 'search', stats: null, about: null,
  kind: '', q: '', sort: 'relevance',
  hits: [], sel: -1, offset: 0, more: false, reqId: 0,
  tidy: 'clusters', tidyData: {}, year: null, projects: null,
  settings: null, draft: null,
};

const PAGE = 40;

/* ─────────────────────────────────────────────── 主题 */
function applyTheme(theme) {
  if (theme === 'light' || theme === 'dark') ROOT.setAttribute('data-theme', theme);
  else ROOT.removeAttribute('data-theme');
}

/* ─────────────────────────────────────────────── 导航 */
const VIEWS = ['search', 'projects', 'tidy', 'year', 'settings', 'about'];

function showView(name, fromHash) {
  // 不用 confirm 把人困在设置页。草稿留在内存里，回来还在，
  // 侧栏上点一个小圆点提醒还没保存就够了。
  if (!VIEWS.includes(name)) name = 'search';
  S.view = name;
  if (!fromHash) {
    // 记在地址栏里：刷新还停在这一页，也能收藏。
    // 查询串在前、hash 在后，顺序反了就成了 #tidy?q=… 这种畸形 URL。
    try {
      const u = new URL(location.href);
      u.hash = name === 'search' ? '' : name;
      history.replaceState(null, '', u);
    } catch { /* 忽略 */ }
  }
  $$('.view').forEach(v => v.classList.toggle('on', v.id === 'view-' + name));
  $$('.tabs button').forEach(b => b.classList.toggle('on', b.dataset.view === name));
  if (name === 'projects') loadProjects();
  if (name === 'tidy') loadTidy();
  if (name === 'year') loadYear();
  if (name === 'settings') loadSettings();
  if (name === 'about') loadAbout();
  if (name === 'search') $('#q').focus();
}

/* ─────────────────────────────────────────────── 检索 */
let timer = null;
function onType() {
  $('#qclear').classList.toggle('hidden', !$('#q').value);
  clearTimeout(timer);
  timer = setTimeout(() => runSearch(), 110);
}

async function runSearch(append) {
  const q = $('#q').value.trim();
  if (!append) { S.offset = 0; S.hits = []; S.sel = -1; }
  S.q = q;
  const id = ++S.reqId;
  const p = new URLSearchParams({ q, limit: String(PAGE), offset: String(S.offset),
                                  order: S.sort });
  if (S.kind) p.set('kind', S.kind);
  // 没输入内容时只列「作品」，不列 .lnk / .gitignore 这类系统碎屑
  if (!q && !S.kind) p.set('recent', '1');
  try {
    const r = await api('search?' + p);
    if (id !== S.reqId) return;              // 旧请求晚到了，丢掉
    S.hits = append ? S.hits.concat(r.hits) : r.hits;
    S.more = r.more || r.hits.length === PAGE;
    if (!append) syncUrl(q);
    renderResults(r, append);
    if (!append && q && r.total) rememberQuery(q);
    renderHints();
  } catch (e) {
    $('#results').innerHTML = `<div class="empty"><b>出错了</b>${esc(e.message)}</div>`;
  }
}

function renderResults(r, append) {
  const list = $('#results');
  const shown = S.hits.length;
  $('#resultMeta').textContent = S.q
    ? `${r.total}${r.more ? '+' : ''} 条结果 · ${r.ms}ms`
    : (S.kind ? `最近改动的 ${shown} 个${KIND_CN[S.kind] || ''}`
               : `最近动过的 ${shown} 件作品`);
  $('#modeTag').textContent = { fts: '索引', like: '扫描正文', list: '' }[r.mode] || '';

  if (!shown) {
    list.innerHTML = S.q
      ? `<div class="empty"><b>没找到「${esc(S.q)}」</b>
           试试更短的词，或换一个说法。中文两三个字通常最灵。</div>`
      : `<div class="empty"><b>${S.stats && S.stats.files ? '最近没有动过的作品' : '索引还是空的'}</b>
           ${S.stats && S.stats.files
             ? '上面输入任意一个词，就能翻遍你写过的每一句话。'
             : '点左下角「重新扫描」，或到「设置」里选好要扫的目录。'}</div>`;
    $('#detail').innerHTML = DETAIL_IDLE;
    $('#more').classList.add('hidden');
    return;
  }

  const base = append ? shown - r.hits.length : 0;
  const html = S.hits.slice(base).map((h, i) => {
    const idx = base + i;
    return `
    <li class="hit fresh" data-i="${idx}" style="--i:${Math.min(i, 14)}">
      <div class="hit-top">
        <span class="tag ${esc(h.kind)}">${KIND_CN[h.kind] || h.kind}</span>
        <span class="hit-name">${hl(markName(h.name))}</span>
        <span class="hit-size">${size(h.size)} · ${when(h.mtime)}</span>
      </div>
      <div class="hit-path">${esc(h.parent)}</div>
      ${h.snip ? `<div class="hit-snip">${hl(h.snip)}</div>` : ''}
    </li>`;
  }).join('');

  if (append) list.insertAdjacentHTML('beforeend', html);
  else { list.innerHTML = html; list.scrollTop = 0; }
  $('#more').classList.toggle('hidden', !S.more);

  // 入场动画只放一次。不摘掉 fresh，后面重排会再抖一遍。
  setTimeout(() => $$('.hit.fresh', list).forEach(el => el.classList.remove('fresh')), 700);

  // 自动选中第一条：右边那半屏本来就该有东西，顺手也省一次点击
  if (!append && S.hits.length && S.sel < 0) select(0, true);
}

/* 文件名里的命中自己标 —— 后端的 snippet 只覆盖正文 */
function markName(name) {
  if (!S.q) return name;
  const i = name.toLowerCase().indexOf(S.q.toLowerCase());
  if (i < 0) return name;
  return name.slice(0, i) + MK_A + name.slice(i, i + S.q.length) +
         MK_B + name.slice(i + S.q.length);
}

function select(i, quiet) {
  if (i < 0 || i >= S.hits.length) return;
  S.sel = i;
  $$('.hit').forEach((el, k) => el.classList.toggle('sel', k === i));
  if (!quiet) {
    const el = $$('.hit')[i];
    if (el) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  showDetail(S.hits[i].id);
}

const DETAIL_IDLE = `
  <div class="d-idle">
    <span class="mark"><svg viewBox="0 0 17 17" fill="none" stroke="currentColor"
      stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"
      style="width:20px;height:20px"><path d="M3.5 2h6l4 4v9a.5.5 0 0 1-.5.5H3.5
      a.5.5 0 0 1-.5-.5v-13A.5.5 0 0 1 3.5 2z"/><path d="M9.5 2v4h4"/></svg></span>
    <p>选中左边任意一条<br>这里会显示它的全文</p>
  </div>`;

const DETAIL_SKELETON = `
  <div class="skel" style="padding-top:4px">
    <i class="w2" style="height:17px"></i><i class="w3"></i>
    <i style="margin-top:22px;height:34px"></i>
    <i class="w1" style="margin-top:22px"></i><i class="w3"></i>
    <i class="w2"></i><i class="w3"></i><i class="w1"></i>
  </div>`;

async function showDetail(id) {
  const d = $('#detail');
  d.innerHTML = DETAIL_SKELETON;
  let f;
  try { f = await api('file/' + id); }
  catch (e) { d.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }

  const facts = [
    ['类别', KIND_CN[f.kind] || f.kind],
    ['大小', size(f.size)],
    ['修改', when(f.mtime)],
    f.project ? ['项目', esc(f.project.name)] : null,
    f.text_len ? ['正文', f.text_len.toLocaleString() + ' 字'] : null,
    f.exists ? null : ['状态', '<span class="warn">文件已不在了</span>'],
    statusNote(f.text_status),
  ].filter(Boolean);

  const copies = (f.copies || []).length
    ? `<div class="copies"><b>另有 ${f.copies.length} 处内容相同：</b>${
        f.copies.map(c => `<span data-p="${esc(c.path)}">${esc(c.path)}</span>`).join('')}</div>`
    : '';

  d.innerHTML = `
    <div class="d-name">${esc(f.name)}</div>
    <p class="d-path">${esc(f.path)}</p>
    <div class="d-acts">
      <button data-act="open">打开</button>
      <button data-act="reveal">在文件夹中显示</button>
    </div>
    <dl class="d-facts">${facts.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>
    ${copies}
    ${f.body ? `<div class="d-body">${hlBody(f.body)}</div>`
             : '<div class="d-body muted">（没有可显示的正文）</div>'}`;

  $$('[data-act]', d).forEach(b => b.onclick = () =>
    open(f.path, b.dataset.act === 'reveal'));
  $$('.copies [data-p]', d).forEach(el => el.onclick = () => open(el.dataset.p, true));
}

function statusNote(st) {
  if (!st) return null;
  const map = {
    cloud: '云端文件，没下载到本地（只索引了文件名）',
    scanned: '扫描件，没有文字层',
    'no-tounicode': '字体没有映射表，取不出文字',
    garbled: '正文乱码', empty: '内容为空', binary: '二进制文件',
    legacy: '老版 Office，正文可能不完整',
    'skip:generated': '生成物，未索引正文',
    'skip:vendor': '第三方代码，未索引正文',
    'skip:data': '数据文件，未索引正文',
    'skip:bulk': '所在目录纯文本太多，未索引正文',
    'skip:minified': '压缩过的代码，未索引正文',
    'skip:toobig': '文件过大，未索引正文',
  };
  if (map[st]) return ['备注', map[st]];
  return st.startsWith('error') ? ['备注', '读取失败'] : null;
}

function hlBody(body) {
  const t = esc(body);
  if (!S.q) return t;
  try {
    const re = new RegExp(S.q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
    return t.replace(re, m => '<mark>' + m + '</mark>');
  } catch { return t; }
}

/* 「最近搜过的」比写死几个例子有用得多——例子只对写例子的人成立。
   存在浏览器本地，不上传，也不进索引。 */
const RECENT_KEY = 'shiyi.recent';
const RECENT_MAX = 8;

function loadRecent() {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]'); }
  catch { return []; }
}

function rememberQuery(q) {
  q = (q || '').trim();
  if (q.length < 2) return;
  try {
    const list = loadRecent().filter(x => x !== q);
    list.unshift(q);
    localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, RECENT_MAX)));
  } catch { /* 隐私模式下写不进去，无所谓 */ }
}

function renderHints() {
  const old = $('#hintbar');
  if (old) old.remove();
  if ($('#q').value || !S.stats || !S.stats.files) return;

  const recent = loadRecent();
  const bar = document.createElement('div');
  bar.id = 'hintbar';
  bar.className = 'hintbar';
  bar.innerHTML = recent.length
    ? '<span>最近搜过：</span>' +
      recent.map(h => `<button data-h="${esc(h)}">${esc(h)}</button>`).join('') +
      '<button id="clearRecent" class="ghost" title="清空">清空</button>'
    : '<span>输入任意一个词，就能翻遍你写过的每一句话。中文两三个字通常最灵。</span>';

  const split = $('#view-search .split');
  split.parentElement.insertBefore(bar, split);
  $$('[data-h]', bar).forEach(b => b.onclick = () => {
    $('#q').value = b.dataset.h;
    onType();
    $('#q').focus();
  });
  const cl = $('#clearRecent', bar);
  if (cl) cl.onclick = () => {
    try { localStorage.removeItem(RECENT_KEY); } catch { /* 无所谓 */ }
    renderHints();
  };
}

async function exportSearch() {
  const btn = $('#btnExportSearch');
  btn.disabled = true;
  try {
    const r = await api('export-search',
                        { q: S.q, kind: S.kind, order: S.sort, format: 'csv' });
    toast(`已导出 ${r.count} 条到桌面`);
    open(r.path);
  } catch (e) { toast('导出失败：' + e.message); }
  btn.disabled = false;
}

/* 读取中给个形状，比转圈更安定，也不会让版面跳动 */
const skeletonRows = n => Array.from({ length: n }, (_, i) =>
  `<div class="skel" style="--i:${i}"><i class="w2" style="height:15px"></i>
   <i class="w3"></i><i class="w1"></i></div>`).join('');
const skeletonCards = n =>
  Array.from({ length: n }, () =>
    `<div class="pcard" style="pointer-events:none"><div class="skel" style="padding:0">
     <i class="w2" style="height:15px"></i><i class="w3"></i><i class="w1"></i></div></div>`).join('');

/* ─────────────────────────────────────────────── 项目 */
async function loadProjects(force) {
  const grid = $('#projectGrid');
  if (!S.projects || force) {
    grid.innerHTML = skeletonCards(6);
    S.projects = (await api('projects')).projects;
  }
  renderProjects();
}

function renderProjects() {
  const f = $('#pq').value.trim().toLowerCase();
  const rows = S.projects.filter(p =>
    !f || p.name.toLowerCase().includes(f) || (p.kinds || '').toLowerCase().includes(f));
  const grid = $('#projectGrid');
  if (!rows.length) {
    grid.innerHTML = '<div class="empty">没有匹配的项目。</div>';
    return;
  }
  grid.innerHTML = rows.map((p, i) => `
    <div class="pcard${p.unpacked || p.third_party ? ' dim' : ''}"
         data-path="${esc(p.path)}" style="--i:${Math.min(i, 18)}">
      <h3>${esc(p.name)}</h3>
      <div class="ppath">${esc(p.path)}</div>
      <div class="prow">
        <span>${p.file_count} 个文件 · ${size(p.size)}</span>
        <span>${when(p.mtime)}</span>
      </div>
      <div class="langs">${(p.kinds || '').split(',').filter(Boolean)
        .map(k => `<span class="lang">${esc(k)}</span>`).join('')}
        ${p.is_git ? `<span class="lang git">git:${esc(p.git_branch || '')}</span>` : ''}
        ${p.unpacked ? '<span class="lang cold">解压/安装</span>' : ''}
      </div>
      <div class="pacts">
        <button data-act="search">在此搜索</button>
        <button data-act="open">打开文件夹</button>
      </div>
    </div>`).join('');
  $$('.pcard', grid).forEach(c => {
    $$('[data-act]', c).forEach(b => b.onclick = e => {
      e.stopPropagation();
      if (b.dataset.act === 'open') open(c.dataset.path);
      else { showView('search'); $('#q').value = ''; toast('在项目内检索：' + $('h3', c).textContent); }
    });
    c.onclick = () => open(c.dataset.path);
  });
}

/* ─────────────────────────────────────────────── 整理 */
async function loadTidy(force) {
  const body = $('#tidyBody');
  if (!S.tidyData.clusters || force) {
    body.innerHTML = skeletonRows(5);
    const [c, d, t] = await Promise.all([api('clusters'), api('duplicates'), api('timeline')]);
    S.tidyData = { clusters: c.clusters, dups: d.groups, stale: t.stale };
  }
  const { clusters, dups } = S.tidyData;
  const waste = clusters.reduce((a, c) => a + c.waste, 0) +
                dups.reduce((a, g) => a + g.bytes - (g.bytes / g.count), 0);
  $('#tidySummary').innerHTML = `
    <div style="--i:0"><b>${clusters.length}</b><span>组版本堆积</span></div>
    <div style="--i:1"><b>${dups.length}${dups.length >= 120 ? '+' : ''}</b><span>组内容重复</span></div>
    <div style="--i:2"><b>${size(waste)}</b><span>只留一份可省下</span></div>`;
  renderTidy();
}

function renderTidy() {
  const body = $('#tidyBody');
  $$('.tidy-tabs button').forEach(b => b.classList.toggle('on', b.dataset.t === S.tidy));

  if (S.tidy === 'clusters') {
    const cs = S.tidyData.clusters;
    body.innerHTML = cs.length ? cs.map((c, i) => `
      <div class="grp" style="--i:${Math.min(i, 14)}">
        <div class="grp-h" data-g="${i}">
          <h4>${esc(c.title)}</h4>
          <span class="badge">${c.count} 份</span>
          <span class="badge q">冗余 ${size(c.waste)}</span>
          <span class="badge q">跨 ${c.span_days} 天</span>
        </div>
        <div class="grp-b">${c.members.map((m, k) => `
          <div class="mem ${k === 0 ? 'keep' : ''}">
            <span class="v">${esc(m.version || '—')}</span>
            <span class="p" data-p="${esc(m.path)}">${esc(m.path)}</span>
            <span class="s">${size(m.size)}</span>
          </div>`).join('')}</div>
      </div>`).join('')
      : '<div class="empty"><b>没有版本堆积</b>难得。</div>';
  } else if (S.tidy === 'dups') {
    const gs = S.tidyData.dups;
    body.innerHTML = gs.length ? gs.map((g, i) => `
      <div class="grp" style="--i:${Math.min(i, 14)}">
        <div class="grp-h">
          <h4>${esc(g.members[0].name)}</h4>
          <span class="badge">${esc(g.label)} ${g.count} 份</span>
          <span class="badge q">${size(g.bytes)}</span>
          <span class="badge q">你的目录里 ${g.own} 份</span>
        </div>
        <div class="grp-b">${g.members.map(m => `
          <div class="mem">
            <span class="v">${m.mine ? '你的' : '收到'}</span>
            <span class="p" data-p="${esc(m.path)}">${esc(m.path)}</span>
            <span class="s">${when(m.mtime)}</span>
          </div>`).join('')}</div>
      </div>`).join('')
      : '<div class="empty"><b>没有内容重复的文件</b></div>';
  } else {
    const st = S.tidyData.stale;
    body.innerHTML = st.length ? `<div class="grp"><div class="grp-b">${st.map(p => `
      <div class="mem">
        <span class="p" data-p="${esc(p.path)}">${esc(p.name)} — ${esc(p.path)}</span>
        <span class="s">${when(p.mtime)}</span>
      </div>`).join('')}</div></div>`
      : '<div class="empty">没有被冷落的项目。</div>';
  }

  $$('.grp-h[data-g]', body).forEach(h => h.onclick = () => {
    const b = h.nextElementSibling;
    b.style.display = b.style.display === 'none' ? '' : 'none';
  });
  $$('[data-p]', body).forEach(el => el.onclick = e => {
    e.stopPropagation();
    open(el.dataset.p, true);
  });
}

/* ─────────────────────────────────────────────── 年鉴 */
async function loadYear() {
  const years = S.stats.years.filter(y => y.year >= 2015 && y.count >= 5).slice(0, 8);
  if (!years.length) {
    $('#yearBody').innerHTML = '<div class="empty">还没有数据。</div>';
    return;
  }
  if (!S.year) S.year = years[0].year;
  $('#yearPick').innerHTML = years.map(y =>
    `<button data-y="${y.year}" class="${y.year === S.year ? 'on' : ''}">${y.year}</button>`).join('');
  $$('#yearPick button').forEach(b => b.onclick = () => { S.year = +b.dataset.y; loadYear(); });

  const body = $('#yearBody');
  body.innerHTML = skeletonRows(4);
  const d = await api('year/' + S.year);
  const acts = d.artifacts || [];

  const months = Array.from({ length: 12 }, (_, i) => ({ m: i + 1, c: 0 }));
  acts.forEach(a => { months[new Date(a.mtime * 1000).getMonth()].c++; });
  const max = Math.max(1, ...months.map(m => m.c));

  body.innerHTML = `
    <div class="ystats">
      <div class="ystat" style="--i:0"><b>${d.files.toLocaleString()}</b><span>个文件动过</span></div>
      <div class="ystat" style="--i:1"><b>${d.artifact_total}</b><span>件成品</span></div>
      <div class="ystat" style="--i:2"><b>${(d.words / 10000).toFixed(1)}万</b><span>字（成品正文）</span></div>
      <div class="ystat" style="--i:3"><b>${d.projects.length}</b><span>个项目在动</span></div>
      <div class="ystat" style="--i:4"><b>${d.busiest_month ? d.busiest_month.slice(5) + '月' : '—'}</b><span>最忙的月份</span></div>
    </div>

    <h2 class="sec">成品分布</h2>
    <div class="chart">${months.map((m, i) =>
      `<div class="bar" style="height:${Math.max(3, m.c / max * 100)}%;--i:${i}"><b>${m.m}月 ${m.c}</b></div>`).join('')}</div>
    <div class="chart-x">${months.map(m => `<span>${m.m}</span>`).join('')}</div>

    <h2 class="sec">这一年做出来的东西
      <span class="sub">（${d.artifact_total}，不含下载与聊天接收）</span>
      <button id="btnExport" class="mini-btn">导出年鉴</button></h2>
    <div class="alist">${acts.slice(0, 60).map(a => `
      <div class="arow" data-p="${esc(a.path)}">
        <span class="tag ${esc(a.kind)}">${KIND_CN[a.kind] || a.kind}</span>
        <span class="an">${esc(a.name)}</span>
        <span class="ad">${size(a.size)}</span>
        <span class="ad">${when(a.mtime)}</span>
      </div>`).join('')}</div>

    <h2 class="sec">最活跃的项目</h2>
    <div class="alist">${d.projects.slice(0, 12).map(p => `
      <div class="arow" data-p="${esc(p.path)}">
        <span class="an">${esc(p.name)}</span>
        <span class="ad">${p.hits} 次改动</span>
      </div>`).join('')}</div>`;

  $$('[data-p]', body).forEach(el => el.onclick = () => open(el.dataset.p, true));
  const be = $('#btnExport');
  if (be) be.onclick = async () => {
    be.disabled = true;
    be.textContent = '生成中…';
    try {
      const r = await api('export-year', { year: S.year });
      toast('已生成到桌面');
      open(r.path);
    } catch (e) { toast('导出失败：' + e.message); }
    be.disabled = false;
    be.textContent = '导出年鉴';
  };
}

/* ─────────────────────────────────────────────── 设置 */
async function loadSettings(force) {
  if (!S.settings || force) {
    S.settings = await api('settings');
    S.draft = JSON.parse(JSON.stringify(S.settings));
  }
  renderSettings();
}

function isDirty() {
  if (!S.settings || !S.draft) return false;
  const keys = ['roots', 'extra_ignores', 'index_content', 'max_text_bytes',
                'scan_on_start', 'auto_scan_minutes', 'open_window_on_start'];
  return keys.some(k => JSON.stringify(S.draft[k]) !== JSON.stringify(S.settings[k]));
}

function markDirty() {
  const dirty = isDirty();
  const tab = $('[data-view="settings"]');
  if (tab) tab.classList.toggle('dirty', dirty);
  return dirty;
}

function renderSettings() {
  const d = S.draft;
  $('#rootList').innerHTML = d.roots.length
    ? d.roots.map((r, i) => `
        <li><span class="rp">${esc(r)}</span>
            <button class="rm" data-i="${i}">移除</button></li>`).join('')
    : '<li class="bad">一个目录都没有，拾遗会无事可做。</li>';
  $$('#rootList .rm').forEach(b => b.onclick = () => {
    d.roots.splice(+b.dataset.i, 1);
    renderSettings();
  });

  $('#ignoreList').innerHTML = d.extra_ignores.length
    ? d.extra_ignores.map((r, i) =>
        `<li>${esc(r)}<button data-i="${i}">×</button></li>`).join('')
    : '<li class="none">没有额外排除项</li>';
  $$('#ignoreList button').forEach(b => b.onclick = () => {
    d.extra_ignores.splice(+b.dataset.i, 1);
    renderSettings();
  });

  $('#optContent').checked = d.index_content;
  $('#optMaxText').value = String(d.max_text_bytes);
  $('#optScanStart').checked = d.scan_on_start;
  $('#optInterval').value = String(d.auto_scan_minutes);
  $('#optOpenWindow').checked = d.open_window_on_start;
  $('#optAutostart').checked = d.autostart;
  $$('#themeSeg button').forEach(b =>
    b.classList.toggle('on', b.dataset.theme === d.theme));
  $('#systemCard').classList.toggle('hidden', !d.platform_supported);

  const dirty = markDirty();
  $('#btnSave').disabled = !dirty;
  $('#btnRevert').disabled = !dirty;
  $('#saveHint').textContent = dirty ? '有未保存的修改' : '设置已是最新';
}

function bindSettings() {
  const set = (k, v) => { S.draft[k] = v; renderSettings(); };
  $('#addRoot').onclick = () => {
    const v = $('#newRoot').value.trim().replace(/^["']|["']$/g, '');
    if (!v) return;
    if (S.draft.roots.includes(v)) return toast('已经在列表里了');
    S.draft.roots.push(v);
    $('#newRoot').value = '';
    renderSettings();
  };
  $('#newRoot').addEventListener('keydown', e => { if (e.key === 'Enter') $('#addRoot').click(); });
  $('#addIgnore').onclick = () => {
    const v = $('#newIgnore').value.trim();
    if (!v) return;
    if (!S.draft.extra_ignores.includes(v)) S.draft.extra_ignores.push(v);
    $('#newIgnore').value = '';
    renderSettings();
  };
  $('#newIgnore').addEventListener('keydown', e => { if (e.key === 'Enter') $('#addIgnore').click(); });

  $('#optContent').onchange = e => set('index_content', e.target.checked);
  $('#optMaxText').onchange = e => set('max_text_bytes', +e.target.value);
  $('#optScanStart').onchange = e => set('scan_on_start', e.target.checked);
  $('#optInterval').onchange = e => set('auto_scan_minutes', +e.target.value);
  $('#optOpenWindow').onchange = e => set('open_window_on_start', e.target.checked);
  // 外观是显示偏好，不是扫描设置，没道理要人再点一次保存
  $$('#themeSeg button').forEach(b => b.onclick = async () => {
    const t = b.dataset.theme;
    S.draft.theme = S.settings.theme = t;
    applyTheme(t);
    renderSettings();
    try { await api('settings', { theme: t }); } catch (e) { toast('记不住这个选择：' + e.message); }
  });

  // 开机自启是系统级动作，点了立刻生效，不跟着「保存」走
  $('#optAutostart').onchange = async e => {
    try {
      const r = await api('autostart', { enable: e.target.checked });
      S.draft.autostart = S.settings.autostart = r.autostart;
      toast(r.autostart ? '已设置开机自启' : '已取消开机自启');
    } catch (err) {
      toast('设置失败：' + err.message);
      e.target.checked = !e.target.checked;
    }
  };

  $('#btnShortcut').onclick = async () => {
    try {
      const r = await api('install', { desktop: true, start_menu: true });
      toast(r.shortcuts && r.shortcuts.length
        ? `已创建 ${r.shortcuts.length} 个快捷方式` : '没能创建快捷方式');
    } catch (e) { toast('失败：' + e.message); }
  };

  $('#btnRevert').onclick = () => {
    S.draft = JSON.parse(JSON.stringify(S.settings));
    applyTheme(S.draft.theme);
    renderSettings();
  };

  $('#btnSave').onclick = async () => {
    const before = JSON.stringify(S.settings.roots) + S.settings.index_content;
    try {
      const r = await api('settings', S.draft);
      S.settings = r.settings;
      S.draft = JSON.parse(JSON.stringify(r.settings));
      renderSettings();
      applyTheme(S.settings.theme);
      const after = JSON.stringify(S.settings.roots) + S.settings.index_content;
      if (before !== after) {
        toast('已保存，开始重新扫描');
        startScan();
      } else {
        toast('设置已保存');
      }
      loadStats();
    } catch (e) { toast('保存失败：' + e.message); }
  };
}

/* ─────────────────────────────────────────────── 关于 */
async function loadAbout() {
  $('#verTag').textContent = VERSION;
  if (!S.about) {
    $('#envList').innerHTML = '<dt><span class="spin"></span></dt><dd>读取中…</dd>';
  }
  const a = await api('about');
  S.about = a;
  $('#whereCode').textContent = a.data_dir.replace(/\\\.shiyi$/, '');
  $('#envList').innerHTML = [
    ['版本', a.version + (a.frozen ? '（独立程序）' : '（源码运行）')],
    ['Python', a.python],
    ['SQLite', a.sqlite],
    ['系统', a.platform],
    ['窗口', a.browser || '默认浏览器'],
    ['索引目录', a.data_dir],
    ['日志', a.log_path],
  ].map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join('');
  renderHealth(a.health);
  $('#btnQuit').classList.toggle('hidden', !a.has_shell);
}

function renderHealth(h) {
  const ok = h.ok;
  $('#healthBox').innerHTML = `
    <div class="hrow ${ok ? 'good' : 'bad'}">
      <b>${ok ? '索引正常' : '索引有问题'}</b>
      <span>${h.files.toLocaleString()} 个文件 · ${size(h.db_bytes)}
        ${h.reclaimable ? '· 可回收 ' + size(h.reclaimable) : ''}</span>
    </div>
    ${(h.problems || []).map(p => `<div class="prob">${esc(p)}</div>`).join('')}`;
}

function bindAbout() {
  $$('[data-maint]').forEach(b => b.onclick = async () => {
    const act = b.dataset.maint;
    if (act === 'reset' || act === 'rebuild') {
      const msg = act === 'reset'
        ? '会清空索引。你的原始文件<b>一个字节都不会动</b>，但检索会一直空到下次扫描。'
        : '会清空索引并立刻重新读一遍所有文件，大概需要一两分钟。';
      if (!await confirmBox(act === 'reset' ? '清空索引？' : '重建索引？', msg,
                            { okText: act === 'reset' ? '清空' : '重建', danger: act === 'reset' }))
        return;
    }
    b.disabled = true;
    try {
      if (act === 'check') $('#healthBox').innerHTML =
        '<div class="hrow"><span class="spin"></span>正在自检，大库要几秒…</div>';
      const r = await api('maintenance', { action: act });
      if (act === 'check') { renderHealth(r.health); toast(r.health.ok ? '索引正常' : '发现问题'); }
      else if (act === 'vacuum') { toast('已回收 ' + size(r.result.saved)); loadAbout(); }
      else if (act === 'rebuild') { toast('正在重建…'); startScan(); }
      else { toast('索引已清空'); loadAbout(); loadStats(); }
    } catch (e) { toast('失败：' + e.message); }
    b.disabled = false;
  });

  $('#btnLoadLog').onclick = async () => {
    try {
      const r = await api('log?lines=300');
      $('#logBox').textContent = r.text;
      $('#logBox').classList.remove('hidden');
    } catch (e) { toast(e.message); }
  };
  $('#btnOpenLog').onclick = () => S.about && open(S.about.log_path, true);

  $('#btnQuit').onclick = async () => {
    if (!await confirmBox('退出拾遗？', '后台服务会停止，托盘图标会消失。下次从桌面图标再打开就行。',
                          { okText: '退出' })) return;
    try { await api('quit', {}); toast('再见。'); setTimeout(() => window.close(), 600); }
    catch (e) { toast(e.message); }
  };

  $('#btnUninstall').onclick = async () => {
    const yes = await confirmBox(
      '卸载拾遗？',
      '会删掉桌面和开始菜单的快捷方式，并取消开机自启。',
      { okText: '卸载', danger: true,
        extra: '<label class="opt"><input type="checkbox" id="rmIndex">' +
               '<span>同时删除索引（<b>不会</b>动你的原始文件）</span></label>' });
    if (yes === false) return;
    try {
      const r = await api('uninstall', { remove_index: yes === true && $('#rmIndex')?.checked });
      toast(`已移除 ${r.removed.length} 个快捷方式${r.index_removed ? '，索引已删除' : ''}`);
    } catch (e) { toast('失败：' + e.message); }
  };
}

/* ─────────────────────────────────────────────── 扫描 */
let scanPoll = null;
async function startScan(full) {
  try { await api('scan', { full: !!full }); }
  catch (e) { return toast('扫描起不来：' + e.message); }
  $('#scanBar').classList.remove('hidden');
  $('#btnScan').disabled = true;
  clearInterval(scanPoll);
  scanPoll = setInterval(pollScan, 400);
}

async function pollScan() {
  let p;
  try { p = await api('scan/status'); } catch { return; }
  const bar = $('#scanBar');
  const pct = p.phase === 'index' && p.total ? p.done / p.total * 100
            : p.phase === 'enumerate' ? 3 : p.phase === 'projects' ? 97 : 100;
  $('.scan-fill', bar).style.right = (100 - pct) + '%';
  $('span', bar).textContent =
    p.phase === 'enumerate' ? `枚举 ${p.seen}`
    : p.phase === 'index' ? `${p.done}/${p.total}`
    : p.phase === 'projects' ? '识别项目'
    : p.phase === 'error' ? '出错' : '完成';

  if (!p.running && (p.phase === 'done' || p.phase === 'error' || p.phase === 'idle')) {
    clearInterval(scanPoll);
    $('#btnScan').disabled = false;
    setTimeout(() => bar.classList.add('hidden'), 1400);
    if (p.message) toast(p.message);
    S.projects = null;
    S.tidyData = {};
    await loadStats();
    if (S.view === 'search') runSearch();
    if (S.view === 'about') loadAbout();
  }
}

/* ─────────────────────────────────────────────── 首次引导 */
async function maybeFirstRun() {
  const st = await api('settings');
  if (st.first_run_done && S.stats.files) return false;
  S.settings = st;
  S.draft = JSON.parse(JSON.stringify(st));
  $('#wizRootList').innerHTML = st.roots.map((r, i) =>
    `<li><span class="rp">${esc(r)}</span><button class="rm" data-i="${i}">移除</button></li>`).join('')
    || '<li class="bad">没找到常见目录，稍后到「设置」里添加。</li>';
  $$('#wizRootList .rm').forEach(b => b.onclick = () => {
    S.draft.roots.splice(+b.dataset.i, 1);
    maybeRenderWizRoots();
  });
  $('#firstrun').classList.remove('hidden');
  return true;
}

function maybeRenderWizRoots() {
  $('#wizRootList').innerHTML = S.draft.roots.map((r, i) =>
    `<li><span class="rp">${esc(r)}</span><button class="rm" data-i="${i}">移除</button></li>`).join('')
    || '<li class="bad">一个都不留的话，拾遗会无事可做。</li>';
  $$('#wizRootList .rm').forEach(b => b.onclick = () => {
    S.draft.roots.splice(+b.dataset.i, 1);
    maybeRenderWizRoots();
  });
}

function bindWizard() {
  const finish = async (scan) => {
    try { await api('settings', S.draft); } catch { /* 记不住也不该拦着 */ }
    $('#firstrun').classList.add('hidden');
    S.settings = null;
    if (scan) startScan();
  };
  $('#wizStart').onclick = () => finish(true);
  $('#wizSkip').onclick = () => finish(false);
}

/* ─────────────────────────────────────────────── 启动 */
async function loadStats() {
  S.stats = await api('stats');
  const s = S.stats;
  applyTheme(s.theme);
  $('#railStats').innerHTML = [
    ['文件', s.files.toLocaleString()],
    ['有正文', s.indexed_text.toLocaleString()],
    ['项目', s.projects],
    ['索引', size(s.db_bytes)],
  ].map(([k, v]) => `<div class="rs-row"><span>${k}</span><b>${v}</b></div>`).join('');

  const kinds = KIND_ORDER
    .filter(k => s.by_kind[k])
    .map(k => [k, s.by_kind[k]])
    .slice(0, 9);
  $('#kindFilters').innerHTML =
    `<button class="chip ${S.kind === '' ? 'on' : ''}" data-k="">全部</button>` +
    kinds.map(([k, n]) =>
      `<button class="chip ${S.kind === k ? 'on' : ''}" data-k="${k}">${KIND_CN[k] || k}<span class="n">${n}</span></button>`).join('');
  $$('.chip').forEach(c => c.onclick = () => {
    S.kind = c.dataset.k;
    $$('.chip').forEach(x => x.classList.toggle('on', x === c));
    runSearch();
  });
}

function drawIcons() {
  $$('[data-i]').forEach(el => {
    const big = el.classList.contains('sb-icon');
    const svg = `<svg viewBox="0 0 17 17" fill="none" stroke="currentColor"
      stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
      class="${el.className}" style="width:${big ? 17 : 16}px;height:${big ? 17 : 16}px;
      flex:0 0 auto">${ICONS[el.dataset.i] || ''}</svg>`;
    el.outerHTML = svg;
  });
}

function bindKeys() {
  document.addEventListener('keydown', e => {
    const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName);
    if (e.ctrlKey && e.key >= '1' && e.key <= '4') {
      e.preventDefault();
      showView(VIEWS[+e.key - 1]);
      return;
    }
    if (e.key === '/' && !typing) {
      e.preventDefault();
      showView('search');
      $('#q').select();
      return;
    }
    if (S.view !== 'search') return;
    if (e.key === 'ArrowDown') { e.preventDefault(); select(S.sel + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); select(Math.max(0, S.sel - 1)); }
    else if (e.key === 'Enter' && S.sel >= 0 && !typing) {
      e.preventDefault();
      open(S.hits[S.sel].path, e.shiftKey);
    } else if (e.key === 'Escape') {
      if ($('#q').value) { $('#q').value = ''; onType(); } else $('#q').blur();
    }
  });
}

/* 允许 ?q=... 直接带查询进来：搜索结果就能收藏、能发给别人。 */
function queryFromUrl() {
  try { return new URLSearchParams(location.search).get('q') || ''; }
  catch { return ''; }
}

function syncUrl(q) {
  try {
    const u = new URL(location.href);
    if (q) u.searchParams.set('q', q); else u.searchParams.delete('q');
    u.hash = S.view === 'search' ? '' : S.view;
    history.replaceState(null, '', u);
  } catch { /* file:// 之类的场景，忽略 */ }
}

async function boot() {
  drawIcons();
  bindKeys();
  bindSettings();
  bindAbout();
  bindWizard();

  $('#q').addEventListener('input', onType);
  $('#qclear').onclick = () => { $('#q').value = ''; onType(); $('#q').focus(); };
  $('#sort').onchange = e => { S.sort = e.target.value; runSearch(); };
  $('#btnExportSearch').onclick = exportSearch;
  $('#more button').onclick = () => { S.offset += PAGE; runSearch(true); };
  $('#pq').addEventListener('input', () => S.projects && renderProjects());
  $('#results').addEventListener('click', e => {
    const li = e.target.closest('.hit');
    if (li) select(+li.dataset.i);
  });
  $('#results').addEventListener('dblclick', e => {
    const li = e.target.closest('.hit');
    if (li) open(S.hits[+li.dataset.i].path);
  });
  $$('.tabs button').forEach(b => b.onclick = () => showView(b.dataset.view));
  $$('.tidy-tabs button').forEach(b => b.onclick = () => { S.tidy = b.dataset.t; renderTidy(); });
  $('#btnScan').onclick = () => startScan();

  // 地址栏里带了什么就从哪儿开始：#tidy 直接落在整理页，?q= 直接带着查询
  const startView = (location.hash || '').replace('#', '');
  if (startView && startView !== 'search') showView(startView, true);
  window.addEventListener('hashchange', () =>
    showView((location.hash || '').replace('#', ''), true));

  const initial = queryFromUrl();
  if (initial) {
    $('#q').value = initial;
    $('#qclear').classList.remove('hidden');
  }

  await loadStats();
  await runSearch();
  if (S.stats.scanning) {
    $('#scanBar').classList.remove('hidden');
    $('#btnScan').disabled = true;
    scanPoll = setInterval(pollScan, 400);
  }
  if (await maybeFirstRun()) return;
  if (!S.stats.files && !S.stats.scanning) startScan();
}

boot().catch(e => toast('启动失败：' + e.message, 6000));
