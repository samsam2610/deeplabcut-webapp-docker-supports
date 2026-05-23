// Pure clip-trim request builders + postfix quick-tag list ops for the ClipExtractor
// feature. Clip geometry/naming lives in clip_naming.mjs (Phase 1); this reuses it.

import { computeEnd, sanitizePostfix } from "./clip_naming.mjs";

// clip-cutter convention: the keyframe sits `preWindow` frames after the clip start.
export function keyFrameForStart(start, preWindow = 200) {
  return start + preWindow;
}

export function buildExtractRequest({ videoPath, start, frames, postfix, preWindow = 200 }) {
  return {
    video_path: videoPath,
    key_frame: keyFrameForStart(start, preWindow),
    start_fn: start,
    end_fn: computeEnd(start, frames),
    postfix: sanitizePostfix(postfix),
  };
}

export function buildRenameRequest({ aviPath, postfix }) {
  return { avi_path: aviPath, postfix: sanitizePostfix(postfix) };
}

export function buildDeleteRequest({ aviPath }) {
  return { avi_path: aviPath };
}

export function buildOverlapRequest({ videoPath, start, preWindow = 200 }) {
  return { video_path: videoPath, key_frame: keyFrameForStart(start, preWindow) };
}

// postfix quick-tag list operations (pure; the feature persists to localStorage).
export function addTag(tags, tag) {
  const t = (tag || "").trim();
  if (!t || tags.includes(t)) return tags.slice();
  return [...tags, t];
}

export function removeTagAt(tags, idx) {
  const next = tags.slice();
  if (idx >= 0 && idx < next.length) next.splice(idx, 1);
  return next;
}
