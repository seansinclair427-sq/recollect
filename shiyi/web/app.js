/* 拾遗 —— 前端。无框架、无构建、无外链，断网也能跑。 */
'use strict';

const TOKEN = document.documentElement.dataset.token;
const $  = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => [...(r || document).querySelectorAll(s)];

/* ─────────────────────────────────────────────── 小工具 */
const api = async (path, body) => {
  const opt = body
    ? { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Shiyi-Token': TOKEN },
        body: JSON.stringify(body) }
    : {};
  const r = await fetch('/api/' + path, opt);
  const j = await r.json().catch(() => ({ error: 'bad json' }));
  if (!r.ok) throw new Error(j.error || r.status);
  return j;
};

const size = n => {
  if (n == null) return '';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (n >= 1024 && i < 4) { n /= 1024; i++; }
  return (i === 0 ? n : n.toFixed(n < 10 ? 1 : 0)) + u[i];
};

const esc = s => String(s ?? '').replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/* 后端用 \x02 \x03 标出命中位置，转义之后再换成 <mark> —— 顺序不能反 */
const MK_A = '', MK_B = '';   // 后端用来标出命中位置的哨兵字符
const hl = s => esc(s).replaceAll(MK_A, '<mark>').replaceAll(MK_B, '</mark>');

const when = ts => {
  if (!ts) return '';
  const d = new Date(ts * 1000), now = new Date();
  const days = Math.floor((now - d) / 86400000);
  if (days === 0) return '今天 ' + d.toTimeString().slice(0, 5);
  if (days === 1) return '昨天';
  if (days < 7) return days + ' 天前';
  if (d.getFullYear() === now.getFullYear())
    return (d.getMonth() + 1) + '月' + d.getDate() + '日';
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') +
         '-' + String(d.getDate()).padStart(2, '0');
};

const KIND_CN = { doc: '文档', slide: '幻灯', sheet: '表格', pdf: 'PDF', code: '代码',
                  image: '图片', video: '视频', audio: '音频', archive: '压缩包',
                  app: '程序', font: '字体', other: '其他' };

const ICONS = {
  search: '<circle cx="7.5" cy="7.5" r="5.5"/><path d="M11.6 11.6 15 15"/>',
  grid: '<rect x="2" y="2" width="5.4" height="5.4" rx="1"/><rect x="9.6" y="2" width="5.4" height="5.4" rx="1"/><rect x="2" y="9.6" width="5.4" height="5.4" rx="1"/><rect x="9.6" y="9.6" width="5.4" height="5.4" rx="1"/>',
  stack: '<path d="M8.5 1.8 15 5.2 8.5 8.6 2 5.2z"/><path d="M2 8.5l6.5 3.4L15 8.5"/><path d="M2 11.8l6.5 3.4L15 11.8"/>',
  clock: '<circle cx="8.5" cy="8.5" r="6.5"/><path d="M8.5 4.6v4.2l2.8 1.7"/>',
};

const toast = (() => {
  const el = $('#toast');
  let t;
  return msg => {
    el.textContent = msg;
    el.classList.add('on');
    clearTimeout(t);
    t = setTimeout(() => el.classList.remove('on'), 2200);
  };
})();

const open = async (path, reveal) => {
  try { await api('open', { path, reveal: !!reveal }); }
  catch (e) { toast('打不开：' + e.message); }
};

/* ─────────────────────────────────────────────── 状态 */
const S = { view: 'search', stats: null, kind: '', hits: [], sel: -1,
            q: '', reqId: 0, tidy: 'clusters', tidyData: {}, year: null };

/* ─────────────────────────────────────────────── 导航 */
function showView(name) {
  S.view = name;
  $$('.view').forEach(v => v.classList.toggle('on', v.id === 'view-' + name));
  $$('.tabs button').forEach(b => b.classList.toggle('on', b.dataset.view === name));
  if (name === 'projects') loadProjects();
  if (name === 'tidy') loadTidy();
  if (name === 'year') loadYear();
  if (name === 'search') $('#q').focus();
}

/* ─────────────────────────────────────────────── 检索 */
let timer = null;
function onType() {
  clearTimeout(timer);
  timer = setTimeout(runSearch, 110);
}

async function runSearch() {
  const q = $('#q').value.trim();
  S.q = q;
  const id = ++S.reqId;
  const p = new URLSearchParams({ q, limit: '60' });
  if (S.kind) p.set('kind', S.kind);
  try {
    const r = await api('search?' + p);
    if (id !== S.reqId) return;              // 旧请求晚到了，丢掉
    S.hits = r.hits;
    S.sel = -1;
    renderResults(r);
    renderHints();
  } catch (e) {
    $('#results').innerHTML = `<div class="empty"><b>出错了</b>${esc(e.message)}</div>`;
  }
}

function renderResults(r) {
  const list = $('#results');
  $('#resultMeta').textContent = S.q
    ? `${r.total}${r.more ? '+' : ''} 条结果 · ${r.ms}ms`
    : `最近改动的 ${r.hits.length} 个文件`;
  $('#modeTag').textContent = { fts: '索引', like: '扫描正文', list: '' }[r.mode] || '';

  if (!r.hits.length) {
    list.innerHTML = S.q
      ? `<div class="empty"><b>没找到「${esc(S.q)}」</b>
           试试更短的词，或换一个说法。中文两三个字通常最灵。</div>`
      : `<div class="empty"><b>索引还是空的</b>
           点左下角「重新扫描」，或在「设置」里选好要扫的目录。</div>`;
    $('#detail').innerHTML = '';
    return;
  }

  list.innerHTML = r.hits.map((h, i) => `
    <li class="hit" data-i="${i}">
      <div class="hit-top">
        <span class="tag ${esc(h.kind)}">${KIND_CN[h.kind] || h.kind}</span>
        <span class="hit-name">${hl(markName(h.name))}</span>
        <span class="hit-size">${size(h.size)} · ${when(h.mtime)}</span>
      </div>
      <div class="hit-path">${esc(h.parent)}</div>
      ${h.snip ? `<div class="hit-snip">${hl(h.snip)}</div>` : ''}
    </li>`).join('');
}

/* 文件名里的命中自己标 —— 后端的 snippet 只覆盖正文 */
function markName(name) {
  if (!S.q) return name;
  const i = name.toLowerCase().indexOf(S.q.toLowerCase());
  if (i < 0) return name;
  return name.slice(0, i) + MK_A + name.slice(i, i + S.q.length) +
         MK_B + name.slice(i + S.q.length);
}

function select(i) {
  if (i < 0 || i >= S.hits.length) return;
  S.sel = i;
  $$('.hit').forEach((el, k) => el.classList.toggle('sel', k === i));
  const el = $$('.hit')[i];
  if (el) el.scrollIntoView({ block: 'nearest' });
  showDetail(S.hits[i].id);
}

async function showDetail(id) {
  const d = $('#detail');
  d.innerHTML = '<div class="empty"><span class="spin"></span>读取中…</div>';
  let f;
  try { f = await api('file/' + id); }
  catch (e) { d.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }

  const facts = [
    ['类别', KIND_CN[f.kind] || f.kind],
    ['大小', size(f.size)],
    ['修改', when(f.mtime)],
    f.project ? ['项目', esc(f.project.name)] : null,
    f.text_len ? ['正文', f.text_len.toLocaleString() + ' 字'] : null,
    statusNote(f.text_status),
  ].filter(Boolean);

  d.innerHTML = `
    <div class="d-name">${esc(f.name)}</div>
    <p class="d-path">${esc(f.path)}</p>
    <div class="d-acts">
      <button data-act="open">打开</button>
      <button data-act="reveal">在文件夹中显示</button>
    </div>
    <dl class="d-facts">${facts.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>
    ${f.body ? `<div class="d-body">${hlBody(f.body)}</div>`
             : '<div class="d-body" style="color:var(--muted)">（没有可显示的正文）</div>'}`;

  $$('[data-act]', d).forEach(b => b.onclick = () =>
    open(f.path, b.dataset.act === 'reveal'));
}

function statusNote(st) {
  if (!st) return null;
  const map = {
    cloud: '云端文件，未下载到本地（只索引了文件名）',
    scanned: '扫描件，无文字层', 'no-tounicode': '字体无映射表，取不出文字',
    garbled: '正文乱码', empty: '内容为空', binary: '二进制文件',
    legacy: '老版 Office，正文可能不完整', 'skip:generated': '生成物，未索引正文',
    'skip:vendor': '第三方代码，未索引正文', 'skip:data': '数据文件，未索引正文',
    'skip:minified': '压缩过的代码，未索引正文', 'skip:toobig': '文件过大，未索引正文',
  };
  return map[st] ? ['备注', map[st]] : (st.startsWith('error') ? ['备注', '读取失败'] : null);
}

function hlBody(body) {
  const t = esc(body);
  if (!S.q || S.q.length < 1) return t;
  try {
    const re = new RegExp(S.q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
    return t.replace(re, m => '<mark>' + m + '</mark>');
  } catch { return t; }
}

/* ─────────────────────────────────────────────── 项目 */
let projCache = null;
async function loadProjects() {
  const grid = $('#projectGrid');
  if (!projCache) {
    grid.innerHTML = '<div class="empty"><span class="spin"></span>整理中…</div>';
    projCache = (await api('projects')).projects;
  }
  renderProjects();
}

function renderProjects() {
  const f = $('#pq').value.trim().toLowerCase();
  const rows = projCache.filter(p =>
    !f || p.name.toLowerCase().includes(f) || (p.kinds || '').toLowerCase().includes(f));
  const grid = $('#projectGrid');
  if (!rows.length) { grid.innerHTML = '<div class="empty">没有匹配的项目。</div>'; return; }
  grid.innerHTML = rows.map(p => `
    <div class="pcard${p.unpacked || p.third_party ? ' dim' : ''}" data-path="${esc(p.path)}">
      <h3>${esc(p.name)}</h3>
      <div class="ppath">${esc(p.path)}</div>
      <div class="prow">
        <span>${p.file_count} 个文件 · ${size(p.size)}</span>
        <span>${when(p.mtime)}</span>
      </div>
      <div class="langs">${(p.kinds || '').split(',').filter(Boolean)
        .map(k => `<span class="lang">${esc(k)}</span>`).join('')}
        ${p.is_git ? `<span class="lang" style="color:var(--seal)">git:${esc(p.git_branch || '')}</span>` : ''}
        ${p.unpacked ? '<span class="lang cold">解压/安装</span>' : ''}
      </div>
    </div>`).join('');
  $$('.pcard', grid).forEach(c => c.onclick = () => open(c.dataset.path));
}

/* ─────────────────────────────────────────────── 整理 */
async function loadTidy() {
  const body = $('#tidyBody');
  if (!S.tidyData.clusters) {
    body.innerHTML = '<div class="empty"><span class="spin"></span>比对中…</div>';
    const [c, d, t] = await Promise.all([api('clusters'), api('duplicates'), api('timeline')]);
    S.tidyData = { clusters: c.clusters, dups: d.groups, stale: t.stale };
  }
  const { clusters, dups } = S.tidyData;
  const waste = clusters.reduce((a, c) => a + c.waste, 0) +
                dups.reduce((a, g) => a + g.bytes - (g.bytes / g.count), 0);
  $('#tidySummary').innerHTML = `
    <div><b>${clusters.length}</b><span>组版本堆积</span></div>
    <div><b>${dups.length}${dups.length >= 120 ? '+' : ''}</b><span>组内容重复</span></div>
    <div><b>${size(waste)}</b><span>只留一份可省下</span></div>`;
  renderTidy();
}

function renderTidy() {
  const body = $('#tidyBody');
  $$('.tidy-tabs button').forEach(b => b.classList.toggle('on', b.dataset.t === S.tidy));

  if (S.tidy === 'clusters') {
    const cs = S.tidyData.clusters;
    body.innerHTML = cs.length ? cs.map((c, i) => `
      <div class="grp">
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
    body.innerHTML = gs.length ? gs.map(g => `
      <div class="grp">
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
  if (!years.length) { $('#yearBody').innerHTML = '<div class="empty">还没有数据。</div>'; return; }
  if (!S.year) S.year = years[0].year;
  $('#yearPick').innerHTML = years.map(y =>
    `<button data-y="${y.year}" class="${y.year === S.year ? 'on' : ''}">${y.year}</button>`).join('');
  $$('#yearPick button').forEach(b => b.onclick = () => { S.year = +b.dataset.y; loadYear(); });

  const body = $('#yearBody');
  body.innerHTML = '<div class="empty"><span class="spin"></span>回顾中…</div>';
  const d = await api('year/' + S.year);

  const months = Array.from({ length: 12 }, (_, i) => ({ m: i + 1, c: 0 }));
  (d.by_month || []).forEach(() => {});
  const acts = d.artifacts || [];
  acts.forEach(a => { months[new Date(a.mtime * 1000).getMonth()].c++; });
  const max = Math.max(1, ...months.map(m => m.c));

  body.innerHTML = `
    <div class="ystats">
      <div class="ystat"><b>${d.files.toLocaleString()}</b><span>个文件动过</span></div>
      <div class="ystat"><b>${d.artifact_total}</b><span>件成品</span></div>
      <div class="ystat"><b>${(d.words / 10000).toFixed(1)}万</b><span>字（成品正文）</span></div>
      <div class="ystat"><b>${d.projects.length}</b><span>个项目在动</span></div>
      <div class="ystat"><b>${d.busiest_month ? d.busiest_month.slice(5) + '月' : '—'}</b><span>最忙的月份</span></div>
    </div>

    <h2 class="sec">成品分布</h2>
    <div class="chart">${months.map(m =>
      `<div class="bar" style="height:${Math.max(2, m.c / max * 100)}%"><b>${m.m}月 ${m.c}</b></div>`).join('')}</div>
    <div class="chart-x">${months.map(m => `<span>${m.m}</span>`).join('')}</div>

    <h2 class="sec">这一年做出来的东西
      <span style="color:var(--muted);font-weight:400">（${d.artifact_total}，不含下载与聊天接收）</span>
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

/* ─────────────────────────────────────────────── 扫描 */
let scanPoll = null;
async function startScan() {
  try { await api('scan', { full: false }); }
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

  if (p.phase === 'done' || p.phase === 'error') {
    clearInterval(scanPoll);
    $('#btnScan').disabled = false;
    setTimeout(() => bar.classList.add('hidden'), 1400);
    toast(p.message || '扫描完成');
    projCache = null; S.tidyData = {};
    await loadStats();
    if (S.view === 'search') runSearch();
  }
}

/* ─────────────────────────────────────────────── 启动 */
async function loadStats() {
  S.stats = await api('stats');
  const s = S.stats;
  $('#railStats').innerHTML =
    `<b>${s.files.toLocaleString()}</b> 个文件<br>` +
    `<b>${s.indexed_text.toLocaleString()}</b> 份有正文<br>` +
    `<b>${s.projects}</b> 个项目<br>` +
    `索引 <b>${size(s.db_bytes)}</b>`;

  const kinds = Object.entries(s.by_kind).filter(([, n]) => n > 0).slice(0, 9);
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
    el.outerHTML = `<svg viewBox="0 0 17 17" fill="none" stroke="currentColor"
      stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
      class="${el.className}" style="width:${el.classList.contains('sb-icon') ? 17 : 16}px;
      height:${el.classList.contains('sb-icon') ? 17 : 16}px;flex:0 0 auto">
      ${ICONS[el.dataset.i] || ''}</svg>`;
  });
}

function bindKeys() {
  document.addEventListener('keydown', e => {
    if (e.key === '/' && document.activeElement !== $('#q') &&
        document.activeElement.tagName !== 'INPUT') {
      e.preventDefault(); showView('search'); $('#q').select();
      return;
    }
    if (S.view !== 'search') return;
    if (e.key === 'ArrowDown') { e.preventDefault(); select(S.sel + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); select(Math.max(0, S.sel - 1)); }
    else if (e.key === 'Enter' && S.sel >= 0) {
      e.preventDefault(); open(S.hits[S.sel].path, e.shiftKey);
    } else if (e.key === 'Escape') {
      if ($('#q').value) { $('#q').value = ''; runSearch(); } else $('#q').blur();
    }
  });
}

const HINTS = ['慧食安', '支教', '红绿灯', '商业企划书', '课表'];

function renderHints() {
  const old = $('#hintbar');
  if (old) old.remove();
  if ($('#q').value || !S.stats.files) return;
  const bar = document.createElement('div');
  bar.id = 'hintbar';
  bar.className = 'hintbar';
  bar.innerHTML = '<span>试试：</span>' +
    HINTS.map(h => `<button data-h="${esc(h)}">${esc(h)}</button>`).join('');
  // 一定要插在 .split 之前 —— .split 是 flex 行，塞进去会把结果列表挤到一边
  const split = $('#view-search .split');
  split.parentElement.insertBefore(bar, split);
  $$('[data-h]', bar).forEach(b => b.onclick = () => {
    $('#q').value = b.dataset.h;
    runSearch();
    $('#q').focus();
  });
}

async function boot() {
  drawIcons();
  bindKeys();
  $('#q').addEventListener('input', onType);
  $('#pq').addEventListener('input', () => projCache && renderProjects());
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
  $('#btnScan').onclick = startScan;

  await loadStats();
  runSearch();
  renderHints();
  if (!S.stats.files) startScan();
}

boot().catch(e => toast('启动失败：' + e.message));

/* ─────────────────────────────────────────────── 设置 */
let cfgDraft = null;

async function openSettings() {
  const c = await api('config');
  cfgDraft = { roots: [...c.roots], index_content: c.index_content };
  $('#optContent').checked = cfgDraft.index_content;
  renderRoots();
  $('#modal').classList.remove('hidden');
  $('#newRoot').focus();
}

function renderRoots() {
  $('#rootList').innerHTML = cfgDraft.roots.length
    ? cfgDraft.roots.map((r, i) => `
        <li><span class="rp">${esc(r)}</span>
            <button class="rm" data-i="${i}" title="移除">移除</button></li>`).join('')
    : '<li class="bad">一个目录都没有，拾遗会无事可做。</li>';
  $$('#rootList .rm').forEach(b => b.onclick = () => {
    cfgDraft.roots.splice(+b.dataset.i, 1);
    renderRoots();
  });
}

function addRoot() {
  const v = $('#newRoot').value.trim().replace(/^["']|["']$/g, '');
  if (!v) return;
  if (cfgDraft.roots.includes(v)) return toast('已经在列表里了');
  cfgDraft.roots.push(v);
  $('#newRoot').value = '';
  renderRoots();
}

async function saveSettings() {
  cfgDraft.index_content = $('#optContent').checked;
  try {
    await api('config', cfgDraft);
  } catch (e) {
    return toast('保存失败：' + e.message);
  }
  $('#modal').classList.add('hidden');
  toast('已保存，开始重新扫描');
  startScan();
}

$('#btnSettings').onclick = openSettings;
$('#addRoot').onclick = addRoot;
$('#newRoot').addEventListener('keydown', e => { if (e.key === 'Enter') addRoot(); });
$('#cancelCfg').onclick = () => $('#modal').classList.add('hidden');
$('#saveCfg').onclick = saveSettings;
$('#modal').addEventListener('click', e => {
  if (e.target.id === 'modal') $('#modal').classList.add('hidden');
});
