// Pure frame-extraction logic for the FrameExtractor feature: batch planning and the
// save-frame request payload. Ported from dlc_3d.js _extractBatch / _extractFrame.

export function parseBatchCount(v, def = 10) {
  const n = parseInt(v, 10);
  return Math.max(2, isNaN(n) ? def : n);
}

export function parseBatchStep(v, def = 1) {
  const n = parseInt(v, 10);
  return Math.max(1, isNaN(n) ? def : n);
}

// Clamp `requested` so frames stay within [startFrame, frameCount-1] at the given step,
// and list the target frames. Returns { count, frames, clamped }.
export function planBatch({ startFrame, step, requested, frameCount }) {
  const maxCount = Math.floor((frameCount - 1 - startFrame) / step) + 1;
  const count = Math.min(requested, maxCount);
  const frames = [];
  for (let i = 0; i < count; i++) frames.push(startFrame + i * step);
  return { count, frames, clamped: count < requested };
}

export function buildSaveFramePayload({ primaryVideo, frameNumber, extractSibling, siblingVideo }) {
  const body = {
    primary_video: primaryVideo,
    primary_frame_number: frameNumber,
    extract_sibling: extractSibling,
  };
  if (extractSibling && siblingVideo) {
    body.sibling_video = siblingVideo;
    body.sibling_frame_number = frameNumber;
  }
  return body;
}
