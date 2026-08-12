// A one-at-a-time lock over the panel's run buttons.
//
// Reported 2026-08-12: the first click on "Run SAM + DINO 3D" seemed to do
// nothing, so it was clicked again — and BOTH jobs ran. Two POSTs seven seconds
// apart, 22 polls each, competing for the same GPU, and whichever finished last
// overwrote the other's result on screen.
//
// The lock covers BOTH run buttons, not each separately: 2D and 3D score the
// same window into the same state, so running them concurrently is the same
// bug wearing a different hat.

/** Take the lock, disabling every button. False when a run is already going. */
export function tryAcquire(buttons) {
  const list = (buttons || []).filter(Boolean);
  if (!list.length) return true;          // nothing to guard; never block a run
  if (list.some((b) => b.disabled)) return false;
  list.forEach((b) => { b.disabled = true; });
  return true;
}

/** Always call this, including on failure — a stuck lock bricks the panel. */
export function release(buttons) {
  (buttons || []).filter(Boolean).forEach((b) => { b.disabled = false; });
}
