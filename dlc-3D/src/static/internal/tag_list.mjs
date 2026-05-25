// Pure tag-list reducer for the inline-3D quick-tags (postfix/status/note). DOM-free.
// add: append a trimmed, deduped (exact-match), non-empty tag. remove: drop the
// exact value. Both return a NEW array and never mutate the input. A non-array
// base coerces to [] so callers can pass an unparsed/absent setting straight in.

const asList = (xs) => (Array.isArray(xs) ? xs : []);

export function addTag(tags, raw) {
  const list = asList(tags);
  const t = String(raw == null ? "" : raw).trim();
  if (!t || list.includes(t)) return list.slice();
  return [...list, t];
}

export function removeTag(tags, value) {
  return asList(tags).filter((t) => t !== value);
}
