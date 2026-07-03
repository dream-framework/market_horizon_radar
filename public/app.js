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
    metric('raw pressure', pctSoft(s.raw_probability), 'ungated formula only'),
    metric('dust', num(raw.dust_cloud), 'reactive compression'),
    metric('decay', num(raw.defensive_decay), 'continuation weakness'),
    metric('reach', num(raw.ridge_reach), 'forward optionality'),
    metric('geo', num(raw.geo_vector), 'exogenous pressure'),
    metric('macro', num(raw.macro_vector), 'context pressure'),
    metric('sync', num(raw.sync), `${raw.sync_evidence_count ?? 0} sync rows`),
    metric('evidence', `${raw.evidence_count ?? 0}`, `${raw.corporate_deformation_count ?? 0} corp rows`),
    metric('confidence', pctSoft(s.confidence), `${s.history_points ?? 0} history rows`),
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
  if (!rows.length) {
    el.innerHTML = '<div class="empty">No history yet. The hourly workflow will populate this.</div>';
    return;
  }
  const w = 720, h = 210, pad = 28;
  const prepared = series.map((s, sidx) => {
    const points = rows.map((r, i) => {
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
  const x = i => pad + (i / Math.max(1, rows.length - 1)) * (w - pad * 2);
  const yVal = v => h - pad - ((v - min) / (max - min)) * (h - pad * 2);
  let paths = '';
  prepared.forEach(s => {
    const cls = s.sidx === 0 ? 'line' : (s.sidx === 1 ? 'line2' : 'line3');
    if (s.points.length) {
      paths += `<path class="${cls}" d="${linePath(s.points, p => x(p.i), p => yVal(p.v))}"></path>`;
    }
  });
  const labels = prepared.map((s, idx) => `<text class="ticktext" x="${pad + idx * 145}" y="17">${esc(s.name)}</text>`).join('');
  el.innerHTML = `<svg viewBox="0 0 ${w} ${h}" role="img">
    <line class="axis" x1="${pad}" y1="${h-pad}" x2="${w-pad}" y2="${h-pad}"></line>
    <line class="axis" x1="${pad}" y1="${pad}" x2="${pad}" y2="${h-pad}"></line>
    ${labels}
    <text class="ticktext" x="${pad}" y="${h-7}">${esc(rows[0].generated_at_utc || '')}</text>
    <text class="ticktext" text-anchor="end" x="${w-pad}" y="${h-7}">${esc(rows[rows.length-1].generated_at_utc || '')}</text>
    ${paths}
  </svg>`;
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

async function main() {
  try {
    const snapshot = await getJson('data/snapshot.json');
    document.getElementById('stamp').textContent = 'generated ' + (snapshot.generated_at_utc || 'n/a');
    renderCards(snapshot);
    renderNarrative(snapshot);
    renderEvidence(snapshot);
    renderFeedStatus(snapshot);
    let history = [];
    try { history = parseHistory(await getText('data/history.jsonl')).slice(-240); } catch { history = []; }
    renderLineChart(document.getElementById('probChart'), history, [
      { name: 'gated p', get: r => r.probability },
      { name: 'raw pressure', get: r => r.raw_probability }
    ]);
    renderLineChart(document.getElementById('indexChart'), history, [
      { name: 'dust', get: r => r.raw_indices?.dust_cloud },
      { name: 'decay', get: r => r.raw_indices?.defensive_decay },
      { name: 'reach', get: r => r.raw_indices?.ridge_reach }
    ]);
  } catch (err) {
    document.getElementById('stamp').textContent = 'no live snapshot';
    document.querySelector('main').innerHTML = `<div class="empty">No live snapshot exists yet. Run the GitHub Action or run <code>python scripts/update_live.py</code>. Error: ${esc(err.message)}</div>`;
  }
}

main();
