// Pure zoom-fit sizing for the tile row. Mirrors viewer_3d.js _vaFitViewer:
//   targetW = min(round(baseW * zoom/100), floor(maxW))
//   marginLeft = overflow ? -extra/2 : 0   (centers content wider than baseW)

export function fitViewerSize({ baseW, maxW, zoom }) {
  const targetW = Math.min(Math.round(baseW * (zoom / 100)), Math.floor(maxW));
  const extra = targetW - baseW;
  return { width: targetW, marginLeft: extra > 0 ? -extra / 2 : 0 };
}
