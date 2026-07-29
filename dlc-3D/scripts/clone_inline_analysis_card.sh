#!/usr/bin/env bash
# Generate the "3D Inline Analysis - Reprojection" clone from the original card.
#
# Kept in-tree so the clone can be regenerated if the original card changes
# while both exist. Re-running OVERWRITES the three generated files, so any
# hand edits to the clone must be re-applied afterwards — that is why the
# reprojection panel lives in its own appended block (see Tasks 4-6), which
# this script preserves by refusing to run once that block is present.
set -euo pipefail

cd "$(dirname "$0")/.."
SRC_CARD="src/templates/partials/card_inline_analysis_3d.html"
SRC_JS="src/static/inline_analysis_3d.js"
SRC_CSS="src/static/inline_analysis_3d.css"
OUT_CARD="src/static/card_inline_analysis_3d_reprojection.html"
OUT_JS="src/static/inline_analysis_3d_reprojection.js"
OUT_CSS="src/static/inline_analysis_3d_reprojection.css"

for f in "$OUT_CARD" "$OUT_JS" "$OUT_CSS"; do
  if [ -f "$f" ] && grep -q "REPROJECTION PANEL" "$f"; then
    echo "refusing to overwrite $f: it contains hand-written panel code" >&2
    exit 1
  fi
done

rename() {
  # Order is irrelevant: the two patterns cannot overlap.
  #   inline-analysis-3d  -> inline-analysis-3d-reprojection  (card/button ids)
  #   ia3d-               -> ia3dr-                           (ids + CSS classes)
  #   _ia3d<Upper>        -> _ia3dr<Upper>                    (JS identifiers)
  #   __iaViewer          -> __iaViewerReproj                 (window global)
  # URLs are unaffected: no fetch path contains "inline-analysis-3d" or "ia3d-".
  sed -e 's/inline-analysis-3d/inline-analysis-3d-reprojection/g' \
      -e 's/ia3d-/ia3dr-/g' \
      -e 's/\b_ia3d\([A-Z]\)/_ia3dr\1/g' \
      -e 's/__iaViewer\b/__iaViewerReproj/g'
}

rename < "$SRC_CARD" > "$OUT_CARD"
rename < "$SRC_JS"   > "$OUT_JS"
rename < "$SRC_CSS"  > "$OUT_CSS"

# The card fragment is injected into an existing <main>, so strip the Jinja
# wrapper if the original partial has one.
sed -i -e '/^{%/d' "$OUT_CARD"

echo "generated:"
wc -c "$OUT_CARD" "$OUT_JS" "$OUT_CSS"
