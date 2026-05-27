// pick_latest_variant.mjs — choose the "latest" h5 variant from a
// /dlc/viewer/h5-variants response array.
//
// Backend ordering (deeplabcut-webapp-docker/src/dlc/viewer.py
// _h5_variants_for_video): raw companion h5(s) first (alphabetical, ts=null),
// then postproc runs sorted by run-dir name == timestamp ASCENDING, each with an
// ISO-8601 `ts`. So the freshest analysis is the variant with the max `ts`; ISO
// 8601 strings compare correctly with `<`/`>` (no Date parse). When no variant
// carries a `ts` (all raw companions — the inline working layer is one of these),
// fall back to the LAST array element (the backend's own ordering puts the freshly
// written companion last alphabetically). Empty/falsy → null.
"use strict";

export function pickLatestVariant(variants) {
  if (!Array.isArray(variants) || variants.length === 0) return null;
  let best = null;
  for (const v of variants) {
    if (v && v.ts && (best === null || v.ts > best.ts)) best = v;
  }
  if (best) return best;
  return variants[variants.length - 1];
}
