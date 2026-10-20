const $ = id => document.getElementById(id);
const text = (tag, value, parent, cls) => {
  const node = document.createElement(tag);
  node.textContent = value;
  if (cls) node.className = cls;
  parent?.append(node);
  return node;
};
const labels = { candidate: '現地確認候補', watch: '空間的な裏付け不足', no_significant_trend: '顕著な長期傾向なし', insufficient: '観測不足', noisy: 'ばらつき大' };
const colors = { candidate: '#c65242', watch: '#c99939', no_significant_trend: '#257f91', insufficient: '#8d999d', noisy: '#8d999d' };
const number = (value, unit = '') => value === undefined || value === null ? '—' : `${Number(value).toFixed(1)}${unit}`;
const svgElement = (tag, attributes, parent) => {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attributes)) el.setAttribute(key, value);
  parent.append(el);
  return el;
};
let report;
let selected;
let selectedCircle;
let reportOrigin;

async function json(url, options = {}) {
  const response = await fetch(url, { ...options, signal: AbortSignal.timeout(20000) });
  if (!response.ok) throw Error(`HTTP ${response.status}`);
  return response.json();
}

async function load() {
  const config = await json('config.json');
  let databaseError;
  // Prefer the DB-verified static snapshot to keep public traffic off DB egress.
  try {
    report = await json('baseline.json');
    reportOrigin = config.snapshotVerified ? 'Supabase保存済みスナップショット' : '保存済み履歴';
  } catch { /* First deployment may read directly from the database. */ }
  if (!report && config.supabaseUrl && config.publishableKey) {
    try {
      const rows = await json(`${config.supabaseUrl}/rest/v1/mikawa_reports?select=payload&order=report_month.desc&limit=1`, {
        headers: { apikey: config.publishableKey }
      });
      if (!rows[0]?.payload) throw Error('月次レポート未登録');
      report = rows[0].payload;
      reportOrigin = 'Supabase';
    } catch (error) { databaseError = error.message; }
  }
  if (!report) throw Error(databaseError ? `Supabaseに接続できません：${databaseError}。履歴ファイルもありません。` : 'データが未接続です。月次収集の実行とSupabaseの公開設定が必要です。');
  if (report.schema_version !== 1 || !report.sources?.length || !Array.isArray(report.points)) throw Error('レポートの形式を確認してください。');
  render();
}

function render() {
  $('connection').textContent = reportOrigin;
  $('area').textContent = `${report.area_km2} km²`;
  $('count').textContent = report.summary.candidate_count;
  $('usable').textContent = report.summary.usable_grid_points ?? report.summary.usable_points;
  $('observed').textContent = report.last_observed;
  $('month').textContent = report.report_month;
  $('generated').textContent = `処理：${report.generated_at.slice(0, 10)}`;
  $('resolution').textContent = `データ解像度 ${Math.max(...report.sources.map(s => s.resolution_m))}m`;
  const age = Math.floor((Date.now() - Date.parse(report.last_observed)) / 86400000);
  $('notice').textContent = `${report.operational_monthly_insar ? '月次InSARの暫定評価' : '公開InSARの履歴評価'}。最終観測から${age}日。${report.stale || age > 90 ? '観測が古いため、現在の状態は判定できません。' : ''} ${report.operational_monthly_insar ? '参照点・大気誤差・施設対応の現地検証が必要です。' : 'この履歴は新規Sentinel-1の月次解析結果ではありません。個別施設との対応は未検証です。'}`;
  $('candidates').replaceChildren();
  const ids = new Set(report.candidate_ids);
  const candidates = report.points.filter(p => ids.has(`${p.source_id}:${p.id}`));
  for (const point of candidates) {
    const button = text('button', '', $('candidates'), 'candidate');
    text('strong', `観測点 ${point.id}`, button);
    text('span', number(point.velocity_mm_year, ' mm/年'), button);
    text('small', `${point.direction === 'ascending' ? '北行' : '南行'} · ${point.stale ? '過去の候補' : '確認候補'} · ${(point.asset_names || []).join(' / ') || '施設未照合'}`, button);
    button.addEventListener('click', () => showPoint(point));
  }
  if (!candidates.length) text('p', '今回の基準で確認候補はありません。観測不足や対象施設の安全性は、この件数から判断できません。', $('candidates'), 'empty');
  for (const source of report.sources) {
    const item = text('div', '', $('source-list'), 'source');
    text('strong', source.name, item);
    text('p', `${source.dates[0]} ～ ${source.dates.at(-1)} / ${source.dates.length}観測 / ${source.resolution_m}m / LOS`, item);
    const link = text('a', '提供元メタデータ', item);
    if (/^https:\/\/(insarmap\.gsi\.go\.jp|search\.asf\.alaska\.edu)\//.test(source.metadata_url)) link.href = source.metadata_url;
    link.target = '_blank'; link.rel = 'noopener';
  }
  for (const limitation of report.limitations) text('li', limitation, $('limitations'));
  document.querySelector('footer').textContent = [...new Set(report.sources.map(s => s.credit))].join(' / ') + ' · 本サービスで再集計 · 点検優先順位検討用 MVP';
  $('export').disabled = false;
  $('export').addEventListener('click', exportCsv);
  $('filter').addEventListener('change', renderMap);
  renderMap();
  if (candidates.length) showPoint(candidates[0]);
}

// A small, dependency-free map at a fixed, explicit AOI. GSI tiles use Web Mercator.
function world(lon, lat, z) {
  const n = 256 * 2 ** z;
  return [(lon + 180) / 360 * n, (1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) / 2 * n];
}

function renderMap() {
  const [west, south, east, north] = report.aoi.bbox;
  const z = 14;
  const centre = world((west + east) / 2, (south + north) / 2, z);
  const corner = [centre[0] - 450, centre[1] - 310];
  const bounds = [world(west, south, z), world(east, north, z)];
  const tiles = $('tiles'); tiles.replaceChildren();
  const width = $('map').clientWidth;
  const factor = width / 900;
  for (let x = Math.floor(corner[0] / 256); x <= Math.floor((corner[0] + 900) / 256); x++) {
    for (let y = Math.floor(corner[1] / 256); y <= Math.floor((corner[1] + 620) / 256); y++) {
      const tile = document.createElement('img'); tile.alt = ''; tile.draggable = false;
      tile.src = `https://cyberjapandata.gsi.go.jp/xyz/pale/${z}/${x}/${y}.png`;
      tile.style.left = `${(x * 256 - corner[0]) * factor}px`;
      tile.style.top = `${(y * 256 - corner[1]) * factor}px`;
      tile.style.width = `${256 * factor}px`; tile.style.height = `${256 * factor}px`;
      tile.addEventListener('error', () => tile.remove());
      tiles.append(tile);
    }
  }
  const overlay = $('overlay'); overlay.replaceChildren();
  svgElement('rect', { x: bounds[0][0] - corner[0], y: bounds[1][1] - corner[1], width: bounds[1][0] - bounds[0][0], height: bounds[0][1] - bounds[1][1], fill: '#167b7b08', stroke: '#167b7b', 'stroke-dasharray': '5 4' }, overlay);
  const filter = $('filter').value;
  // Display one direction at a time at overlapping locations, while selecting
  // other sources remains possible from the candidate list/detail selector.
  const primary = report.sources[0].id;
  for (const point of report.points) {
    if (point.source_id !== primary && filter !== 'candidate') continue;
    if (filter === 'candidate' && !['candidate', 'watch'].includes(point.status)) continue;
    if (filter === 'usable' && point.quality !== 'usable') continue;
    if (filter === 'insufficient' && point.quality === 'usable') continue;
    const [x, y] = world(point.lon, point.lat, z);
    const circle = svgElement('circle', { cx: x - corner[0], cy: y - corner[1], r: point.status === 'candidate' ? 5 : 2.8, fill: colors[point.status], tabindex: 0, 'aria-label': `${point.id} ${labels[point.status]}` }, overlay);
    svgElement('title', {}, circle).textContent = `${point.id}: ${labels[point.status]}`;
    const select = () => { selectedCircle?.classList.remove('selected'); circle.classList.add('selected'); selectedCircle = circle; showPoint(point); };
    circle.addEventListener('click', select);
    circle.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(); } });
  }
}

function showPoint(point) {
  selected = point;
  const detail = $('detail'); detail.replaceChildren();
  text('h3', `観測点 ${point.id}`, detail);
  const source = report.sources.find(s => s.id === point.source_id);
  text('p', `${point.lat.toFixed(6)}, ${point.lon.toFixed(6)} / ${source.direction === 'ascending' ? '北行' : '南行'} / ${point.resolution_m}m`, detail);
  text('p', `${labels[point.status]}${point.stale ? ' · 過去の観測に基づく評価' : ''}`, detail, 'status');
  const grid = text('div', '', detail, 'detail-grid');
  for (const [label, value] of [['LOS速度', number(point.velocity_mm_year, ' mm/年')], ['残差のばらつき', number(point.residual_mm, ' mm')], ['有効観測数', point.observations], ['近傍の同符号点', point.neighbor_support]]) {
    const cell = text('div', label, grid); text('strong', value, cell);
  }
  text('p', '正：衛星へ近づく / 負：衛星から遠ざかる。上下方向の沈下量とは異なります。', detail);
  drawChart(source.dates, point.series, detail);
  text('p', '推奨：施設台帳・工事履歴と照合し、測量担当者が現地確認の必要性を判断。', detail);
  const label = text('label', '手元の確認メモ（このブラウザだけに保存）', detail);
  const notes = document.createElement('textarea'); notes.rows = 3; notes.placeholder = '工事照合・現地確認日など'; label.append(notes);
  const key = `mikawa-notes:${point.source_id}:${point.id}`;
  try { notes.value = localStorage.getItem(key) || ''; } catch { /* storage disabled */ }
  notes.addEventListener('input', () => { try { localStorage.setItem(key, notes.value); } catch { /* storage full */ } });
}

function drawChart(dates, values, parent) {
  const valid = values.map((v, i) => [Date.parse(dates[i]), v]).filter(p => p[1] !== null && Number.isFinite(p[1]));
  if (valid.length < 2) { text('p', '時系列を描画できる観測値が不足しています。', parent); return; }
  const minX = valid[0][0], maxX = valid.at(-1)[0];
  const minY = Math.min(...valid.map(p => p[1])) - 3, maxY = Math.max(...valid.map(p => p[1])) + 3;
  const chart = svgElement('svg', { viewBox: '0 0 400 175', class: 'chart', role: 'img', 'aria-label': 'LOS変位の時系列、単位mm' }, parent);
  const x = date => 38 + (date - minX) / (maxX - minX) * 350;
  const y = value => 145 - (value - minY) / (maxY - minY) * 130;
  for (let i = 0; i < 4; i++) {
    const value = minY + (maxY - minY) * i / 3;
    svgElement('line', { x1: 38, x2: 390, y1: y(value), y2: y(value) }, chart);
    svgElement('text', { x: 0, y: y(value) + 4 }, chart).textContent = value.toFixed(0);
  }
  // Do not connect lines across missing epochs or long gaps.
  for (let i = 1; i < dates.length; i++) {
    if (values[i - 1] === null || values[i] === null || Date.parse(dates[i]) - Date.parse(dates[i - 1]) > 180 * 86400000) continue;
    svgElement('line', { x1: x(Date.parse(dates[i - 1])), y1: y(values[i - 1]), x2: x(Date.parse(dates[i])), y2: y(values[i]), style: 'stroke:#167b7b;stroke-width:1.5' }, chart);
  }
  for (const [date, value] of valid) svgElement('circle', { cx: x(date), cy: y(value), r: 2.5, fill: '#167b7b' }, chart);
  svgElement('text', { x: 38, y: 169 }, chart).textContent = new Date(minX).toISOString().slice(0, 10);
  svgElement('text', { x: 305, y: 169 }, chart).textContent = new Date(maxX).toISOString().slice(0, 10);
}

function exportCsv() {
  const ids = new Set(report.candidate_ids);
  const fields = ['id', 'lat', 'lon', 'direction', 'velocity_mm_year', 'residual_mm', 'last_observed', 'stale', 'status'];
  const rows = report.points.filter(p => ids.has(`${p.source_id}:${p.id}`));
  const csv = '\ufeff' + [fields.join(','), ...rows.map(p => fields.map(k => JSON.stringify(p[k] ?? '')).join(','))].join('\r\n');
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a'); a.href = url; a.download = `mikawa-${report.report_month}.csv`; a.click();
  URL.revokeObjectURL(url);
}

let resize;
window.addEventListener('resize', () => { clearTimeout(resize); resize = setTimeout(() => { if (report) renderMap(); }, 200); });
load().catch(error => { $('connection').textContent = '未接続'; $('notice').textContent = error.message; $('notice').classList.add('error'); });
