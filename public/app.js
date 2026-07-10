async function getJson(url) {
  const r = await fetch(url + '?t=' + Date.now(), { cache: 'no-store' });
  if (!r.ok) throw new Error(url + ' returned ' + r.status);
  return await r.json();
}

async function getText(url) {
  const r = await fetch(url + '?t=' + Date.now(), { cache: 'no-store' });
  if (!r.ok) throw new Error(url + ' returned ' + r.status);
  return await r.text();
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}

function pct(x) {
  if (x === null || x === undefined || Number.isNaN(Number(x))) return 'not scored';
  return (Number(x) * 100).toFixed(1) + '%';
}

function pctSoft(x) {
  if (x === null || x === undefined || Number.isNaN(Number(x))) return 'n/a';
  return (Number(x) * 100).toFixed(1) + '%';
}

function num(x) {
  if (x === null || x === undefined || Number.isNaN(Number(x))) return 'n/a';
  return Number(x).toFixed(2);
}

function metric(label, value, sub, cls) {
  return `<div class="metric ${esc(cls || '')}"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="sub">${esc(sub)}</div></div>`;
}

function gateSummary(score) {
  const reasons = score.gate_reasons || [];
  if (!reasons.length) return 'open';
  return reasons.length + ' gate' + (reasons.length === 1 ? '' : 's');
}

function renderCards(snapshot) {
  const s = snapshot.score || {};
  const raw = s.raw_indices || {};
  const phaseClass = s.phase === 'WARMUP' ? 'warnmetric' : '';
  const probabilityLabel = s.probability == null ? 'not scored' : pct(s.probability);
  const html = [
    metric('phase', `${s.phase || 'n/a'}`, `${s.phase_label || ''}`, phaseClass),
    metric('gated p', probabilityLabel, s.baseline_status || 'n/a', s.probability == null ? 'warnmetric' : ''),
    metric('raw pressure', s.raw_probability == null ? 'suppressed' : pctSoft(s.raw_probability), s.raw_probability_probe == null ? 'ungated formula only' : ('probe ' + pctSoft(s.raw_probability_probe))),
    metric('dust', num(raw.dust_cloud), 'reactive compression'),
    metric('decay', num(raw.defensive_decay), 'continuation weakness'),
    metric('reach', num(raw.ridge_reach), 'forward optionality'),
    metric('geo', num(raw.geo_vector), 'exogenous pressure'),
    metric('macro', num(raw.macro_vector), 'context pressure'),
    metric('sync', num(raw.sync), `${raw.sync_evidence_count ?? 0} sync rows`),
    metric('evidence', `${raw.evidence_count ?? 0}`, `${raw.corporate_deformation_count ?? 0} corp rows`),
    metric('confidence', pctSoft(s.confidence), `${s.history_rows_available ?? s.history_points ?? 0} history rows`),
    metric('gate', gateSummary(s), (s.gate_reasons || [])[0] || 'score eligible')
  ].join('');
  document.getElementById('cards').innerHTML = html;
}

function renderNarrative(snapshot) {
  const n = snapshot.narrative || {};
  const english = (n.english || []).map(x => `<p>${esc(x)}</p>`).join('');
  document.getElementById('narrative').innerHTML = english || '<div class="empty">No live narrative generated.</div>';
  const math = n.math || {};
  document.getElementById('math').textContent = [
    math.formula || '',
    '',
    'z_indices = ' + JSON.stringify(math.z_indices || {}, null, 2),
    'raw_indices = ' + JSON.stringify(math.raw_indices || {}, null, 2),
    '',
    math.interpretation || ''
  ].join('\n');
}

function parseHistory(text) {
  return text.split('\n').filter(x => x.trim()).map(x => {
    try { return JSON.parse(x); } catch { return null; }
  }).filter(Boolean);
}

function linePath(points, getX, getY) {
  return points.map((p, i) => `${i === 0 ? 'M' : 'L'}${getX(p).toFixed(1)},${getY(p).toFixed(1)}`).join(' ');
}

function renderLineChart(el, rows, series) {
  const cleanRows = rows.filter(r => r && r.generated_at_utc);
  if (!cleanRows.length) {
    el.innerHTML = '<div class="empty">No history yet. The hourly workflow will populate this.</div>';
    return;
  }
  const w = 720, h = 210, pad = 28;
  const prepared = series.map((s, sidx) => {
    const points = cleanRows.map((r, i) => {
      const v = Number(s.get(r));
      return Number.isFinite(v) ? { i, v } : null;
    }).filter(Boolean);
    return { ...s, sidx, points };
  });
  const vals = prepared.flatMap(s => s.points.map(p => p.v));
  if (!vals.length) {
    el.innerHTML = '<div class="empty">No numeric history yet.</div>';
    return;
  }
  let min = Math.min(...vals), max = Math.max(...vals);
  if (Math.abs(max - min) < 1e-9) { max += 1; min -= 1; }
  const x = i => pad + (i / Math.max(1, cleanRows.length - 1)) * (w - pad * 2);
  const yVal = v => h - pad - ((v - min) / (max - min)) * (h - pad * 2);
  let shapes = '';
  prepared.forEach(s => {
    const cls = s.sidx === 0 ? 'line' : (s.sidx === 1 ? 'line2' : 'line3');
    if (s.points.length >= 2) {
      shapes += `<path class="${cls}" d="${linePath(s.points, p => x(p.i), p => yVal(p.v))}"></path>`;
    }
    shapes += s.points.map(p => `<circle class="${cls} point" cx="${x(p.i).toFixed(1)}" cy="${yVal(p.v).toFixed(1)}" r="3.2"></circle>`).join('');
  });
  const labels = prepared.map((s, idx) => `<text class="ticktext" x="${pad + idx * 145}" y="17">${esc(s.name)}</text>`).join('');
  el.innerHTML = `<svg viewBox="0 0 ${w} ${h}" role="img">
    <line class="axis" x1="${pad}" y1="${h-pad}" x2="${w-pad}" y2="${h-pad}"></line>
    <line class="axis" x1="${pad}" y1="${pad}" x2="${pad}" y2="${h-pad}"></line>
    ${labels}
    <text class="ticktext" x="${pad}" y="${h-7}">${esc(cleanRows[0].generated_at_utc || '')}</text>
    <text class="ticktext" text-anchor="end" x="${w-pad}" y="${h-7}">${esc(cleanRows[cleanRows.length-1].generated_at_utc || '')}</text>
    ${shapes}
  </svg>`;
}

function snapshotAsHistoryRow(snapshot) {
  const s = snapshot.score || {};
  return {
    generated_at_utc: snapshot.generated_at_utc,
    probability: s.probability,
    raw_probability: s.raw_probability,
    raw_probability_probe: s.raw_probability_probe,
    phase: s.phase,
    phase_label: s.phase_label,
    confidence: s.confidence,
    baseline_status: s.baseline_status,
    raw_indices: s.raw_indices || {},
    z_indices: s.z_indices || {},
    evidence_count: snapshot.source_counts?.evidence_total ?? s.raw_indices?.evidence_count
  };
}

function renderEvidence(snapshot) {
  const body = document.querySelector('#evidenceTable tbody');
  const rows = snapshot.top_evidence || [];
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="5" class="empty">No live evidence rows collected.</td></tr>';
    return;
  }
  body.innerHTML = rows.map(ev => {
    const classes = (ev.classes || []).map(c => `<span class="badge">${esc(c)}</span>`).join('');
    return `<tr>
      <td>${esc(ev.event_time_utc || '')}</td>
      <td>${classes}</td>
      <td>${esc(ev.entity || '')}</td>
      <td><a href="${esc(ev.url)}" target="_blank" rel="noreferrer">${esc(ev.title || '')}</a><div class="sub">${esc(ev.summary || '')}</div></td>
      <td>${esc(ev.source_type || '')}<div class="sub">${esc(ev.source || '')}</div></td>
    </tr>`;
  }).join('');
}

function renderFeedStatus(snapshot) {
  const rows = snapshot.feed_status || [];
  document.getElementById('feedStatus').innerHTML = rows.map(r => {
    const status = r.ok ? '<span class="ok">OK</span>' : '<span class="fail">FAIL/SKIP</span>';
    return `<div class="feeditem">${status}<b>${esc(r.source || '')}</b><small>${esc(JSON.stringify(r))}</small></div>`;
  }).join('') || '<div class="empty">No feed status available.</div>';
}

// ── Live update state ──────────────────────────────────────────────
// Tracks the last snapshot timestamp we've rendered.
// When the hourly GitHub Action commits new data, the timestamp
// changes and we silently re-render everything.
let lastSeenTimestamp = null;
let isRendering = false;

async function renderAll(snapshot) {
  document.getElementById('stamp').textContent = 'generated ' + (snapshot.generated_at_utc || 'n/a');
  renderCards(snapshot);
  renderNarrative(snapshot);
  renderEvidence(snapshot);
  renderFeedStatus(snapshot);
  let history = [];
  try { history = parseHistory(await getText('data/history.jsonl')).slice(-240); } catch { history = []; }
  if (!history.length && snapshot.generated_at_utc) history = [snapshotAsHistoryRow(snapshot)];
  renderLineChart(document.getElementById('probChart'), history, [
    { name: 'gated p', get: r => r.probability },
    { name: 'raw/probe', get: r => r.raw_probability ?? r.raw_probability_probe }
  ]);
  renderLineChart(document.getElementById('indexChart'), history, [
    { name: 'dust', get: r => r.raw_indices?.dust_cloud },
    { name: 'decay', get: r => r.raw_indices?.defensive_decay },
    { name: 'reach', get: r => r.raw_indices?.ridge_reach }
  ]);
}

async function checkForUpdate() {
  // Prevent overlapping renders if a poll fires while a previous
  // render is still in flight.
  if (isRendering) return;
  isRendering = true;
  try {
    const resp = await fetch('data/snapshot.json?t=' + Date.now(), { cache: 'no-store' });
    if (!resp.ok) return;
    const snapshot = await resp.json();
    const ts = snapshot.generated_at_utc;
    // Only re-render if the timestamp actually changed (new data from Action).
    if (ts && ts !== lastSeenTimestamp) {
      lastSeenTimestamp = ts;
      await renderAll(snapshot);
    }
  } catch {
    // Snapshot not available yet (404 or network error) — silently retry next cycle.
  } finally {
    isRendering = false;
  }
}

// ── Boot ───────────────────────────────────────────────────────────
// Initial render: fetches snapshot.json and renders everything.
// If snapshot doesn't exist yet, shows the error message.
async function init() {
  try {
    const snapshot = await getJson('data/snapshot.json');
    lastSeenTimestamp = snapshot.generated_at_utc;
    await renderAll(snapshot);
  } catch (err) {
    document.getElementById('stamp').textContent = 'no live snapshot';
    document.querySelector('main').innerHTML = `<div class="empty">No live snapshot exists yet. Run the GitHub Action or run <code>python scripts/update_live.py</code>. Error: ${esc(err.message)}</div>`;
  }
}

// Start initial render immediately.
init();

// Poll every 5 minutes for fresh data.
// The GitHub Action runs hourly at minute 7; 5-min polling ensures
// new data appears within ~5 minutes of commit — no page reload needed.
setInterval(checkForUpdate, 5 * 60 * 1000);
