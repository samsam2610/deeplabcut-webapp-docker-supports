// Pure, DOM-free tag→color helpers shared by the StatusNoteTimeline feature.
// No storage, no randomness, no Date, no reliance on call/insertion order —
// deterministic given only the inputs each function receives, so the same tag
// name always resolves to the same palette slot regardless of session, which
// video's CSV it came from, or what other tags happen to appear alongside it
// (the bug this replaces: the old `assignColors(uniqueValues(...), palette)`
// cycled the palette by *first-seen order within that one CSV*, so the same
// tag name could land on a different color in a different video).

const HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/;

// Reject anything that is not a plain `#rrggbb` string. Used both when
// applying a stored/override color (fall back to the deterministic default)
// and before persisting one — a malformed value reaching
// `style.setProperty("--chip-color", …)` is a CSS-injection vector, so every
// override must pass through here before it is trusted.
export function isValidHexColor(value) {
  return typeof value === "string" && HEX_COLOR_RE.test(value);
}

// FNV-1a 32-bit — simple, fast, and stable across engines/processes/sessions.
// Pure function of the string's characters only; no external state.
function hashString(str) {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

// Deterministic default color for `name`: same name → same palette entry,
// always — independent of what other tags exist, what order they were
// queried in, or which video/session this is. `palette` is a plain array of
// color strings (hex or otherwise); the caller owns its contents.
export function tagColor(name, palette) {
  if (!Array.isArray(palette) || !palette.length) return undefined;
  const idx = hashString(String(name)) % palette.length;
  return palette[idx];
}

// Order `tags` (an array of tag-name strings) so that any tag with a key in
// `overrides` (a { tag: color } map — only key membership matters, the color
// value isn't inspected here) sorts before the rest. Both groups are then
// sorted alphabetically using ordinary (non-locale) string comparison, so the
// result is identical across environments/ICU versions. A key present in
// `overrides` but absent from `tags` never appears in the output — this
// function only reorders what it's given, it doesn't invent entries.
export function sortTags(tags, overrides) {
  const ov = overrides || {};
  const overridden = [];
  const rest = [];
  for (const t of tags || []) {
    if (Object.prototype.hasOwnProperty.call(ov, t)) overridden.push(t);
    else rest.push(t);
  }
  const byName = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  overridden.sort(byName);
  rest.sort(byName);
  return overridden.concat(rest);
}
