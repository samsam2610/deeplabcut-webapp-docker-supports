/* sam-training debug panel.
 *
 * Layers are rendered from whatever /api/layers returns, keyed on `kind`
 * (box | mask | scalar). Stage 2 and 3 do not exist yet; when they do they add
 * layers to that payload and appear here with no change to this file.
 */
'use strict';

const PREFIX = '/sam-training';
const $ = (id) => document.getElementById(id);

const state = {
  video: null,
  nFrames: 0,
  frame: 0,
  sweep: null,
  layersOn: {},          // layer name -> bool
  img: new Image(),
  layers: [],
};

/* ── video list ─────────────────────────────────────────────────────── */

async function loadVideos() {
  const list = $('st-video-list');
  list.innerHTML = '<p class="empty">Loading…</p>';
  let data;
  try {
    data = await (await fetch(`${PREFIX}/api/videos`)).json();
  } catch (e) {
    list.innerHTML = `<p class="empty">Could not load videos: ${e}</p>`;
    return;
  }
  $('st-project').textContent = data.project || '';
  if (!data.videos || !data.videos.length) {
    list.innerHTML = '<p class="empty">No tracked videos.</p>';
    return;
  }
  list.innerHTML = '';
  data.videos.forEach((v) => {
    const row = document.createElement('div');
    row.className = 'vid';
    row.dataset.path = v.path;
    row.innerHTML = `
      <span class="vid-name" title="${v.path}">${v.name}</span>
      <span class="tag ${v.is_training ? 'done' : 'pending'}">${v.tag}</span>
      <span class="counts">${v.n_onsets} onsets · ${v.n_outcomes} s/f · ${v.n_orphans} orphan</span>`;
    row.onclick = () => selectVideo(v, row);
    list.appendChild(row);
  });
}

function selectVideo(v, row) {
  document.querySelectorAll('.vid').forEach((r) => r.classList.remove('sel'));
  row.classList.add('sel');
  state.video = v.path;
  state.sweep = null;
  state.frame = 0;
  $('st-calibrate').disabled = false;
  $('st-sweep').disabled = false;
  $('st-calib-note').textContent = 'not calibrated';
  $('st-sweep-note').textContent = 'not swept';
  $('st-acceptance').textContent = '';
  drawTimeline();
  showFrame(0);
}

/* ── stage 0 ────────────────────────────────────────────────────────── */

async function calibrate() {
  $('st-calibrate').disabled = true;
  $('st-calib-note').textContent = 'calibrating…';
  try {
    const r = await fetch(`${PREFIX}/api/calibrate`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video: state.video }),
    });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    $('st-calib-note').textContent =
      `template from frame ${d.template_frame} · p75 match ${d.score} · ${d.n_sampled} sampled`;
    showFrame(d.template_frame);
  } catch (e) {
    $('st-calib-note').textContent = `failed: ${e.message}`;
  } finally {
    $('st-calibrate').disabled = false;
  }
}

/* ── stage 1 ────────────────────────────────────────────────────────── */

async function sweep() {
  $('st-sweep').disabled = true;
  $('st-sweep-note').textContent = 'starting…';
  const r = await fetch(`${PREFIX}/api/sweep`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ video: state.video }),
  });
  const d = await r.json();
  if (d.error) {
    $('st-sweep-note').textContent = `failed: ${d.error}`;
    $('st-sweep').disabled = false;
    return;
  }
  if (d.state === 'done') { applySweep(d); return; }
  pollJob(d.job);
}

async function pollJob(jobId) {
  const bar = $('st-sweep-progress');
  bar.classList.remove('hidden');
  const tick = async () => {
    const j = await (await fetch(`${PREFIX}/api/job/${jobId}`)).json();
    bar.firstElementChild.style.width = `${Math.round((j.progress || 0) * 100)}%`;
    $('st-sweep-note').textContent =
      `sweeping… ${Math.round((j.progress || 0) * 100)}%`;
    if (j.state === 'running') { setTimeout(tick, 1500); return; }
    bar.classList.add('hidden');
    if (j.state === 'error') {
      $('st-sweep-note').textContent = `failed: ${j.message}`;
      $('st-sweep').disabled = false;
      return;
    }
    const d = await (await fetch(`${PREFIX}/api/sweep`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video: state.video }),
    })).json();
    applySweep(d);
  };
  tick();
}

function applySweep(d) {
  state.sweep = d;
  state.nFrames = d.n_frames;
  $('st-sweep').disabled = false;
  $('st-sweep-note').textContent =
    `${d.n_frames} frames · ${d.armed.length} armed intervals · ${d.windows.length} windows`;
  const a = d.acceptance || {};
  if (a.known) {
    const pct = (100 * a.onset_is_candidate / a.known).toFixed(1);
    $('st-acceptance').innerHTML =
      `onset is a candidate frame: <b>${a.onset_is_candidate}/${a.known}</b> (${pct}%) ` +
      `— anything stage 1 drops, stages 2–3 cannot recover`;
  }
  drawTimeline();
}

/* ── timeline ───────────────────────────────────────────────────────── */

function drawTimeline() {
  const cv = $('st-timeline');
  const w = cv.clientWidth || 900;
  if (cv.width !== w) cv.width = w;
  const h = cv.height;
  const g = cv.getContext('2d');
  g.clearRect(0, 0, w, h);
  g.fillStyle = '#1b1e24'; g.fillRect(0, 0, w, h);

  const d = state.sweep;
  if (!d) {
    g.fillStyle = '#98a1b0'; g.font = '12px system-ui';
    g.fillText('Sweep a video to see the pellet trace, armed intervals and windows.', 12, h / 2);
    return;
  }
  const N = d.n_frames || 1;
  const x = (f) => (f / N) * w;

  // search windows behind everything
  g.fillStyle = 'rgba(76,141,255,.20)';
  d.windows.forEach((win) => g.fillRect(x(win.start), 0, Math.max(1, x(win.end) - x(win.start)), h));

  // armed intervals
  g.fillStyle = 'rgba(102,156,53,.45)';
  d.armed.forEach((iv) => g.fillRect(x(iv.start), h - 26, Math.max(1, x(iv.end) - x(iv.start)), 26));

  // NCC trace
  const tr = d.trace;
  g.strokeStyle = '#8ec5ff'; g.lineWidth = 1; g.beginPath();
  for (let i = 0; i < tr.frames.length; i++) {
    const px = x(tr.frames[i]);
    const py = (h - 30) * (1 - Math.max(0, Math.min(1, tr.scores[i])));
    i ? g.lineTo(px, py) : g.moveTo(px, py);
  }
  g.stroke();

  // threshold
  const ty = (h - 30) * (1 - d.threshold);
  g.strokeStyle = 'rgba(255,255,255,.25)'; g.setLineDash([4, 4]);
  g.beginPath(); g.moveTo(0, ty); g.lineTo(w, ty); g.stroke(); g.setLineDash([]);

  // markers
  g.strokeStyle = '#ffd23b';
  d.outcomes.forEach((o) => { g.beginPath(); g.moveTo(x(o.frame), h - 26); g.lineTo(x(o.frame), h); g.stroke(); });
  g.strokeStyle = '#ff4d4d';
  d.onsets.forEach((o) => { g.beginPath(); g.moveTo(x(o.frame), 0); g.lineTo(x(o.frame), 14); g.stroke(); });

  // cursor
  g.strokeStyle = '#fff'; g.beginPath();
  g.moveTo(x(state.frame), 0); g.lineTo(x(state.frame), h); g.stroke();
}

$('st-timeline').addEventListener('click', (ev) => {
  if (!state.sweep) return;
  const r = ev.currentTarget.getBoundingClientRect();
  showFrame(Math.round(((ev.clientX - r.left) / r.width) * state.sweep.n_frames));
});

/* ── frame + layers ─────────────────────────────────────────────────── */

async function showFrame(n) {
  if (!state.video) return;
  state.frame = Math.max(0, n | 0);
  $('st-frame').value = state.frame;
  drawTimeline();

  state.img.onload = () => redraw();
  state.img.src = `${PREFIX}/api/frame?video=${encodeURIComponent(state.video)}&n=${state.frame}`;

  try {
    const d = await (await fetch(
      `${PREFIX}/api/layers?video=${encodeURIComponent(state.video)}&n=${state.frame}`)).json();
    if (d.error) {
      $('st-frame-note').textContent = d.error;
      state.layers = [];
    } else {
      state.layers = d.layers || [];
      $('st-frame-note').textContent = d.pellet_present ? 'pellet present' : 'pellet absent';
      $('st-pending').textContent = (d.pending || []).length
        ? `not yet wired: ${d.pending.join(', ')}` : '';
      buildToggles();
    }
  } catch (e) {
    $('st-frame-note').textContent = String(e);
  }
  redraw();
}

function buildToggles() {
  const box = $('st-layers');
  box.innerHTML = '';
  state.layers.filter((l) => l.kind !== 'scalar').forEach((l) => {
    if (!(l.name in state.layersOn)) state.layersOn[l.name] = true;
    const lab = document.createElement('label');
    lab.innerHTML = `<input type="checkbox" ${state.layersOn[l.name] ? 'checked' : ''}/>
      <span class="chip" style="background:${l.colour}"></span>${l.label || l.name}`;
    lab.querySelector('input').onchange = (e) => {
      state.layersOn[l.name] = e.target.checked; redraw();
    };
    box.appendChild(lab);
  });
}

function redraw() {
  const cv = $('st-canvas');
  const img = state.img;
  if (!img.naturalWidth) return;
  cv.width = img.naturalWidth; cv.height = img.naturalHeight;
  const g = cv.getContext('2d');
  g.drawImage(img, 0, 0);

  state.layers.forEach((l) => {
    if (l.kind === 'scalar' || state.layersOn[l.name] === false) return;
    if (l.kind === 'box') {
      g.strokeStyle = l.colour; g.lineWidth = 2;
      g.strokeRect(l.x, l.y, l.w, l.h);
      if (l.label) {
        g.fillStyle = l.colour; g.font = '13px ui-monospace, monospace';
        g.fillText(l.label, l.x + 3, Math.max(12, l.y - 4));
      }
    } else if (l.kind === 'mask') {
      drawMask(g, l);
    }
  });

  const sc = state.layers.filter((l) => l.kind === 'scalar');
  $('st-scalars').innerHTML = sc.map((l) =>
    `<span><span class="k">${l.label || l.name}</span> ${l.value.toFixed(3)}</span>`).join('');
}

/* Run-length decode straight into an ImageData overlay — a paw-sized mask is a
 * few hundred runs, so this is cheaper than shipping a PNG per frame. */
function drawMask(g, l) {
  if (!l.rle || !l.w || !l.h) return;
  const im = g.createImageData(l.w, l.h);
  const [r, gg, b] = hexToRgb(l.colour);
  let pos = 0, on = false;
  for (const run of l.rle) {
    if (on) {
      for (let i = pos; i < pos + run; i++) {
        const o = i * 4;
        im.data[o] = r; im.data[o + 1] = gg; im.data[o + 2] = b; im.data[o + 3] = 110;
      }
    }
    pos += run; on = !on;
  }
  const tmp = document.createElement('canvas');
  tmp.width = l.w; tmp.height = l.h;
  tmp.getContext('2d').putImageData(im, 0, 0);
  g.drawImage(tmp, 0, 0, g.canvas.width, g.canvas.height);
}

function hexToRgb(hex) {
  const v = parseInt(hex.replace('#', ''), 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
}

/* ── wiring ─────────────────────────────────────────────────────────── */

$('st-refresh').onclick = loadVideos;
$('st-calibrate').onclick = calibrate;
$('st-sweep').onclick = sweep;
$('st-frame').onchange = (e) => showFrame(parseInt(e.target.value, 10) || 0);
document.querySelectorAll('[data-step]').forEach((b) => {
  b.onclick = () => showFrame(state.frame + parseInt(b.dataset.step, 10));
});
document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT') return;
  if (e.key === 'ArrowLeft')  showFrame(state.frame - (e.shiftKey ? 10 : 1));
  if (e.key === 'ArrowRight') showFrame(state.frame + (e.shiftKey ? 10 : 1));
});
window.addEventListener('resize', drawTimeline);

loadVideos();
drawTimeline();
