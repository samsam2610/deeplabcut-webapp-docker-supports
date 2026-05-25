// Pure geometry for the hover / show-names marker-name label box.
// Values copied verbatim from frame_labeler_3d.js:1243-1248 so the shared
// markerEditor's name label matches the frame labeler exactly.

export const NAME_LABEL_FONT = "bold 11px 'JetBrains Mono', monospace";

// Given a marker center (cx,cy), radius r, and the measured text width, return
// the label-box rect + text anchor. The caller sets ctx.font = NAME_LABEL_FONT,
// measures the text, fills the box (rgba(12,13,16,.65)), then fills the text in
// the marker's color.
export function nameLabelBox(cx, cy, r, textWidth) {
  return {
    font: NAME_LABEL_FONT,
    boxX: cx + r + 2,
    boxY: cy - 7,
    boxW: textWidth + 6,
    boxH: 14,
    textX: cx + r + 5,
    textY: cy + 4,
  };
}
