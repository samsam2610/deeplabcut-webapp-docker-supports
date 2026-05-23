// Pure CSV status/note logic shared by the StatusNoteTimeline feature.
// Operates purely in CSV frame_number space; no DOM, no fetch.
// Status value "0" and empty values are treated as "no annotation".

export function uniqueValues(rows, field) {
  const out = [];
  const seen = new Set();
  for (const r of rows) {
    const v = r[field];
    if (!v) continue;
    if (field === "frame_line_status" && v === "0") continue;
    if (!seen.has(v)) { seen.add(v); out.push(v); }
  }
  return out;
}

export function assignColors(values, palette) {
  const map = {};
  values.forEach((v, i) => { map[v] = palette[i % palette.length]; });
  return map;
}

// Nearest frame_number strictly in `dir` from `fromFrame` whose `field` value is in
// `active` (a Set or array; status "0"/empty excluded). Returns the frame_number or null.
export function findMatchingFrame(rows, field, active, fromFrame, dir) {
  const set = active instanceof Set ? active : new Set(active);
  if (!set.size) return null;
  const frames = rows
    .filter((r) => {
      const v = r[field];
      return v && !(field === "frame_line_status" && v === "0") && set.has(v);
    })
    .map((r) => Number(r.frame_number))
    .sort((a, b) => a - b);
  if (dir < 0) {
    let prev = null;
    for (const f of frames) { if (f < fromFrame) prev = f; else break; }
    return prev;
  }
  for (const f of frames) { if (f > fromFrame) return f; }
  return null;
}

export function rowForFrame(rows, frameNumber) {
  return rows.find((r) => Number(r.frame_number) === frameNumber) || null;
}

export function isInterestingAnnotation(note, status) {
  return Boolean(note) || Boolean(status && status !== "0");
}

// Return a NEW rows array with savedRow updated/inserted (sorted) when interesting,
// or the row at that frame removed when not. Never mutates the input.
export function applySavedRow(rows, savedRow, isInteresting) {
  const fn = Number(savedRow.frame_number);
  const idx = rows.findIndex((r) => Number(r.frame_number) === fn);
  const next = rows.slice();
  if (isInteresting) {
    if (idx >= 0) next[idx] = savedRow;
    else { next.push(savedRow); next.sort((a, b) => Number(a.frame_number) - Number(b.frame_number)); }
  } else if (idx >= 0) {
    next.splice(idx, 1);
  }
  return next;
}

export function buildSaveRowPayload({ csvPath, frameNumber, note, status, fps }) {
  return { csv_path: csvPath, frame_number: frameNumber, note, frame_line_status: status, fps };
}
