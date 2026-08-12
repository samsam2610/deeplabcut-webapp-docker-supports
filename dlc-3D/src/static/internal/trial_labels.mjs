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
