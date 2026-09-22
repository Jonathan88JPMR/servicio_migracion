let charts = {};
let filesState = { tipo: 'ap', estado: '', gatipo: '', ref: '', page: 1, per_page: 25 };
let activeRunId = null;
let runStart = null;
let runTimer = null;
let configCache = null;
let entornosCache = [];

function showAlert(msg, type='danger') {
  const box = document.getElementById('alert-box');
  const div = document.createElement('div');
  div.className = `alert alert-${type} alert-dismissible fade show`;
  div.innerHTML = `${msg}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>`;
  box.appendChild(div);
  setTimeout(() => div.remove(), 8000);
}

function formatDate(d) {
  if (!d) return '';
  try { return new Date(d).toLocaleString('es-PE'); } catch (e) { return d; }
}

function formatDuration(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}m ${s}s`;
}

function startRunTimer() {
  if (runTimer) clearInterval(runTimer);
  runTimer = setInterval(updateRunInfo, 1000);
  updateRunInfo();
}

function stopRunTimer() {
  if (runTimer) { clearInterval(runTimer); runTimer = null; }
}

function updateRunInfo() {
  if (!runStart) return;
  const elapsed = Date.now() - runStart.getTime();
  const startStr = runStart.toLocaleTimeString('es-PE');
  document.querySelectorAll('.run-info').forEach(info => {
    info.innerHTML = `Iniciada: <strong>${startStr}</strong>. Transcurrido: <strong>${formatDuration(elapsed)}</strong>`;
  });
}

function escapeJs(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\n/g, '\\n').replace(/\r/g, '\\r');
}

function showError(etapa, msg) {
  const modal = new bootstrap.Modal(document.getElementById('errorModal'));
  document.getElementById('error-title').textContent = 'Detalle del error';
  const body = document.getElementById('error-body');
  body.innerHTML = '';
  const p = document.createElement('p');
  const strong = document.createElement('strong');
  strong.textContent = 'Etapa: ';
  p.appendChild(strong);
  const span = document.createElement('span');
  span.className = 'badge bg-secondary';
  span.textContent = etapa || '-';
  p.appendChild(span);
  body.appendChild(p);
  const pre = document.createElement('pre');
  pre.style.whiteSpace = 'pre-wrap';
  pre.style.wordBreak = 'break-word';
  pre.textContent = msg || '(sin mensaje)';
  body.appendChild(pre);
  modal.show();
}

async function loadStats() {
  try {
    const res = await fetch('/api/stats');
    const data = await res.json();
    if (!data.ok) { showAlert(data.error || 'Error cargando estadísticas'); return; }
    renderStats(data);
    renderCharts(data);
  } catch (e) { showAlert('Error de red: ' + e.message); }
}

function renderStats(data) {
  const ap = data.ap || {};
  const ms = data.ms || {};
  const cfg = data.configured_batch || {};
  document.getElementById('stat-cards').innerHTML = `
    <div class="col-md-2 col-6"><div class="card text-bg-info"><div class="card-body"><h6>AP total</h6><h3>${ap.total || 0}</h3></div></div></div>
    <div class="col-md-2 col-6"><div class="card text-bg-warning"><div class="card-body"><h6>AP pendientes</h6><h3>${ap.pending || 0}</h3></div></div></div>
    <div class="col-md-2 col-6"><div class="card text-bg-success"><div class="card-body"><h6>AP completados</h6><h3>${ap.done || 0}</h3></div></div></div>
    <div class="col-md-2 col-6"><div class="card text-bg-secondary"><div class="card-body"><h6>MS pendientes</h6><h3>${ms.pending || 0}</h3></div></div></div>
    <div class="col-md-2 col-6"><div class="card text-bg-success"><div class="card-body"><h6>GD_Archivo (prueba)</h6><h3>${data.gd_test || 0}</h3></div></div></div>
    <div class="col-md-2 col-6"><div class="card text-bg-light border"><div class="card-body"><h6>Última ejecución</h6><small>${formatDate(data.last_run)}</small><br><small>Batch AP: ${cfg.BATCH_AP_DOCUMENTO_PRUEBA || 0}</small></div></div></div>
  `;
}

function destroyChart(id) { if (charts[id]) { charts[id].destroy(); charts[id] = null; } }

function renderCharts(data) {
  const palette = ['#198754','#0dcaf0','#ffc107','#dc3545','#6c757d','#0d6efd','#6610f2'];
  const apEst = (data.ap && data.ap.by_estado) || [];
  const apGat = (data.ap && data.ap.by_gatipo) || [];
  const msEst = (data.ms && data.ms.by_estado) || [];

  destroyChart('chart-ap-estado');
  charts['chart-ap-estado'] = new Chart(document.getElementById('chart-ap-estado'), {
    type: 'doughnut',
    data: { labels: apEst.map(x => x.Estado), datasets: [{ data: apEst.map(x => x.total), backgroundColor: palette }] },
    options: { responsive: true, plugins: { title: { display: true, text: 'AP por estado' } } }
  });

  destroyChart('chart-ap-gatipo');
  charts['chart-ap-gatipo'] = new Chart(document.getElementById('chart-ap-gatipo'), {
    type: 'bar',
    data: { labels: apGat.map(x => x.Gatipo), datasets: [{ label: 'Total', data: apGat.map(x => x.total), backgroundColor: '#0d6efd' }] },
    options: { responsive: true, plugins: { title: { display: true, text: 'AP por GATipo (total)' } }, scales: { y: { beginAtZero: true } } }
  });

  destroyChart('chart-ms-estado');
  charts['chart-ms-estado'] = new Chart(document.getElementById('chart-ms-estado'), {
    type: 'doughnut',
    data: { labels: msEst.map(x => x.Estado), datasets: [{ data: msEst.map(x => x.total), backgroundColor: palette }] },
    options: { responsive: true, plugins: { title: { display: true, text: 'MS_Archivo por estado' } } }
  });

  destroyChart('chart-ap-gatipo-done');
  charts['chart-ap-gatipo-done'] = new Chart(document.getElementById('chart-ap-gatipo-done'), {
    type: 'bar',
    data: { labels: apGat.map(x => x.Gatipo), datasets: [{ label: 'Completados', data: apGat.map(x => x.completados), backgroundColor: '#198754' }] },
    options: { responsive: true, plugins: { title: { display: true, text: 'AP por GATipo (completados)' } }, scales: { y: { beginAtZero: true } } }
  });
}

async function loadConfig() {
  try {
    const res = await fetch('/api/config');
    const data = await res.json();
    if (!data.ok) { showAlert(data.error); return; }
    configCache = data.config;
    entornosCache = data.entornos || [];
    renderEntornoSelect(data.entorno_activo, data.entornos);
    renderConfig(data.config);
  } catch (e) { showAlert('Error cargando configuración: ' + e.message); }
}

function renderEntornoSelect(activo, entornos) {
  const wrap = document.getElementById('config-entorno-wrap');
  if (!wrap) return;
  let html = '<div class="row"><div class="col-sm-4"><label class="form-label fw-bold">Entorno</label></div><div class="col-sm-8"><select id="config-entorno" class="form-select mb-3">';
  for (const e of entornos) {
    const disabled = (e.Entorno === 'PRODUCCION' && !e.ProduccionHabilitado) ? 'disabled' : '';
    const selected = e.Entorno === activo ? 'selected' : '';
    html += `<option value="${e.Entorno}" ${disabled} ${selected}>${e.Entorno} - ${e.Descripcion || ''}</option>`;
  }
  html += '</select></div></div>';
  wrap.innerHTML = html;
  document.getElementById('config-entorno').addEventListener('change', onEntornoChange);
}

async function onEntornoChange(ev) {
  const nuevo = ev.target.value;
  if (configCache && nuevo === configCache.ENTORNO) return;
  const opt = entornosCache.find(e => e.Entorno === nuevo);
  if (nuevo === 'PRODUCCION' && !opt?.ProduccionHabilitado) {
    showAlert('PRODUCCION está bloqueado. Se requiere permiso explícito para habilitarlo.');
    ev.target.value = configCache.ENTORNO;
    return;
  }
  if (!confirm(`¿Cambiar entorno activo a ${nuevo}?`)) {
    ev.target.value = configCache.ENTORNO;
    return;
  }
  try {
    const res = await fetch('/api/cambiar-entorno', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ entorno: nuevo }) });
    const data = await res.json();
    if (!data.ok) { showAlert(data.error); loadConfig(); return; }
    showAlert(`Entorno activo cambiado a ${nuevo}`, 'success');
    loadConfig();
    loadStats();
  } catch (e) { showAlert('Error cambiando entorno: ' + e.message); }
}

function renderConfig(cfg) {
  const form = document.getElementById('config-form');
  form.innerHTML = '';
  const skip = ['Entorno','ENTORNO','ProduccionHabilitado','Activo','FechaRegistro','Id','Descripcion',
                'BD_SPRING_PRUEBA','BD_SPRING_PRODUCCION','RUTA_RAIZ_PRUEBA','RUTA_RAIZ_PRODUCCION'];
  for (const [k, v] of Object.entries(cfg)) {
    if (skip.includes(k)) continue;
    const disabled = (k === 'MODO_SERVICIO') ? 'disabled' : '';
    const div = document.createElement('div');
    div.className = 'mb-2 row';
    div.innerHTML = `
      <label class="col-sm-4 col-form-label">${k}</label>
      <div class="col-sm-8">
        <input type="text" class="form-control config-input" data-key="${k}" value="${v || ''}" ${disabled}>
      </div>
    `;
    form.appendChild(div);
  }
}

async function saveConfig() {
  const inputs = document.querySelectorAll('.config-input');
  const updates = {};
  inputs.forEach(i => { if (!i.disabled) updates[i.dataset.key] = i.value; });
  try {
    const res = await fetch('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(updates) });
    const data = await res.json();
    if (data.ok) { showAlert('Configuración guardada', 'success'); loadConfig(); }
    else { showAlert((data.errors || []).join('<br>') || data.error); }
  } catch (e) { showAlert('Error guardando: ' + e.message); }
}

async function loadFiles(page=1) {
  filesState.tipo = document.getElementById('files-tipo').value;
  filesState.estado = document.getElementById('files-estado').value;
  filesState.gatipo = document.getElementById('files-gatipo').value;
  filesState.ref = document.getElementById('files-ref').value;
  filesState.page = page;
  const params = new URLSearchParams(filesState);
  try {
    const res = await fetch('/api/files?' + params);
    const data = await res.json();
    if (!data.ok) { showAlert(data.error); return; }
    renderFiles(data);
  } catch (e) { showAlert('Error de red: ' + e.message); }
}

function renderFiles(data) {
  const rows = data.rows || [];
  const tipo = filesState.tipo;
  let html = '<table class="table table-sm table-striped table-hover"><thead><tr>';
  if (tipo === 'ap') {
    html += '<th>Id</th><th>GATipo</th><th>Nombre</th><th>Obligación</th><th>OC/OS</th><th>Estado</th><th>Intentos</th><th>Traslado</th><th>ArchivoId</th><th>Error</th><th></th>';
    html += '</tr></thead><tbody>';
    for (const r of rows) {
      const refs = (r.Referencias || '').split(', ').filter(Boolean)
        .map(ref => `<span class="badge text-bg-light border">${ref}</span>`).join(' ');
      html += `<tr>
        <td>${r.IdApDocumentoArchivo}</td>
        <td>${r.Gatipo}</td>
        <td>${r.Ganombre}</td>
        <td>${r.ObligacionNumeroDocumento}</td>
        <td>${refs}</td>
        <td><span class="badge bg-${estadoColor(r.Estado)}">${r.Estado}</span></td>
        <td>${r.Intentos}</td>
        <td>${formatDate(r.FechaTraslado)}</td>
        <td>${r.ArchivoId || ''}</td>
        <td>${r.Estado === 'ERROR' ? `<button class="btn btn-sm btn-outline-danger" onclick="showError('${escapeJs(r.Etapa)}', '${escapeJs(r.MensajeError)}')">Ver error</button>` : ''}</td>
        <td><button class="btn btn-sm btn-outline-primary" onclick="previewFile('${r.IdApDocumentoArchivo}', 'ap')">Ver</button></td>
      </tr>`;
    }
  } else {
    html += '<th>Id</th><th>Tabla</th><th>Nombre</th><th>Estado</th><th>Traslado</th><th>ArchivoId</th><th>Error</th><th></th>';
    html += '</tr></thead><tbody>';
    for (const r of rows) {
      html += `<tr>
        <td>${r.IdArchivo}</td>
        <td>${r.Tabla}</td>
        <td>${r.Nombre}</td>
        <td><span class="badge bg-${estadoColor(r.Estado)}">${r.Estado}</span></td>
        <td>${formatDate(r.FechaTraslado)}</td>
        <td>${r.ArchivoId || ''}</td>
        <td>${r.Estado === 'ERROR' ? `<button class="btn btn-sm btn-outline-danger" onclick="showError('${escapeJs(r.Etapa)}', '${escapeJs(r.MensajeError)}')">Ver error</button>` : ''}</td>
        <td><button class="btn btn-sm btn-outline-primary" onclick="previewFile('${r.IdArchivo}', 'ms')">Ver</button></td>
      </tr>`;
    }
  }
  html += '</tbody></table>';
  document.getElementById('files-table-wrap').innerHTML = html;

  const pages = Math.ceil(data.total / data.per_page);
  let pager = '';
  if (pages > 1) {
    pager = '<div class="btn-group btn-group-sm" role="group" aria-label="Paginación">';
    pager += `<button type="button" class="btn btn-outline-primary" onclick="loadFiles(${data.page - 1})" ${data.page === 1 ? 'disabled' : ''}>&laquo;</button>`;
    pager += `<button type="button" class="btn btn-outline-primary" onclick="loadFiles(${data.page - 1})" ${data.page === 1 ? 'disabled' : ''}>&lt;</button>`;
    const radius = 2;
    let start = Math.max(1, data.page - radius);
    let end = Math.min(pages, data.page + radius);
    if (end - start + 1 < 5) {
      if (data.page <= radius) end = Math.min(pages, 5);
      else start = Math.max(1, pages - 4);
    }
    if (start > 1) pager += '<button type="button" class="btn btn-outline-primary" disabled>...</button>';
    for (let i = start; i <= end; i++) {
      pager += `<button type="button" class="btn ${i === data.page ? 'btn-primary' : 'btn-outline-primary'}" onclick="loadFiles(${i})">${i}</button>`;
    }
    if (end < pages) pager += '<button type="button" class="btn btn-outline-primary" disabled>...</button>';
    pager += `<button type="button" class="btn btn-outline-primary" onclick="loadFiles(${data.page + 1})" ${data.page === pages ? 'disabled' : ''}>&gt;</button>`;
    pager += `<button type="button" class="btn btn-outline-primary" onclick="loadFiles(${pages})" ${data.page === pages ? 'disabled' : ''}>&raquo;</button>`;
    pager += '</div>';
  }
  document.getElementById('files-pager').innerHTML = `<div class="mt-3"><small class="text-muted">Total: ${data.total} | Página ${data.page} de ${pages}</small></div><div class="mt-1">${pager}</div>`;

  const gatWrap = document.getElementById('filter-gatipo-wrap');
  gatWrap.style.display = (tipo === 'ap') ? 'block' : 'none';
  const refWrap = document.getElementById('filter-ref-wrap');
  refWrap.style.display = (tipo === 'ap') ? 'block' : 'none';
}

function estadoColor(e) {
  if (e === 'COMPLETADO') return 'success';
  if (e === 'ERROR') return 'danger';
  if (e === 'PENDIENTE') return 'warning';
  return 'secondary';
}

function previewFile(id, tipo) {
  const modal = new bootstrap.Modal(document.getElementById('previewModal'));
  document.getElementById('preview-title').textContent = `Vista previa - ${tipo} ${id}`;
  document.getElementById('preview-iframe').src = `/api/preview/${tipo}/${id}`;
  modal.show();
}

async function runNow() {
  if (activeRunId) { showAlert('Ya hay una ejecución activa'); return; }
  if (configCache && configCache.MODO_SERVICIO !== 'PRUEBA') {
    showAlert('Solo se puede ejecutar en modo PRUEBA'); return;
  }
  try {
    const res = await fetch('/api/run', { method: 'POST' });
    const data = await res.json();
    if (!data.ok) { showAlert((data.errors || []).join('<br>') || data.error); return; }
    activeRunId = data.run_id;
    runStart = new Date();
    document.querySelectorAll('.run-output').forEach(b => { b.innerHTML = ''; });
    startRunTimer();
    pollRun();
  } catch (e) { showAlert('Error iniciando: ' + e.message); }
}

async function runAll() {
  if (activeRunId) { showAlert('Ya hay una ejecución activa'); return; }
  if (configCache && configCache.MODO_SERVICIO !== 'PRUEBA') {
    showAlert('Solo se puede ejecutar en modo PRUEBA'); return;
  }
  if (!confirm('¿Procesar todo lo faltante? Puede tardar varios minutos.')) return;
  try {
    const res = await fetch('/api/run/all', { method: 'POST' });
    const data = await res.json();
    if (!data.ok) { showAlert(data.error); return; }
    activeRunId = data.run_id;
    runStart = new Date();
    document.querySelectorAll('.run-output').forEach(b => { b.innerHTML = ''; });
    startRunTimer();
    pollRun();
  } catch (e) { showAlert('Error iniciando: ' + e.message); }
}

async function runOrden() {
  if (activeRunId) { showAlert('Ya hay una ejecución activa'); return; }
  if (configCache && configCache.MODO_SERVICIO !== 'PRUEBA') {
    showAlert('Solo se puede ejecutar en modo PRUEBA'); return;
  }
  const numero = document.getElementById('run-orden-numero').value.trim();
  const tipo = document.getElementById('run-orden-tipo').value;
  if (!numero) { showAlert('Ingrese el número de OC/OS'); return; }
  try {
    const res = await fetch('/api/run/orden', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ numero, tipo }) });
    const data = await res.json();
    if (!data.ok) { showAlert(data.error); return; }
    showAlert(`Orden ${numero}: ${data.pending_ap} archivos AP + ${data.pending_ms} adjuntos MS pendientes (${data.obligaciones} obligaciones)`, 'info');
    activeRunId = data.run_id;
    runStart = new Date();
    document.querySelectorAll('.run-output').forEach(b => { b.innerHTML = ''; });
    startRunTimer();
    pollRun();
  } catch (e) { showAlert('Error iniciando: ' + e.message); }
}

function pollRun() {
  if (!activeRunId) return;
  const interval = setInterval(async () => {
    try {
      const res = await fetch('/api/run/' + activeRunId);
      const data = await res.json();
      if (!data.ok) {
        clearInterval(interval); stopRunTimer(); activeRunId = null; runStart = null;
        showAlert(data.error); return;
      }
      document.querySelectorAll('.run-output').forEach(box => {
        box.textContent = data.output.join('\n');
        box.scrollTop = box.scrollHeight;
      });
      if (data.status !== 'running') {
        clearInterval(interval);
        const end = new Date();
        const duration = runStart ? (end - runStart) : 0;
        const startStr = runStart ? runStart.toLocaleTimeString('es-PE') : '-';
        const endStr = end.toLocaleTimeString('es-PE');
        stopRunTimer();
        activeRunId = null;
        runStart = null;
        document.querySelectorAll('.run-info').forEach(el => {
          el.innerHTML = `Iniciada: <strong>${startStr}</strong>. Finalizada: <strong>${endStr}</strong>. Duración total: <strong>${formatDuration(duration)}</strong>`;
        });
        showAlert(`Ejecución finalizada con estado: ${data.status} (código ${data.exit_code})`, data.status === 'success' ? 'success' : 'danger');
        loadStats();
        loadLog();
      }
    } catch (e) { clearInterval(interval); stopRunTimer(); activeRunId = null; runStart = null; showAlert('Error consultando ejecución: ' + e.message); }
  }, 2000);
}

async function loadLog() {
  try {
    const res = await fetch('/api/log?tail=200');
    const data = await res.json();
    if (!data.ok) { showAlert(data.error); return; }
    document.getElementById('log-box').textContent = data.lines.join('\n');
  } catch (e) { showAlert('Error cargando log: ' + e.message); }
}

async function init() {
  await loadConfig();
  await loadStats();
  await loadLog();
  document.getElementById('files-tipo').addEventListener('change', () => loadFiles(1));
  document.getElementById('files-estado').addEventListener('change', () => loadFiles(1));
  document.getElementById('files-gatipo').addEventListener('change', () => loadFiles(1));
  document.getElementById('files-ref').addEventListener('change', () => loadFiles(1));
  document.getElementById('tab-files').addEventListener('shown.bs.tab', () => loadFiles(1));
  document.getElementById('tab-log').addEventListener('shown.bs.tab', loadLog);
}

init();
