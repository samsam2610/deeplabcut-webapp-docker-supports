// Pure seek planning: clamp the target frame and list the parallel tile loads.
// Mirrors viewer_3d.js Controller.seek (clamp + Promise.all over tiles, sibling skipped
// in frames mode). The DOM shell turns each load into an <img>.src assignment.

import { clampFrame } from "./frame_pacer.mjs";

export function planSeek({ n, frameCount, tiles, framesMode = false }) {
  const frame = clampFrame(n, 0, Math.max(frameCount - 1, 0));
  const loads = [];
  for (const t of tiles) {
    if (!t.videoRel) continue;
    if (t.cam !== 0 && framesMode) continue; // sibling has no labeled-frame folder
    loads.push({ cam: t.cam, videoRel: t.videoRel, frame });
  }
  return { frame, loads };
}
