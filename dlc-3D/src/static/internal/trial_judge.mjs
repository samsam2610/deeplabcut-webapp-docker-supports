// Human markers on a trial strip, and the candidate-judging parameters.
//
// Pure: no DOM, no fetch. The card's drawing code calls these so they can be
// tested, which is the whole reason they are not inline in the card.
//
// The clamp mirrors sam-training/src/judging.py exactly. Both sides clamp
// rather than reject so the panel can never display a value the backend
// silently replaced.

export const DEFAULT_JUDGE = {
  threshold: 0.55,      // per-camera NCC a match must reach
  min_run: 6,           // samples a state flip must persist (debounce)
  lookback: 3000,       // how far a window reaches back from its marker
  min_candidates: 30,   // armed frames below which a trial is skipped
  guard: 0,             // frames a window may reach past the PREVIOUS marker
  max_3d_dist: 2.0,     // how far the triangulated match may sit from the pellet
  max_epi_px: 15.0,     // how far off the epipolar line the cam1 paw may sit
};

const OUTCOMES = ["s", "f"];
const ONSET_TAGS = ["start-success", "start-failure"];

// Exact matching, as the backend does: `start-failure` must never pick up
// `start-failure-candidate`, which is our proposal and not a human's mark.
export function isHumanMarker(note) {
  const n = String(note ?? "").trim();
  return OUTCOMES.includes(n) || ONSET_TAGS.includes(n);
}

export function markerStyle(note) {
  const n = String(note ?? "").trim();
  if (n === "s" || n === "start-success") return { colour: "#4ade80", label: n };
  if (n === "f" || n === "start-failure") return { colour: "#ff4d4d", label: n };
  return { colour: "#98a1b0", label: n };
}

function sorted(markers) {
  return (markers || []).slice().sort((a, b) => a.frame - b.frame);
}

// Every human marker the strip should draw, the closing one included.
export function markersInSpan(markers, start, end) {
  return sorted(markers).filter((m) => m.frame >= start && m.frame <= end);
}

// Markers strictly INSIDE the span. With guard = 0 this is always empty; any
// entry means the window spans a nearer marker, so some of its candidates
// belong to an earlier trial and would take this trial's outcome as their
// label. That is the trial #11 bug, and it must be visible on the strip.
export function intervening(markers, start, end) {
  return sorted(markers).filter((m) => m.frame >= start && m.frame < end);
}

// ── judging parameters ──────────────────────────────────────────────────────

// A blank or unparsable field means "leave it alone". Coercing "" to 0 would
// set a threshold of 0 (everything is a pellet) from a cleared input.
function num(raw, fallback) {
  if (raw === null || raw === undefined) return fallback;
  if (typeof raw === "string" && raw.trim() === "") return fallback;
  const v = Number(raw);
  return Number.isFinite(v) ? v : fallback;
}

const int = (raw, fallback) => Math.trunc(num(raw, fallback));
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

export function clampJudge(raw) {
  const d = raw || {};
  const lookback = Math.max(1, int(d.lookback, DEFAULT_JUDGE.lookback));
  return {
    threshold: clamp(num(d.threshold, DEFAULT_JUDGE.threshold), 0, 1),
    min_run: Math.max(1, int(d.min_run, DEFAULT_JUDGE.min_run)),
    lookback,
    min_candidates: Math.max(0, int(d.min_candidates, DEFAULT_JUDGE.min_candidates)),
    // A distance in calibration units, not a frame count: real pellets measure
    // <= 1.03, so truncating to an integer would make the gate untunable.
    max_3d_dist: Math.max(0, num(d.max_3d_dist, DEFAULT_JUDGE.max_3d_dist)),
    max_epi_px: Math.max(0, num(d.max_epi_px, DEFAULT_JUDGE.max_epi_px)),
    // Reaching further back than the window opens is not a describable state.
    guard: Math.min(lookback, Math.max(0, int(d.guard, DEFAULT_JUDGE.guard))),
  };
}
