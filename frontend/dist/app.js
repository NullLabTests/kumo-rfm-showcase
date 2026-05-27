const API = '';
let templates = [];
let currentRunMode = 'fast';
let lastResult = null;
let lastResultB = null;
let lastTiming = null;
let graphData = null;
let previewData = null;
let queryHistory = JSON.parse(localStorage.getItem('kumo_history') || '[]');
let comparisonMode = false;
let isLineChart = false;
let currentChartData = null;
let pageSize = 100;
let currentPage = 1;
let sortKey = null;
let sortAsc = true;
let currentExplainResult = null;


function init() {
  loadHistory();
  pollStatus();

  document.querySelectorAll('.sidebar-item').forEach(el => {
    el.addEventListener('click', () => {
      document.querySelectorAll('.sidebar-item').forEach(x => x.classList.remove('active'));
      document.querySelectorAll('.page').forEach(x => x.classList.remove('active'));
      el.classList.add('active');
      const page = document.getElementById('page-' + el.dataset.page);
      if (page) page.classList.add('active');
    });
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { toggleHelp(false); return; }
    if (e.key === '?') { e.preventDefault(); toggleHelp(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      const pql = document.getElementById('pql-input');
      if (document.activeElement === pql || document.activeElement === document.getElementById('dash-pql')) {
        e.preventDefault();
        if (document.getElementById('page-query').classList.contains('active')) runQuery();
        else runDashQuery();
      }
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      if (document.activeElement && document.activeElement.tagName === 'TEXTAREA') {
        e.preventDefault();
        saveQuery();
      }
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'd') {
      if (document.activeElement && document.activeElement.tagName === 'TEXTAREA') {
        e.preventDefault();
        document.getElementById('pql-input').value = '';
        if (document.getElementById('pql-input-b')) document.getElementById('pql-input-b').value = '';
        toast('Editor cleared', 'info');
      }
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
      e.preventDefault();
      const cb = document.getElementById('compare-check');
      cb.checked = !cb.checked;
      toggleComparison();
      toast(cb.checked ? 'Comparison mode ON' : 'Comparison mode OFF', 'info');
    }
    if (e.key >= '1' && e.key <= '7' && !e.ctrlKey && !e.metaKey) {
      const idx = parseInt(e.key) - 1;
      if (idx < templates.length && templates.length > 0 && document.getElementById('page-query')?.classList.contains('active')) {
        e.preventDefault();
        loadTemplate(idx);
      }
    }
    if (e.key === 'r' && !e.ctrlKey && !e.metaKey && !e.altKey) {
      if (document.activeElement && document.activeElement.tagName === 'BODY') {
        const qp = document.getElementById('page-query');
        if (qp && qp.classList.contains('active') && lastResult) {
          e.preventDefault();
          clearResults();
        }
      }
    }
  });

  document.getElementById('result-page-size')?.addEventListener('change', e => {
    pageSize = parseInt(e.target.value) || 100;
    currentPage = 1;
    renderPagedResults();
    renderPagination();
  });
}


async function pollStatus() {
  for (let i = 0; i < 90; i++) {
    try {
      const r = await fetch(API + '/api/status').then(x => x.json());
      updateApiBadge(r.api_key_configured);
      if (r.message) {
        document.getElementById('dash-loading-text').textContent = r.message;
      }
      if (r.loaded) {
        onDatasetReady(r.dataset);
        return;
      }
      if (r.error) {
        showLoadingError(r.error);
        return;
      }
    } catch (e) { /* server not up yet */ }
    await new Promise(r => setTimeout(r, 2000));
  }
  showLoadingError('Server not responding after 3 minutes. Is the API key set in .env?');
}

function updateApiBadge(configured) {
  const dot = document.getElementById('dot-api');
  const label = document.getElementById('label-api');
  dot.className = configured ? 'dot ok' : 'dot';
  label.textContent = configured ? 'Key OK' : 'No Key';
}

function onDatasetReady(dataset) {
  document.getElementById('badge-ds').style.display = 'inline-flex';
  document.getElementById('label-ds').textContent = dataset;
  document.getElementById('ds-name-display').textContent = dataset;
  document.getElementById('ds-select').value = dataset;
  document.getElementById('dash-loading').style.display = 'none';
  document.getElementById('dash-ready').style.display = 'block';
  document.getElementById('dash-error').style.display = 'none';
  loadAll();
}

function showLoadingError(msg) {
  document.getElementById('dash-loading').style.display = 'none';
  const err = document.getElementById('dash-error');
  err.style.display = 'block';
  document.getElementById('dash-error-text').textContent = msg;
}


async function loadAll() {
  try {
    const [tplRes, graphRes] = await Promise.all([
      fetch(API + '/api/pql-templates').then(r => r.json()),
      fetch(API + '/api/graph').then(r => r.json()),
    ]);
    templates = tplRes.templates;
    graphData = graphRes;
    await loadPreview();
    renderDashboard(graphRes);
    renderTemplates();
    renderDataExplorer(graphRes);
  } catch (e) {
    toast('Failed to load data: ' + e.message, 'error');
  }
}

async function loadPreview() {
  try {
    const r = await fetch(API + '/api/preview').then(x => x.json());
    previewData = r.tables;
  } catch (e) { /* preview is optional */ }
}


function renderDashboard(g) {
  const stats = document.getElementById('stat-grid');
  let tableCount = 0, totalRows = 0;
  let html = '';
  for (const [name, info] of Object.entries(g.tables || {})) {
    tableCount++;
    totalRows += info.rows;
    html += `<div class="stat-card"><div class="val">${info.rows.toLocaleString()}</div><div class="lbl">${name}</div></div>`;
  }
  html += `<div class="stat-card"><div class="val">${tableCount}</div><div class="lbl">tables</div></div>`;
  stats.innerHTML = html;
  document.getElementById('stat-tables').textContent = tableCount;
  document.getElementById('stat-rows').textContent = totalRows.toLocaleString();

  document.getElementById('quick-templates').innerHTML = templates.slice(0, 6).map((t, i) =>
    `<button class="secondary sm" onclick="loadTemplate(${i})" title="${t.description}">${t.name}</button>`
  ).join('');

  renderRecentDash();
}

function renderRecentDash() {
  const el = document.getElementById('dash-recent');
  const list = document.getElementById('dash-recent-list');
  if (!queryHistory.length) { el.style.display = 'none'; return; }
  el.style.display = 'block';
  const recent = queryHistory.slice(-3).reverse();
  list.innerHTML = recent.map((h, i) =>
    `<div class="history-item" onclick="reRun(${queryHistory.length - 1 - i})">
      <code>${h.query}</code>
      <span class="meta">${h.time}</span>
    </div>`
  ).join('');
}


function renderTemplates() {
  document.getElementById('template-grid').innerHTML = templates.map((t, i) =>
    `<div class="tcard" onclick="loadTemplate(${i})">
      <h4>${t.name}</h4>
      <p>${t.description}</p>
      <code>${t.query.length > 75 ? t.query.slice(0, 70) + '...' : t.query}</code>
    </div>`
  ).join('');
}

function loadTemplate(idx) {
  const t = templates[idx];
  document.getElementById('pql-input').value = t.query;
  document.getElementById('dash-pql').value = t.query;
  navigateTo('query');
}


function navigateTo(page) {
  document.querySelectorAll('.sidebar-item').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('.page').forEach(x => x.classList.remove('active'));
  document.querySelector(`[data-page="${page}"]`).classList.add('active');
  document.getElementById(`page-${page}`).classList.add('active');
}


function renderDataExplorer(g) {
  let html = '';
  for (const [name, info] of Object.entries(g.tables || {})) {
    const cols = Object.entries(info.columns || {});
    html += `<div class="card">
      <div class="card-header">
        <div class="card-title"><span class="icon">&#128451;</span> ${name}</div>
        <div class="btn-group">
          <span style="font-size:11px;color:var(--text2);padding:2px 8px;background:var(--bg);border-radius:4px;">${info.rows.toLocaleString()} rows</span>
          ${info.primary_key && info.primary_key !== 'None' ? `<span style="font-size:10px;padding:2px 8px;background:rgba(245,158,11,.15);border-radius:4px;color:var(--warning);">PK: ${info.primary_key}</span>` : ''}
          ${info.time_column && info.time_column !== 'None' ? `<span style="font-size:10px;padding:2px 8px;background:rgba(59,130,246,.15);border-radius:4px;color:var(--info);">T: ${info.time_column}</span>` : ''}
        </div>
      </div>
      <table class="schema-table"><thead><tr><th>Column</th><th>Type</th><th>Semantic</th></tr></thead><tbody>`;
    for (const [c, ci] of cols) {
      const stype = ci.stype || 'unknown';
      let sc = '';
      if (stype.includes('primary_key')) sc = 'stype-badge pk';
      else if (stype.includes('temporal')) sc = 'stype-badge time';
      else if (stype.includes('numerical')) sc = 'stype-badge num';
      else if (stype.includes('categorical')) sc = 'stype-badge cat';
      html += `<tr><td><code style="color:var(--accent);">${c}</code></td><td><span class="stype-badge">${ci.dtype}</span></td><td><span class="${sc}">${stype}</span></td></tr>`;
    }
    html += '</tbody></table>';
    html += buildPreviewHTML(name);
    html += '</div>';
  }
  document.getElementById('data-body').innerHTML = html || '<p style="color:var(--text2);">No tables loaded.</p>';
}

function buildPreviewHTML(tableName) {
  const prev = previewData && previewData[tableName];
  if (!prev || !prev.rows || !prev.rows.length) return '';
  let html = `<details style="margin-top:10px;"><summary style="cursor:pointer;font-size:12px;color:var(--text2);padding:4px 0;">Preview (first ${prev.rows.length} of ${prev.total_rows.toLocaleString()} rows)</summary>
    <div class="table-wrap" style="margin-top:6px;"><table class="preview-table"><thead><tr>`;
  for (const col of prev.columns) html += `<th>${col}</th>`;
  html += '</tr></thead><tbody>';
  for (const row of prev.rows) {
    html += '<tr>';
    for (const col of prev.columns) {
      const v = row[col];
      const s = v === null || v === undefined
        ? '<span style="color:var(--text3)">NULL</span>'
        : formatCell(v);
      html += `<td>${s}</td>`;
    }
    html += '</tr>';
  }
  html += '</tbody></table></div></details>';
  return html;
}

function formatCell(v) {
  if (typeof v === 'number') return Number.isInteger(v) ? v : v.toFixed(3);
  const s = String(v);
  return s.length > 30 ? s.slice(0, 27) + '...' : s;
}


function setRunMode(mode, btn) {
  currentRunMode = mode;
  document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}

function getEntityIds() {
  const val = document.getElementById('entity-ids').value.trim();
  if (!val) return null;
  return val.split(',').map(s => s.trim()).filter(s => s).map(s => isNaN(s) ? s : Number(s));
}

function setEntityIds(val) {
  document.getElementById('entity-ids').value = val || '';
}

function clearResults() {
  document.getElementById('query-result').style.display = 'none';
  document.getElementById('query-result-body').innerHTML = '';
  document.getElementById('query-result-b').style.display = 'none';
  document.getElementById('query-result-body-b').innerHTML = '';
  document.getElementById('export-btns').style.display = 'none';
  lastResult = null;
  lastResultB = null;
  lastTiming = null;
  currentChartData = null;
}

function runQuery() {
  const q = document.getElementById('pql-input').value.trim();
  if (!q) { toast('Enter a query', 'warning'); return; }
  clearResults();
  doPredict(q, false);
}

function explainQuery() {
  const q = document.getElementById('pql-input').value.trim();
  if (!q) { toast('Enter a query', 'warning'); return; }
  clearResults();
  doPredict(q, true);
}

function runDashQuery() {
  const q = document.getElementById('dash-pql').value.trim();
  if (!q) { toast('Enter a query', 'warning'); return; }
  clearResults();
  doPredict(q, false);
}

function explainDashQuery() {
  const q = document.getElementById('dash-pql').value.trim();
  if (!q) { toast('Enter a query', 'warning'); return; }
  clearResults();
  doPredict(q, true);
}

async function doPredict(query, explain) {
  isLineChart = false;
  const btn = explain ? document.getElementById('explain-btn') : document.getElementById('run-btn');
  const container = document.getElementById('query-result');
  const bodyEl = document.getElementById('query-result-body');

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> ' + (explain ? 'Explaining' : 'Running');
  container.style.display = 'block';
  bodyEl.innerHTML = '<div class="loading-state" style="padding:20px;"><div class="spinner-lg"></div></div>';
  document.getElementById('export-btns').style.display = 'none';

  const t0 = performance.now();

  try {
    const payload = { query, graph_id: 'default', run_mode: currentRunMode, explain };
    const eids = getEntityIds();
    if (eids) payload.entity_ids = eids;

    const resp = await fetch(API + '/api/predict', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || JSON.stringify(data));

    const elapsed = ((performance.now() - t0) / 1000).toFixed(2);
    lastTiming = elapsed;

    const r = data.result;
    let html = '';

    if (explain && r.summary) {
      currentExplainResult = r;
      html += `<div class="explain-text">${r.summary}</div>`;
      if (r.cohorts && r.cohorts.length) {
        html += '<div style="margin-top:10px;font-size:12px;color:var(--text2);">Cohort explanations: ' + r.cohorts.length + ' groups</div>';
      }
    }

    if (r.prediction && r.prediction.length) {
      sortKey = null;
      sortAsc = true;
      currentPage = 1;
      html += renderTiming(elapsed);
      html += `<div style="margin-top:8px;">${buildResultTable(r.prediction)}${renderPagination(r.prediction)}</div>`;
      drawChart(r.prediction);
    }

    if (!html) html = '<div class="result-area"><pre>' + JSON.stringify(r, null, 2) + '</pre></div>';

    bodyEl.innerHTML = html;
    document.getElementById('export-btns').style.display = '';
    lastResult = r;
    addHistory(query, explain, eids ? eids.join(',') : '');
  } catch (e) {
    bodyEl.innerHTML = renderError(e.message);
    lastResult = null;
    currentExplainResult = null;
    document.getElementById('export-btns').style.display = 'none';
  } finally {
    btn.disabled = false;
    btn.innerHTML = explain ? '&#128269; Explain' : '&#9654; Run Query';
  }
}

function renderTiming(seconds) {
  return `<div class="timing-badge" style="display:flex;gap:6px;align-items:center;margin-bottom:6px;">
    <span style="font-size:11px;color:var(--text2);background:var(--surface2);padding:2px 8px;border-radius:4px;border:1px solid var(--border);">
      &#9201; ${seconds}s
    </span>
    <span style="font-size:11px;color:var(--text2);background:var(--surface2);padding:2px 8px;border-radius:4px;border:1px solid var(--border);">
      &#128196; ${lastResult && lastResult.prediction ? lastResult.prediction.length + ' rows' : ''}
    </span>
  </div>`;
}

function renderError(msg) {
  const recoverable = msg.includes('live display') || msg.includes('429') || msg.includes('timeout');
  return `<div class="alert error" style="margin-top:10px;">
    <span class="alert-icon">&#9888;</span>
    <div style="flex:1;">
      <div style="font-weight:600;margin-bottom:4px;">Prediction failed</div>
      <div style="font-size:12px;opacity:.8;">${msg}</div>
      ${recoverable ? '<button class="secondary sm" onclick="runQuery()" style="margin-top:8px;">&#x21bb; Retry</button>' : ''}
    </div>
  </div>`;
}

function buildResultTable(prediction) {
  if (!prediction || !prediction.length) return '';
  const keys = Object.keys(prediction[0]);

  const sorted = getSortedData(prediction, keys);
  const paged = getPagedData(sorted);

  let html = `<div class="table-wrap sortable-table"><table><thead><tr>`;
  keys.forEach(k => {
    const dir = sortKey === k ? (sortAsc ? '&#9650;' : '&#9660;') : '';
    html += `<th onclick="sortByKey('${k}')" style="cursor:pointer;user-select:none;">${k} ${dir}</th>`;
  });
  html += '</tr></thead><tbody>';
  paged.forEach(row => {
    html += '<tr>';
    keys.forEach(k => {
      const v = row[k];
      const s = v === null || v === undefined
        ? '<span style="color:var(--text3)">NULL</span>'
        : (typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(4)) : String(v));
      html += `<td><span onclick="copyCellValue('${String(v).replace(/'/g, "\\'")}')" title="Click to copy">${s}</span></td>`;
    });
    html += '</tr>';
  });
  html += '</tbody></table></div>';
  return html;
}

function getSortedData(data, keys) {
  if (!sortKey) return data;
  return [...data].sort((a, b) => {
    const va = a[sortKey], vb = b[sortKey];
    if (va == null) return 1;
    if (vb == null) return -1;
    if (typeof va === 'number' && typeof vb === 'number') {
      return sortAsc ? va - vb : vb - va;
    }
    return sortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
  });
}

function getPagedData(data) {
  const start = (currentPage - 1) * pageSize;
  return data.slice(start, start + pageSize);
}

function sortByKey(key) {
  if (sortKey === key) {
    sortAsc = !sortAsc;
  } else {
    sortKey = key;
    sortAsc = true;
  }
  currentPage = 1;
  if (lastResult && lastResult.prediction) {
    const bodyEl = document.getElementById('query-result-body');
    const existing = bodyEl.querySelector('.sortable-table');
    const pagination = bodyEl.querySelector('.pagination-controls');
    const timing = bodyEl.querySelector('.timing-badge');
    if (existing) {
      let html = timing ? timing.outerHTML : '';
      html += renderTiming(lastTiming);
      html += `<div style="margin-top:8px;">${buildResultTable(lastResult.prediction)}${renderPagination(lastResult.prediction)}</div>`;
      html += bodyEl.innerHTML.includes('explain-text') ? bodyEl.querySelector('.explain-text').outerHTML : '';
      bodyEl.innerHTML = html;
    }
  }
}

function renderPagination(data) {
  if (!data || data.length <= pageSize) return '';
  const total = data.length;
  const totalPages = Math.ceil(total / pageSize);
  return `<div class="pagination-controls" style="display:flex;align-items:center;gap:8px;padding:8px 0;font-size:12px;color:var(--text2);flex-wrap:wrap;">
    <span>${total.toLocaleString()} rows</span>
    <span style="color:var(--text3);">|</span>
    <button class="ghost sm" onclick="changePage(${currentPage - 1})" ${currentPage <= 1 ? 'disabled' : ''}>&#9664; Prev</button>
    <span>Page ${currentPage} of ${totalPages}</span>
    <button class="ghost sm" onclick="changePage(${currentPage + 1})" ${currentPage >= totalPages ? 'disabled' : ''}>Next &#9654;</button>
    <span style="color:var(--text3);">|</span>
    <label style="display:flex;align-items:center;gap:4px;">
      <span>Rows/page:</span>
      <select class="page-size-select" onchange="changePageSize(this.value)" style="width:auto;padding:2px 6px;font-size:11px;background:var(--bg);border:1px solid var(--border);border-radius:3px;color:var(--text);">
        <option value="25" ${pageSize === 25 ? 'selected' : ''}>25</option>
        <option value="50" ${pageSize === 50 ? 'selected' : ''}>50</option>
        <option value="100" ${pageSize === 100 ? 'selected' : ''}>100</option>
        <option value="250" ${pageSize === 250 ? 'selected' : ''}>250</option>
        <option value="0" ${pageSize === 0 ? 'selected' : ''}>All</option>
      </select>
    </label>
  </div>`;
}

function changePage(p) {
  currentPage = p;
  if (lastResult && lastResult.prediction) {
    const bodyEl = document.getElementById('query-result-body');
    const timing = bodyEl.querySelector('.timing-badge');
    const explainText = bodyEl.querySelector('.explain-text');
    let html = timing ? timing.outerHTML : '';
    html += renderTiming(lastTiming);
    html += `<div style="margin-top:8px;">${buildResultTable(lastResult.prediction)}${renderPagination(lastResult.prediction)}</div>`;
    if (explainText) html += explainText.outerHTML;
    bodyEl.innerHTML = html;
  }
}

function changePageSize(size) {
  pageSize = parseInt(size) || 0;
  currentPage = 1;
  if (lastResult && lastResult.prediction) {
    const bodyEl = document.getElementById('query-result-body');
    const timing = bodyEl.querySelector('.timing-badge');
    const explainText = bodyEl.querySelector('.explain-text');
    let html = timing ? timing.outerHTML : '';
    html += renderTiming(lastTiming);
    html += `<div style="margin-top:8px;">${buildResultTable(lastResult.prediction)}${renderPagination(lastResult.prediction)}</div>`;
    if (explainText) html += explainText.outerHTML;
    bodyEl.innerHTML = html;
  }
}

function copyCellValue(val) {
  navigator.clipboard.writeText(val).then(() => {
    toast('Copied: ' + (val.length > 40 ? val.slice(0, 37) + '...' : val), 'success');
  }).catch(() => { /* ignore */ });
}


function toggleHelp(forceState) {
  const modal = document.getElementById('help-modal');
  if (forceState === false) { modal.classList.remove('open'); return; }
  modal.classList.toggle('open');
}


function toggleComparison() {
  const cb = document.getElementById('compare-check');
  const editor = document.getElementById('compare-editor');
  comparisonMode = cb.checked;
  editor.style.display = comparisonMode ? 'block' : 'none';
  if (!comparisonMode) {
    document.getElementById('query-result-b').style.display = 'none';
  }
}

async function runCompareB() {
  const q = document.getElementById('pql-input-b').value.trim();
  if (!q) { toast('Enter query B', 'warning'); return; }
  await doPredictCompareB(q, false);
}

async function explainCompareB() {
  const q = document.getElementById('pql-input-b').value.trim();
  if (!q) { toast('Enter query B', 'warning'); return; }
  await doPredictCompareB(q, true);
}

async function doPredictCompareB(query, explain) {
  const container = document.getElementById('query-result-b');
  const bodyEl = document.getElementById('query-result-body-b');
  container.style.display = 'block';
  bodyEl.innerHTML = '<div class="loading-state" style="padding:20px;"><div class="spinner-lg"></div></div>';

  try {
    const payload = { query, graph_id: 'default', run_mode: currentRunMode, explain };
    const eids = getEntityIds();
    if (eids) payload.entity_ids = eids;

    const resp = await fetch(API + '/api/predict', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || JSON.stringify(data));

    const r = data.result;
    let html = '';

    if (explain && r.summary) {
      html += '<div class="explain-text">' + r.summary + '</div>';
    }

    if (r.prediction && r.prediction.length) {
      html += buildResultTable(r.prediction);
      drawChartCompareB(r.prediction);
    }

    if (!html) html = '<div class="result-area"><pre>' + JSON.stringify(r, null, 2) + '</pre></div>';

    bodyEl.innerHTML = html;
    lastResultB = r;
    addHistory(query, explain, eids ? eids.join(',') : '');
    toast('Query B completed', 'success');
  } catch (e) {
    bodyEl.innerHTML = '<div class="alert error"><span class="alert-icon">&#9888;</span>' + e.message + '</div>';
    lastResultB = null;
  }
}

function drawChartCompareB(prediction) {
  const oldChart = document.getElementById('chart-canvas-container-b');
  if (oldChart) oldChart.remove();
  if (!prediction || prediction.length < 2) return;

  const keys = Object.keys(prediction[0]);
  const numKeys = keys.filter(k =>
    typeof prediction[0][k] === 'number' && k !== 'ENTITY' && !k.startsWith('ANCHOR')
  );
  if (!numKeys.length) return;

  const labelKey = keys.find(k => k === 'ENTITY' || k === 'user_id' || k === 'item_id' || k === 'order_id') || keys[0];
  const valKey = numKeys[0];

  const container = document.getElementById('query-result-body-b');
  const wrap = document.createElement('div');
  wrap.id = 'chart-canvas-container-b';
  wrap.className = 'chart-wrap';
  wrap.innerHTML = '<canvas height="180"></canvas>';
  container.appendChild(wrap);

  const canvas = wrap.querySelector('canvas');
  const ctx = canvas.getContext('2d');
  const rect = wrap.getBoundingClientRect();
  canvas.width = rect.width || 600;
  canvas.height = 180;

  const w = canvas.width, h = canvas.height;
  const pad = { top: 18, right: 18, bottom: 28, left: 50 };
  const cw = w - pad.left - pad.right;
  const ch = h - pad.top - pad.bottom;

  const labels = prediction.map(r => String(r[labelKey]));
  const values = prediction.map(r => r[valKey]);
  const maxVal = Math.max(...values, 0.001);

  ctx.fillStyle = '#090b14';
  ctx.fillRect(0, 0, w, h);

  ctx.strokeStyle = '#2a2e48';
  ctx.lineWidth = 0.5;
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + ch * (1 - i / 4);
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(w - pad.right, y); ctx.stroke();
    ctx.fillStyle = '#5a6480';
    ctx.font = '9px sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText((maxVal * i / 4).toFixed(1), pad.left - 5, y + 3);
  }

  const barW = Math.min(32, cw / labels.length * 0.6);
  const gap = cw / labels.length;
  const color = '#22d3ee';

  values.forEach((v, i) => {
    const x = pad.left + gap * i + (gap - barW) / 2;
    const barH = (v / maxVal) * ch;
    const y = pad.top + ch - barH;

    const grad = ctx.createLinearGradient(x, y, x, pad.top + ch);
    grad.addColorStop(0, color);
    grad.addColorStop(1, color + '44');
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.roundRect(x, y, barW, barH, [3, 3, 0, 0]);
    ctx.fill();

    ctx.fillStyle = '#8892b0';
    ctx.font = '9px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(labels[i], x + barW / 2, pad.top + ch + 15);

    ctx.fillStyle = '#e2e8f0';
    ctx.font = 'bold 9px sans-serif';
    ctx.fillText(typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(2)) : String(v), x + barW / 2, y - 3);
  });
}


function copyPQL(id) {
  const el = document.getElementById(id);
  if (!el || !el.value) { toast('Nothing to copy', 'warning'); return; }
  navigator.clipboard.writeText(el.value).then(() => {
    toast('Query copied', 'success');
  }).catch(() => {
    const ta = document.createElement('textarea');
    ta.value = el.value;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    toast('Query copied', 'success');
  });
}


function downloadCSV() {
  if (!lastResult || !lastResult.prediction || !lastResult.prediction.length) {
    toast('No results to download', 'warning');
    return;
  }
  const rows = lastResult.prediction;
  const keys = Object.keys(rows[0]);
  let csv = keys.join(',') + '\n';
  rows.forEach(row => {
    csv += keys.map(k => {
      const v = row[k];
      if (v === null || v === undefined) return '';
      const s = String(v);
      return s.includes(',') || s.includes('"') ? '"' + s.replace(/"/g, '""') + '"' : s;
    }).join(',') + '\n';
  });
  downloadFile(csv, 'prediction.csv', 'text/csv');
  toast('CSV file downloaded', 'success');
}

function downloadJSON() {
  if (!lastResult || !lastResult.prediction || !lastResult.prediction.length) {
    toast('No results to download', 'warning');
    return;
  }
  const json = JSON.stringify(lastResult.prediction, null, 2);
  downloadFile(json, 'prediction.json', 'application/json');
  toast('JSON file downloaded', 'success');
}

function downloadFile(content, filename, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}


function toggleChartType() {
  isLineChart = !isLineChart;
  document.querySelectorAll('.chart-type-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.type === (isLineChart ? 'line' : 'bar'));
  });
  if (currentChartData) drawChart(currentChartData);
}

function drawChart(prediction) {
  currentChartData = prediction;
  const oldChart = document.getElementById('chart-canvas-container');
  if (oldChart) oldChart.remove();

  if (!prediction || prediction.length < 2) return;

  const keys = Object.keys(prediction[0]);
  const numKeys = keys.filter(k =>
    typeof prediction[0][k] === 'number' && k !== 'ENTITY' && !k.startsWith('ANCHOR')
  );
  if (!numKeys.length) return;

  const labelKey = keys.find(k => k === 'ENTITY' || k === 'user_id' || k === 'item_id' || k === 'order_id') || keys[0];
  const valKey = numKeys[0];

  const container = document.getElementById('query-result-body');
  const wrap = document.createElement('div');
  wrap.id = 'chart-canvas-container';
  wrap.className = 'chart-wrap';
  wrap.innerHTML = `<canvas height="200"></canvas><div class="chart-toolbar"><button class="chart-type-btn active" data-type="bar" onclick="toggleChartType()">&#9632; Bar</button><button class="chart-type-btn" data-type="line" onclick="toggleChartType()">&#9585;&#9586; Line</button></div>`;
  container.appendChild(wrap);

  const canvas = wrap.querySelector('canvas');
  const ctx = canvas.getContext('2d');
  const rect = wrap.getBoundingClientRect();
  canvas.width = rect.width || 600;
  canvas.height = 200;

  const w = canvas.width, h = canvas.height;
  const pad = { top: 20, right: 20, bottom: 30, left: 55 };
  const cw = w - pad.left - pad.right;
  const ch = h - pad.top - pad.bottom;

  const labels = prediction.map(r => String(r[labelKey]));
  const values = prediction.map(r => r[valKey]);
  const maxVal = Math.max(...values, 0.001);

  ctx.fillStyle = '#090b14';
  ctx.fillRect(0, 0, w, h);

  ctx.strokeStyle = '#2a2e48';
  ctx.lineWidth = 0.5;
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + ch * (1 - i / 4);
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(w - pad.right, y); ctx.stroke();
    ctx.fillStyle = '#5a6480';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText((maxVal * i / 4).toFixed(1), pad.left - 6, y + 3);
  }

  const colors = ['#7c5cfc', '#22d3ee', '#10b981', '#f59e0b', '#ef4444', '#3b82f6', '#a78bfa'];

  if (isLineChart) {
    const gap = cw / Math.max(values.length - 1, 1);
    ctx.beginPath();
    values.forEach((v, i) => {
      const x = pad.left + gap * i;
      const y = pad.top + ch - (v / maxVal) * ch;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.strokeStyle = '#7c5cfc';
    ctx.lineWidth = 2.5;
    ctx.stroke();

    ctx.shadowColor = 'rgba(124,92,252,0.3)';
    ctx.shadowBlur = 8;
    ctx.beginPath();
    values.forEach((v, i) => {
      const x = pad.left + gap * i;
      const y = pad.top + ch - (v / maxVal) * ch;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.strokeStyle = '#7c5cfc';
    ctx.lineWidth = 2.5;
    ctx.stroke();
    ctx.shadowBlur = 0;

    values.forEach((v, i) => {
      const x = pad.left + gap * i;
      const y = pad.top + ch - (v / maxVal) * ch;
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fillStyle = '#7c5cfc';
      ctx.fill();
      ctx.strokeStyle = '#090b14';
      ctx.lineWidth = 2;
      ctx.stroke();

      ctx.fillStyle = '#e2e8f0';
      ctx.font = 'bold 10px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(2)) : String(v), x, y - 10);
    });

    labels.forEach((l, i) => {
      const x = pad.left + gap * i;
      ctx.fillStyle = '#8892b0';
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(l, x, pad.top + ch + 16);
    });
  } else {
    const barW = Math.min(40, cw / labels.length * 0.6);
    const gap = cw / labels.length;

    values.forEach((v, i) => {
      const x = pad.left + gap * i + (gap - barW) / 2;
      const barH = (v / maxVal) * ch;
      const y = pad.top + ch - barH;

      const grad = ctx.createLinearGradient(x, y, x, pad.top + ch);
      grad.addColorStop(0, colors[i % colors.length]);
      grad.addColorStop(1, colors[i % colors.length] + '44');
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.roundRect(x, y, barW, barH, [3, 3, 0, 0]);
      ctx.fill();

      ctx.fillStyle = '#8892b0';
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(labels[i], x + barW / 2, pad.top + ch + 16);

      ctx.fillStyle = '#e2e8f0';
      ctx.font = 'bold 10px sans-serif';
      ctx.fillText(typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(2)) : String(v), x + barW / 2, y - 4);
    });
  }

  ctx.fillStyle = '#5a6480';
  ctx.font = '10px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText(valKey.replace(/_/g, ' '), pad.left + cw / 2, h - 2);
}


function showComparisonLayout(resultA, resultB) {
  const bodyEl = document.getElementById('query-result-body');
  const bodyElB = document.getElementById('query-result-body-b');
  document.getElementById('query-result').style.display = 'block';
  document.getElementById('query-result-b').style.display = 'block';

  document.getElementById('export-btns').style.display = 'none';
  document.getElementById('query-result').querySelector('.card').classList.add('compare-pane');
}


function addHistory(query, explained, entityIds) {
  queryHistory.push({
    query, explained,
    entityIds: entityIds || '',
    time: new Date().toLocaleString(),
    ts: Date.now(),
  });
  if (queryHistory.length > 50) queryHistory = queryHistory.slice(-50);
  localStorage.setItem('kumo_history', JSON.stringify(queryHistory));
  loadHistory();
  renderRecentDash();
}

function loadHistory() {
  const list = document.getElementById('history-list');
  if (!queryHistory.length) {
    list.innerHTML = '<div class="empty-state"><div class="icon">&#128337;</div><p>No queries yet. Run one in <strong>Query Lab</strong>.</p></div>';
    return;
  }
  list.innerHTML = [...queryHistory].reverse().map((h, i) => {
    const idx = queryHistory.length - 1 - i;
    const eidTag = h.entityIds ? `<span class="meta" style="margin-left:4px;">[${h.entityIds}]</span>` : '';
    return `<div class="history-item" onclick="reRun(${idx})">
      <code>${h.query}</code>
      <span class="meta">${h.time}${h.explained ? ' &middot; explained' : ''}${eidTag}</span>
      <button class="ghost sm" onclick="event.stopPropagation();deleteHistory(${idx})" title="Delete">&#10005;</button>
    </div>`;
  }).join('');
}

function reRun(idx) {
  const h = queryHistory[idx];
  if (!h) return;
  document.getElementById('pql-input').value = h.query;
  setEntityIds(h.entityIds || '');
  navigateTo('query');
  if (h.explained) explainQuery(); else runQuery();
}

function saveQuery() {
  const q = document.getElementById('pql-input').value.trim();
  if (!q) { toast('Nothing to save', 'warning'); return; }
  addHistory(q, false, getEntityIds() ? getEntityIds().join(',') : '');
  toast('Query saved to history', 'success');
}

function deleteHistory(idx) {
  queryHistory.splice(idx, 1);
  localStorage.setItem('kumo_history', JSON.stringify(queryHistory));
  loadHistory();
  renderRecentDash();
}

function clearHistory() {
  if (!queryHistory.length) return;
  queryHistory = [];
  localStorage.setItem('kumo_history', JSON.stringify(queryHistory));
  loadHistory();
  renderRecentDash();
  toast('History cleared', 'info');
}


function exportCSV() {
  if (!lastResult || !lastResult.prediction || !lastResult.prediction.length) {
    toast('No results to export', 'warning');
    return;
  }
  const rows = lastResult.prediction;
  const keys = Object.keys(rows[0]);
  let csv = keys.join(',') + '\n';
  rows.forEach(row => {
    csv += keys.map(k => {
      const v = row[k];
      if (v === null || v === undefined) return '';
      const s = String(v);
      return s.includes(',') || s.includes('"') ? '"' + s.replace(/"/g, '""') + '"' : s;
    }).join(',') + '\n';
  });
  copyText(csv, 'CSV copied to clipboard');
}

function exportJSON() {
  if (!lastResult || !lastResult.prediction || !lastResult.prediction.length) {
    toast('No results to export', 'warning');
    return;
  }
  copyText(JSON.stringify(lastResult.prediction, null, 2), 'JSON copied to clipboard');
}

function copyText(text, msg) {
  navigator.clipboard.writeText(text).then(() => toast(msg, 'success')).catch(() => {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    toast(msg, 'success');
  });
}


async function switchDataset(id) {
  const select = document.getElementById('ds-select');
  const current = await fetch(API + '/api/status').then(r => r.json());
  if (current.loaded && current.dataset === id) {
    toast('Already on ' + id, 'info');
    return;
  }

  select.disabled = true;
  document.getElementById('dash-ready').style.display = 'none';
  document.getElementById('dash-loading').style.display = 'flex';
  document.getElementById('dash-loading-text').textContent = 'Switching to ' + id + '...';
  const bodyEl = document.getElementById('data-body');
  if (bodyEl) bodyEl.innerHTML = '<div class="loading-state"><div class="spinner-lg"></div> Loading ' + id + '...</div>';

  try {
    await fetch(API + '/api/load-dataset', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dataset: id, graph_id: 'default' }),
    });

    for (let i = 0; i < 60; i++) {
      await new Promise(r => setTimeout(r, 3000));
      const st = await fetch(API + '/api/status').then(r => r.json());
      if (st.loaded && st.dataset === id) {
        document.getElementById('badge-ds').style.display = 'inline-flex';
        document.getElementById('label-ds').textContent = id;
        document.getElementById('ds-name-display').textContent = id;
        document.getElementById('dash-loading').style.display = 'none';
        document.getElementById('dash-ready').style.display = 'block';
        document.getElementById('dash-error').style.display = 'none';
        await loadAll();
        toast('Switched to ' + id, 'success');
        return;
      }
      if (st.error) throw new Error(st.error);
    }
    throw new Error('Dataset load timed out');
  } catch (e) {
    document.getElementById('dash-loading').innerHTML = '<span class="alert-icon">&#9888;</span> Switch failed: ' + e.message;
    toast('Failed: ' + e.message, 'error');
  } finally {
    select.disabled = false;
  }
}


function toast(msg, type) {
  const c = document.getElementById('toast-container');
  const t = document.createElement('div');
  t.className = 'toast ' + (type || 'info');
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => {
    t.style.opacity = '0';
    t.style.transition = 'opacity .3s';
    setTimeout(() => t.remove(), 300);
  }, 2500);
}


init();
