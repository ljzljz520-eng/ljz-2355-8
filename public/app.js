const $ = (id) => document.getElementById(id);
const state = {
  map: null,
  route: null,
  session: null,
  downloads: new Set()
};

const params = () => {
  const p = new URLSearchParams({
    package: $('packageSelect').value,
    at: $('timeSelect').value,
    language: $('languageSelect').value
  });
  const mode = $('modeSelect').value;
  const floorId = $('floorSelect').value;
  const zoneId = $('zoneSelect').value;
  const maxMinutes = $('durationSelect').value;
  if (mode) p.set('mode', mode);
  if (floorId) p.set('floorId', floorId);
  if (zoneId) p.set('zoneId', zoneId);
  if (maxMinutes) p.set('maxMinutes', maxMinutes);
  return p;
};

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw Object.assign(new Error(body.error?.message ?? 'request failed'), { body });
  return body;
}

function showError(element, error) {
  const code = error.body?.error?.code;
  const details = error.body?.error?.details;
  element.textContent = code
    ? `${code}\n${error.message}${details ? `\n${JSON.stringify(details, null, 2)}` : ''}`
    : error.message;
  element.classList.remove('hidden');
}

function clearError(element) {
  element.textContent = '';
  element.classList.add('hidden');
}

function text(value, language) {
  if (!value) return '';
  return value[language] ?? value.zh ?? value.en ?? '';
}

async function loadMapAndZones() {
  const pkg = $('packageSelect').value;
  const at = $('timeSelect').value;
  clearError($('mapError'));
  state.route = null;
  try {
    state.map = await api(`/api/map?package=${encodeURIComponent(pkg)}&at=${encodeURIComponent(at)}`);
    $('layoutBadge').textContent = `布局版 ${state.map.layoutVersion}`;
    $('timeBadge').textContent = `信息时点 ${state.map.informationAt}`;
    populateZones();
    renderMap();
  } catch (error) {
    state.map = null;
    $('layoutBadge').textContent = '布局版不可用';
    renderEmptySvg();
    showError($('mapError'), error);
  }
}

function populateZones() {
  const currentFloor = $('floorSelect').value;
  const currentZone = $('zoneSelect').value;
  const zones = state.map.nodes.filter((node) => node.type === 'zone' && (!currentFloor || node.floorId === currentFloor));
  $('zoneSelect').innerHTML = '<option value="">全部</option>' + zones.map((zone) => `<option value="${zone.id}">${text(zone.name, 'zh')}</option>`).join('');
  if ([...$('zoneSelect').options].some((option) => option.value === currentZone)) $('zoneSelect').value = currentZone;

  const nodes = state.map.nodes;
  $('fromSelect').innerHTML = nodes.filter((n) => ['lobby', 'zone'].includes(n.type)).map((n) => `<option value="${n.id}">${text(n.name, 'zh')}</option>`).join('');
  $('fromSelect').value = 'f1-lobby';
}

function windowColor(status) {
  return { open: 'open', closed: 'closed', unknown: 'unknown' }[status] ?? 'unknown';
}

function renderEmptySvg() {
  $('map').innerHTML = '<text x="24" y="235" class="floor-label">当前离线包缺少该时点的布局块；不能用旧图猜测展柜。</text>';
}

function renderMap() {
  if (!state.map) return renderEmptySvg();
  const svg = $('map');
  const positions = state.map.positions;
  const routeNodeSet = new Set(state.route?.path ?? []);
  const routeEdges = new Set((state.route?.edges ?? []).map((edge) => edge.id));
  const floorOffsets = { f1: 0, f2: 155, f3: 310 };

  const edgeSvg = state.map.edges.map((edge) => {
    const a = positions[edge.source];
    const b = positions[edge.target];
    const s = state.map.windows.edges[edge.id];
    const cls = ['edge', s.status === 'closed' ? 'blocked' : '', s.status === 'unknown' ? 'unknown' : '', routeEdges.has(edge.id) ? 'route-edge' : ''].join(' ').trim();
    return `<line class="${cls}" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" data-id="${edge.id}"/>`;
  }).join('');

  const routeSvg = (state.route?.edges ?? []).map((edge) => {
    const a = positions[edge.source];
    const b = positions[edge.target];
    return `<line class="route-line" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"/>`;
  }).join('');

  const nodeSvg = state.map.nodes.map((node) => {
    const p = positions[node.id];
    const stateClass = node.type === 'zone' ? windowColor(state.map.windows.zones[node.id]?.status) : 'open';
    const radius = node.type === 'lobby' ? 8 : node.type === 'zone' ? 8 : 5;
    const inRoute = routeNodeSet.has(node.id) ? 'stroke:#0f6b8f;stroke-width:3' : '';
    const name = node.type === 'case' ? node.id.split('-').slice(-2).join('-') : text(node.name, 'zh');
    return `
      <g>
        <circle class="node ${stateClass}" style="${inRoute}" cx="${p.x}" cy="${p.y}" r="${radius}"/>
        <text class="node-label" x="${p.x}" y="${p.y - 10}">${name}</text>
      </g>`;
  }).join('');

  const labels = Object.entries(floorOffsets).map(([id, y]) => `<text x="14" y="${y + 28}" class="floor-label">${id.toUpperCase()}</text>`).join('');
  svg.innerHTML = labels + edgeSvg + routeSvg + nodeSvg;
}

async function loadDocuments() {
  clearError($('docsError'));
  try {
    const result = await api(`/api/documents?${params()}`);
    $('layoutBadge').textContent = `布局版 ${result.layoutVersion}`;
    $('documents').innerHTML = result.documents.map((item) => {
      const stale = item.stale
        ? '<span class="tag warn">长/短稿各自核对：待复核</span>'
        : '<span class="tag good">已核对</span>';
      const zoneState = item.location?.zoneState;
      const zoneTag = zoneState
        ? `<span class="tag ${zoneState.status === 'open' ? 'good' : zoneState.status === 'unknown' ? 'warn' : 'bad'}">展区 ${zoneState.status}${zoneState.reason ? `:${zoneState.reason}` : ''}</span>`
        : '<span class="tag warn">当前无有效展柜</span>';
      return `<article class="card">
        <h3>${item.title}</h3>
        <div class="meta">
          <span class="tag">${item.mode === 'long' ? '长稿' : '短稿'} · ${item.durationMinutes} 分钟</span>
          <span class="tag">${item.exhibitId}</span>
          <span class="tag">${item.floorId}/${item.zoneId ?? '-'}</span>
          ${zoneTag}${stale}
        </div>
        <p>展柜：${item.location?.nodeId ?? '无当前位置'}${item.location?.note ? '（' + text(item.location.note, 'zh') + '）' : ''}</p>
      </article>`;
    }).join('') || '<p>没有符合楼层、展区、时长条件的资料。</p>';
  } catch (error) {
    $('documents').innerHTML = '';
    showError($('docsError'), error);
  }
}

async function calculateRoute() {
  const p = new URLSearchParams({
    package: $('packageSelect').value,
    at: $('timeSelect').value,
    from: $('fromSelect').value,
    to: $('toSelect').value
  });
  try {
    state.route = await api(`/api/route?${p}`);
    if (state.route.reachable) {
      $('routeResult').innerHTML = `<span class="tag good">可达，距离 ${state.route.distance}</span>\n${state.route.path.join(' → ')}`;
    } else {
      const r = state.route.reason;
      $('routeResult').innerHTML = `<span class="tag bad">${r.code}</span>\n${r.message}\n${JSON.stringify(r.details, null, 2)}`;
    }
    renderMap();
  } catch (error) {
    state.route = null;
    $('routeResult').innerHTML = '';
    showError($('routeResult'), error);
    renderMap();
  }
}

async function refreshPackages() {
  const info = await api('/api/packages');
  $('packageInfo').textContent = JSON.stringify(info.packages, null, 2);
}

async function startUpdate(missing = false) {
  state.session = await api('/api/update/session', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      packageId: 'route-old',
      missingBlockKeys: missing ? ['content:e-bronze:2'] : []
    })
  });
  state.downloads = new Set();
  renderSession();
}

async function downloadOneChunk() {
  if (!state.session) await startUpdate(false);
  const manifest = await api('/api/packages');
  const next = manifest.targetRouteManifest.files.flatMap((file) =>
    file.chunks.map((chunk) => ({ file, chunk }))
  ).find(({ file, chunk }) => !state.downloads.has(`${file.key}:${chunk.index}`));
  if (!next) return;
  const status = await api('/api/update/chunk', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ sessionId: state.session.sessionId, key: next.file.key, index: next.chunk.index })
  });
  state.downloads.add(`${next.file.key}:${next.chunk.index}`);
  state.session = status;
  renderSession();
}

async function activate() {
  if (!state.session) await startUpdate(false);
  try {
    // The demo session has one shard per small block; download every shard.
    while (state.session.completedChunks < state.session.totalChunks) {
      // eslint-disable-next-line no-await-in-loop
      await downloadOneChunk();
    }
    const result = await api('/api/update/activate', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ sessionId: state.session.sessionId })
    });
    state.session = { ...state.session, status: 'activated' };
    $('updateResult').textContent = `已原子激活：${JSON.stringify(result.activated, null, 2)}`;
    await refreshPackages();
  } catch (error) {
    showError($('updateResult'), error);
    await refreshPackages();
  }
}

async function rollback() {
  const result = await api('/api/update/rollback', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: '{}'
  });
  $('updateResult').textContent = `已回滚到清单 ${result.manifestVersion}`;
  await refreshPackages();
}

function renderSession() {
  if (!state.session) return;
  $('updateResult').textContent = JSON.stringify(state.session, null, 2);
}

async function refreshAll() {
  await Promise.all([loadMapAndZones(), loadDocuments(), refreshPackages()]);
}

$('refreshBtn').addEventListener('click', refreshAll);
$('routeBtn').addEventListener('click', calculateRoute);
$('startUpdateBtn').addEventListener('click', () => startUpdate(false).catch((e) => showError($('updateResult'), e)));
$('startBrokenBtn').addEventListener('click', () => startUpdate(true).catch((e) => showError($('updateResult'), e)));
$('downloadBtn').addEventListener('click', () => downloadOneChunk().catch((e) => showError($('updateResult'), e)));
$('activateBtn').addEventListener('click', activate);
$('rollbackBtn').addEventListener('click', rollback);
$('floorSelect').addEventListener('change', () => {
  $('zoneSelect').value = '';
  refreshAll();
});
for (const id of ['packageSelect', 'timeSelect', 'zoneSelect', 'durationSelect', 'languageSelect', 'modeSelect']) {
  $(id).addEventListener('change', refreshAll);
}

refreshAll();
