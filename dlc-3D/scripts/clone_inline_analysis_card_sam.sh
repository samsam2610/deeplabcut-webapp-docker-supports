#!/usr/bin/env bash
# Generate the "3D Inline Analysis - SAM Model" clone from the original card.
#
# Deliberately a sibling of clone_inline_analysis_card.sh rather than a
# generalisation of it: that script regenerates the reprojection clone, which
# carries hand-written panel code, and rewriting it to take a suffix would put
# working output at risk for no gain. Two small scripts beat one clever one.
#
# Re-running OVERWRITES the three generated files, so hand edits to the clone
# must live in the SAM PANEL block, which this script refuses to clobber (same
# guard as the reprojection script). That block is NOT appended at the end —
# it lives inside #ia3ds-player-section, as the last child, right after
# #ia3ds-clip-panel-wrap — so it takes part in the drag-reorder stack. Putting
# it back outside the section after a regeneration would silently drop it out
# of that stack.
set -euo pipefail

cd "$(dirname "$0")/.."
SRC_CARD="src/templates/partials/card_inline_analysis_3d.html"
SRC_JS="src/static/inline_analysis_3d.js"
SRC_CSS="src/static/inline_analysis_3d.css"
OUT_CARD="src/static/card_inline_analysis_3d_sam.html"
OUT_JS="src/static/inline_analysis_3d_sam.js"
OUT_CSS="src/static/inline_analysis_3d_sam.css"

for f in "$OUT_CARD" "$OUT_JS" "$OUT_CSS"; do
  if [ -f "$f" ] && grep -q "SAM PANEL" "$f"; then
    echo "refusing to overwrite $f: it contains hand-written panel code" >&2
    exit 1
  fi
done

rename() {
  # Order is irrelevant: the patterns cannot overlap.
  #   inline-analysis-3d  -> inline-analysis-3d-sam   (card/button ids)
  #   ia3d-               -> ia3ds-                   (ids + CSS classes)
  #   _ia3d<Upper>        -> _ia3ds<Upper>            (JS identifiers)
  #   __iaViewer          -> __iaViewerSam            (window global)
  # URLs are unaffected: no fetch path contains "inline-analysis-3d" or "ia3d-".
  sed -e 's/inline-analysis-3d/inline-analysis-3d-sam/g' \
      -e 's/ia3d-/ia3ds-/g' \
      -e 's/\b_ia3d\([A-Z]\)/_ia3ds\1/g' \
      -e 's/__iaViewer\b/__iaViewerSam/g'
}

rename < "$SRC_CARD" > "$OUT_CARD"
rename < "$SRC_JS"   > "$OUT_JS"
rename < "$SRC_CSS"  > "$OUT_CSS"

# The card fragment is injected into an existing <main>, so strip the Jinja
# wrapper if the original partial has one.
sed -i -e '/^{%/d' "$OUT_CARD"

echo "generated:"
wc -c "$OUT_CARD" "$OUT_JS" "$OUT_CSS"
echo
echo "NOTE: the SAM PANEL block and the SAM BOOTSTRAP block must now be"
echo "re-added by hand — see git history for the versions this replaced."
echo "They do NOT go at the end: the SAM PANEL block belongs inside"
echo "#ia3ds-player-section, as its last child, right after"
echo "#ia3ds-clip-panel-wrap, so it stays part of the drag-reorder stack."
