// Pure tile-layout planning: primary tile (cam 0) always present; sibling tile (cam 1)
// only when a sibling video was discovered. Mirrors viewer_3d.js Controller tile decision.

export function planTiles({
  primaryVideoRel,
  siblingVideoRel,
  primaryLabel = "main",
  siblingLabel = "sibling",
}) {
  const tiles = [{ cam: 0, videoRel: primaryVideoRel, label: primaryLabel }];
  if (siblingVideoRel) {
    tiles.push({ cam: 1, videoRel: siblingVideoRel, label: siblingLabel });
  }
  return tiles;
}
