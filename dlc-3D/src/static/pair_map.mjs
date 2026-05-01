export const FL3D_FRAME_RE = /^img_cam(\d+)_(\d{4})_(\d+)\.png$/;

export function buildPairMap(frames) {
  const pairMap = new Map();
  const camSet  = new Set();
  for (const fname of frames) {
    const m = FL3D_FRAME_RE.exec(fname);
    if (!m) continue;
    const cam = +m[1], order = +m[2], frame = +m[3];
    camSet.add(cam);
    if (!pairMap.has(frame)) pairMap.set(frame, []);
    pairMap.get(frame).push({ cam, fname, order });
  }
  return {
    pairMap,
    camSet: [...camSet].sort((a, b) => a - b),
    frameNumbers: [...pairMap.keys()].sort((a, b) => a - b),
  };
}
