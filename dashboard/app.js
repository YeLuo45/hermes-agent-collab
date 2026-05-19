// dashboard/app.js — Extended Admin UI for hermes-agent-collab
// Adds: Workspaces, Quotas, Audit, Experiments, Knowledge Graph, Notifications, Settings

const API_BASE = '/api/collab/v1';

// ─── Global state (supplements existing globals from index.html inline script) ─
let workspaces = [];
let quotas = [];
let auditLogs = [];
let experiments = [];
let kgNodes = [];
let notifications = [];
let cacheStats = {};
let i18nLocales = [];
let currentLocale = 'en';

// ─── Tab management ─────────────────────────────────────────────────────────
// Override switchTab from inline script to also load data for new tabs
const _origSwitchTab = typeof switchTab === 'function' ? switchTab : null;

function switchTab(tab) {
  // Call original if exists
  if (_origSwitchTab) {
    _origSwitchTab(tab);
  } else {
    // Fallback if original not defined
    currentTab = tab;
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    const navItem = document.querySelector(`.nav-item[data-tab="${tab}"]`);
    if (navItem) navItem.classList.add('active');
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    const panel = document.getElementById(`panel-${tab}`);
    if (panel) panel.classList.add('active');
  }

  // Load data for new tabs
  switch (tab) {
    case 'workspaces': loadWorkspaces(); break;
    case 'quotas': loadQuotas(); break;
    case 'audit': loadAudit(); break;
    case 'experiments': loadExperiments(); break;
    case 'kg': loadKnowledgeGraph(); break;
    case 'notifications': loadNotifications(); break;
    case 'settings': loadSettings(); break;
  }
}

// Make switchTab globally available
window.switchTab = switchTab;

// ─── Workspaces ─────────────────────────────────────────────────────────────
async function loadWorkspaces() {
  try {
    const data = await fetch(`${API_BASE}/workspaces`).then(r => r.json()).catch(() => ({}));
    workspaces = data.workspaces || [];
    renderWorkspaces();
  } catch (e) {
    document.getElementById('workspacesTable').innerHTML = '<div class="empty-state"><div class="icon">⚠</div>Failed to load workspaces</div>';
  }
}

function renderWorkspaces() {
  const container = document.getElementById('workspacesTable');
  if (!workspaces.length) {
    container.innerHTML = '<div class="empty-state"><div class="icon">🏢</div>No workspaces</div>';
    return;
  }
  container.innerHTML = `<table>
    <thead><tr><th>Name</th><th>ID</th><th>Owner</th><th>Agents</th><th>Created</th></tr></thead>
    <tbody>
      ${workspaces.map(ws => `<tr>
        <td><b>${ws.name || '—'}</b></td>
        <td><code style="font-size:11px;color:var(--text-dim)">${ws.workspace_id || '—'}</code></td>
        <td>${ws.owner_id || '—'}</td>
        <td>${ws.agent_count || 0}</td>
        <td>${ws.created_at ? timeAgo(ws.created_at) : '—'}</td>
      </tr>`).join('')}
    </tbody>
  </table>`;
}

// ─── Quotas ─────────────────────────────────────────────────────────────────
async function loadQuotas() {
  try {
    const data = await fetch(`${API_BASE}/quotas`).then(r => r.json()).catch(() => ({}));
    quotas = data.quotas || data.workspaces || [];
    renderQuotas();
  } catch (e) {
    document.getElementById('quotasTable').innerHTML = '<div class="empty-state"><div class="icon">⚠</div>Failed to load quotas</div>';
  }
}

function renderQuotas() {
  const container = document.getElementById('quotasTable');
  if (!quotas.length) {
    container.innerHTML = '<div class="empty-state"><div class="icon">📊</div>No quota data</div>';
    return;
  }
  container.innerHTML = `<table>
    <thead><tr><th>Workspace</th><th>API Calls</th><th>Storage</th><th>Agents</th><th>Status</th></tr></thead>
    <tbody>
      ${quotas.map(q => {
        const apiUsed = q.api_calls_used || 0;
        const apiLimit = q.api_calls_limit || 0;
        const apiPct = apiLimit ? Math.round(apiUsed / apiLimit * 100) : 0;
        const storageUsed = q.storage_used_mb || 0;
        const storageLimit = q.storage_limit_mb || 0;
        const storagePct = storageLimit ? Math.round(storageUsed / storageLimit * 100) : 0;
        const overQuota = apiPct >= 100 || storagePct >= 100;
        return `<tr>
          <td><b>${q.workspace_id || '—'}</b></td>
          <td>
            <div style="display:flex;align-items:center;gap:8px">
              <div style="flex:1;height:6px;background:var(--border);border-radius:3px">
                <div style="width:${Math.min(apiPct,100)}%;height:100%;background:${apiPct>=90?'var(--red)':apiPct>=70?'var(--yellow)':'var(--green)'};border-radius:3px"></div>
              </div>
              <span style="font-size:11px;color:var(--text-dim);min-width:50px">${apiUsed}/${apiLimit}</span>
            </div>
          </td>
          <td>
            <div style="display:flex;align-items:center;gap:8px">
              <div style="flex:1;height:6px;background:var(--border);border-radius:3px">
                <div style="width:${Math.min(storagePct,100)}%;height:100%;background:${storagePct>=90?'var(--red)':storagePct>=70?'var(--yellow)':'var(--green)'};border-radius:3px"></div>
              </div>
              <span style="font-size:11px;color:var(--text-dim);min-width:50px">${storageUsed}MB</span>
            </div>
          </td>
          <td>${q.max_agents || '∞'}</td>
          <td>${overQuota ? '<span style="color:var(--red);font-size:12px;font-weight:600">⚠ Over Quota</span>' : '<span style="color:var(--green);font-size:12px">✓ OK</span>'}</td>
        </tr>`;
      }).join('')}
    </tbody>
  </table>`;
}

// ─── Audit ──────────────────────────────────────────────────────────────────
async function loadAudit() {
  try {
    const data = await fetch(`${API_BASE}/audit/logs?limit=100`).then(r => r.json()).catch(() => ({}));
    auditLogs = data.logs || data.entries || [];
    renderAudit();
  } catch (e) {
    document.getElementById('auditTable').innerHTML = '<div class="empty-state"><div class="icon">⚠</div>Failed to load audit logs</div>';
  }
}

function renderAudit() {
  const container = document.getElementById('auditTable');
  if (!auditLogs.length) {
    container.innerHTML = '<div class="empty-state"><div class="icon">📋</div>No audit logs</div>';
    return;
  }
  container.innerHTML = `<table>
    <thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Target</th><th>Hash Chain</th></tr></thead>
    <tbody>
      ${auditLogs.slice(0, 100).map(log => `<tr>
        <td style="font-size:11px;color:var(--text-dim)">${fmtTime(log.timestamp || log.created_at)}</td>
        <td><span style="color:var(--blue)">${log.actor || log.user_id || '—'}</span></td>
        <td><span class="event-badge badge-phase">${log.action || log.event_type || '—'}</span></td>
        <td style="font-size:11px;color:var(--text-dim)">${log.target || '—'}</td>
        <td><code style="font-size:10px;color:var(--text-dim)">${(log.hash || log.hash_chain || '').slice(0, 16)}…</code></td>
      </tr>`).join('')}
    </tbody>
  </table>`;
}

// ─── Experiments (A/B Testing) ───────────────────────────────────────────────
async function loadExperiments() {
  try {
    const data = await fetch(`${API_BASE}/experiments`).then(r => r.json()).catch(() => ({}));
    experiments = data.experiments || [];
    renderExperiments();
  } catch (e) {
    document.getElementById('experimentsTable').innerHTML = '<div class="empty-state"><div class="icon">⚠</div>Failed to load experiments</div>';
  }
}

function renderExperiments() {
  const container = document.getElementById('experimentsTable');
  if (!experiments.length) {
    container.innerHTML = '<div class="empty-state"><div class="icon">🧪</div>No experiments</div>';
    return;
  }
  container.innerHTML = `<table>
    <thead><tr><th>Name</th><th>Status</th><th>Variants</th><th>Traffic</th><th>Started</th><th>Results</th></tr></thead>
    <tbody>
      ${experiments.map(exp => {
        const variants = exp.variants || [];
        const variantInfo = variants.map(v => `${v.name}(${v.weight})`).join(' / ');
        const statusColor = exp.status === 'running' ? 'var(--green)' : exp.status === 'stopped' ? 'var(--yellow)' : 'var(--text-dim)';
        const results = exp.results;
        let resultInfo = '—';
        if (results) {
          const winner = results.winner;
          const significance = results.significance;
          resultInfo = winner ? `${winner} wins (p=${significance?.toFixed(3) || '—'})` : 'No winner yet';
        }
        return `<tr>
          <td><b>${exp.name || exp.experiment_id || '—'}</b></td>
          <td><span style="color:${statusColor};font-size:12px;font-weight:600">${exp.status || '—'}</span></td>
          <td style="font-size:12px">${variantInfo || '—'}</td>
          <td>${exp.traffic_split ? exp.traffic_split.join('/') : '—'}</td>
          <td style="font-size:11px;color:var(--text-dim)">${exp.started_at ? timeAgo(exp.started_at) : '—'}</td>
          <td style="font-size:11px">${resultInfo}</td>
        </tr>`;
      }).join('')}
    </tbody>
  </table>`;
}

// ─── Knowledge Graph ─────────────────────────────────────────────────────────
async function loadKnowledgeGraph() {
  try {
    const [nodesData, statsData] = await Promise.all([
      fetch(`${API_BASE}/kg/nodes?limit=100`).then(r => r.json()).catch(() => ({})),
      fetch(`${API_BASE}/kg/stats`).then(r => r.json()).catch(() => ({})),
    ]);
    kgNodes = nodesData.nodes || [];
    renderKnowledgeGraph(statsData);
  } catch (e) {
    document.getElementById('kgContent').innerHTML = '<div class="empty-state"><div class="icon">⚠</div>Failed to load knowledge graph</div>';
  }
}

function renderKnowledgeGraph(stats) {
  const container = document.getElementById('kgContent');
  const statsHtml = stats ? `
    <div class="stats-grid" style="margin-bottom:20px">
      <div class="stat-card"><div class="label">Nodes</div><div class="value">${stats.node_count ?? '—'}</div></div>
      <div class="stat-card"><div class="label">Relationships</div><div class="value">${stats.relationship_count ?? '—'}</div></div>
      <div class="stat-card"><div class="label">Labels</div><div class="value">${stats.label_count ?? '—'}</div></div>
    </div>
  ` : '';

  if (!kgNodes.length) {
    container.innerHTML = statsHtml + '<div class="empty-state"><div class="icon">🕸️</div>No knowledge graph nodes</div>';
    return;
  }

  // Group by label
  const byLabel = {};
  kgNodes.forEach(n => {
    const label = n.label || n.type || 'Unknown';
    if (!byLabel[label]) byLabel[label] = [];
    byLabel[label].push(n);
  });

  const labelSections = Object.entries(byLabel).map(([label, nodes]) => `
    <div class="section" style="margin-bottom:12px">
      <div class="section-header"><span class="section-title">${label} (${nodes.length})</span></div>
      <div class="section-body" style="padding:8px 12px">
        ${nodes.map(n => `<span style="display:inline-block;background:var(--surface2);padding:3px 10px;border-radius:12px;font-size:12px;margin:2px">${n.name || n.id || n.node_id || '—'}</span>`).join('')}
      </div>
    </div>
  `).join('');

  container.innerHTML = statsHtml + labelSections;
}

// ─── Notifications ──────────────────────────────────────────────────────────
async function loadNotifications() {
  try {
    const data = await fetch(`${API_BASE}/notifications/channels`).then(r => r.json()).catch(() => ({}));
    notifications = data.channels || data || [];
    renderNotifications();
  } catch (e) {
    document.getElementById('notificationsTable').innerHTML = '<div class="empty-state"><div class="icon">⚠</div>Failed to load notifications</div>';
  }
}

function renderNotifications() {
  const container = document.getElementById('notificationsTable');
  if (!notifications.length) {
    container.innerHTML = '<div class="empty-state"><div class="icon">🔔</div>No notification channels configured</div>';
    return;
  }
  container.innerHTML = `<table>
    <thead><tr><th>Channel</th><th>Type</th><th>Status</th><th>Config</th></tr></thead>
    <tbody>
      ${notifications.map(ch => {
        const enabled = ch.enabled !== false;
        const typeColor = { slack: '#4A154B', email: 'var(--blue)', webhook: 'var(--purple)', console: 'var(--green)' }[ch.type] || 'var(--text-dim)';
        return `<tr>
          <td><b>${ch.name || ch.channel_name || '—'}</b></td>
          <td><span style="color:${typeColor};font-weight:600;font-size:12px">${ch.type || '—'}</span></td>
          <td>${enabled ? '<span style="color:var(--green);font-size:12px">✓ Enabled</span>' : '<span style="color:var(--text-dim);font-size:12px">Disabled</span>'}</td>
          <td style="font-size:11px;color:var(--text-dim)">${ch.config ? JSON.stringify(ch.config).slice(0, 60) : '—'}</td>
        </tr>`;
      }).join('')}
    </tbody>
  </table>`;
}

// ─── Settings ──────────────────────────────────────────────────────────────
async function loadSettings() {
  // Load i18n locales
  try {
    const data = await fetch(`${API_BASE}/i18n/locales`).then(r => r.json()).catch(() => ({}));
    i18nLocales = data.locales || [];
    currentLocale = data.current_locale || 'en';
    renderSettings();
  } catch (e) {
    renderSettingsError();
  }

  // Load cache stats
  try {
    cacheStats = await fetch(`${API_BASE}/cache/stats`).then(r => r.json()).catch(() => ({}));
    renderCacheStats();
  } catch (e) {}
}

function renderSettings() {
  const localeOptions = i18nLocales.map(l =>
    `<option value="${l.code}" ${l.code === currentLocale ? 'selected' : ''}>${l.native_name || l.name} (${l.code})</option>`
  ).join('');

  document.getElementById('settingsContent').innerHTML = `
    <div class="section">
      <div class="section-header"><span class="section-title">Language / i18n</span></div>
      <div class="section-body">
        <div style="display:flex;gap:12px;align-items:center">
          <select class="filter-select" id="localeSelect" onchange="changeLocale(this.value)" style="padding:6px 12px;font-size:13px">
            ${localeOptions}
          </select>
          <button onclick="loadSettings()" style="background:var(--surface2);border:1px solid var(--border);color:var(--text);padding:6px 12px;border-radius:6px;cursor:pointer;font-size:12px">Refresh</button>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-header"><span class="section-title">System Info</span></div>
      <div class="section-body">
        <table style="font-size:13px">
          <tr><td style="color:var(--text-dim);padding:6px 12px 6px 0">Project</td><td><b>hermes-agent-collab</b></td></tr>
          <tr><td style="color:var(--text-dim);padding:6px 12px 6px 0">Branch</td><td><code>gh-pages</code></td></tr>
          <tr><td style="color:var(--text-dim);padding:6px 12px 6px 0">API Base</td><td><code>${API_BASE}</code></td></tr>
        </table>
      </div>
    </div>

    <div class="section">
      <div class="section-header"><span class="section-title">Cache Backend</span></div>
      <div class="section-body" id="cacheStatsBody">
        <div style="color:var(--text-dim);font-size:13px">Loading cache stats…</div>
      </div>
    </div>
  `;

  renderCacheStats();
}

function renderCacheStats() {
  const body = document.getElementById('cacheStatsBody');
  if (!body) return;
  if (Object.keys(cacheStats).length === 0) {
    body.innerHTML = '<div style="color:var(--text-dim);font-size:13px">Cache stats unavailable (Redis may not be connected)</div>';
    return;
  }
  body.innerHTML = `<table style="font-size:13px">
    <tr><td style="color:var(--text-dim);padding:6px 12px 6px 0">Backend</td><td><b>${cacheStats.backend || '—'}</b></td></tr>
    <tr><td style="color:var(--text-dim);padding:6px 12px 6px 0">Connected</td><td>${cacheStats.connected ? '<span style="color:var(--green)">✓ Yes</span>' : '<span style="color:var(--red)">✗ No</span>'}</td></tr>
    <tr><td style="color:var(--text-dim);padding:6px 12px 6px 0">Redis URL</td><td><code style="font-size:11px">${cacheStats.redis_url || '—'}</code></td></tr>
  </table>`;
}

function renderSettingsError() {
  document.getElementById('settingsContent').innerHTML = '<div class="empty-state"><div class="icon">⚠</div>Failed to load settings</div>';
}

async function changeLocale(locale) {
  try {
    await fetch(`${API_BASE}/i18n/locales/${locale}`, { method: 'PUT' });
    currentLocale = locale;
  } catch (e) {
    alert('Failed to change locale');
  }
}

// ─── Utilities ──────────────────────────────────────────────────────────────
function timeAgo(ts) {
  if (!ts) return '—';
  const diff = Date.now() - new Date(ts).getTime();
  if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`;
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  return `${Math.floor(diff / 3600000)}h ago`;
}

function fmtTime(ts) {
  if (!ts) return '—';
  return new Date(ts).toLocaleTimeString();
}
