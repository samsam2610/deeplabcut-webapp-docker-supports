// How a trial reads in the dropdown, and which outcome the Add button offers.
//
// Tag state is DERIVED from the companion CSV on every load, never stored: the
// tag can be placed, moved or removed in the main webapp, and a cached answer
// would quietly disagree with the file the user is looking at.

/** Text for one <option>. */
export function trialLabel(t, i) {
  const truth = t.onset == null ? "orphan" : `tag ${t.onset}`;
  let line = `#${i + 1}  ${t.outcome}  [${t.start}–${t.end}]  `
    + `${t.n_candidates} cand  ${truth}`;
  if (t.result) {
    line += `  ·  pick ${t.result.pick}`;
    // A result scored under different judging parameters is shown, not hidden
    // and not discarded — an hour of batch scoring is worth more than a clean
    // rule about staleness.
    if (t.result.stale) line += " (stale)";
  }
  const tag = t.tag;
  if (tag && tag.kind === "human") line += `  ✓ ${tag.note} @${tag.frame}`;
  else if (tag && tag.kind === "candidate") line += `  ~ ${tag.note} @${tag.frame}`;
  return line;
}

/** Which of success/failure the Add control should start on. */
export function defaultOutcome(t) {
  // The trial's own marker: the label is READ from the human s/f, never
  // predicted. The user can still flip it — they are looking at the frame.
  return t && t.outcome === "f" ? "f" : "s";
}

/** The note that would be written for a reviewed single-trial add. */
export function tagNote(outcome) {
  return outcome === "f" ? "start-failure" : "start-success";
}

/** Trials with a stored result — what "add all as candidates" would write. */
export function writableTrials(list, includeTagged = false) {
  return (list || []).filter((t) => t.result
    && !(t.tag && t.tag.kind === "human" && !includeTagged));
}

/**
 * What the thumbnail strips should show for a trial.
 *
 * Always `{clear: true, …}`: every trial change empties BOTH strips first.
 * Clearing only the 2D one left the previous trial's paired thumbnails on
 * screen while browsing, which is indistinguishable from the new trial having
 * those candidates.
 *
 * `render` is null when the trial has no stored result — nothing to draw, and
 * drawing the last run's frames would be a lie about this trial.
 */
export function candidateStrips(trial) {
  const r = trial && trial.result;
  const top = (r && r.top) || [];
  const strip = r && r.mode === "3d" ? "pairs" : "single";
  if (top.length) return { clear: true, render: strip, top, partial: false };
  // Stored before the ranking was kept: the pick is still knowable, so show
  // that rather than nothing. Flagged partial so the panel can say the ranking
  // is missing instead of implying one thumbnail was the whole result.
  if (r && r.pick != null) {
    return { clear: true, render: strip, top: [r.pick], partial: true };
  }
  return { clear: true, render: null, top: [], partial: false };
}

/**
 * Index of the trial whose window contains `frame`, or -1.
 *
 * Windows do not overlap once `past prev marker` is 0, but they can when it is
 * raised, so the FIRST match wins — deterministic, and the earlier trial is the
 * one whose marker follows the frame soonest.
 */
export function trialContaining(list, frame) {
  const f = Number(frame);
  if (!Number.isFinite(f)) return -1;
  return (list || []).findIndex((t) => t && f >= t.start && f <= t.end);
}

/**
 * Should the panel follow the playhead to another trial?
 *
 * Governed by an explicit lock, off by default. Locked, ANY cursor movement
 * follows — note navigation, scrubbing, playback alike; unlocked, nothing
 * moves on its own.
 *
 * The first attempt at this followed only when the playhead landed exactly on a
 * note, inferring the user's intent from where they stopped. It did not work,
 * and it could not be predicted from the outside: the same drag either moved
 * the trial or did not, depending on what happened to be under the cursor at
 * the end. A switch the user owns beats a heuristic that guesses.
 *
 * -1 means "stay": unlocked, no containing trial, or already there. The caller
 * does nothing on -1 — silent, as asked.
 */
export function followTarget(list, locked, frame, currentIndex) {
  if (!locked) return -1;
  const idx = trialContaining(list, frame);
  return idx === currentIndex ? -1 : idx;
}
