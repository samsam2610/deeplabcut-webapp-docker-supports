// Which panels a card shows, and in what order.
//
// Pure so it can be tested without a DOM, and so the one rule that matters is
// stated in one place: the DOM decides WHICH panels exist, a saved order only
// decides their SEQUENCE. Let a saved list decide membership and a panel
// shipped after the user last dragged something disappears for them.

export function applyOrder(domIds, savedOrder) {
  const present = (domIds || []).filter((id) => typeof id === "string");
  const known = new Set(present);
  const seen = new Set();
  const out = [];
  for (const id of savedOrder || []) {
    if (known.has(id) && !seen.has(id)) {
      seen.add(id);
      out.push(id);
    }
  }
  for (const id of present) {
    if (!seen.has(id)) {
      seen.add(id);
      out.push(id);
    }
  }
  return out;
}

/** Move `movedId` before `beforeId`; a null target means the end. */
export function reorder(ids, movedId, beforeId) {
  const all = (ids || []).slice();
  if (!all.includes(movedId)) return all;
  if (beforeId === movedId) return all;
  const rest = all.filter((id) => id !== movedId);
  const at = beforeId == null ? -1 : rest.indexOf(beforeId);
  if (at < 0) {
    rest.push(movedId);
    return rest;
  }
  rest.splice(at, 0, movedId);
  return rest;
}

/** Sequence equality — lets the caller skip a pointless save. */
export function sameOrder(a, b) {
  const x = a || [];
  const y = b || [];
  return x.length === y.length && x.every((v, i) => v === y[i]);
}

/**
 * Where a drop lands: the id to insert before, or null for the end.
 *
 * `low` is true when the pointer was in the lower half of the target, which is
 * the only gesture that reaches the end of the list. Returns:
 *   - a string id — insert the moved panel immediately before that id;
 *   - null — append the moved panel to the end;
 *   - undefined — a no-op: the drop would leave the panel exactly where it
 *     already sits (including when `movedId` is not present in `ids`), so the
 *     caller can skip the move. Without this, `reorder` would either take the
 *     moved id as its own target and send it to the bottom, or perform a save
 *     that changes nothing.
 * A two-way `null` overload (end-of-list vs. no-op) would be ambiguous, which
 * is why "no-op" is `undefined` rather than `null`.
 */
export function dropTarget(ids, movedId, targetId, low) {
  const all = (ids || []).slice();
  if (!all.includes(movedId)) return undefined;
  const at = all.indexOf(targetId);
  if (at < 0) return undefined;
  const before = low ? (all[at + 1] ?? null) : targetId;
  if (before === movedId) return undefined;
  const next = reorder(all, movedId, before);
  if (sameOrder(next, all)) return undefined;
  return before;
}
